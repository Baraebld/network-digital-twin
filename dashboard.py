#!/usr/bin/env python3
"""Local Network Digital Twin & Monitoring Dashboard Launcher.

Serves an interactive web dashboard integrating the simulated network,
SNMP telemetry, fault injection, Cisco CLI diagnostics, and Digital Twin verification.
"""

import argparse
import sys
from pathlib import Path

from src.network_dt.core.state_engine import StateEngine
from src.network_dt.monitoring.dashboard import create_dashboard_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Network Digital Twin & Monitoring Web Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--model", default="data/network_golden_state.json", help="Path to Golden State JSON model")
    args = parser.parse_args()

    state = StateEngine()
    server = create_dashboard_server(
        host=args.host,
        port=args.port,
        state_engine=state,
        golden_path=Path(args.model),
    )

    print("=" * 70)
    print("NETWORK DIGITAL TWIN & MONITORING DASHBOARD")
    print("=" * 70)
    print(f"\n[+] Dashboard URL: http://{args.host}:{args.port}/")
    print(f"[+] Shared State : {state.state_file}")
    print(f"[+] Golden Model : {args.model}")
    print("[+] Environment  : 100% Pure Software Simulation (No physical equipment)")
    print("[+] Auto-refresh : 10 seconds")
    print("\nPress Ctrl+C to terminate the dashboard server.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down dashboard server...")
        server.server_close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
