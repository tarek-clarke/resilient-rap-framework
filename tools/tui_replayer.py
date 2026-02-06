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
from rich.text import Text

# Path setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import BOTH Adapters
from adapters.sports.ingestion_sports import SportsIngestor
from adapters.clinical.ingestion_clinical import ClinicalIngestor

# Import F1 Telemetry Logger
from modules.f1_telemetry_logger import F1TelemetryLogger

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
    
    # Column name mapping (in case semantic layer didn't catch everything)
    clean_names = {
        # F1 Headers
        'driver_id': 'Driver',
        'hr_watch_01': 'Heart Rate (bpm)',
        'brk_tmp_fr': 'Brake Temp (°C)',
        'tyre_press_fl': 'Tyre Pressure (psi)',
        'car_velocity': 'Speed (km/h)',
        'eng_rpm_log': 'RPM',
        # ICU Headers
        'patient_id': 'Patient ID',
        'pulse_ox_fingertip': 'Heart Rate (bpm)',
        'o2_sat_percent': 'SpO2 (%)',
        'bp_sys_art_line': 'Systolic BP (mmHg)',
        'bp_dia_cuff': 'Diastolic BP (mmHg)',
        'breaths_pm_vent': 'Resp Rate (/min)'
    }
    
    for col in df.columns:
        # Use clean name if available, otherwise use original
        display_name = clean_names.get(col, col)
        
        # Highlight originally-messy columns in CYAN to show what the AI fixed
        if col in MESSY_TAGS:
            table.add_column(display_name, justify="right", style="cyan")
        else:
            table.add_column(display_name, justify="right")
    
    # Show all 20 drivers (full grid)
    for index, row in df.tail(20).iterrows():
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

def create_high_freq_telemetry_table(telemetry_data):
    """Creates table for high-frequency F1 telemetry logger."""
    table = Table(title="🏎️ High-Frequency Telemetry (50Hz IMU + GPS)", expand=True)
    
    # IMU columns
    table.add_column("Sample", justify="right", style="dim")
    table.add_column("Time (s)", justify="right")
    table.add_column("G-Lateral", justify="right", style="yellow")
    table.add_column("G-Long", justify="right", style="yellow")
    table.add_column("G-Vert", justify="right", style="yellow")
    table.add_column("Speed (kph)", justify="right", style="cyan")
    table.add_column("Heading", justify="right", style="cyan")
    
    # Show last 12 samples
    for sample in telemetry_data[-12:]:
        imu = sample['imu']
        gps = sample['gps']
        
        # Extract values handling chaos-injected field names
        gx = imu.get('gx') or imu.get('g_force_lateral', 0.0)
        gy = imu.get('gy') or imu.get('g_force_longitudinal', 0.0)
        gz = imu.get('gz') or imu.get('g_force_vertical', 0.0)
        speed = gps.get('speed', 0.0)
        heading = gps.get('heading', 0.0)
        
        table.add_row(
            f"{sample['sample_id']:05d}",
            f"{sample['elapsed_time_s']:.2f}",
            f"{gx:+.2f}G",
            f"{gy:+.2f}G",
            f"{gz:+.2f}G",
            f"{speed:.0f}",
            f"{heading:.0f}°"
        )
    
    return table

def create_chaos_panel(logger):
    """Shows chaos injection status and self-healing stats."""
    table = Table(title="⚡ Chaos Engineering Panel", border_style="red", expand=True)
    table.add_column("Metric", style="white")
    table.add_column("Value", justify="right", style="magenta")
    
    chaos_status = "🔴 ACTIVE" if logger.chaos_active else "🟢 NORMAL"
    table.add_row("Chaos State", chaos_status)
    table.add_row("Schema Drift Events", str(len(logger.drift_events)))
    table.add_row("Auto-Repairs", str(logger.auto_repairs))
    table.add_row("Learned Mappings", str(len(logger.schema_map)))
    
    # Show recent mappings
    if logger.schema_map:
        table.add_row("", "")  # Spacer
        table.add_row("[bold]Recent Mappings:[/bold]", "")
        for messy, gold in list(logger.schema_map.items())[-3:]:
            table.add_row(f"  '{messy}'", f"→ '{gold}'")
    
    return Panel(table, title="🛡️ Self-Healing System", expand=False)

def run_tui():
    console.clear()
    console.rule("[bold blue]Resilient RAP Framework[/bold blue]")
    
    # --- SELECT MODE ---
    console.print("\n[bold]Available Simulation Modes:[/bold]")
    console.print("  [1] F1 Sports Telemetry (Static Chaos)")
    console.print("  [2] ICU Clinical Monitor (FHIR/HL7)")
    console.print("  [3] F1 High-Frequency Logger (Dynamic Chaos + Self-Healing) [bold green]← NEW![/bold green]")
    
    mode = Prompt.ask(
        "\nSelect Mode", 
        choices=["1", "2", "3"], 
        default="3"
    )
    
    if mode == "1":
        ingestor = SportsIngestor(source_name="F1_Session_Live")
        title = "Live F1 Telemetry Stream"
        console.print("[green]🏎️  Initializing F1 Sports Protocol...[/green]")
        use_high_freq_logger = False
    elif mode == "2":
        ingestor = ClinicalIngestor(source_name="ICU_Monitor_04")
        title = "Live ICU Patient Monitor"
        console.print("[green]🏥 Initializing Clinical HL7 Protocol...[/green]")
        use_high_freq_logger = False
    else:
        # Mode 3: High-frequency telemetry logger
        console.print("[green]🏎️  Initializing High-Frequency Telemetry Logger (50Hz)...[/green]")
        console.print("[yellow]⚡ Chaos injection enabled - random schema drift every 50 samples[/yellow]")
        logger = F1TelemetryLogger(
            driver_id="VER",
            sample_rate_hz=10,  # Reduced for TUI readability
            enable_chaos=True,
            chaos_frequency=50
        )
        use_high_freq_logger = True
        telemetry_buffer = []
    
    time.sleep(1)

    # --- LAYOUT ---
    layout = Layout()
    layout.split_column(
        Layout(name="telemetry"), 
        Layout(name="resilience", size=14) 
    )

    with Live(layout, refresh_per_second=4, screen=True) as live:
        if use_high_freq_logger:
            # High-frequency logger mode
            telemetry_stream = logger.generate_telemetry_stream()
            
            while True:
                try:
                    # Get next telemetry packet
                    packet = next(telemetry_stream)
                    telemetry_buffer.append(packet)
                    
                    # Keep only last 100 samples
                    if len(telemetry_buffer) > 100:
                        telemetry_buffer.pop(0)
                    
                    # Update TUI
                    layout["telemetry"].update(create_high_freq_telemetry_table(telemetry_buffer))
                    layout["resilience"].update(create_chaos_panel(logger))
                    
                except StopIteration:
                    console.print("[yellow]Telemetry stream ended[/yellow]")
                    break
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    console.print(f"[red]Pipeline Error: {e}[/red]")
                    break
        else:
            # Original ingestor mode
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