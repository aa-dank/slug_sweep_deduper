import httpx
import os
import sqlite3
from urllib import parse


class ArchivesApp:

    def __init__(self, username, password, app_url=None):
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
    
    def enqueue_delete_edit(self, target_path):
        old_path = parse.quote(target_path)
        delete_url = self.edit_url_template.format('DELETE', old_path, '')
        delete_response = httpx.get(url=delete_url,
                                    headers= self.request_headers,
                                    verify=False)
        return delete_response
    

class SweepDB:

    def __init__(self, storage_location, staging_location = "staging"):
        self.storage_location = storage_location
        self.staging_location = staging_location
        self.filename = "sweep_db.sqlite"
        
        # copy the databse from storage to staging, if it doesn't exist make a new one in staging loc
        if not os.path.exists(os.path.join(self.storage_location, self.filename)):

    def instantiate_new_db(self):
        # Placeholder for database instantiation logic
        pass

    #method for ending the sweep and copying the db back to storage
    def finalize_db(self):
        pass

    def record_processed_location(self, location):
        # adds a location to the database
        pass

    #TODO: additional sqlite db logic here


class ArchivesAppDB:
    # class for functionality associated with the ArchivesApp database

    def __init__(self, url, username, password):


