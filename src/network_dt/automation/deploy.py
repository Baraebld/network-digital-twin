"""Simulated network automation deployer and verification engine.

Provides automated provisioning of Cisco switches and routers using conceptual
Cisco IOS command generation and direct execution on the shared StateEngine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ..core.models import Device, DhcpPool, Interface, SnmpConfig, SshConfig, Vlan
from ..core.state_engine import StateEngine
from ..simulation.sim_network import SimulatedNetwork
from .templates import (
    render_access_port_commands,
    render_dhcp_pool_commands,
    render_snmp_commands,
    render_ssh_commands,
    render_subinterface_commands,
    render_trunk_port_commands,
    render_vlan_commands,
)


@dataclass
class DeploymentAction:
    """Represents a discrete automated provisioning operation and its Cisco CLI transcript."""
    device_name: str
    action_type: str
    commands: List[str]
    success: bool
    details: str


@dataclass
class VerificationCheck:
    """Individual verification rule and its evaluation result."""
    category: str
    target: str
    expected: str
    actual: str
    passed: bool
    details: str = ""


@dataclass
class VerificationReport:
    """Comprehensive post-deployment verification summary."""
    checks: List[VerificationCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total_count(self) -> int:
        return len(self.checks)


class DeviceInventory:
    """Parser and container for the Netmiko inventory file (`devices.yaml`)."""

    def __init__(self, inventory_path: Path):
        self.inventory_path = Path(inventory_path)
        self.devices: List[Dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        """Parse inventory from YAML file."""
        if not self.inventory_path.exists():
            return
        with open(self.inventory_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            self.devices = data.get("devices", [])

    def get_device(self, name_or_host: str) -> Optional[Dict[str, Any]]:
        for dev in self.devices:
            if dev.get("name") == name_or_host or dev.get("host") == name_or_host:
                return dev
        return None


class AutomationDeployer:
    """Automates network configuration deployment across virtual Cisco devices."""

    def __init__(
        self,
        state_engine: Optional[StateEngine] = None,
        inventory_path: Optional[Path] = None,
    ):
        self.state = state_engine if state_engine is not None else StateEngine()
        self.inventory = DeviceInventory(inventory_path or Path("config") / "devices.yaml")
        self.sim_net = SimulatedNetwork(state_engine=self.state)
        self.history: List[DeploymentAction] = []

    def configure_ssh(
        self,
        device_id: str,
        domain_name: str = "lab.local",
        version: int = 2,
        rsa_key_size: int = 1024,
        username: str = "admin",
        password: str = "password123",
    ) -> DeploymentAction:
        """Simulate Cisco IOS SSH activation."""
        device = self.state.get_device(device_id)
        if not device:
            action = DeploymentAction(device_id, "SSH_CONFIG", [], False, f"Device '{device_id}' not found.")
            self.history.append(action)
            return action

        cmds = render_ssh_commands(domain_name, rsa_key_size, username, password)
        device.ssh_config.enabled = True
        device.ssh_config.version = version
        device.ssh_config.domain_name = domain_name
        device.ssh_config.rsa_key_size = rsa_key_size
        device.ssh_config.admin_user = username

        self.state.save()
        action = DeploymentAction(device.name, "SSH_CONFIG", cmds, True, f"SSH v{version} activated with RSA {rsa_key_size}-bit keys.")
        self.history.append(action)
        return action

    def configure_snmp(
        self,
        device_id: str,
        community: str = "public",
        mode: str = "RO",
        location: str = "Lab",
        contact: str = "Admin",
    ) -> DeploymentAction:
        """Simulate Cisco IOS SNMP agent activation."""
        device = self.state.get_device(device_id)
        if not device:
            action = DeploymentAction(device_id, "SNMP_CONFIG", [], False, f"Device '{device_id}' not found.")
            self.history.append(action)
            return action

        cmds = render_snmp_commands(community, mode, location, contact)
        device.snmp_config.enabled = True
        device.snmp_config.community = community
        device.snmp_config.mode = mode
        device.snmp_config.location = location
        device.snmp_config.contact = contact

        self.state.save()
        action = DeploymentAction(device.name, "SNMP_CONFIG", cmds, True, f"SNMP enabled with community '{community}' ({mode}).")
        self.history.append(action)
        return action

    def create_vlan(
        self,
        device_id: str,
        vlan_id: int,
        name: str,
        subnet: Optional[str] = None,
        gateway: Optional[str] = None,
    ) -> DeploymentAction:
        """Create a VLAN on a switch and register it in the state engine."""
        device = self.state.get_device(device_id)
        if not device:
            action = DeploymentAction(device_id, "CREATE_VLAN", [], False, f"Device '{device_id}' not found.")
            self.history.append(action)
            return action

        if not (1 <= vlan_id <= 4094):
            action = DeploymentAction(device.name, "CREATE_VLAN", [], False, f"Invalid VLAN ID {vlan_id}. Must be between 1 and 4094.")
            self.history.append(action)
            return action

        cmds = render_vlan_commands(vlan_id, name)
        if vlan_id not in device.vlans:
            device.vlans.append(vlan_id)

        # Register in global VLAN table if subnet and gateway provided or if not already present
        if vlan_id not in self.state.vlans:
            sub = subnet or f"192.168.{vlan_id}.0/24"
            gw = gateway or f"192.168.{vlan_id}.1"
            self.state.vlans[vlan_id] = Vlan(vlan_id=vlan_id, name=name, subnet=sub, gateway=gw)

        self.state.save()
        action = DeploymentAction(device.name, "CREATE_VLAN", cmds, True, f"VLAN {vlan_id} ({name}) created successfully.")
        self.history.append(action)
        return action

    def configure_access_port(
        self,
        device_id: str,
        port_name: str,
        vlan_id: int,
    ) -> DeploymentAction:
        """Assign a switch port to an access VLAN."""
        device = self.state.get_device(device_id)
        if not device:
            action = DeploymentAction(device_id, "ACCESS_PORT", [], False, f"Device '{device_id}' not found.")
            self.history.append(action)
            return action

        iface = device.get_interface(port_name)
        if not iface:
            action = DeploymentAction(device.name, "ACCESS_PORT", [], False, f"Interface '{port_name}' not found on {device.name}.")
            self.history.append(action)
            return action

        if not (1 <= vlan_id <= 4094):
            action = DeploymentAction(device.name, "ACCESS_PORT", [], False, f"Invalid access VLAN {vlan_id}.")
            self.history.append(action)
            return action

        cmds = render_access_port_commands(port_name, vlan_id)
        iface.mode = "access"
        iface.access_vlan = vlan_id
        iface.admin_status = "UP"
        iface.oper_status = "UP"

        self.state.save()
        action = DeploymentAction(device.name, "ACCESS_PORT", cmds, True, f"Port {port_name} assigned to access VLAN {vlan_id}.")
        self.history.append(action)
        return action

    def configure_trunk_port(
        self,
        device_id: str,
        port_name: str,
        allowed_vlans: List[int],
    ) -> DeploymentAction:
        """Configure an 802.1Q dot1Q trunk link."""
        device = self.state.get_device(device_id)
        if not device:
            action = DeploymentAction(device_id, "TRUNK_PORT", [], False, f"Device '{device_id}' not found.")
            self.history.append(action)
            return action

        iface = device.get_interface(port_name)
        if not iface:
            action = DeploymentAction(device.name, "TRUNK_PORT", [], False, f"Interface '{port_name}' not found on {device.name}.")
            self.history.append(action)
            return action

        cmds = render_trunk_port_commands(port_name, allowed_vlans)
        iface.mode = "trunk"
        iface.allowed_vlans = sorted(list(set(allowed_vlans)))
        iface.admin_status = "UP"
        iface.oper_status = "UP"

        self.state.save()
        action = DeploymentAction(device.name, "TRUNK_PORT", cmds, True, f"Port {port_name} configured as trunk allowing VLANs {allowed_vlans}.")
        self.history.append(action)
        return action

    def configure_subinterface(
        self,
        device_id: str,
        subif_name: str,
        dot1q_vlan: int,
        ip_address: str,
        netmask: str = "255.255.255.0",
    ) -> DeploymentAction:
        """Configure an 802.1Q router subinterface for inter-VLAN routing."""
        device = self.state.get_device(device_id)
        if not device:
            action = DeploymentAction(device_id, "SUBINTERFACE", [], False, f"Device '{device_id}' not found.")
            self.history.append(action)
            return action

        if device.device_type != "router":
            action = DeploymentAction(device.name, "SUBINTERFACE", [], False, f"Device {device.name} is a {device.device_type}, not a router.")
            self.history.append(action)
            return action

        cmds = render_subinterface_commands(subif_name, dot1q_vlan, ip_address, netmask)
        subif = device.get_interface(subif_name)
        if not subif:
            subif = Interface(
                name=subif_name,
                oper_status="UP",
                admin_status="UP",
                mode="subinterface",
                dot1q_vlan=dot1q_vlan,
                ip_address=ip_address,
                subnet_mask=netmask,
            )
            device.interfaces[subif_name] = subif
        else:
            subif.mode = "subinterface"
            subif.dot1q_vlan = dot1q_vlan
            subif.ip_address = ip_address
            subif.subnet_mask = netmask
            subif.oper_status = "UP"
            subif.admin_status = "UP"

        self.state.save()
        action = DeploymentAction(device.name, "SUBINTERFACE", cmds, True, f"Subinterface {subif_name} configured with dot1Q {dot1q_vlan} and IP {ip_address}.")
        self.history.append(action)
        return action

    def configure_dhcp_pool(
        self,
        device_id: str,
        pool_name: str,
        network: str,
        netmask: str,
        default_router: str,
        dns_server: str = "8.8.8.8",
        excluded_addresses: Optional[List[str]] = None,
    ) -> DeploymentAction:
        """Configure a DHCP server pool on the central router."""
        device = self.state.get_device(device_id)
        if not device:
            action = DeploymentAction(device_id, "DHCP_POOL", [], False, f"Device '{device_id}' not found.")
            self.history.append(action)
            return action

        if device.device_type != "router":
            action = DeploymentAction(device.name, "DHCP_POOL", [], False, f"Device {device.name} is a {device.device_type}, cannot host DHCP pools.")
            self.history.append(action)
            return action

        excl = excluded_addresses or []
        cmds = render_dhcp_pool_commands(pool_name, network, netmask, default_router, dns_server, excl)
        pool = DhcpPool(
            name=pool_name,
            network=network,
            netmask=netmask,
            default_router=default_router,
            dns_server=dns_server,
            excluded_addresses=excl,
        )
        device.dhcp_pools[pool_name] = pool

        self.state.save()
        action = DeploymentAction(device.name, "DHCP_POOL", cmds, True, f"DHCP pool '{pool_name}' deployed ({network}/{netmask}).")
        self.history.append(action)
        return action

    def deploy_device(self, device_id: str) -> List[DeploymentAction]:
        """Deploy role-specific configurations based on the device identity."""
        actions: List[DeploymentAction] = []
        device = self.state.get_device(device_id)
        if not device:
            return [DeploymentAction(device_id, "DEPLOY_DEVICE", [], False, f"Device '{device_id}' not found.")]

        # Base SSH & SNMP
        actions.append(self.configure_ssh(device.name))
        actions.append(self.configure_snmp(device.name))

        if device.device_type == "switch":
            # 1. VLAN creation
            for vlan_id, (vlan_name, subnet, gw) in [
                (10, ("Management_SW1", "192.168.10.0/24", "192.168.10.1")),
                (20, ("Utilisateurs_A", "192.168.20.0/24", "192.168.20.1")),
                (30, ("Management_SW2", "192.168.30.0/24", "192.168.30.1")),
                (40, ("Utilisateurs_B", "192.168.40.0/24", "192.168.40.1")),
            ]:
                actions.append(self.create_vlan(device.name, vlan_id, vlan_name, subnet, gw))

            # 2. Trunk link to router
            actions.append(self.configure_trunk_port(device.name, "GigabitEthernet1/0/1", [10, 20, 30, 40]))

            # 3. Access ports based on switch role
            if device.name == "SWITCH-A" or "SW1" in device.aliases:
                actions.append(self.configure_access_port(device.name, "GigabitEthernet1/0/7", 10))
                actions.append(self.configure_access_port(device.name, "GigabitEthernet1/0/17", 20))
            elif device.name == "SWITCH-B" or "SW2" in device.aliases:
                actions.append(self.configure_access_port(device.name, "GigabitEthernet1/0/5", 30))
                actions.append(self.configure_access_port(device.name, "GigabitEthernet1/0/13", 40))

        elif device.device_type == "router":
            # 1. Subinterfaces
            subifs = [
                ("GigabitEthernet0/0.10", 10, "192.168.10.1"),
                ("GigabitEthernet0/0.20", 20, "192.168.20.1"),
                ("GigabitEthernet0/1.30", 30, "192.168.30.1"),
                ("GigabitEthernet0/1.40", 40, "192.168.40.1"),
            ]
            for sub_name, vlan_id, ip_addr in subifs:
                actions.append(self.configure_subinterface(device.name, sub_name, vlan_id, ip_addr))

            # 2. DHCP Pools (Section 2.4 Figure 7)
            pools = [
                ("VLAN10", "192.168.10.0", "192.168.10.1", ["192.168.10.1", "192.168.10.2"]),
                ("VLAN20", "192.168.20.0", "192.168.20.1", ["192.168.20.1", "192.168.20.2"]),
                ("VLAN30", "192.168.30.0", "192.168.30.1", ["192.168.30.1", "192.168.30.2"]),
                ("VLAN40", "192.168.40.0", "192.168.40.1", ["192.168.40.1", "192.168.40.2"]),
            ]
            for p_name, net, gw, excl in pools:
                actions.append(self.configure_dhcp_pool(device.name, p_name, net, "255.255.255.0", gw, "8.8.8.8", excl))

        return actions

    def deploy_all(self) -> List[DeploymentAction]:
        """Deploy automated configurations to all devices defined in inventory."""
        all_actions: List[DeploymentAction] = []
        # Target canonical devices
        for target in ["SWITCH-A", "SWITCH-B", "ROUTER-GW"]:
            acts = self.deploy_device(target)
            all_actions.extend(acts)
        self.state.save()
        return all_actions

    def verify_deployment(self) -> VerificationReport:
        """Perform comprehensive automated verification matching Section 2.5."""
        report = VerificationReport()

        # 1. SSH Verification
        for dev_name in ["ROUTER-GW", "SWITCH-A", "SWITCH-B"]:
            dev = self.state.get_device(dev_name)
            ssh_ok = dev is not None and dev.ssh_config.enabled and dev.ssh_config.version == 2
            report.checks.append(VerificationCheck(
                category="SSH",
                target=dev_name,
                expected="SSH v2 Enabled",
                actual="SSH v2 Enabled" if ssh_ok else "Disabled/Not Configured",
                passed=ssh_ok,
                details=f"Domain: {dev.ssh_config.domain_name if dev else 'N/A'}",
            ))

        # 2. SNMP Verification
        for dev_name in ["ROUTER-GW", "SWITCH-A", "SWITCH-B"]:
            dev = self.state.get_device(dev_name)
            snmp_ok = dev is not None and dev.snmp_config.enabled and dev.snmp_config.community == "public"
            report.checks.append(VerificationCheck(
                category="SNMP",
                target=dev_name,
                expected="Community: public (RO)",
                actual=f"Community: {dev.snmp_config.community} ({dev.snmp_config.mode})" if snmp_ok else "Disabled",
                passed=snmp_ok,
                details=f"Location: {dev.snmp_config.location if dev else 'N/A'}",
            ))

        # 3. Switch VLANs Verification
        for sw_name in ["SWITCH-A", "SWITCH-B"]:
            sw = self.state.get_device(sw_name)
            expected_vlans = {10, 20, 30, 40}
            actual_vlans = set(sw.vlans) if sw else set()
            vlans_ok = expected_vlans.issubset(actual_vlans)
            report.checks.append(VerificationCheck(
                category="VLAN",
                target=sw_name,
                expected="VLANs 10, 20, 30, 40 present",
                actual=f"VLANs {sorted(list(actual_vlans))}",
                passed=vlans_ok,
                details="Switch VLAN database verified.",
            ))

        # 4. Trunk Link Verification
        for sw_name in ["SWITCH-A", "SWITCH-B"]:
            sw = self.state.get_device(sw_name)
            trunk = sw.get_interface("GigabitEthernet1/0/1") if sw else None
            trunk_ok = (
                trunk is not None
                and trunk.is_operational
                and trunk.mode == "trunk"
                and {10, 20, 30, 40}.issubset(set(trunk.allowed_vlans))
            )
            report.checks.append(VerificationCheck(
                category="TRUNK",
                target=f"{sw_name}:Gi1/0/1",
                expected="Mode: trunk, Status: UP, Allowed: 10,20,30,40",
                actual=f"Mode: {trunk.mode if trunk else 'None'}, Status: {trunk.oper_status if trunk else 'None'}",
                passed=trunk_ok,
                details=f"Allowed: {trunk.allowed_vlans if trunk else []}",
            ))

        # 5. Router Subinterfaces Verification
        r1 = self.state.get_device("ROUTER-GW")
        subifs_to_check = [
            ("GigabitEthernet0/0.10", 10, "192.168.10.1"),
            ("GigabitEthernet0/0.20", 20, "192.168.20.1"),
            ("GigabitEthernet0/1.30", 30, "192.168.30.1"),
            ("GigabitEthernet0/1.40", 40, "192.168.40.1"),
        ]
        for sub_name, vlan_id, ip_addr in subifs_to_check:
            sub = r1.get_interface(sub_name) if r1 else None
            sub_ok = (
                sub is not None
                and sub.is_operational
                and sub.dot1q_vlan == vlan_id
                and sub.ip_address == ip_addr
            )
            report.checks.append(VerificationCheck(
                category="SUBINTERFACE",
                target=f"ROUTER-GW:{sub_name}",
                expected=f"dot1Q {vlan_id}, IP: {ip_addr}",
                actual=f"dot1Q {sub.dot1q_vlan if sub else 'None'}, IP: {sub.ip_address if sub else 'None'}",
                passed=sub_ok,
                details=f"Status: {sub.oper_status if sub else 'None'}",
            ))

        # 6. DHCP Pools Verification
        for vlan_id in [10, 20, 30, 40]:
            p_name = f"VLAN{vlan_id}"
            pool = r1.dhcp_pools.get(p_name) if r1 else None
            pool_ok = (
                pool is not None
                and pool.network == f"192.168.{vlan_id}.0"
                and pool.default_router == f"192.168.{vlan_id}.1"
            )
            report.checks.append(VerificationCheck(
                category="DHCP",
                target=f"ROUTER-GW:{p_name}",
                expected=f"Net: 192.168.{vlan_id}.0/24, GW: 192.168.{vlan_id}.1",
                actual=f"Net: {pool.network if pool else 'None'}, GW: {pool.default_router if pool else 'None'}",
                passed=pool_ok,
                details=f"Excluded: {pool.excluded_addresses if pool else []}",
            ))

        # 7. Connectivity Verification (Section 2.5 Figure 8)
        # Ping VLAN 30 -> VLAN 20
        ping_res = self.sim_net.ping("192.168.30.3", "192.168.20.3")
        report.checks.append(VerificationCheck(
            category="CONNECTIVITY",
            target="192.168.30.3 -> 192.168.20.3",
            expected="0% packet loss, ~1ms latency",
            actual=f"{ping_res.packet_loss_pct}% loss, {ping_res.avg_latency_ms}ms latency",
            passed=ping_res.success,
            details=ping_res.message,
        ))

        # Traceroute VLAN 30 -> VLAN 20
        trace_res = self.sim_net.traceroute("192.168.30.3", "192.168.20.3")
        hops_ok = trace_res.success and len(trace_res.hops) >= 2 and trace_res.hops[0].ip == "192.168.30.1"
        report.checks.append(VerificationCheck(
            category="CONNECTIVITY",
            target="Traceroute 192.168.30.3 -> 192.168.20.3",
            expected="Hop 1: 192.168.30.1, Hop 2: 192.168.20.3",
            actual=f"{len(trace_res.hops)} hops routed" if trace_res.success else "Failed",
            passed=hops_ok,
            details="Router-on-a-stick path confirmed.",
        ))

        return report
