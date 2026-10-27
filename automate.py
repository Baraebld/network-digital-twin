#!/usr/bin/env python3
"""Network Automation CLI.

Simulates Netmiko automated configuration deployment and verification across
switches SW1, SW2 and router R1.

Reference: Section 2 of Rapport_TP_Reseau.pdf.
"""

import argparse
import sys
from pathlib import Path

from src.network_dt.automation.deploy import AutomationDeployer
from src.network_dt.core.state_engine import StateEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Automated Network Deployment & Verification")
    parser.add_argument("--verify-only", action="store_true", help="Run verification without redeploying")
    parser.add_argument("--inventory", default="config/devices.yaml", help="Path to devices inventory YAML")
    args = parser.parse_args()

    state = StateEngine()
    deployer = AutomationDeployer(state_engine=state, inventory_path=Path(args.inventory))

    print("=" * 70)
    print("NETWORK AUTOMATION ENGINE -- Netmiko Cisco IOS Deployment")
    print("=" * 70)

    if not args.verify_only:
        print(f"\n[*] Reading inventory from: {args.inventory}")
        for dev in deployer.inventory.devices:
            print(f"    - Found Device: {dev.get('name')} | Host: {dev.get('host')} | Type: {dev.get('device_type')}")

        print("\n[*] Starting automated configuration deployment...")
        actions = deployer.deploy_all()
        for act in actions:
            status_tag = "[OK]" if act.success else "[FAILED]"
            print(f"  {status_tag} {act.device_name:<12} | {act.action_type:<16} | {act.details}")

    print("\n[*] Running automated configuration verification (Section 2.5)...")
    report = deployer.verify_deployment()

    print("\n" + "-" * 70)
    print(f"{'CATEGORY':<14} {'TARGET':<24} {'STATUS':<10} {'DETAILS'}")
    print("-" * 70)
    for check in report.checks:
        status_str = "PASS" if check.passed else "FAIL"
        print(f"{check.category:<14} {check.target:<24} {status_str:<10} {check.actual}")
    print("-" * 70)

    print(f"\nVerification Result: {report.passed_count}/{report.total_count} checks passed.")
    if report.all_passed:
        print("[SUCCESS] All configurations verified. Network fully operational.\n")
        return 0
    else:
        print("[ERROR] One or more verification checks failed.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
