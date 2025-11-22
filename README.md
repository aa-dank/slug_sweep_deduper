# Slug Sweep Deduper

A Windows CLI utility for safely removing redundant duplicate files from UCSC PPDO construction records archives.

## Features

- **Operator-Driven Workflow**: Interactive review and selection of files to delete
- **Safe Deletion**: All deletions go through the Archives App API to maintain audit logs
- **Progress Tracking**: SQLite database tracks processed locations and files
- **Periodic Sync**: Automatic backup of tracking database every 10 minutes
- **File Preview**: Open files for inspection before deciding to delete
- **Comprehensive Deduplication**: Shows ALL locations of duplicate files across the entire server

## Installation

This project uses `uv` for Python package management.

1. Clone the repository
2. Install dependencies:
   ```powershell
   uv sync
   ```

3. Copy `.env.example` to `.env` and fill in your configuration:
   ```powershell
   cp .env.example .env
   ```

4. Initialize the tracking database:
   ```powershell
   uv run slug-sweep-deduper init-db
   ```

## Configuration

Edit `.env` with your environment-specific values:

```env
# Archives App Postgres Database
ARCHIVES_DB_HOST=localhost
ARCHIVES_DB_NAME=archives_db
ARCHIVES_DB_USER=admin
ARCHIVES_DB_PASSWORD=secret

# Archives App API
ARCHIVES_APP_URL=https://archives.example.com
ARCHIVES_APP_USER=sweep_user
ARCHIVES_APP_PASSWORD=sweep_pass

# SweepDB Storage (CIFS share)
SWEEP_DB_LOCATION=N:\path\to\share

# File Server Mount Point
FILE_SERVER_MOUNT=N:\PPDO\Records
```

## Usage

### Run a Sweep

To deduplicate files in a specific location:

```powershell
uv run slug-sweep-deduper sweep "N:\PPDO\Records\42xx   Student Housing West\4203\4203"
```

### Interactive Commands

During a sweep session, you can use these commands:

- **Numbers** (e.g., `1 3 5`) - Delete the specified file instances
- **c** - Keep all copies and mark this file as processed
- **o <#>** (e.g., `o 2`) - Open a specific file for inspection
- **s** - Skip this file without processing
- **q** - Quit and sync database

### Manual Database Sync

To manually sync the local database to the CIFS share:

```powershell
uv run slug-sweep-deduper sync-db
```

### Debug Mode

Enable verbose error output:

```powershell
uv run slug-sweep-deduper sweep --debug "N:\path\to\location"
```

## How It Works

1. **Query**: Finds files in the target location that have duplicates anywhere on the server
2. **Filter**: Applies optional filters to exclude certain file types
3. **Review**: Shows you a table of all locations for each duplicate file
4. **Action**: You choose which instances to delete
5. **Delete**: Deletion requests are sent to the Archives App API
6. **Track**: All decisions and deletions are recorded in the SweepDB

## File Filtering

To add custom filters, edit `filters.py`:

```python
def my_custom_filter(file_record) -> bool:
    """Return True to exclude this file from review."""
    # Your logic here
    return False

# Add to ACTIVE_FILTERS list
ACTIVE_FILTERS = [
    my_custom_filter,
]
```

Example filters are provided but commented out:
- `exclude_cad_fonts` - Exclude CAD support files (.shx, .lin, etc.)
- `exclude_system_files` - Exclude OS files (Thumbs.db, .DS_Store, etc.)

## Database Schema

The SweepDB SQLite database tracks:

- **processed_locations**: Locations that have been swept
- **processed_files**: Files that have been reviewed
- **deleted_files**: Files that were deleted
- **errors**: Errors encountered during operations

## Safety Features

- All deletions go through the Archives App API (no direct file system access)
- Confirmation prompts before deletion
- Already-processed files are skipped automatically
- Periodic database backups prevent data loss
- Comprehensive error logging

## Requirements

- Windows 11
- Python 3.13+
- uv (Python package manager)
- Network access to:
  - Archives App API
  - Archives Postgres database
  - CIFS-mounted file server

## Project Structure

```
slug_sweep_deduper/
├── cli.py         # Click CLI interface
├── sweep.py       # Main sweep workflow
├── service.py     # Database and API clients
├── filters.py     # File filtering functions
├── utils.py       # Path utilities and helpers
├── pyproject.toml # Project dependencies
└── .env           # Environment configuration
```

## License

Internal tool for UCSC PPDO use.
