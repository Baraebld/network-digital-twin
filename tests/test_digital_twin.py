"""Unit tests for the Network Digital Twin Golden State prototype (Part 5).

Validates baseline calibration, safe overwrite protection, comparison against
the shared network simulator, exact 100% -> 98% -> 100% integrity scoring,
and deviation alert generation matching Section 5 of the report.
"""

import tempfile
import unittest
from pathlib import Path

from src.network_dt.core.state_engine import StateEngine
from src.network_dt.twin.engine import DigitalTwinEngine


class TestDigitalTwin(unittest.TestCase):
    """Test suite for Golden State comparison and integrity check."""

    def setUp(self) -> None:
        """Create an isolated temporary environment with state engine and twin engine."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "simulated_network.json"
        self.golden_path = Path(self.temp_dir.name) / "network_golden_state.json"

        self.state = StateEngine(state_file=self.state_file)
        self.engine = DigitalTwinEngine(
            state_engine=self.state,
            golden_state_path=self.golden_path,
        )

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_baseline_creation_and_overwrite_protection(self) -> None:
        """Verify baseline creation and guard against accidental overwriting."""
        # 1. Initial calibration creates the file
        self.assertFalse(self.golden_path.exists())
        self.engine.calibrate(force=False)
        self.assertTrue(self.golden_path.exists())

        # 2. Subsequent calibration without force must raise FileExistsError
        with self.assertRaises(FileExistsError):
            self.engine.calibrate(force=False)

        # 3. Calibration with force=True succeeds
        model = self.engine.calibrate(force=True)
        self.assertIn("ROUTER-GW", model)
        self.assertIn("SWITCH-A", model)
        self.assertIn("SWITCH-B", model)

    def test_missing_golden_state_error(self) -> None:
        """Verify check_integrity raises FileNotFoundError if model has not been calibrated."""
        uncalibrated_path = Path(self.temp_dir.name) / "missing_model.json"
        engine = DigitalTwinEngine(state_engine=self.state, golden_state_path=uncalibrated_path)
        with self.assertRaises(FileNotFoundError):
            engine.check_integrity()

    def test_normal_state_integrity(self) -> None:
        """Verify pristine network produces exactly 100% integrity and healthy status."""
        self.engine.calibrate(force=True)
        result = self.engine.check_integrity()

        self.assertEqual(result.score, 100)
        self.assertEqual(result.total_monitored, 50)
        self.assertEqual(result.total_matching, 50)
        self.assertTrue(result.is_healthy)
        self.assertFalse(result.has_deviations)
        self.assertEqual(result.status_message, "SYSTEM HEALTHY - MATCHES TWIN MODEL")
        self.assertEqual(len(result.alerts), 0)

    def test_documented_failure_98_percent_and_alert(self) -> None:
        """Verify shutting down SW1 Gi1/0/17 yields 98% score and exact deviation alert."""
        # Calibrate pristine state (50 items)
        self.engine.calibrate(force=True)

        # Simulate documented failure: SW1 GigabitEthernet1/0/17 is shut down
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "DOWN")

        # Evaluate Digital Twin integrity
        result = self.engine.check_integrity()

        self.assertEqual(result.score, 98, "Integrity score must be exactly 98% on 1 port failure")
        self.assertEqual(result.total_monitored, 50)
        self.assertEqual(result.total_matching, 49)
        self.assertFalse(result.is_healthy)
        self.assertTrue(result.has_deviations)
        self.assertEqual(result.status_message, "WARNING - DEVIATION DETECTED")

        # Verify alert content matches Figure 16
        self.assertEqual(len(result.alerts), 1)
        alert = result.alerts[0]
        self.assertEqual(alert.device_name, "SWITCH-A")
        self.assertEqual(alert.interface_name, "GigabitEthernet1/0/17")
        self.assertEqual(alert.actual_status, "DOWN")
        self.assertEqual(alert.expected_status, "UP")
        self.assertIn("STATE MISMATCH: GigabitEthernet1/0/17 is DOWN (Model expects UP)", alert.message)

    def test_full_recovery_restores_100_percent(self) -> None:
        """Verify post-remediation recovery restores 100% score and resolves all alerts."""
        self.engine.calibrate(force=True)

        # 1. Inject failure
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "DOWN")
        res_fail = self.engine.check_integrity()
        self.assertEqual(res_fail.score, 98)

        # 2. Remediate failure (no shutdown)
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "UP")

        # 3. Re-evaluate
        res_recovered = self.engine.check_integrity()
        self.assertEqual(res_recovered.score, 100)
        self.assertEqual(res_recovered.total_matching, 50)
        self.assertTrue(res_recovered.is_healthy)
        self.assertFalse(res_recovered.has_deviations)
        self.assertEqual(res_recovered.status_message, "SYSTEM HEALTHY - MATCHES TWIN MODEL")
        self.assertEqual(len(res_recovered.alerts), 0)

    def test_transparent_scoring_formula(self) -> None:
        """Verify the mathematical scoring rule (round(matching / total * 100)) on multiple deviations."""
        self.engine.calibrate(force=True)

        # Two interfaces down: SW1 Gi1/0/7 and Gi1/0/17
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/7", "DOWN")
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "DOWN")

        result = self.engine.check_integrity()
        # 48 / 50 = 0.96 -> 96%
        self.assertEqual(result.total_matching, 48)
        self.assertEqual(result.score, 96)
        self.assertEqual(len(result.alerts), 2)


if __name__ == "__main__":
    unittest.main()
