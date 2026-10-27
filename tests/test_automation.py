"""Unit tests for the simulated network automation module (Part 2).

Tests inventory parsing, successful provisioning, invalid configuration handling,
and post-deployment verification checks.
"""

import tempfile
import unittest
from pathlib import Path

from src.network_dt.automation.deploy import AutomationDeployer, DeviceInventory
from src.network_dt.core.state_engine import StateEngine


class TestNetworkAutomation(unittest.TestCase):
    """Test suite for automated provisioning and verification."""

    def setUp(self) -> None:
        """Create an isolated temporary state engine and deployer for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "simulated_network.json"
        self.state = StateEngine(state_file=self.state_file)
        self.deployer = AutomationDeployer(
            state_engine=self.state,
            inventory_path=Path("config") / "devices.yaml",
        )

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_inventory_parsing(self) -> None:
        """Verify device inventory parses devices.yaml correctly."""
        inv = DeviceInventory(Path("config") / "devices.yaml")
        self.assertEqual(len(inv.devices), 3)

        sw1 = inv.get_device("SW1")
        self.assertIsNotNone(sw1)
        self.assertEqual(sw1["host"], "192.168.30.2")
        self.assertEqual(sw1["device_type"], "cisco_ios")

        r1 = inv.get_device("R1")
        self.assertIsNotNone(r1)
        self.assertEqual(r1["host"], "192.168.30.1")

        sw2 = inv.get_device("SW2")
        self.assertIsNotNone(sw2)
        self.assertEqual(sw2["host"], "192.168.10.2")

    def test_successful_deploy_all(self) -> None:
        """Verify full automated deployment on switches and router."""
        actions = self.deployer.deploy_all()
        self.assertTrue(len(actions) > 0)
        for act in actions:
            self.assertTrue(act.success, f"Action failed: {act.action_type} on {act.device_name} ({act.details})")

        # Verify device properties post-deployment
        r1 = self.state.get_device("ROUTER-GW")
        self.assertTrue(r1.ssh_config.enabled)
        self.assertEqual(r1.ssh_config.version, 2)
        self.assertTrue(r1.snmp_config.enabled)
        self.assertEqual(r1.snmp_config.community, "public")
        self.assertEqual(len(r1.dhcp_pools), 4)

        swa = self.state.get_device("SWITCH-A")
        self.assertTrue(swa.ssh_config.enabled)
        self.assertTrue(swa.snmp_config.enabled)
        self.assertTrue({10, 20, 30, 40}.issubset(set(swa.vlans)))
        trunk_a = swa.get_interface("GigabitEthernet1/0/1")
        self.assertEqual(trunk_a.mode, "trunk")
        self.assertEqual(trunk_a.allowed_vlans, [10, 20, 30, 40])

        swb = self.state.get_device("SWITCH-B")
        self.assertTrue(swb.ssh_config.enabled)
        self.assertTrue(swb.snmp_config.enabled)
        self.assertTrue({10, 20, 30, 40}.issubset(set(swb.vlans)))

    def test_individual_operations(self) -> None:
        """Verify discrete automated operations produce correct CLI transcripts and state changes."""
        # SSH configuration
        act_ssh = self.deployer.configure_ssh("SWITCH-A", domain_name="test.local", version=2)
        self.assertTrue(act_ssh.success)
        self.assertIn("ip domain-name test.local", act_ssh.commands)
        self.assertIn("ip ssh version 2", act_ssh.commands)

        # SNMP configuration
        act_snmp = self.deployer.configure_snmp("ROUTER-GW", community="public", mode="RO")
        self.assertTrue(act_snmp.success)
        self.assertIn("snmp-server community public RO", act_snmp.commands)

        # VLAN creation
        act_vlan = self.deployer.create_vlan("SWITCH-A", 99, "Test_VLAN")
        self.assertTrue(act_vlan.success)
        self.assertIn("vlan 99", act_vlan.commands)
        self.assertIn(99, self.state.get_device("SWITCH-A").vlans)

        # Access port configuration
        act_acc = self.deployer.configure_access_port("SWITCH-A", "GigabitEthernet1/0/10", 99)
        self.assertTrue(act_acc.success)
        iface = self.state.get_device("SWITCH-A").get_interface("GigabitEthernet1/0/10")
        self.assertEqual(iface.mode, "access")
        self.assertEqual(iface.access_vlan, 99)

        # Subinterface configuration
        act_sub = self.deployer.configure_subinterface("ROUTER-GW", "GigabitEthernet0/0.99", 99, "192.168.99.1")
        self.assertTrue(act_sub.success)
        sub = self.state.get_device("ROUTER-GW").get_interface("GigabitEthernet0/0.99")
        self.assertEqual(sub.dot1q_vlan, 99)
        self.assertEqual(sub.ip_address, "192.168.99.1")

        # DHCP pool configuration
        act_dhcp = self.deployer.configure_dhcp_pool(
            "ROUTER-GW",
            "TEST_POOL",
            "192.168.99.0",
            "255.255.255.0",
            "192.168.99.1",
            excluded_addresses=["192.168.99.1", "192.168.99.2"],
        )
        self.assertTrue(act_dhcp.success)
        self.assertIn("TEST_POOL", self.state.get_device("ROUTER-GW").dhcp_pools)

    def test_invalid_configurations(self) -> None:
        """Verify deployer gracefully handles and rejects invalid configurations."""
        # 1. Invalid VLAN ID (< 1 or > 4094)
        act_vlan_low = self.deployer.create_vlan("SWITCH-A", 0, "Invalid_Low")
        self.assertFalse(act_vlan_low.success)
        self.assertIn("Invalid VLAN ID", act_vlan_low.details)

        act_vlan_high = self.deployer.create_vlan("SWITCH-A", 5000, "Invalid_High")
        self.assertFalse(act_vlan_high.success)
        self.assertIn("Invalid VLAN ID", act_vlan_high.details)

        # 2. Nonexistent interface on switch
        act_port = self.deployer.configure_access_port("SWITCH-A", "GigabitEthernet9/9/9", 10)
        self.assertFalse(act_port.success)
        self.assertIn("Interface 'GigabitEthernet9/9/9' not found", act_port.details)

        # 3. Subinterface on a switch (invalid operation)
        act_sub_switch = self.deployer.configure_subinterface("SWITCH-A", "GigabitEthernet1/0/1.10", 10, "192.168.10.1")
        self.assertFalse(act_sub_switch.success)
        self.assertIn("not a router", act_sub_switch.details)

        # 4. DHCP pool on a switch (invalid operation)
        act_dhcp_switch = self.deployer.configure_dhcp_pool("SWITCH-A", "POOL_FAIL", "192.168.10.0", "255.255.255.0", "192.168.10.1")
        self.assertFalse(act_dhcp_switch.success)
        self.assertIn("cannot host DHCP pools", act_dhcp_switch.details)

        # 5. Nonexistent device
        act_no_dev = self.deployer.configure_ssh("NONEXISTENT_DEVICE")
        self.assertFalse(act_no_dev.success)
        self.assertIn("not found", act_no_dev.details)

    def test_verification_report_success(self) -> None:
        """Verify verification report passes on deployed network."""
        self.deployer.deploy_all()
        report = self.deployer.verify_deployment()
        self.assertTrue(report.all_passed)
        self.assertEqual(report.passed_count, report.total_count)
        self.assertTrue(report.total_count >= 15)

    def test_verification_detects_misconfigurations(self) -> None:
        """Verify verification report detects disabled services or broken configs."""
        self.deployer.deploy_all()

        # 1. Disable SSH on SWITCH-A
        swa = self.state.get_device("SWITCH-A")
        swa.ssh_config.enabled = False
        self.state.save()

        rep1 = self.deployer.verify_deployment()
        self.assertFalse(rep1.all_passed)
        failed_ssh = [c for c in rep1.checks if c.category == "SSH" and not c.passed]
        self.assertEqual(len(failed_ssh), 1)
        self.assertEqual(failed_ssh[0].target, "SWITCH-A")

        # Restore SSH
        swa.ssh_config.enabled = True
        self.state.save()

        # 2. Break trunk on SWITCH-B
        swb = self.state.get_device("SWITCH-B")
        swb.get_interface("GigabitEthernet1/0/1").oper_status = "DOWN"
        self.state.save()

        rep2 = self.deployer.verify_deployment()
        self.assertFalse(rep2.all_passed)
        failed_trunk = [c for c in rep2.checks if c.category == "TRUNK" and not c.passed]
        self.assertEqual(len(failed_trunk), 1)
        self.assertEqual(failed_trunk[0].target, "SWITCH-B:Gi1/0/1")


if __name__ == "__main__":
    unittest.main()
