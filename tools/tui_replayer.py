import sys
import json
import time
import traceback
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

# FIX 1: Force Terminal Mode (Critical for Docker/Pipes)
console = Console(force_terminal=True)

class ResilientDashboard:
    def __init__(self):
        self.logs = []
        self.system_status = "HEALTHY"
        self.status_color = "green"
        self.processed_count = 0
        self.drifts_healed = 0
        self.schema_map = {} 

    def make_layout(self):
        layout = Layout()
        layout.split_row(
            Layout(name="telemetry", ratio=2),
            Layout(name="logs", ratio=1)
        )
        return layout

    def generate_telemetry_table(self, data):
        table = Table(title="🏎️  LIVE F1 TELEMETRY FEED (50Hz)", expand=True, box=box.ROUNDED, border_style="blue")
        table.add_column("Metric", style="dim")
        table.add_column("Value", justify="right", style="bold white")
        table.add_column("Status", justify="center")

        if not data:
            return table

        speed = float(data.get('speed_kph', 0))
        speed_color = "green" if speed < 300 else "red blink"
        
        hr = float(data.get('heart_rate_bpm', 0))
        hr_bar = "♥" * (int(hr) // 20)
        
        table.add_row("Speed", f"[{speed_color}]{speed:.1f} KPH[/]", "✅")
        table.add_row("RPM", f"{data.get('rpm', 0)}", "✅")
        table.add_row("Heart Rate", f"{hr} BPM", f"[red]{hr_bar}[/]")
        table.add_row("Throttle", f"{data.get('throttle_pct', 0)}%", "✅")
        
        return Panel(
            Align.center(table, vertical="middle"),
            title="INGESTION STREAM",
            border_style="blue"
        )

    def generate_log_panel(self):
        log_text = Text()
        for log in self.logs[-12:]:
            log_text.append(log + "\n")
        
        return Layout(
            Panel(log_text, title="SYSTEM LOGS", border_style="white"),
        )

    def process_packet(self, line):
        try:
            # Skip empty lines
            if not line.strip(): 
                return None
                
            packet = json.loads(line)
            self.processed_count += 1
            
            # MEMORY APPLIED
            for bad_key, good_key in self.schema_map.items():
                if bad_key in packet:
                    packet[good_key] = packet.pop(bad_key)
            
            # DRIFT DETECTION
            if "speed_kmh" in packet and "speed_kmh" not in self.schema_map:
                self.system_status = "⚠️ DRIFT DETECTED"
                self.status_color = "red blink"
                self.logs.append(f"[red bold]ALERT: Schema mismatch 'speed_kmh'[/]")
                self.logs.append(f"[yellow]Agent: Analyzing semantics...[/]")
                time.sleep(0.5) 
                
                self.schema_map["speed_kmh"] = "speed_kph"
                packet["speed_kph"] = packet.pop("speed_kmh")
                self.drifts_healed += 1
                
                self.logs.append(f"[green bold]SUCCESS: Alias created. Resuming.[/]")
                self.system_status = "ACTIVE"
                self.status_color = "green"
            
            return packet
        except Exception:
            return None

dashboard = ResilientDashboard()

def run():
    layout = dashboard.make_layout()
    # Initialize empty
    layout["telemetry"].update(dashboard.generate_telemetry_table(None))
    layout["logs"].update(dashboard.generate_log_panel())
    
    # PASS THE CONSOLE TO LIVE
    with Live(layout, refresh_per_second=10, screen=True, console=console):
        for line in sys.stdin:
            packet = dashboard.process_packet(line)
            if packet:
                layout["telemetry"].update(dashboard.generate_telemetry_table(packet))
                layout["logs"].update(dashboard.generate_log_panel())

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        # LOG CRASH TO FILE
        with open("crash.log", "w") as f:
            f.write(traceback.format_exc())