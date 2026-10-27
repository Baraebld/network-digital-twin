"""Unified persistence and shared state engine for the simulated network.

Loads and synchronizes live network state from/to `.state/simulated_network.json`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .models import Device, DhcpPool, Interface, SnmpConfig, SshConfig, Vlan


class StateEngine:
    """Shared state engine representing the active virtual network infrastructure."""

    DEFAULT_STATE_FILE = Path(".state") / "simulated_network.json"
    DEFAULT_CONFIG_DIR = Path("config")

    def __init__(self, state_file: Optional[Path] = None, auto_load: bool = True):
        self.state_file = Path(state_file) if state_file else self.DEFAULT_STATE_FILE
        self.devices: Dict[str, Device] = {}
        self.vlans: Dict[int, Vlan] = {}
        self.hosts: Dict[str, Dict[str, Any]] = {}

        if auto_load:
            self.load()

    def get_canonical_device_name(self, identifier: str) -> Optional[str]:
        """Resolve any alias/hostname/IP to canonical device key."""
        for name, device in self.devices.items():
            if device.matches_identifier(identifier):
                return name
        return None

    def get_device(self, identifier: str) -> Optional[Device]:
        """Retrieve device by canonical name, alias, hostname, or IP."""
        key = self.get_canonical_device_name(identifier)
        if key:
            return self.devices[key]
        return None

    def get_vlan(self, vlan_id: int) -> Optional[Vlan]:
        """Retrieve VLAN definition by integer ID."""
        return self.vlans.get(vlan_id)

    def set_interface_status(
        self,
        device_id: str,
        interface_name: str,
        oper_status: str,
        admin_status: Optional[str] = None,
    ) -> bool:
        """Update interface operational and/or administrative status and persist."""
        device = self.get_device(device_id)
        if not device:
            return False

        iface = device.get_interface(interface_name)
        if not iface:
            return False

        iface.oper_status = oper_status.upper()
        if admin_status:
            iface.admin_status = admin_status.upper()
        elif oper_status.upper() == "UP":
            iface.admin_status = "UP"
        elif oper_status.upper() == "DOWN":
            iface.admin_status = "DOWN"

        self.save()
        return True

    def initialize_default_topology(self) -> None:
        """Create baseline default topology conforming to the report specification."""
        self.vlans = {
            10: Vlan(10, "Management_SW1", "192.168.10.0/24", "192.168.10.1", "SW1 Management"),
            20: Vlan(20, "Utilisateurs_A", "192.168.20.0/24", "192.168.20.1", "Users A Segment"),
            30: Vlan(30, "Management_SW2", "192.168.30.0/24", "192.168.30.1", "SW2 & R1 Management"),
            40: Vlan(40, "Utilisateurs_B", "192.168.40.0/24", "192.168.40.1", "Users B Segment"),
        }

        # Initialize ROUTER-GW (R1)
        router_ifaces: Dict[str, Interface] = {
            "GigabitEthernet0/0": Interface(
                name="GigabitEthernet0/0",
                oper_status="UP",
                admin_status="UP",
                mode="routed",
                connected_to="SWITCH-A:GigabitEthernet1/0/1",
            ),
            "GigabitEthernet0/1": Interface(
                name="GigabitEthernet0/1",
                oper_status="UP",
                admin_status="UP",
                mode="routed",
                connected_to="SWITCH-B:GigabitEthernet1/0/1",
            ),
            "GigabitEthernet0/3": Interface(
                name="GigabitEthernet0/3",
                oper_status="UP",
                admin_status="UP",
                mode="routed",
            ),
            "GigabitEthernet0/0.10": Interface(
                name="GigabitEthernet0/0.10",
                oper_status="UP",
                admin_status="UP",
                mode="subinterface",
                dot1q_vlan=10,
                ip_address="192.168.10.1",
                subnet_mask="255.255.255.0",
            ),
            "GigabitEthernet0/0.20": Interface(
                name="GigabitEthernet0/0.20",
                oper_status="UP",
                admin_status="UP",
                mode="subinterface",
                dot1q_vlan=20,
                ip_address="192.168.20.1",
                subnet_mask="255.255.255.0",
            ),
            "GigabitEthernet0/1.30": Interface(
                name="GigabitEthernet0/1.30",
                oper_status="UP",
                admin_status="UP",
                mode="subinterface",
                dot1q_vlan=30,
                ip_address="192.168.30.1",
                subnet_mask="255.255.255.0",
            ),
            "GigabitEthernet0/1.40": Interface(
                name="GigabitEthernet0/1.40",
                oper_status="UP",
                admin_status="UP",
                mode="subinterface",
                dot1q_vlan=40,
                ip_address="192.168.40.1",
                subnet_mask="255.255.255.0",
            ),
        }

        router_dhcp: Dict[str, DhcpPool] = {
            "VLAN10": DhcpPool("VLAN10", "192.168.10.0", "255.255.255.0", "192.168.10.1", "8.8.8.8", ["192.168.10.1", "192.168.10.2"]),
            "VLAN20": DhcpPool("VLAN20", "192.168.20.0", "255.255.255.0", "192.168.20.1", "8.8.8.8", ["192.168.20.1", "192.168.20.2"]),
            "VLAN30": DhcpPool("VLAN30", "192.168.30.0", "255.255.255.0", "192.168.30.1", "8.8.8.8", ["192.168.30.1", "192.168.30.2"]),
            "VLAN40": DhcpPool("VLAN40", "192.168.40.0", "255.255.255.0", "192.168.40.1", "8.8.8.8", ["192.168.40.1", "192.168.40.2"]),
        }

        r1 = Device(
            name="ROUTER-GW",
            aliases=["R1", "Router0", "R1.lab.local"],
            device_type="router",
            hostname="R1.lab.local",
            primary_ip="192.168.10.1",
            management_vlan=10,
            is_reachable=True,
            uptime_ticks=2089548,
            interfaces=router_ifaces,
            dhcp_pools=router_dhcp,
            ssh_config=SshConfig(enabled=True),
            snmp_config=SnmpConfig(enabled=True),
        )

        # Initialize SWITCH-A (SW1) - 28 Catalyst ports + SVIs + FastEthernet0
        swa_ifaces: Dict[str, Interface] = {
            "Vlan1": Interface(name="Vlan1", oper_status="DOWN", admin_status="DOWN", mode="svi"),
            "Vlan10": Interface(name="Vlan10", oper_status="UP", admin_status="UP", mode="svi", ip_address="192.168.10.2", subnet_mask="255.255.255.0"),
        }
        for i in range(1, 29):
            port_name = f"GigabitEthernet1/0/{i}"
            if i == 1:
                swa_ifaces[port_name] = Interface(
                    name=port_name,
                    oper_status="UP",
                    admin_status="UP",
                    mode="trunk",
                    allowed_vlans=[10, 20, 30, 40],
                    connected_to="ROUTER-GW:GigabitEthernet0/0",
                )
            elif i == 7:
                swa_ifaces[port_name] = Interface(
                    name=port_name,
                    oper_status="UP",
                    admin_status="UP",
                    mode="access",
                    access_vlan=10,
                    connected_host="192.168.10.10",
                )
            elif i == 17:
                swa_ifaces[port_name] = Interface(
                    name=port_name,
                    oper_status="UP",
                    admin_status="UP",
                    mode="access",
                    access_vlan=20,
                    connected_host="192.168.20.3",
                )
            else:
                swa_ifaces[port_name] = Interface(
                    name=port_name,
                    oper_status="DOWN",
                    admin_status="DOWN",
                    mode="access",
                    access_vlan=1,
                )
        swa_ifaces["FastEthernet0"] = Interface(name="FastEthernet0", oper_status="DOWN", admin_status="DOWN", mode="routed")

        swa = Device(
            name="SWITCH-A",
            aliases=["SW1", "Switch0", "SW-A", "SW-A.lab.local"],
            device_type="switch",
            hostname="SW-A.lab.local",
            primary_ip="192.168.10.2",
            management_vlan=10,
            is_reachable=True,
            uptime_ticks=3854114,
            interfaces=swa_ifaces,
            vlans=[10, 20, 30, 40],
            ssh_config=SshConfig(enabled=True),
            snmp_config=SnmpConfig(enabled=True),
        )

        # Initialize SWITCH-B (SW2) - 28 Catalyst ports + SVIs + FastEthernet0
        swb_ifaces: Dict[str, Interface] = {
            "Vlan1": Interface(name="Vlan1", oper_status="DOWN", admin_status="DOWN", mode="svi"),
            "Vlan30": Interface(name="Vlan30", oper_status="UP", admin_status="UP", mode="svi", ip_address="192.168.30.2", subnet_mask="255.255.255.0"),
        }
        for i in range(1, 29):
            port_name = f"GigabitEthernet1/0/{i}"
            if i == 1:
                swb_ifaces[port_name] = Interface(
                    name=port_name,
                    oper_status="UP",
                    admin_status="UP",
                    mode="trunk",
                    allowed_vlans=[10, 20, 30, 40],
                    connected_to="ROUTER-GW:GigabitEthernet0/1",
                )
            elif i == 5:
                swb_ifaces[port_name] = Interface(
                    name=port_name,
                    oper_status="UP",
                    admin_status="UP",
                    mode="access",
                    access_vlan=30,
                    connected_host="192.168.30.3",
                )
            elif i == 13:
                swb_ifaces[port_name] = Interface(
                    name=port_name,
                    oper_status="UP",
                    admin_status="UP",
                    mode="access",
                    access_vlan=40,
                    connected_host="192.168.40.3",
                )
            else:
                swb_ifaces[port_name] = Interface(
                    name=port_name,
                    oper_status="DOWN",
                    admin_status="DOWN",
                    mode="access",
                    access_vlan=1,
                )
        swb_ifaces["FastEthernet0"] = Interface(name="FastEthernet0", oper_status="DOWN", admin_status="DOWN", mode="routed")

        swb = Device(
            name="SWITCH-B",
            aliases=["SW2", "Switch1", "SW-B", "SW-B.lab.local"],
            device_type="switch",
            hostname="SW-B.lab.local",
            primary_ip="192.168.30.2",
            management_vlan=30,
            is_reachable=True,
            uptime_ticks=3854114,
            interfaces=swb_ifaces,
            vlans=[10, 20, 30, 40],
            ssh_config=SshConfig(enabled=True),
            snmp_config=SnmpConfig(enabled=True),
        )

        self.devices = {
            "ROUTER-GW": r1,
            "SWITCH-A": swa,
            "SWITCH-B": swb,
        }

        self.hosts = {
            "192.168.10.10": {"name": "PC-VLAN10", "vlan": 10, "gateway": "192.168.10.1", "device": "SWITCH-A", "port": "GigabitEthernet1/0/7"},
            "192.168.20.3": {"name": "PC-VLAN20", "vlan": 20, "gateway": "192.168.20.1", "device": "SWITCH-A", "port": "GigabitEthernet1/0/17"},
            "192.168.30.3": {"name": "PC-VLAN30", "vlan": 30, "gateway": "192.168.30.1", "device": "SWITCH-B", "port": "GigabitEthernet1/0/5"},
            "192.168.40.3": {"name": "PC-VLAN40", "vlan": 40, "gateway": "192.168.40.1", "device": "SWITCH-B", "port": "GigabitEthernet1/0/13"},
        }

    def save(self) -> None:
        """Persist current state atomically to JSON file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "vlans": {str(k): v.to_dict() for k, v in self.vlans.items()},
            "devices": {k: v.to_dict() for k, v in self.devices.items()},
            "hosts": self.hosts,
        }
        temp_file = self.state_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, self.state_file)

    def load(self) -> None:
        """Load state from JSON file or initialize default topology if absent."""
        if not self.state_file.exists():
            self.initialize_default_topology()
            self.save()
            return

        with open(self.state_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.vlans = {int(k): Vlan.from_dict(v) for k, v in data.get("vlans", {}).items()}
        self.devices = {k: Device.from_dict(v) for k, v in data.get("devices", {}).items()}
        self.hosts = data.get("hosts", {})

    def export_golden_state(self) -> Dict[str, Any]:
        """Export state matching the exact schema of network_golden_state.json (Figure 15)."""
        golden: Dict[str, Any] = {}
        for dev_key, dev in self.devices.items():
            if_dict: Dict[str, str] = {}
            for if_name, iface in dev.interfaces.items():
                if_dict[if_name] = iface.oper_status.upper()
            golden[dev_key] = {
                "ip": dev.primary_ip,
                "interfaces": if_dict,
            }
        return golden

    def export_canonical_50_interfaces(self) -> Dict[str, Dict[str, str]]:
        """Export the exact 50 monitored interfaces used for the Digital Twin integrity check.
        
        Selection:
        - ROUTER-GW: 2 physical trunk interfaces (Gi0/0, Gi0/1)
        - SWITCH-A: 24 Gigabit access ports (Gi1/0/1 through Gi1/0/24)
        - SWITCH-B: 24 Gigabit access ports (Gi1/0/1 through Gi1/0/24)
        Total: 2 + 24 + 24 = exactly 50 monitored interfaces.
        """
        canonical: Dict[str, Dict[str, str]] = {
            "ROUTER-GW": {},
            "SWITCH-A": {},
            "SWITCH-B": {},
        }
        # Router: 2 uplinks
        r1 = self.get_device("ROUTER-GW")
        if r1:
            for if_name in ["GigabitEthernet0/0", "GigabitEthernet0/1"]:
                if if_name in r1.interfaces:
                    canonical["ROUTER-GW"][if_name] = r1.interfaces[if_name].oper_status.upper()

        # Switch A: ports 1 to 24
        swa = self.get_device("SWITCH-A")
        if swa:
            for i in range(1, 25):
                port_name = f"GigabitEthernet1/0/{i}"
                if port_name in swa.interfaces:
                    canonical["SWITCH-A"][port_name] = swa.interfaces[port_name].oper_status.upper()

        # Switch B: ports 1 to 24
        swb = self.get_device("SWITCH-B")
        if swb:
            for i in range(1, 25):
                port_name = f"GigabitEthernet1/0/{i}"
                if port_name in swb.interfaces:
                    canonical["SWITCH-B"][port_name] = swb.interfaces[port_name].oper_status.upper()

        return canonical
