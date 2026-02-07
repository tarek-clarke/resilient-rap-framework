"""
Test Semantic Translator
-------------------------
Demonstrates the BERT-based field reconciliation system.
Shows how messy sensor tags are mapped to the Gold Standard schema.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.translator import SemanticTranslator
from rich.console import Console
from rich.table import Table

console = Console()

def main():
    """Test the semantic translator with various messy field names."""
    
    console.print("\n[bold cyan]🧪 Semantic Translator Test[/bold cyan]\n")
    
    # Define Gold Standard Schema
    gold_standard = [
        "Heart Rate (bpm)",
        "Brake Temperature (Celsius)",
        "Tyre Pressure (psi)",
        "Speed (km/h)",
        "RPM",
        "Engine Temperature (°C)",
        "Throttle (%)",
        "Gear",
        "Blood Oxygen (O2 Saturation)",
        "Body Temperature (Celsius)"
    ]
    
    console.print("[yellow]Gold Standard Schema:[/yellow]")
    for field in gold_standard:
        console.print(f"  • {field}")
    
    # Initialize translator
    console.print("\n[yellow]Initializing BERT model (all-MiniLM-L6-v2)...[/yellow]")
    translator = SemanticTranslator(gold_standard)
    console.print("[green]✓ Model loaded[/green]\n")
    
    # Test cases: messy field names that should map to the gold standard
    test_cases = [
        # Clinical/Biometric
        ("hr_watch_01", "Heart Rate variant"),
        ("pulse_ox", "Pulse oximeter"),
        ("pulse_ox_fingertip", "Clinical pulse ox"),
        ("heart_bpm", "Heart rate BPM"),
        ("o2_sat_percent", "Oxygen saturation"),
        ("temp_celsius", "Body temperature"),
        
        # Mechanical
        ("brk_tmp_fr", "Brake temp variant"),
        ("brake_temp_front", "Front brake temp"),
        ("front_brake_celsius", "Brake celsius"),
        
        # Vehicle dynamics
        ("tyre_press_fl", "Tyre pressure variant"),
        ("tire_pressure", "Tire pressure"),
        ("car_velocity", "Vehicle velocity"),
        ("vehicle_speed", "Speed variant"),
        ("speed_kph", "Speed KPH"),
        
        # Engine
        ("eng_rpm_log", "Engine RPM variant"),
        ("engine_revs", "Engine revolutions"),
        ("motor_rpm", "Motor RPM"),
        ("eng_temp", "Engine temp short"),
        ("engine_temperature", "Engine temp full"),
        
        # Controls
        ("throttle_pct", "Throttle percentage"),
        ("accelerator", "Accelerator pedal"),
        ("current_gear", "Gear variant"),
        ("gear_position", "Gear position"),
        
        # Edge cases (should NOT match with high confidence)
        ("battery_voltage", "Should fail"),
        ("fuel_level", "Should fail"),
        ("random_sensor_xyz", "Should fail")
    ]
    
    # Run tests
    console.print("[bold magenta]🔧 Testing Semantic Reconciliation:[/bold magenta]\n")
    
    table = Table(title="Semantic Mapping Results (Threshold: 0.45)")
    table.add_column("Messy Field", style="yellow", width=25)
    table.add_column("Description", style="dim", width=20)
    table.add_column("Mapped To", style="green", width=28)
    table.add_column("Confidence", style="cyan", justify="right", width=10)
    table.add_column("Status", justify="center", width=6)
    
    success_count = 0
    failed_count = 0
    
    for messy_field, description in test_cases:
        target_field, confidence = translator.resolve(messy_field, threshold=0.45)
        
        if target_field:
            status = "✓"
            success_count += 1
            confidence_str = f"{confidence:.1%}"
            mapped_to = target_field
            style = "green"
        else:
            status = "✗"
            failed_count += 1
            confidence_str = f"{confidence:.1%}"
            mapped_to = "No match"
            style = "red"
        
        table.add_row(
            messy_field,
            description,
            mapped_to,
            confidence_str,
            f"[{style}]{status}[/{style}]"
        )
    
    console.print(table)
    
    # Summary
    console.print(f"\n[bold cyan]📊 Summary:[/bold cyan]")
    console.print(f"  Total tests: {len(test_cases)}")
    console.print(f"  [green]Successful mappings: {success_count}[/green]")
    console.print(f"  [red]Failed mappings: {failed_count}[/red]")
    console.print(f"  Success rate: {success_count/len(test_cases):.1%}")
    
    # Show threshold behavior
    console.print(f"\n[bold yellow]🎯 Threshold Analysis:[/bold yellow]")
    console.print(f"  Current threshold: 0.45 (45% confidence minimum)")
    console.print(f"  Fields below threshold are rejected to prevent false mappings")
    console.print(f"  This ensures high-quality semantic reconciliation")
    
    # Interactive example
    console.print(f"\n[bold cyan]💡 Try your own field:[/bold cyan]")
    console.print(f'  Example: python3 -c "from modules.translator import SemanticTranslator; t = SemanticTranslator({gold_standard[:3]}); print(t.resolve(\'hr_sensor\'))"')
    
    return success_count, failed_count


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")