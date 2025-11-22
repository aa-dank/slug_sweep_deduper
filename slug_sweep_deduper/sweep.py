"""Main sweep workflow and interactive review loop."""

import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich import print as rprint

from slug_sweep_deduper.service import SweepDB, ArchivesAppDB, ArchivesApp
from slug_sweep_deduper.utils import (
    normalize_path_for_query,
    build_file_path,
    format_file_size,
    TempFileManager
)
from slug_sweep_deduper.filters import ACTIVE_FILTERS


console = Console()


def apply_filters(file_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply active filters to file records.
    
    Parameters
    ----------
    file_records : list
        List of file record dictionaries
    
    Returns
    -------
    list
        Filtered list of file records (excluded files removed)
    """
    filtered = []
    for record in file_records:
        excluded = False
        for filter_func in ACTIVE_FILTERS:
            if filter_func(record):
                excluded = True
                break
        if not excluded:
            filtered.append(record)
    return filtered


def group_by_file_id(file_records: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """Group file records by archives_app_file_id.
    
    Parameters
    ----------
    file_records : list
        List of file record dictionaries
    
    Returns
    -------
    dict
        Dictionary mapping file_id to list of location records
    """
    grouped = defaultdict(list)
    for record in file_records:
        grouped[record['archives_app_file_id']].append(record)
    return dict(grouped)


def display_file_locations(file_id: int, locations: List[Dict[str, Any]], 
                          file_server_mount: str, target_location: str) -> None:
    """Display a Rich table showing all locations for a file.
    
    Parameters
    ----------
    file_id : int
        The archives_app_file_id
    locations : list
        List of location dictionaries
    file_server_mount : str
        The FILE_SERVER_MOUNT path
    target_location : str
        The target location being swept (for marking "current loc")
    """
    table = Table(title=f"File ID: {file_id} ({locations[0]['filename']})")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("File Path", style="white")
    table.add_column("Size", justify="right", style="green")
    table.add_column("Notes", style="yellow")
    
    for idx, loc in enumerate(locations, start=1):
        full_path = build_file_path(
            file_server_mount,
            loc['file_server_directories'],
            loc['filename']
        )
        size_str = format_file_size(loc['size'])
        
        # Mark files in target location as "current loc"
        notes = "current loc" if loc['file_server_directories'] == target_location else "duplicate"
        
        table.add_row(str(idx), str(full_path), size_str, notes)
    
    console.print(table)


def parse_user_command(command: str) -> tuple[str, List[int]]:
    """Parse user command input.
    
    Parameters
    ----------
    command : str
        Raw user input
    
    Returns
    -------
    tuple
        (command_type, list_of_numbers)
        command_type can be: 'delete', 'keep', 'open', 'skip', 'quit'
    """
    command = command.strip().lower()
    
    if not command:
        return ('invalid', [])
    
    if command == 'c':
        return ('keep', [])
    elif command == 's':
        return ('skip', [])
    elif command == 'q':
        return ('quit', [])
    elif command.startswith('o '):
        try:
            num = int(command.split()[1])
            return ('open', [num])
        except (IndexError, ValueError):
            return ('invalid', [])
    else:
        # Try to parse as numbers for deletion
        try:
            numbers = [int(x) for x in command.split()]
            return ('delete', numbers)
        except ValueError:
            return ('invalid', [])


def run_sweep(location_path: str, env_config: Dict[str, str], debug: bool = False) -> None:
    """Run the interactive sweep workflow for a location.
    
    Parameters
    ----------
    location_path : str
        The Windows path to the target location
    env_config : dict
        Environment configuration dictionary
    debug : bool
        Whether to show debug output
    """
    # Initialize services
    console.print("[cyan]Initializing services...[/cyan]")
    
    sweep_db = SweepDB(
        storage_location=env_config['SWEEP_DB_LOCATION'],
        staging_location='.'
    )
    
    archives_db = ArchivesAppDB(
        host=env_config['ARCHIVES_DB_HOST'],
        dbname=env_config['ARCHIVES_DB_NAME'],
        user=env_config['ARCHIVES_DB_USER'],
        password=env_config['ARCHIVES_DB_PASSWORD']
    )
    archives_db.connect()
    
    archives_app = ArchivesApp(
        username=env_config['ARCHIVES_APP_USER'],
        password=env_config['ARCHIVES_APP_PASSWORD'],
        app_url=env_config['ARCHIVES_APP_URL']
    )
    
    temp_manager = TempFileManager()
    
    try:
        # Convert user path to query format
        file_server_mount = env_config['FILE_SERVER_MOUNT']
        target_location = normalize_path_for_query(location_path, file_server_mount)
        
        console.print(f"[cyan]Querying for duplicates in:[/cyan] {target_location}")
        
        # Query for duplicates
        duplicate_records = archives_db.find_duplicates_in_location(target_location)
        
        if not duplicate_records:
            console.print("[yellow]No duplicate files found in this location.[/yellow]")
            return
        
        console.print(f"[green]Found {len(duplicate_records)} duplicate file instances.[/green]")
        
        # Apply filters
        filtered_records = apply_filters(duplicate_records)
        console.print(f"[green]After filtering: {len(filtered_records)} file instances to review.[/green]")
        
        # Remove already-processed files
        unprocessed_records = [
            rec for rec in filtered_records 
            if not sweep_db.is_file_processed(rec['archives_app_file_id'])
        ]
        
        console.print(f"[green]Unprocessed files: {len(unprocessed_records)} instances.[/green]")
        
        # Group by file_id
        grouped = group_by_file_id(unprocessed_records)
        
        if not grouped:
            console.print("[yellow]All files have already been processed.[/yellow]")
            return
        
        console.print(f"[green]Ready to review {len(grouped)} unique files.[/green]\n")
        
        # Create a processed_location record
        location_id = sweep_db.record_processed_location(
            location_path=location_path,
            duplicates_count=len(grouped),
            completed=False
        )
        
        # Periodic sync tracking
        last_sync_time = time.time()
        sync_interval = 600  # 10 minutes in seconds
        
        # Interactive review loop
        file_ids = list(grouped.keys())
        for file_idx, file_id in enumerate(file_ids, start=1):
            console.print(f"\n[bold cyan]File {file_idx} of {len(file_ids)}[/bold cyan]")
            
            # Get ALL locations for this file
            all_locations = archives_db.get_all_locations_for_file(file_id)
            
            # Display table
            display_file_locations(file_id, all_locations, file_server_mount, target_location)
            
            # Interactive prompt loop for this file
            while True:
                console.print("\n[yellow]Commands:[/yellow]")
                console.print("  [cyan]<numbers>[/cyan] - Delete specific instances (e.g., '1 3')")
                console.print("  [cyan]c[/cyan] - Keep all copies (mark processed)")
                console.print("  [cyan]o <#>[/cyan] - Open file for inspection")
                console.print("  [cyan]s[/cyan] - Skip this file")
                console.print("  [cyan]q[/cyan] - Quit and sync database")
                
                user_input = Prompt.ask("\nYour choice")
                cmd_type, numbers = parse_user_command(user_input)
                
                if cmd_type == 'invalid':
                    console.print("[red]Invalid command. Please try again.[/red]")
                    continue
                
                elif cmd_type == 'quit':
                    console.print("[yellow]Quitting and syncing database...[/yellow]")
                    sweep_db.sync_to_storage()
                    temp_manager.cleanup()
                    return
                
                elif cmd_type == 'skip':
                    console.print("[yellow]Skipping this file.[/yellow]")
                    break
                
                elif cmd_type == 'keep':
                    # Mark as processed with decision "kept_all"
                    sweep_db.record_processed_file(
                        archives_app_file_id=file_id,
                        processed_location_id=location_id,
                        decision='kept_all'
                    )
                    console.print("[green]Marked as processed (all copies kept).[/green]")
                    break
                
                elif cmd_type == 'open':
                    num = numbers[0]
                    if 1 <= num <= len(all_locations):
                        loc = all_locations[num - 1]
                        file_path = build_file_path(
                            file_server_mount,
                            loc['file_server_directories'],
                            loc['filename']
                        )
                        console.print(f"[cyan]Opening file: {file_path}[/cyan]")
                        if temp_manager.copy_and_open(file_path):
                            console.print("[green]File opened successfully.[/green]")
                        else:
                            console.print("[red]Failed to open file.[/red]")
                    else:
                        console.print("[red]Invalid file number.[/red]")
                    continue
                
                elif cmd_type == 'delete':
                    # Validate numbers
                    valid_numbers = [n for n in numbers if 1 <= n <= len(all_locations)]
                    if not valid_numbers:
                        console.print("[red]No valid file numbers specified.[/red]")
                        continue
                    
                    # Confirm deletion
                    console.print(f"\n[yellow]You are about to delete {len(valid_numbers)} file(s):[/yellow]")
                    for num in valid_numbers:
                        loc = all_locations[num - 1]
                        file_path = build_file_path(
                            file_server_mount,
                            loc['file_server_directories'],
                            loc['filename']
                        )
                        console.print(f"  [{num}] {file_path}")
                    
                    confirm = Prompt.ask("\nConfirm deletion? (yes/no)", default="no")
                    if confirm.lower() not in ['yes', 'y']:
                        console.print("[yellow]Deletion cancelled.[/yellow]")
                        continue
                    
                    # Record processed file
                    if len(valid_numbers) == len(all_locations):
                        decision = 'deleted_all'
                    else:
                        decision = 'deleted_some'
                    
                    processed_file_id = sweep_db.record_processed_file(
                        archives_app_file_id=file_id,
                        processed_location_id=location_id,
                        decision=decision
                    )
                    
                    # Delete each selected file
                    for num in valid_numbers:
                        loc = all_locations[num - 1]
                        file_path = build_file_path(
                            file_server_mount,
                            loc['file_server_directories'],
                            loc['filename']
                        )
                        
                        console.print(f"[cyan]Deleting: {file_path}[/cyan]")
                        success, error = archives_app.enqueue_delete_edit(str(file_path))
                        
                        if success:
                            # Record deletion
                            sweep_db.record_deleted_file(
                                processed_file_id=processed_file_id,
                                path=str(file_path),
                                file_size=loc['size']
                            )
                            console.print("[green]Deletion task enqueued successfully.[/green]")
                        else:
                            # Log error
                            sweep_db.log_error(
                                operation='delete',
                                message=error,
                                context=str(file_path)
                            )
                            console.print(f"[red]Error enqueuing deletion: {error}[/red]")
                    
                    console.print("[green]File processed.[/green]")
                    break
            
            # Periodic sync check
            current_time = time.time()
            if current_time - last_sync_time >= sync_interval:
                console.print("[cyan]\nPerforming periodic database sync...[/cyan]")
                sweep_db.sync_to_storage()
                last_sync_time = current_time
        
        # Mark location as completed
        console.print("\n[green]All files in location processed.[/green]")
        
    except Exception as e:
        console.print(f"[red]Error during sweep: {e}[/red]")
        if debug:
            import traceback
            console.print(traceback.format_exc())
        sweep_db.log_error(
            operation='sweep',
            message=str(e),
            context=location_path
        )
    
    finally:
        # Final sync and cleanup
        console.print("[cyan]Syncing database to storage...[/cyan]")
        sweep_db.sync_to_storage()
        sweep_db.close()
        archives_db.close()
        temp_manager.cleanup()
        console.print("[green]Sweep complete.[/green]")