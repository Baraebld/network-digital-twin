"""Unit tests for the simulated SNMP provider and monitoring service (Part 3).

Validates standard MIB OIDs, UP/DOWN status mapping (1=UP, 2=DOWN),
documented device interface coverage, device reachability, dynamic failure detection,
and event logging.
"""

import tempfile
import unittest
from pathlib import Path

from src.network_dt.core.state_engine import StateEngine
from src.network_dt.monitoring.service import MonitoringService
from src.network_dt.monitoring.snmp_provider import (
    OID_IF_DESCR,
    OID_IF_STATUS,
    OID_SYS_CONTACT,
    OID_SYS_LOCATION,
    OID_SYS_NAME,
    OID_SYS_UPTIME,
    SimulatedSnmpProvider,
    SnmpError,
    SnmpTimeoutError,
)


class TestSnmpMonitoring(unittest.TestCase):
    """Test suite for simulated SNMP provider and monitoring service."""

    def setUp(self) -> None:
        """Initialize an isolated temporary state engine and monitoring service."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "simulated_network.json"
        self.state = StateEngine(state_file=self.state_file)
        self.provider = SimulatedSnmpProvider(state_engine=self.state)
        self.monitor = MonitoringService(state_engine=self.state)

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_snmp_get_scalar_oids(self) -> None:
        """Verify querying standard scalar OIDs from Section 3.2 Figure 10."""
        # sysName
        self.assertEqual(self.provider.get("192.168.10.1", OID_SYS_NAME), "R1.lab.local")
        self.assertEqual(self.provider.get("192.168.10.2", OID_SYS_NAME), "SW-A.lab.local")
        self.assertEqual(self.provider.get("192.168.30.2", OID_SYS_NAME), "SW-B.lab.local")

        # sysUpTime
        uptime_r1 = self.provider.get("192.168.10.1", OID_SYS_UPTIME)
        self.assertTrue(uptime_r1.isdigit())
        self.assertTrue(int(uptime_r1) > 0)

        # sysContact & sysLocation
        self.assertEqual(self.provider.get("192.168.10.1", OID_SYS_CONTACT), "Admin")
        self.assertEqual(self.provider.get("192.168.10.1", OID_SYS_LOCATION), "Lab")

    def test_up_down_status_mapping(self) -> None:
        """Verify the 1=UP, 2=DOWN convention and text translation."""
        # Switch A: GigabitEthernet1/0/1 is UP (trunk link) -> status code 1
        # Switch A: GigabitEthernet1/0/2 is DOWN (unused port) -> status code 2
        walk_results = self.provider.snmp_walk_interfaces("192.168.10.2")
        status_dict = dict(walk_results)

        self.assertIn("GigabitEthernet1/0/1", status_dict)
        self.assertEqual(status_dict["GigabitEthernet1/0/1"], "UP (OK)")

        self.assertIn("GigabitEthernet1/0/2", status_dict)
        self.assertEqual(status_dict["GigabitEthernet1/0/2"], "DOWN (FAIL)")

    def test_documented_interfaces_r1(self) -> None:
        """Verify R1 interface status matches Section 3.4 table (Gi0/0, Gi0/1, subinterfaces UP)."""
        poll = self.monitor.poll_device("ROUTER-GW")
        self.assertTrue(poll.is_reachable)
        ifaces = {iface.name: iface for iface in poll.interfaces}

        # Documented router interfaces that must be UP
        expected_up = [
            "GigabitEthernet0/0",
            "GigabitEthernet0/1",
            "GigabitEthernet0/0.10",
            "GigabitEthernet0/0.20",
            "GigabitEthernet0/1.30",
            "GigabitEthernet0/1.40",
        ]
        for if_name in expected_up:
            self.assertIn(if_name, ifaces, f"R1 must report {if_name}")
            self.assertTrue(ifaces[if_name].is_up, f"R1 {if_name} must be UP")
            self.assertEqual(ifaces[if_name].status_code, 1)
            self.assertEqual(ifaces[if_name].status_text, "UP (OK)")

    def test_documented_interfaces_sw1(self) -> None:
        """Verify SW1 interface status matches Section 3.4 table (Gi1/0/1, 7, 17, Vlan10 UP; Vlan1 DOWN)."""
        poll = self.monitor.poll_device("SWITCH-A")
        self.assertTrue(poll.is_reachable)
        ifaces = {iface.name: iface for iface in poll.interfaces}

        # UP ports
        for port in ["GigabitEthernet1/0/1", "GigabitEthernet1/0/7", "GigabitEthernet1/0/17", "Vlan10"]:
            self.assertIn(port, ifaces)
            self.assertTrue(ifaces[port].is_up, f"SW1 {port} must be UP")
            self.assertEqual(ifaces[port].status_code, 1)

        # DOWN port
        self.assertIn("Vlan1", ifaces)
        self.assertFalse(ifaces["Vlan1"].is_up)
        self.assertEqual(ifaces["Vlan1"].status_code, 2)
        self.assertEqual(ifaces["Vlan1"].status_text, "DOWN (FAIL)")

    def test_documented_interfaces_sw2(self) -> None:
        """Verify SW2 interface status matches Section 3.4 table (Gi1/0/1, 5, 13, Vlan30 UP; Vlan1 DOWN)."""
        poll = self.monitor.poll_device("SWITCH-B")
        self.assertTrue(poll.is_reachable)
        ifaces = {iface.name: iface for iface in poll.interfaces}

        # UP ports
        for port in ["GigabitEthernet1/0/1", "GigabitEthernet1/0/5", "GigabitEthernet1/0/13", "Vlan30"]:
            self.assertIn(port, ifaces)
            self.assertTrue(ifaces[port].is_up, f"SW2 {port} must be UP")
            self.assertEqual(ifaces[port].status_code, 1)

        # DOWN port
        self.assertIn("Vlan1", ifaces)
        self.assertFalse(ifaces["Vlan1"].is_up)
        self.assertEqual(ifaces["Vlan1"].status_code, 2)

    def test_device_unreachable_and_error_logging(self) -> None:
        """Verify UNREACHABLE detection matches Section 3.4 screenshot text."""
        # Simulate device offline
        r1 = self.state.get_device("ROUTER-GW")
        r1.is_reachable = False
        self.state.save()

        # Poll router
        poll = self.monitor.poll_device("ROUTER-GW")
        self.assertFalse(poll.is_reachable)
        self.assertIn("is UNREACHABLE! Check connection.", poll.error)

        # Check recorded event
        unreachable_evts = [e for e in self.monitor.events_log if e.event_type == "DEVICE_UNREACHABLE"]
        self.assertEqual(len(unreachable_evts), 1)
        self.assertEqual(unreachable_evts[0].level, "ERROR")
        self.assertEqual(unreachable_evts[0].device_name, "ROUTER-GW")

    def test_dynamic_failure_and_recovery_detection(self) -> None:
        """Verify a failure in the shared simulator (SW1 Gi1/0/17 shutdown) is detected by monitoring."""
        # 1. Baseline poll: Gi1/0/17 is UP
        poll1 = self.monitor.poll_device("SWITCH-A")
        iface17_before = next(i for i in poll1.interfaces if i.name == "GigabitEthernet1/0/17")
        self.assertTrue(iface17_before.is_up)

        # 2. Simulate shutdown of Gi1/0/17 in shared state
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "DOWN")

        # 3. Next poll: Monitoring must immediately detect DOWN (FAIL)
        poll2 = self.monitor.poll_device("SWITCH-A")
        iface17_after = next(i for i in poll2.interfaces if i.name == "GigabitEthernet1/0/17")
        self.assertFalse(iface17_after.is_up)
        self.assertEqual(iface17_after.status_code, 2)
        self.assertEqual(iface17_after.status_text, "DOWN (FAIL)")

        # Verify INTERFACE_DOWN event logged
        down_evts = [e for e in self.monitor.events_log if e.event_type == "INTERFACE_DOWN"]
        self.assertEqual(len(down_evts), 1)
        self.assertEqual(down_evts[0].target, "GigabitEthernet1/0/17")

        # 4. Simulate recovery (no shutdown)
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "UP")

        # 5. Next poll: Monitoring must detect recovery to UP (OK)
        poll3 = self.monitor.poll_device("SWITCH-A")
        iface17_recovered = next(i for i in poll3.interfaces if i.name == "GigabitEthernet1/0/17")
        self.assertTrue(iface17_recovered.is_up)
        self.assertEqual(iface17_recovered.status_code, 1)
        self.assertEqual(iface17_recovered.status_text, "UP (OK)")

        # Verify INTERFACE_UP event logged
        up_evts = [e for e in self.monitor.events_log if e.event_type == "INTERFACE_UP"]
        self.assertEqual(len(up_evts), 1)

    def test_periodic_monitoring_loop(self) -> None:
        """Verify periodic polling execution and clean termination."""
        poll_cycles: list = []

        def callback(results):
            poll_cycles.append(results)

        # Run 3 fast cycles (0.01s interval)
        self.monitor.start_periodic(interval_seconds=0.01, max_cycles=3, callback=callback)
        self.assertEqual(len(poll_cycles), 3)
        for res_list in poll_cycles:
            self.assertEqual(len(res_list), 3)  # R1, SW1, SW2


if __name__ == "__main__":
    unittest.main()
