#!/usr/bin/env python3
"""Digital Network (Digital Twin) CLI.

Executes baseline calibration and Digital Twin integrity checks against the
Golden State reference model.

Reference: Section 5, Figures 16 & 17 of Rapport_TP_Reseau.pdf.
"""

import argparse
import sys
from pathlib import Path

from src.network_dt.core.state_engine import StateEngine
from src.network_dt.twin.engine import DigitalTwinEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Network Digital Twin Integrity Engine")
    parser.add_argument(
        "mode",
        nargs="?",
        default="check",
        choices=["calibrate", "check"],
        help="Run mode: 'calibrate' (learn normal state) or 'check' (evaluate live integrity)",
    )
    parser.add_argument(
        "--model",
        default="data/network_golden_state.json",
        help="Path to Golden State reference JSON file",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite of existing Golden State during calibration",
    )
    args = parser.parse_args()

    # Fallback to root network_golden_state.json if data/ path doesn't exist
    model_path = Path(args.model)
    if not model_path.exists() and Path("network_golden_state.json").exists():
        model_path = Path("network_golden_state.json")

    state = StateEngine()
    engine = DigitalTwinEngine(state_engine=state, golden_state_path=model_path)

    if args.mode == "calibrate":
        print("[MODE: CALIBRATION] Learning network behavior...")
        print("-> Scanning ROUTER-GW...")
        print("-> Scanning SWITCH-A...")
        print("-> Scanning SWITCH-B...")

        try:
            engine.calibrate(force=args.force)
        except FileExistsError as err:
            print(f"\n[WARNING] {err}")
            print("Use --force to overwrite the existing Golden State baseline.\n")
            return 1

        print(f"\n[SUCCESS] Digital Twin Model saved to '{model_path}'.")
        print("The system now knows what 'Normal' looks like.\n")
        return 0

    # Default mode: Integrity Check
    print("DIGITAL TWIN INTEGRITY CHECK")
    print("=" * 50)
    print("Analyzing ROUTER-GW...")
    print("Analyzing SWITCH-A...")
    print("Analyzing SWITCH-B...")

    try:
        result = engine.check_integrity()
    except FileNotFoundError as err:
        print(f"\n[ERROR] {err}\n")
        return 1

    print(f"\n[ integrity: {result.score}% ] {result.status_message}")

    if result.has_deviations:
        print("\n--- DETECTED FAULTS (Deviation from Model) ---")
        for alert in result.alerts:
            print(alert.message)
        print()
        return 2

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
