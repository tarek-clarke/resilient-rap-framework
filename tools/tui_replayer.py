import sys
import os
import time
import pandas as pd
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.console import Console
from rich.prompt import Prompt

# Path setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import BOTH Adapters
from adapters.sports.ingestion_sports import SportsIngestor
from adapters.clinical.ingestion_clinical import ClinicalIngestor

console = Console()

# Define the "Messy" tags for highlighting purposes
MESSY_TAGS = [
    # F1 Tags
    'hr_watch_01', 'brk_tmp_fr', 'tyre_press_fl', 'car_velocity', 'eng_rpm_log',
    # Clinical Tags
    'pulse_ox_fingertip', 'o2_sat_percent', 'bp_sys_art_line', 'bp_dia_cuff', 'breaths_pm_vent'
]

def create_telemetry_table(df, title):
    """Creates the main data table."""
    table = Table(title=f"📡 {title}", expand=True)
    
    for col in df.columns:
        # Highlight messy columns in CYAN to show what the AI needs to fix
        if col in MESSY_TAGS:
            table.add_column(col, justify="right", style="cyan")
        else:
            table.add_column(col, justify="right")
    
    # Show last 10 rows
    for index, row in df.tail(10).iterrows():
        table.add_row(*[str(x) for x in row.values])
    return table

def create_resilience_panel(ingestor):
    """Visualizes the Semantic Mapping."""
    table = Table(title="🧠 Semantic Reconciliation Layer", border_style="green", expand=True)
    table.add_column("Incoming Tag", style="cyan")
    table.add_column("Mapped Standard", style="green")
    table.add_column("Confidence", style="magenta")

    if hasattr(ingestor, 'last_resolutions') and ingestor.last_resolutions:
        for res in ingestor.last_resolutions:
            table.add_row(
                str(res['raw_field']), 
                str(res['target_field']), 
                str(res['confidence'])
            )
    else:
        table.add_row("Scanning for drift...", "-", "-")
    
    return Panel(table, title="Autonomous Repair", expand=False)

def run_tui():
    console.clear()
    console.rule("[bold blue]Resilient RAP Framework[/bold blue]")
    
    # --- SELECT MODE ---
    mode = Prompt.ask(
        "Select Simulation Mode", 
        choices=["1", "2"], 
        default="1"
    )
    
    if mode == "1":
        ingestor = SportsIngestor(source_name="F1_Session_Live")
        title = "Live F1 Telemetry Stream"
        console.print("[green]🏎️  Initializing F1 Sports Protocol...[/green]")
    else:
        ingestor = ClinicalIngestor(source_name="ICU_Monitor_04")
        title = "Live ICU Patient Monitor"
        console.print("[green]🏥 Initializing Clinical HL7 Protocol...[/green]")
    
    time.sleep(1)

    # --- LAYOUT ---
    layout = Layout()
    layout.split_column(
        Layout(name="telemetry"), 
        Layout(name="resilience", size=12) 
    )

    with Live(layout, refresh_per_second=4, screen=True) as live:
        while True:
            try:
                # Run the pipeline
                df = ingestor.run()
                
                # Update TUI
                layout["telemetry"].update(create_telemetry_table(df, title))
                layout["resilience"].update(create_resilience_panel(ingestor))
                
                time.sleep(0.8)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Pipeline Error: {e}[/red]")
                break

if __name__ == "__main__":
    run_tui()