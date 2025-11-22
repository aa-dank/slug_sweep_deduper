"""CLI interface for Slug Sweep Deduper."""

import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from slug_sweep_deduper.service import SweepDB
from slug_sweep_deduper.sweep import run_sweep


console = Console()


def load_env_config() -> dict:
    """Load and validate environment configuration.
    
    Returns
    -------
    dict
        Dictionary of environment variables
    
    Raises
    ------
    SystemExit
        If required environment variables are missing
    """
    load_dotenv()
    
    required_vars = [
        'ARCHIVES_DB_HOST',
        'ARCHIVES_DB_NAME',
        'ARCHIVES_DB_USER',
        'ARCHIVES_DB_PASSWORD',
        'ARCHIVES_APP_URL',
        'ARCHIVES_APP_USER',
        'ARCHIVES_APP_PASSWORD',
        'SWEEP_DB_LOCATION',
        'FILE_SERVER_MOUNT',
    ]
    
    config = {}
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if value is None:
            missing_vars.append(var)
        else:
            config[var] = value
    
    if missing_vars:
        console.print("[red]Error: Missing required environment variables:[/red]")
        for var in missing_vars:
            console.print(f"  - {var}")
        console.print("\nPlease create a .env file with all required variables.")
        console.print("See .env.example for reference.")
        sys.exit(1)
    
    return config


@click.group()
@click.version_option(version="0.1.0")
def main():
    """Slug Sweep Deduper - Safe deduplication tool for PPDO archives."""
    pass


@main.command()
@click.argument('location', type=str)
@click.option('--debug', is_flag=True, help='Enable debug output')
def sweep(location: str, debug: bool):
    """Run interactive deduplication sweep for LOCATION.
    
    LOCATION should be a Windows path to the target directory.
    Example: N:\\PPDO\\Records\\42xx   Student Housing West\\4203\\4203
    """
    try:
        # Load environment config
        config = load_env_config()
        
        # Validate location path exists
        location_path = Path(location)
        if not location_path.exists():
            console.print(f"[red]Error: Location does not exist: {location}[/red]")
            sys.exit(1)
        
        if not location_path.is_dir():
            console.print(f"[red]Error: Location is not a directory: {location}[/red]")
            sys.exit(1)
        
        # Run sweep
        run_sweep(str(location_path), config, debug=debug)
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Sweep interrupted by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        if debug:
            import traceback
            console.print(traceback.format_exc())
        sys.exit(1)


@main.command('init-db')
def init_db():
    """Initialize a new SweepDB database.
    
    Creates a new sweep_db.sqlite file in the SWEEP_DB_LOCATION from .env.
    """
    try:
        config = load_env_config()
        
        db_location = config['SWEEP_DB_LOCATION']
        db_path = Path(db_location) / "sweep_db.sqlite"
        
        if db_path.exists():
            console.print(f"[yellow]Database already exists at: {db_path}[/yellow]")
            confirm = click.confirm("Do you want to overwrite it?", default=False)
            if not confirm:
                console.print("[yellow]Operation cancelled.[/yellow]")
                return
            db_path.unlink()
        
        # Create new database
        console.print(f"[cyan]Creating new database at: {db_path}[/cyan]")
        sweep_db = SweepDB(storage_location=db_location, staging_location='.')
        sweep_db.sync_to_storage()
        sweep_db.close()
        
        console.print("[green]Database created successfully.[/green]")
        
    except Exception as e:
        console.print(f"[red]Error creating database: {e}[/red]")
        sys.exit(1)


@main.command('sync-db')
def sync_db():
    """Manually sync the local database to storage.
    
    Copies the local sweep_db.sqlite to SWEEP_DB_LOCATION.
    """
    try:
        config = load_env_config()
        
        local_db = Path('.') / 'sweep_db.sqlite'
        if not local_db.exists():
            console.print("[red]Error: No local database found (sweep_db.sqlite).[/red]")
            sys.exit(1)
        
        console.print("[cyan]Syncing database to storage...[/cyan]")
        sweep_db = SweepDB(storage_location=config['SWEEP_DB_LOCATION'], staging_location='.')
        sweep_db.sync_to_storage()
        sweep_db.close()
        
        console.print("[green]Database synced successfully.[/green]")
        
    except Exception as e:
        console.print(f"[red]Error syncing database: {e}[/red]")
        sys.exit(1)


if __name__ == '__main__':
    main()