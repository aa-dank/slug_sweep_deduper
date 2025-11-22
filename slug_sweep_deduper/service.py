import httpx
import os
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib import parse
import psycopg


class ArchivesApp:
    """Client for Archives App API operations."""

    def __init__(self, username: str, password: str, app_url: str):
        self.username = username
        self.password = password
        self.app_url = app_url
        
        # Determine protocol based on app_url
        protocol = "https://" if not self.app_url.startswith(("http://", "https://")) else ""
        base_url = f"{protocol}{self.app_url}"
        
        self.edit_url_template = f"{base_url}/api/server_change?edit_type={{}}&old_path={{}}&new_path={{}}"
        self.request_headers = {'user': self.username, 'password': self.password}
        self.consolidation_url_template = f"{base_url}/api/consolidate_dirs?asset_path={{}}&destination_path={{}}"
        self.archiving_url_template = f"{base_url}/api/upload_file"
        self.project_location_url_template = f"{base_url}/api/project_location"
        self.file_locations_url_template = f"{base_url}/api/archived_or_not"
    
    def enqueue_delete_edit(self, target_path: str) -> tuple[bool, Optional[str]]:
        """Enqueue a deletion task via the Archives App API.
        
        Returns:
            tuple[bool, Optional[str]]: (success, error_message)
        """
        try:
            old_path = parse.quote(target_path)
            delete_url = self.edit_url_template.format('DELETE', old_path, '')
            delete_response = httpx.get(
                url=delete_url,
                headers=self.request_headers,
                verify=False,
                timeout=30.0
            )
            delete_response.raise_for_status()
            return (True, None)
        except Exception as e:
            return (False, str(e))


class SweepDB:
    """Manages the local SQLite tracking database."""

    def __init__(self, storage_location: str, staging_location: str = "."):
        self.storage_location = Path(storage_location)
        self.staging_location = Path(staging_location)
        self.filename = "sweep_db.sqlite"
        
        self.storage_path = self.storage_location / self.filename
        self.staging_path = self.staging_location / self.filename
        
        self.conn: Optional[sqlite3.Connection] = None
        
        # Copy database from storage to staging, or create new if missing
        if self.storage_path.exists():
            shutil.copy2(self.storage_path, self.staging_path)
        else:
            self._create_new_db()
        
        # Open connection to staging database
        self.conn = sqlite3.connect(str(self.staging_path))
        self.conn.row_factory = sqlite3.Row

    def _create_new_db(self):
        """Create a new database with the required schema."""
        conn = sqlite3.connect(str(self.staging_path))
        cursor = conn.cursor()
        
        # Create processed_locations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location_path TEXT NOT NULL,
                datetime TEXT NOT NULL,
                duplicates_count INTEGER NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0
            )
        """)
        
        # Create processed_files table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archives_app_file_id INTEGER UNIQUE NOT NULL,
                processed_location_id INTEGER NOT NULL,
                decision TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                FOREIGN KEY (processed_location_id) REFERENCES processed_locations(id)
            )
        """)
        
        # Create deleted_files table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deleted_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                processed_file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                deleted_at TEXT NOT NULL,
                FOREIGN KEY (processed_file_id) REFERENCES processed_files(id)
            )
        """)
        
        # Create errors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                context TEXT
            )
        """)
        
        conn.commit()
        conn.close()

    def sync_to_storage(self):
        """Atomically sync the staging database back to storage."""
        if self.conn:
            self.conn.commit()
        
        # Atomic replace: write to temp, then move
        temp_path = self.storage_location / "sweep_db.tmp"
        shutil.copy2(self.staging_path, temp_path)
        shutil.move(str(temp_path), str(self.storage_path))

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def is_file_processed(self, archives_app_file_id: int) -> bool:
        """Check if a file_id has already been processed."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT 1 FROM processed_files WHERE archives_app_file_id = ?",
            (archives_app_file_id,)
        )
        return cursor.fetchone() is not None

    def record_processed_location(self, location_path: str, duplicates_count: int, completed: bool = True) -> int:
        """Record a processed location and return its ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO processed_locations (location_path, datetime, duplicates_count, completed)
            VALUES (?, ?, ?, ?)
            """,
            (location_path, datetime.utcnow().isoformat(), duplicates_count, 1 if completed else 0)
        )
        self.conn.commit()
        return cursor.lastrowid

    def record_processed_file(self, archives_app_file_id: int, processed_location_id: int, decision: str) -> int:
        """Record a processed file and return its ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO processed_files (archives_app_file_id, processed_location_id, decision, processed_at)
            VALUES (?, ?, ?, ?)
            """,
            (archives_app_file_id, processed_location_id, decision, datetime.utcnow().isoformat())
        )
        self.conn.commit()
        return cursor.lastrowid

    def record_deleted_file(self, processed_file_id: int, path: str, file_size: int):
        """Record a deleted file."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO deleted_files (processed_file_id, path, file_size, deleted_at)
            VALUES (?, ?, ?, ?)
            """,
            (processed_file_id, path, file_size, datetime.utcnow().isoformat())
        )
        self.conn.commit()

    def log_error(self, operation: str, message: str, context: Optional[str] = None):
        """Log an error to the database."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO errors (operation, message, timestamp, context)
            VALUES (?, ?, ?, ?)
            """,
            (operation, message, datetime.utcnow().isoformat(), context)
        )
        self.conn.commit()


class ArchivesAppDB:
    """PostgreSQL database interface for Archives App."""

    def __init__(self, host: str, dbname: str, user: str, password: str):
        self.host = host
        self.dbname = dbname
        self.user = user
        self.password = password
        self.conn: Optional[psycopg.Connection] = None

    def connect(self):
        """Establish connection to the database."""
        self.conn = psycopg.connect(
            host=self.host,
            dbname=self.dbname,
            user=self.user,
            password=self.password
        )

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def find_duplicates_in_location(self, target_location: str) -> List[Dict[str, Any]]:
        """Find all files with duplicates that exist in the target location.
        
        Returns list of dicts with keys: archives_app_file_id, file_server_directories, 
        filename, size, loc_count
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                WITH locs AS (
                    SELECT
                        fl.file_id AS archives_app_file_id,
                        fl.file_server_directories,
                        fl.filename,
                        f.size,
                        COUNT(*) OVER (PARTITION BY fl.file_id) AS loc_count
                    FROM file_locations fl
                    JOIN files f ON f.id = fl.file_id
                    WHERE fl.file_server_directories = %(target_location)s
                )
                SELECT *
                FROM locs
                WHERE loc_count > 1
                """,
                {"target_location": target_location}
            )
            
            columns = [desc[0] for desc in cur.description]
            results = []
            for row in cur.fetchall():
                results.append(dict(zip(columns, row)))
            return results

    def get_all_locations_for_file(self, file_id: int) -> List[Dict[str, Any]]:
        """Get all locations where a file exists.
        
        Returns list of dicts with keys: file_server_directories, filename, size
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    fl.file_server_directories,
                    fl.filename,
                    f.size
                FROM file_locations fl
                JOIN files f ON f.id = fl.file_id
                WHERE fl.file_id = %(file_id)s
                """,
                {"file_id": file_id}
            )
            
            columns = [desc[0] for desc in cur.description]
            results = []
            for row in cur.fetchall():
                results.append(dict(zip(columns, row)))
            return results
