"""Unit tests for the network simulation core.

Validates device models, VLAN segmentation, subinterfaces, DHCP pools,
persistent shared state, simulated connectivity, and failure recovery.
"""

import tempfile
import unittest
from pathlib import Path

from src.network_dt.core.models import Interface, PortMode, Vlan
from src.network_dt.core.state_engine import StateEngine
from src.network_dt.simulation.sim_network import SimulatedNetwork


class TestNetworkSimulationCore(unittest.TestCase):
    """Test suite verifying virtual network behavior and persistence."""

    def setUp(self) -> None:
        """Create an isolated temporary StateEngine for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "simulated_network.json"
        self.state = StateEngine(state_file=self.state_file)
        self.net = SimulatedNetwork(state_engine=self.state)

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_topology_initialization(self) -> None:
        """Verify initial devices, hostnames, and aliases conform to the report."""
        # Router
        r1 = self.state.get_device("ROUTER-GW")
        self.assertIsNotNone(r1)
        self.assertEqual(r1.device_type, "router")
        self.assertEqual(r1.primary_ip, "192.168.10.1")
        # Test alias resolution
        self.assertIs(self.state.get_device("R1"), r1)
        self.assertIs(self.state.get_device("Router0"), r1)
        self.assertIs(self.state.get_device("R1.lab.local"), r1)

        # Switch A
        swa = self.state.get_device("SWITCH-A")
        self.assertIsNotNone(swa)
        self.assertEqual(swa.device_type, "switch")
        self.assertEqual(swa.primary_ip, "192.168.10.2")
        self.assertIs(self.state.get_device("SW1"), swa)
        self.assertIs(self.state.get_device("SW-A"), swa)

        # Switch B
        swb = self.state.get_device("SWITCH-B")
        self.assertIsNotNone(swb)
        self.assertEqual(swb.device_type, "switch")
        self.assertEqual(swb.primary_ip, "192.168.30.2")
        self.assertIs(self.state.get_device("SW2"), swb)
        self.assertIs(self.state.get_device("SW-B"), swb)

    def test_vlans_subnets_and_gateways(self) -> None:
        """Verify VLANs 10, 20, 30, and 40 have documented subnets and gateways."""
        expected_vlans = {
            10: ("Management_SW1", "192.168.10.0/24", "192.168.10.1"),
            20: ("Utilisateurs_A", "192.168.20.0/24", "192.168.20.1"),
            30: ("Management_SW2", "192.168.30.0/24", "192.168.30.1"),
            40: ("Utilisateurs_B", "192.168.40.0/24", "192.168.40.1"),
        }
        for vlan_id, (name, subnet, gateway) in expected_vlans.items():
            vlan = self.state.get_vlan(vlan_id)
            self.assertIsNotNone(vlan, f"VLAN {vlan_id} must exist")
            self.assertEqual(vlan.subnet, subnet)
            self.assertEqual(vlan.gateway, gateway)

    def test_router_subinterfaces_and_dhcp(self) -> None:
        """Verify Router subinterfaces with 802.1Q dot1Q and DHCP pools."""
        r1 = self.state.get_device("ROUTER-GW")
        self.assertIsNotNone(r1)

        # Subinterfaces
        subif_names = [
            "GigabitEthernet0/0.10",
            "GigabitEthernet0/0.20",
            "GigabitEthernet0/1.30",
            "GigabitEthernet0/1.40",
        ]
        for name in subif_names:
            subif = r1.get_interface(name)
            self.assertIsNotNone(subif, f"Subinterface {name} should exist")
            self.assertEqual(subif.oper_status, "UP")
            self.assertEqual(subif.mode, "subinterface")

        # DHCP Pools
        for vlan_id in [10, 20, 30, 40]:
            pool_name = f"VLAN{vlan_id}"
            self.assertIn(pool_name, r1.dhcp_pools)
            pool = r1.dhcp_pools[pool_name]
            self.assertEqual(pool.dns_server, "8.8.8.8")
            self.assertEqual(pool.default_router, f"192.168.{vlan_id}.1")
            self.assertIn(f"192.168.{vlan_id}.1", pool.excluded_addresses)

    def test_switch_port_layout(self) -> None:
        """Verify Catalyst 28-port switch model and SVIs."""
        swa = self.state.get_device("SWITCH-A")
        self.assertIsNotNone(swa)

        # Trunk port
        trunk = swa.get_interface("GigabitEthernet1/0/1")
        self.assertIsNotNone(trunk)
        self.assertEqual(trunk.mode, "trunk")
        self.assertEqual(trunk.oper_status, "UP")
        self.assertEqual(trunk.allowed_vlans, [10, 20, 30, 40])

        # Access port Gi1/0/17 (normal state)
        port17 = swa.get_interface("GigabitEthernet1/0/17")
        self.assertIsNotNone(port17)
        self.assertEqual(port17.mode, "access")
        self.assertEqual(port17.access_vlan, 20)
        self.assertEqual(port17.oper_status, "UP")

        # SVIs
        vlan1 = swa.get_interface("Vlan1")
        self.assertEqual(vlan1.oper_status, "DOWN")
        vlan10 = swa.get_interface("Vlan10")
        self.assertEqual(vlan10.oper_status, "UP")
        self.assertEqual(vlan10.ip_address, "192.168.10.2")

    def test_state_persistence_across_instances(self) -> None:
        """Verify state is correctly saved to and loaded from JSON."""
        # Mutate state in engine 1
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "DOWN")

        # Load state in a separate engine 2 from the same file
        reloaded_state = StateEngine(state_file=self.state_file)
        reloaded_swa = reloaded_state.get_device("SWITCH-A")
        self.assertIsNotNone(reloaded_swa)
        port17 = reloaded_swa.get_interface("GigabitEthernet1/0/17")
        self.assertIsNotNone(port17)
        self.assertEqual(port17.oper_status, "DOWN")
        self.assertEqual(port17.admin_status, "DOWN")

    def test_simulated_inter_vlan_connectivity(self) -> None:
        """Verify simulated inter-VLAN ping and traceroute without real OS sockets."""
        # Ping VLAN 30 (PC VLAN30) -> VLAN 40 (PC VLAN40) [Section 1.4, Figure 2]
        res1 = self.net.ping("192.168.30.3", "192.168.40.3")
        self.assertTrue(res1.success)
        self.assertEqual(res1.packet_loss_pct, 0.0)
        self.assertEqual(res1.packets_received, 4)
        self.assertEqual(res1.avg_latency_ms, 1.0)

        # Ping VLAN 30 (PC VLAN30) -> VLAN 20 (PC VLAN20) [Section 1.4, Figure 3]
        res2 = self.net.ping("192.168.30.3", "192.168.20.3")
        self.assertTrue(res2.success)
        self.assertEqual(res2.packet_loss_pct, 0.0)

        # Traceroute VLAN 30 -> VLAN 20 [Section 2.5, Figure 8]
        trace = self.net.traceroute("192.168.30.3", "192.168.20.3")
        self.assertTrue(trace.success)
        self.assertEqual(len(trace.hops), 2)
        self.assertEqual(trace.hops[0].ip, "192.168.30.1")  # Hop 1: Gateway
        self.assertEqual(trace.hops[1].ip, "192.168.20.3")  # Hop 2: Destination

    def test_port_failure_and_recovery_cycle(self) -> None:
        """Verify fault injection on SW1 Gi1/0/17 and remediation cycle (Part 4)."""
        # Baseline ping: Success
        self.assertTrue(self.net.ping("192.168.30.3", "192.168.20.3").success)

        # Step 1: Simulate failure (administrative shutdown)
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "DOWN", admin_status="DOWN")

        # Step 2: Ping must fail (100% loss)
        fail_res = self.net.ping("192.168.30.3", "192.168.20.3")
        self.assertFalse(fail_res.success)
        self.assertEqual(fail_res.packet_loss_pct, 100.0)
        self.assertIn("GigabitEthernet1/0/17 is DOWN", fail_res.message)

        # Step 3: Cisco CLI diagnosis command
        cli_out = self.net.execute_cisco_command("SWITCH-A", "show ip interface brief")
        self.assertIn("GigabitEthernet1/0/17", cli_out)
        self.assertIn("administratively down", cli_out)

        # Step 4: Remediation (no shutdown)
        remediation_out = self.net.execute_cisco_command("SWITCH-A", "interface GigabitEthernet1/0/17 no shutdown")
        self.assertIn("changed state to up", remediation_out)

        # Step 5: Post-recovery ping: Success
        recover_res = self.net.ping("192.168.30.3", "192.168.20.3")
        self.assertTrue(recover_res.success)
        self.assertEqual(recover_res.packet_loss_pct, 0.0)

    def test_device_unreachable_simulation(self) -> None:
        """Verify device reachability toggle reproduces Section 3.4 UNREACHABLE state."""
        r1 = self.state.get_device("ROUTER-GW")
        self.assertIsNotNone(r1)
        r1.is_reachable = False
        self.state.save()

        # Inter-VLAN ping must fail because router is down
        res = self.net.ping("192.168.30.3", "192.168.20.3")
        self.assertFalse(res.success)
        self.assertIn("ROUTER-GW is UNREACHABLE", res.message)

        # Restore reachability
        r1.is_reachable = True
        self.state.save()
        self.assertTrue(self.net.ping("192.168.30.3", "192.168.20.3").success)

    def test_golden_state_serialization_and_exact_scoring(self) -> None:
        """Verify Golden State schema and the exact 50-interface mathematical scoring model."""
        # 1. Full Golden State export
        golden = self.state.export_golden_state()
        self.assertIn("ROUTER-GW", golden)
        self.assertIn("SWITCH-A", golden)
        self.assertIn("SWITCH-B", golden)
        self.assertEqual(golden["ROUTER-GW"]["ip"], "192.168.10.1")
        self.assertEqual(golden["SWITCH-A"]["ip"], "192.168.10.2")
        self.assertEqual(golden["SWITCH-B"]["ip"], "192.168.30.2")

        # 2. Canonical 50-interface monitored model
        canonical_baseline = self.state.export_canonical_50_interfaces()
        total_items = sum(len(ifaces) for ifaces in canonical_baseline.values())
        self.assertEqual(total_items, 50, "Monitored canonical model must have exactly 50 interfaces")

        # In baseline, 100% of interfaces match
        matches_baseline = 0
        for dev, ifaces in canonical_baseline.items():
            for if_name, status in ifaces.items():
                if self.state.get_device(dev).get_interface(if_name).oper_status == status:
                    matches_baseline += 1
        score_baseline = round((matches_baseline / total_items) * 100)
        self.assertEqual(score_baseline, 100)

        # When SWITCH-A Gi1/0/17 is DOWN
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "DOWN")
        matches_fault = 0
        for dev, ifaces in canonical_baseline.items():
            for if_name, status in ifaces.items():
                if self.state.get_device(dev).get_interface(if_name).oper_status == status:
                    matches_fault += 1
        self.assertEqual(matches_fault, 49)
        score_fault = round((matches_fault / total_items) * 100)
        self.assertEqual(score_fault, 98, "Score during 1 port deviation must be exactly 98%")

        # Post-recovery: restore Gi1/0/17 to UP
        self.state.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "UP")
        matches_recovered = sum(
            1 for dev, ifaces in canonical_baseline.items()
            for if_name, status in ifaces.items()
            if self.state.get_device(dev).get_interface(if_name).oper_status == status
        )
        score_recovered = round((matches_recovered / total_items) * 100)
        self.assertEqual(score_recovered, 100, "Score after recovery must return to 100%")


if __name__ == "__main__":
    unittest.main()
