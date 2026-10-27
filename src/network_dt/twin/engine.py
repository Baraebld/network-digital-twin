"""Digital Twin engine based on Golden State comparison.

Compares the active network state against a baseline model (network_golden_state.json),
computes an integrity score, and flags operational deviations.

Note:
This implementation is an educational Golden State comparison prototype,
designed to validate network configuration integrity against a reference baseline,
rather than an industrial real-time digital twin.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.state_engine import StateEngine
from .models import DeviationAlert, IntegrityCheckResult


class DigitalTwinEngine:
    """Orchestrates baseline calibration and live integrity verification."""

    DEFAULT_GOLDEN_STATE_PATH = Path("data") / "network_golden_state.json"

    def __init__(
        self,
        state_engine: Optional[StateEngine] = None,
        golden_state_path: Optional[Path] = None,
    ):
        self.state = state_engine if state_engine is not None else StateEngine()
        self.golden_state_path = Path(golden_state_path) if golden_state_path else self.DEFAULT_GOLDEN_STATE_PATH

    def calibrate(self, force: bool = False) -> Dict[str, Any]:
        """Capture the current operational state and write it to the Golden State file.
        
        Args:
            force: If False, prevents silently overwriting an existing Golden State file.
            
        Returns:
            Dictionary representation of the saved Golden State model.
            
        Raises:
            FileExistsError: If the Golden State file already exists and force is False.
        """
        if self.golden_state_path.exists() and not force:
            raise FileExistsError(
                f"Golden State already exists at '{self.golden_state_path}'. "
                f"Specify force=True to overwrite."
            )

        # Re-read active state to ensure up-to-date baseline
        self.state.load()
        baseline_data = self.state.export_canonical_50_interfaces()

        # Format consistent with report Figure 15
        formatted_model: Dict[str, Any] = {}
        for dev_name in ["ROUTER-GW", "SWITCH-A", "SWITCH-B"]:
            dev = self.state.get_device(dev_name)
            if not dev:
                continue
            ifaces = baseline_data.get(dev_name, {})
            formatted_model[dev_name] = {
                "ip": dev.primary_ip,
                "interfaces": ifaces,
            }

        self.golden_state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.golden_state_path, "w", encoding="utf-8") as f:
            json.dump(formatted_model, f, indent=2)

        return formatted_model

    def load_golden_state(self) -> Dict[str, Any]:
        """Load and parse the reference Golden State model from disk."""
        if not self.golden_state_path.exists():
            raise FileNotFoundError(
                f"Golden State file not found at '{self.golden_state_path}'. "
                f"Run calibration first ('python dn.py calibrate')."
            )

        with open(self.golden_state_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def check_integrity(self) -> IntegrityCheckResult:
        """Evaluate the current shared network state against the Golden State reference.
        
        Scoring Rule:
        The canonical prototype monitors N_total = 50 interfaces across the 3 devices:
        - 2 router uplinks (Gi0/0, Gi0/1)
        - 24 switch ports on Switch A (Gi1/0/1 to Gi1/0/24)
        - 24 switch ports on Switch B (Gi1/0/1 to Gi1/0/24)
        
        Integrity score is calculated as:
            Score = round((N_matching / N_total) * 100)
            
        - Normal baseline: 50/50 matching -> 100%
        - 1 failure (e.g. SW1 Gi1/0/17 DOWN): 49/50 matching -> 98%
        - Recovery: 50/50 matching -> 100%
        
        This ratio is a transparent prototype drift metric, not an industry-standard index.
        """
        # Always reload shared persistent state so concurrent/recent mutations are visible
        self.state.load()
        model = self.load_golden_state()

        analyzed_devices: List[str] = []
        alerts: List[DeviationAlert] = []
        total_monitored = 0
        total_matching = 0

        for dev_name, dev_data in model.items():
            analyzed_devices.append(dev_name)
            expected_ifaces = dev_data.get("interfaces", {})
            live_dev = self.state.get_device(dev_name)

            for if_name, expected_status in expected_ifaces.items():
                total_monitored += 1
                expected_norm = expected_status.upper()

                if not live_dev or not live_dev.is_reachable:
                    actual_status = "UNREACHABLE"
                    alerts.append(DeviationAlert(
                        device_name=dev_name,
                        interface_name=if_name,
                        actual_status=actual_status,
                        expected_status=expected_norm,
                        message=f"> [{dev_name}] STATE MISMATCH: Device is UNREACHABLE (Model expects {if_name} {expected_norm})",
                    ))
                    continue

                live_iface = live_dev.get_interface(if_name)
                actual_status = live_iface.oper_status.upper() if live_iface else "MISSING"

                if actual_status == expected_norm:
                    total_matching += 1
                else:
                    msg = f"> [{dev_name}] STATE MISMATCH: {if_name} is {actual_status} (Model expects {expected_norm})"
                    alerts.append(DeviationAlert(
                        device_name=dev_name,
                        interface_name=if_name,
                        actual_status=actual_status,
                        expected_status=expected_norm,
                        message=msg,
                    ))

        if total_monitored > 0:
            score = round((total_matching / total_monitored) * 100)
        else:
            score = 100

        is_healthy = (score == 100 and len(alerts) == 0)
        status_msg = "SYSTEM HEALTHY - MATCHES TWIN MODEL" if is_healthy else "WARNING - DEVIATION DETECTED"

        return IntegrityCheckResult(
            score=score,
            total_monitored=total_monitored,
            total_matching=total_matching,
            is_healthy=is_healthy,
            status_message=status_msg,
            alerts=alerts,
            analyzed_devices=analyzed_devices,
        )
