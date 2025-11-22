"""Filtering functions for excluding files from deduplication review.

Each filter function should accept a file_record dict and return True if the
file should be EXCLUDED from review, False otherwise.

File record structure:
    {
        'archives_app_file_id': int,
        'file_server_directories': str,
        'filename': str,
        'size': int,
        'loc_count': int
    }

To add a new filter:
1. Define a function following the contract: def my_filter(file_record) -> bool
2. Add the function to the ACTIVE_FILTERS list below
"""

from typing import Dict, Any, List, Callable


def no_filter(file_record: Dict[str, Any]) -> bool:
    """Placeholder filter that never excludes anything.
    
    This demonstrates the filter contract. Replace or add additional
    filters as needed.
    
    Parameters
    ----------
    file_record : dict
        Dictionary containing file information
    
    Returns
    -------
    bool
        Always returns False (do not exclude)
    """
    return False


def exclude_cad_fonts(file_record: Dict[str, Any]) -> bool:
    """Exclude CAD font and pattern files.
    
    Example filter for excluding common CAD support files that are
    typically duplicated intentionally.
    """
    filename = file_record.get('filename', '').lower()
    cad_extensions = {'.shx', '.lin', '.pat', '.pcx'}
    return any(filename.endswith(ext) for ext in cad_extensions)


def exclude_system_files(file_record: Dict[str, Any]) -> bool:
    """Exclude common system and thumbnail files.
    
    Example filter for excluding OS-generated files.
    """
    filename = file_record.get('filename', '').lower()
    system_files = {'thumbs.db', '.ds_store', 'desktop.ini'}
    return filename in system_files


# List of active filters to apply during sweep
# Filters are applied in order; if any returns True, the file is excluded
ACTIVE_FILTERS: List[Callable[[Dict[str, Any]], bool]] = [
    no_filter,
    # Uncomment the following to enable additional filters:
    # exclude_cad_fonts,
    # exclude_system_files,
]