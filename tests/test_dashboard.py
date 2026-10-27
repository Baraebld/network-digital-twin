"""Integration tests for the local web dashboard and REST API.

Tests the dashboard server, status endpoint, fault injection (/api/troubleshoot/shutdown),
diagnostic command execution, and link recovery (/api/troubleshoot/recover).
"""

import json
import socket
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from src.network_dt.core.state_engine import StateEngine
from src.network_dt.monitoring.dashboard import create_dashboard_server
from src.network_dt.twin.engine import DigitalTwinEngine


def find_free_port() -> int:
    """Find an available local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestDashboardIntegration(unittest.TestCase):
    """End-to-end integration tests for dashboard HTTP endpoints."""

    def setUp(self) -> None:
        """Start local dashboard server on an ephemeral port with an isolated state file."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "simulated_network.json"
        self.golden_path = Path(self.temp_dir.name) / "network_golden_state.json"

        # Initialize baseline state & golden state
        self.state = StateEngine(state_file=self.state_file)
        twin = DigitalTwinEngine(state_engine=self.state, golden_state_path=self.golden_path)
        twin.calibrate(force=True)

        self.port = find_free_port()
        self.server = create_dashboard_server(
            host="127.0.0.1",
            port=self.port,
            state_engine=self.state,
            golden_path=self.golden_path,
        )

        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        """Shutdown server and clean up directory."""
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2.0)
        self.temp_dir.cleanup()

    def _get(self, path: str) -> tuple[int, bytes]:
        req = urllib.request.Request(f"{self.base_url}{path}")
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read()

    def _post_json(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_html_dashboard_serves_simulation_notice(self) -> None:
        """Verify root page returns HTML with clear simulation disclaimer."""
        status, body = self._get("/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("Pure Software Simulation", html)
        self.assertIn("100% simulated in-process in Python", html)
        self.assertIn("Digital Twin Integrity", html)
        self.assertIn("SWITCH-A (SW1)", html)

    def test_full_failure_and_recovery_flow(self) -> None:
        """Verify the full lifecycle: normal (100%) -> failure (98%) -> recovery (100%)."""
        # 1. Baseline status
        status, body = self._get("/api/status")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["digital_twin"]["score"], 100)
        self.assertTrue(data["digital_twin"]["is_healthy"])
        self.assertEqual(len(data["digital_twin"]["alerts"]), 0)

        # 2. Trigger Failure: Shutdown SW1 Gi1/0/17
        post_status, post_resp = self._post_json("/api/troubleshoot/shutdown")
        self.assertEqual(post_status, 200)
        self.assertTrue(post_resp["success"])

        # 3. Verify Degraded State: 98% integrity and alert
        _, body_fail = self._get("/api/status")
        data_fail = json.loads(body_fail.decode("utf-8"))
        self.assertEqual(data_fail["digital_twin"]["score"], 98)
        self.assertFalse(data_fail["digital_twin"]["is_healthy"])
        self.assertEqual(len(data_fail["digital_twin"]["alerts"]), 1)
        alert_msg = data_fail["digital_twin"]["alerts"][0]["message"]
        self.assertIn("STATE MISMATCH: GigabitEthernet1/0/17 is DOWN (Model expects UP)", alert_msg)

        # Check port in device interfaces list
        swa_data = next(d for d in data_fail["devices"] if d["name"] == "SWITCH-A")
        p17 = next(i for i in swa_data["interfaces"] if i["name"] == "GigabitEthernet1/0/17")
        self.assertFalse(p17["is_up"])
        self.assertEqual(p17["status_code"], 2)
        self.assertEqual(p17["status_text"], "DOWN (FAIL)")

        # 4. Verify Diagnostic Commands (Section 4.1.3)
        # show interfaces GigabitEthernet1/0/17
        _, diag1 = self._post_json("/api/diagnostics", {
            "device": "SWITCH-A",
            "command": "show interfaces GigabitEthernet1/0/17",
        })
        self.assertIn("GigabitEthernet1/0/17 is administratively down", diag1["output"])

        # show interfaces status
        _, diag2 = self._post_json("/api/diagnostics", {
            "device": "SWITCH-A",
            "command": "show interfaces status",
        })
        self.assertIn("disabled", diag2["output"])

        # show ip interface brief
        _, diag3 = self._post_json("/api/diagnostics", {
            "device": "SWITCH-A",
            "command": "show ip interface brief",
        })
        self.assertIn("administratively down", diag3["output"])

        # 5. Trigger Recovery: No Shutdown
        post_rec_status, post_rec_resp = self._post_json("/api/troubleshoot/recover")
        self.assertEqual(post_rec_status, 200)
        self.assertTrue(post_rec_resp["success"])

        # 6. Verify Recovered State: 100% integrity and no alerts
        _, body_rec = self._get("/api/status")
        data_rec = json.loads(body_rec.decode("utf-8"))
        self.assertEqual(data_rec["digital_twin"]["score"], 100)
        self.assertTrue(data_rec["digital_twin"]["is_healthy"])
        self.assertEqual(len(data_rec["digital_twin"]["alerts"]), 0)

        # Verify diagnostic shows port is UP again
        _, diag_rec = self._post_json("/api/diagnostics", {
            "device": "SWITCH-A",
            "command": "show interfaces GigabitEthernet1/0/17",
        })
        self.assertIn("GigabitEthernet1/0/17 is up", diag_rec["output"])

    def test_automate_endpoint(self) -> None:
        """Verify triggering network automation deployment from dashboard."""
        status, resp = self._post_json("/api/automate")
        self.assertEqual(status, 200)
        self.assertTrue(resp["success"])
        self.assertTrue(resp["actions_count"] > 0)


if __name__ == "__main__":
    unittest.main()
