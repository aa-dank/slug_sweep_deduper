import os
import re
import shutil
import tempfile
import subprocess
from pathlib import Path, PurePosixPath
from typing import Optional


def build_file_path(base_mount: str,
                    server_dir: str,
                    filename: str = None) -> Path:
    """
    Join a server-relative path + filename onto a machine-specific
    mount-point.

    Parameters
    ----------
    base_mount : str
        The local mount of the records share, e.g.
        r"N:\\PPDO\\Records"  (Windows)  or  "/mnt/records" (Linux).
    server_dir : str
        The value from file_locations.file_server_directories
        (always stored with forward-slashes).
    filename   : str
        file_locations.filename

    Returns
    -------
    pathlib.Path  – ready for open(), exists(), etc.
    """
    # 1) Treat the DB field as a *POSIX* path (it always uses “/”)
    rel_parts = PurePosixPath(server_dir).parts     # -> tuple of segments

    # 2) Let Path figure out the separator style of this machine
    full_path = Path(base_mount).joinpath(*rel_parts)
    if filename:
        full_path = full_path.joinpath(filename)

    return full_path


def split_path(path):
    """
    Split a path into a list of directories/files/mount points. It is built to accomodate Splitting both Windows and Linux paths
    on linux systems. (It will not necessarily work to process linux paths on Windows systems)
    :param path: The path to split.
    """

    def detect_filepath_type(filepath):
        """
        Detects the cooresponding OS of the filepath. (Windows, Linux, or Unknown)
        :param filepath: The filepath to detect.
        :return: The OS of the filepath. (Windows, Linux, or Unknown)
        """
        windows_pattern = r"^[A-Za-z]:\\(.+)$"
        linux_pattern = r"^/([^/]+/)*[^/]+$"

        if re.match(windows_pattern, filepath):
            return "Windows"
        elif re.match(linux_pattern, filepath):
            return "Linux"
        else:
            return "Unknown"
        
    def split_windows_path(filepath):
        """"""
        parts = []
        curr_part = ""
        is_absolute = False

        if filepath.startswith("\\\\"):
            # UNC path
            parts.append(filepath[:2])
            filepath = filepath[2:]
        elif len(filepath) >= 2 and filepath[1] == ":":
            # Absolute path
            parts.append(filepath[:2])
            filepath = filepath[2:]
            is_absolute = True

        for char in filepath:
            if char == "\\":
                if curr_part:
                    parts.append(curr_part)
                    curr_part = ""
            else:
                curr_part += char

        if curr_part:
            parts.append(curr_part)

        if not is_absolute and not parts:
            # Relative path with a single directory or filename
            parts.append(curr_part)

        return parts
    
    def split_other_path(path):

        allparts = []
        while True:
            parts = os.path.split(path)
            if parts[0] == path:  # sentinel for absolute paths
                allparts.insert(0, parts[0]) 
                break
            elif parts[1] == path:  # sentinel for relative paths
                allparts.insert(0, parts[1])
                break
            else:
                path = parts[0]
                allparts.insert(0, parts[1])
        return allparts

    path = str(path)
    path_type = detect_filepath_type(path)
    
    if path_type == "Windows":
        return split_windows_path(path)
    
    return split_other_path(path)

def extract_server_dirs(full_path: str | Path, base_mount: str | Path) -> str:
    """
    Parameters
    ----------
    full_path   Absolute path on the client machine
                e.g. r"N:\\\\PPDO\\\\Records\\\\49xx   Long Marine Lab\\\\4932\\\\..."
    base_mount  The local mount-point for the records share
                e.g. r"N:\\\\PPDO\\\\Records"   or   "/mnt/records"

    Returns
    -------
    str   --  value suitable for file_locations.file_server_directories
              (always forward-slash separators, no leading slash)
    """
    # Normalise to platform-aware Path objects
    full = Path(full_path).expanduser().resolve()
    base = Path(base_mount).expanduser().resolve()

    # 1) Get the sub-path *relative* to the mount
    try:
        rel_parts = full.relative_to(base)
    except ValueError:               # not under base_mount
        raise ValueError(f"{full} is not under {base}")

    # 2) Convert to POSIX form (forces forward slashes)
    return str(PurePosixPath(rel_parts))


def normalize_path_for_query(user_path: str | Path, mount: str | Path) -> str:
    """Convert a Windows user path to the Postgres query format.
    
    Parameters
    ----------
    user_path : str | Path
        The full Windows path entered by the user
        e.g. r"N:\\PPDO\\Records\\42xx   Student Housing West\\4203\\4203\\F - Bid Documents"
    mount : str | Path
        The file server mount point
        e.g. r"N:\\PPDO\\Records"
    
    Returns
    -------
    str
        The relative path with forward slashes suitable for Postgres queries
        e.g. "42xx   Student Housing West/4203/4203/F - Bid Documents"
    """
    return extract_server_dirs(user_path, mount)


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format.
    
    Parameters
    ----------
    size_bytes : int
        File size in bytes
    
    Returns
    -------
    str
        Formatted size string (e.g., "1.5 MB", "823 KB")
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class TempFileManager:
    """Manages temporary file copies for the 'open' command."""
    
    def __init__(self):
        self.temp_dir: Optional[Path] = None
    
    def get_temp_dir(self) -> Path:
        """Get or create the temporary directory."""
        if self.temp_dir is None:
            self.temp_dir = Path(tempfile.gettempdir()) / "slug_sweep_deduper_open"
            self.temp_dir.mkdir(parents=True, exist_ok=True)
        return self.temp_dir
    
    def copy_and_open(self, source_path: Path) -> bool:
        """Copy a file to temp directory and open it with the default application.
        
        Parameters
        ----------
        source_path : Path
            Path to the source file
        
        Returns
        -------
        bool
            True if successful, False otherwise
        """
        try:
            temp_dir = self.get_temp_dir()
            dest_path = temp_dir / source_path.name
            
            # Copy file to temp directory
            shutil.copy2(source_path, dest_path)
            
            # Open with default application (Windows)
            subprocess.Popen(['cmd', '/c', 'start', '', str(dest_path)], shell=False)
            
            return True
        except Exception as e:
            print(f"Error opening file: {e}")
            return False
    
    def cleanup(self):
        """Remove the temporary directory and all its contents."""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None
