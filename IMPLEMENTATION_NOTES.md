# Implementation Notes

## Build Completion Summary

The Slug Sweep Deduper has been fully implemented according to the specification in `development/slug_sweep_deduper_spec.md`.

### What Was Built

#### 1. Core Services (`service.py`)

- **SweepDB**: Complete SQLite tracking database with:
  - 4 tables: processed_locations, processed_files, deleted_files, errors
  - Automatic copy-down from CIFS share on initialization
  - Atomic sync-back using temporary file pattern
  - Methods for recording all operations and checking processed status

- **ArchivesAppDB**: PostgreSQL query interface with:
  - Connection management via psycopg
  - CTE-based duplicate detection query (exact match on target directory)
  - Method to fetch all locations for a given file_id across entire server

- **ArchivesApp**: API client with:
  - Deletion task enqueueing via `/api/server_change`
  - Error handling and response checking
  - Returns (success: bool, error_message: Optional[str]) tuples

#### 2. Interactive Sweep Workflow (`sweep.py`)

- Query duplicates in target location
- Apply filter pipeline from `filters.py`
- Exclude already-processed files
- Group by file_id
- For each file, fetch ALL locations (not just target directory)
- Display Rich-formatted tables with:
  - File number, full Windows path, size, notes (current loc vs duplicate)
- Interactive command loop:
  - **Numbers** (e.g., `1 3`) - Delete selected instances with confirmation
  - **c** - Keep all copies, mark processed
  - **o <#>** - Open file for inspection
  - **s** - Skip file
  - **q** - Quit and sync
- Periodic sync every 10 minutes
- Comprehensive error logging to SweepDB

#### 3. Path Utilities (`utils.py`)

- `build_file_path()` - Join server-relative path onto Windows mount
- `extract_server_dirs()` - Convert Windows path to Postgres format
- `normalize_path_for_query()` - Wrapper for path normalization
- `format_file_size()` - Human-readable file sizes (B, KB, MB, GB)
- `TempFileManager` class:
  - Creates temp directory on demand
  - Copies files and opens with default application
  - Cleanup on exit

#### 4. Filter System (`filters.py`)

- Simple function-based filtering
- `no_filter()` - Placeholder that excludes nothing
- Example filters provided (commented out):
  - `exclude_cad_fonts()` - CAD support files
  - `exclude_system_files()` - Thumbs.db, .DS_Store, etc.
- `ACTIVE_FILTERS` list for easy configuration

#### 5. CLI Interface (`cli.py`)

Three commands:
- `sweep <LOCATION>` - Main interactive deduplication
- `init-db` - Initialize new SweepDB
- `sync-db` - Manual sync to storage
- `--debug` flag for verbose error output
- Environment variable validation on startup

### Key Implementation Decisions

1. **Package Structure**: Used standard Python package layout with `slug_sweep_deduper/` subdirectory to enable proper CLI entry point installation via uv.

2. **Import Paths**: Fully qualified imports (`slug_sweep_deduper.module`) for proper package resolution.

3. **Database Filename**: Using `sweep_db.sqlite` (not `util.sqlite` or similar).

4. **Periodic Sync**: Implemented with simple time-based check in the main loop (every 600 seconds).

5. **Error Handling**: API failures log to database and continue processing (don't halt execution).

6. **Path Display**: Tables show full Windows paths for operator clarity.

7. **Confirmation**: Required for deletion operations to prevent accidents.

### Testing Checklist

Before first production use:

- [ ] Create `.env` file with actual credentials
- [ ] Test database initialization: `uv run slug-sweep-deduper init-db`
- [ ] Test manual sync: `uv run slug-sweep-deduper sync-db`
- [ ] Test sweep on small location with known duplicates
- [ ] Verify API deletion calls work
- [ ] Verify periodic sync occurs
- [ ] Test the 'open' command opens files correctly
- [ ] Test quit command syncs and cleans up
- [ ] Verify already-processed files are skipped on re-sweep

### Operational Notes

- The tool is idempotent - you can re-run sweeps on the same location and already-processed files will be skipped
- The SweepDB tracks decisions by `archives_app_file_id`, so once a file is processed in one location, it won't appear in future sweeps of other locations
- All deletions go through the Archives App API, maintaining audit logs
- Temp files from the 'open' command are cleaned up on normal exit or quit command
- Database is synced periodically and on exit to minimize data loss risk

### Dependencies

All managed via `pyproject.toml` and installed with `uv sync`:
- click (CLI framework)
- httpx (HTTP client)
- psycopg[binary] (PostgreSQL driver)
- python-dotenv (environment configuration)
- rich (terminal UI)

### Known Limitations

- Windows-only (by design)
- Single directory mode only (no recursive sweep)
- No undo capability (deletions are permanent once API processes them)
- Requires network access to both Postgres DB and Archives App API
- Large result sets may cause slow queries (no pagination implemented)

## Next Steps

1. Set up production `.env` file
2. Initialize production SweepDB on CIFS share
3. Begin deduplication work starting with highest-priority locations
4. Consider enabling additional filters as patterns emerge
5. Monitor SweepDB errors table for any recurring issues
