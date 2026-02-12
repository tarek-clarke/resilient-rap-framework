"""
OpenF1 Adapter Demo
-------------------
Demonstrates how to use the OpenF1Adapter to fetch real F1 telemetry data.

Usage:
    python tools/demo_openf1.py --session 9158 --driver 1
"""
import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.openf1.ingestion_openf1 import OpenF1Adapter
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def main():
    parser = argparse.ArgumentParser(description='Fetch F1 telemetry from OpenF1 API')
    parser.add_argument(
        '--session',
        type=int,
        default=9158,
        help='Session key (e.g., 9158 for 2024 Abu Dhabi GP)'
    )
    parser.add_argument(
        '--driver',
        type=int,
        default=None,
        help='Driver number (optional, fetches all if not specified)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Number of records to display'
    )
    
    args = parser.parse_args()
    
    console.print("\n[bold cyan]🏎️  OpenF1 Telemetry Ingestion Demo[/bold cyan]")
    console.print(f"Session: {args.session}, Driver: {args.driver or 'All'}\n")
    
    try:
        # Initialize the adapter
        console.print("[yellow]Initializing OpenF1 Adapter...[/yellow]")
        adapter = OpenF1Adapter(
            session_key=args.session,
            driver_number=args.driver
        )
        
        # Fetch and process data
        console.print("[yellow]Fetching telemetry data...[/yellow]")
        df = adapter.fetch_data()
        
        # Display results
        console.print(f"\n[green]✓ Successfully fetched {len(df)} telemetry records[/green]\n")
        
        # Show data table
        table = Table(title=f"F1 Telemetry Data (First {args.limit} records)")
        
        for col in df.columns[:8]:  # Show first 8 columns
            table.add_column(col, style="cyan")
        
        for _, row in df.head(args.limit).iterrows():
            table.add_row(*[str(row[col])[:20] for col in df.columns[:8]])
        
        console.print(table)
        
        # Show semantic reconciliation results
        if adapter.last_resolutions:
            console.print("\n[bold magenta]🔧 Semantic Reconciliation Results:[/bold magenta]")
            for resolution in adapter.last_resolutions[:5]:
                console.print(
                    f"  [yellow]{resolution['raw_field']}[/yellow] → "
                    f"[green]{resolution['target_field']}[/green] "
                    f"(confidence: {resolution['confidence']:.2%})"
                )
        
        # Show lineage summary
        console.print(f"\n[bold blue]📋 Pipeline Lineage:[/bold blue]")
        for entry in adapter.lineage:
            console.print(f"  • {entry['stage']} at {entry['timestamp']}")
        
        # Export audit log
        audit_path = "data/openf1_audit.json"
        adapter.export_audit_log(audit_path)
        console.print(f"\n[green]✓ Audit log exported to: {audit_path}[/green]")
        
        # Show data statistics
        console.print("\n[bold cyan]📊 Data Statistics:[/bold cyan]")
        stats_table = Table()
        stats_table.add_column("Metric", style="yellow")
        stats_table.add_column("Value", style="green")
        
        if 'vehicle_speed' in df.columns:
            stats_table.add_row("Avg Speed", f"{df['vehicle_speed'].mean():.2f} km/h")
            stats_table.add_row("Max Speed", f"{df['vehicle_speed'].max():.2f} km/h")
        
        if 'engine_rpm' in df.columns:
            stats_table.add_row("Avg RPM", f"{df['engine_rpm'].mean():.0f}")
            stats_table.add_row("Max RPM", f"{df['engine_rpm'].max():.0f}")
        
        stats_table.add_row("Total Records", str(len(df)))
        stats_table.add_row("Unique Drivers", str(df['driver_num'].nunique()) if 'driver_num' in df.columns else "N/A")
        
        console.print(stats_table)
        
    except ConnectionError as e:
        console.print(f"\n[red]✗ Connection Error: {e}[/red]")
        console.print("[yellow]Tip: Check your internet connection and API availability[/yellow]")
        return 1
        
    except Exception as e:
        console.print(f"\n[red]✗ Error: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
