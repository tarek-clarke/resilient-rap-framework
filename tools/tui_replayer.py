import sys
import os
import time
import random
import pandas as pd
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.console import Console

# --- FIX: Add root directory to Python path so we can find 'modules' ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from adapters.sports.ingestion_sports import SportsIngestor

console = Console()

def create_telemetry_table(df):
    """Creates the main data table."""
    table = Table(title="🏎️  Live F1 Telemetry Stream")
    for col in df.columns:
        table.add_column(col, justify="right")
    
    # Show last 5 rows
    for index, row in df.tail(5).iterrows():
        table.add_row(*[str(x) for x in row.values])
    return table

def create_resilience_panel(ingestor):
    """
    VISUALIZES THE SEMANTIC LAYER.
    Shows exactly how the ML model mapped messy tags to standard ones.
    """
    table = Table(title="🧠 Semantic Reconciliation Layer", border_style="green")
    table.add_column("Incoming Tag", style="cyan")
    table.add_column("Mapped Standard", style="green")
    table.add_column("Confidence", style="magenta")

    # This hooks into the 'last_resolutions' we added to BaseIngestor
    if hasattr(ingestor, 'last_resolutions'):
        for res in ingestor.last_resolutions:
            table.add_row(
                str(res['raw_field']), 
                str(res['target_field']), 
                str(res['confidence'])
            )
    else:
        table.add_row("Waiting for data...", "-", "-")
    
    return Panel(table, title="Autonomous Repair", expand=False)

def run_tui():
    # 1. Initialize the Resilient Ingestor
    ingestor = SportsIngestor(source_name="Live_TUI_Session")
    
    layout = Layout()
    layout.split_column(
        Layout(name="telemetry", ratio=2),
        Layout(name="resilience", ratio=1)
    )

    console.print("[bold yellow]Initializing Resilient RAP Framework...[/bold yellow]")
    time.sleep(1)

    with Live(layout, refresh_per_second=4) as live:
        while True:
            # Run the full pipeline (Connect -> Extract -> Semantic Fix)
            try:
                df = ingestor.run()
                
                # Simulate "Live" updates by tweaking values slightly
                # (Just for demo purposes so numbers move)
                for col in df.select_dtypes(include='number').columns:
                    df[col] = df[col] + random.uniform(-0.5, 0.5)

                # Update the Layout
                layout["telemetry"].update(create_telemetry_table(df))
                layout["resilience"].update(create_resilience_panel(ingestor))
                
                time.sleep(0.8) # Simulate 1.25Hz polling rate
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Pipeline Error: {e}[/red]")
                break

if __name__ == "__main__":
    run_tui()