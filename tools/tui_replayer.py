import sys
import json
import time
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

# Initialize Console
console = Console()

class ResilientDashboard:
    def __init__(self):
        self.logs = []
        self.system_status = "HEALTHY"
        self.status_color = "green"
        self.processed_count = 0
        self.drifts_healed = 0
        
        # THIS IS THE MEMORY (The "Fix")
        # Maps bad_key -> good_key
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

        # Speed Logic
        speed = data.get('speed_kph', 0)
        speed_color = "green" if speed < 300 else "red blink"
        
        # Heart Rate Logic
        hr = data.get('heart_rate_bpm', 0)
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
        
        status_panel = Panel(
            Align.center(f"[bold {self.status_color}]{self.system_status}[/]", vertical="middle"),
            title="RESILIENCE LAYER",
            border_style=self.status_color,
            height=3
        )
        
        return Layout(
            Panel(log_text, title="SYSTEM LOGS", border_style="white"),
        )

    def process_packet(self, line):
        try:
            packet = json.loads(line)
            self.processed_count += 1
            
            # STEP 1: APPLY KNOWN FIXES (The "Memory")
            # If we learned a fix previously, apply it silently
            for bad_key, good_key in self.schema_map.items():
                if bad_key in packet:
                    packet[good_key] = packet.pop(bad_key)
            
            # STEP 2: DETECT NEW DRIFT
            if "speed_kmh" in packet and "speed_kmh" not in self.schema_map:
                # NEW ERROR -> TRIGGER RED ALERT
                self.system_status = "⚠️ DRIFT DETECTED"
                self.status_color = "red blink"
                self.logs.append(f"[red bold]ALERT: Schema mismatch 'speed_kmh'[/]")
                self.logs.append(f"[yellow]Agent: Analyzing semantics...[/]")
                
                # Simulate "Thinking" time (0.5s)
                time.sleep(0.5) 
                
                # THE FIX
                self.schema_map["speed_kmh"] = "speed_kph"  # Learn the fix
                packet["speed_kph"] = packet.pop("speed_kmh") # Apply fix
                self.drifts_healed += 1
                
                self.logs.append(f"[green bold]SUCCESS: Alias created. Resuming.[/]")
                
                # Return to Green
                self.system_status = "ACTIVE"
                self.status_color = "green"
            
            return packet
            
        except json.JSONDecodeError:
            return None

# --- EXECUTION LOGIC (This was missing) ---
dashboard = ResilientDashboard()

def run():
    layout = dashboard.make_layout()
    
    with Live(layout, refresh_per_second=10, screen=True):
        for line in sys.stdin:
            packet = dashboard.process_packet(line)
            if packet:
                layout["telemetry"].update(dashboard.generate_telemetry_table(packet))
                layout["logs"].update(dashboard.generate_log_panel())

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass