"""Core domain models for the network simulation environment.

Defines interfaces, VLANs, DHCP pools, devices, and connectivity result structures.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PortMode(str, Enum):
    """Switch and router port operational modes."""
    ACCESS = "access"
    TRUNK = "trunk"
    ROUTED = "routed"
    SUBINTERFACE = "subinterface"
    SVI = "svi"


@dataclass
class Interface:
    """Represents a physical or logical network interface."""
    name: str
    oper_status: str = "DOWN"       # "UP" or "DOWN"
    admin_status: str = "UP"        # "UP" or "DOWN" (shutdown sets to "DOWN")
    mode: str = "access"            # "access", "trunk", "routed", "subinterface", "svi"
    access_vlan: Optional[int] = None
    allowed_vlans: List[int] = field(default_factory=list)
    ip_address: Optional[str] = None
    subnet_mask: Optional[str] = None
    dot1q_vlan: Optional[int] = None
    connected_to: Optional[str] = None      # e.g., "SWITCH-A:GigabitEthernet1/0/1"
    connected_host: Optional[str] = None    # e.g., "192.168.20.3"
    description: Optional[str] = None

    @property
    def is_operational(self) -> bool:
        """Interface is operational only if both admin_status and oper_status are UP."""
        return self.admin_status.upper() == "UP" and self.oper_status.upper() == "UP"

    def shutdown(self) -> None:
        """Administratively disable the interface."""
        self.admin_status = "DOWN"
        self.oper_status = "DOWN"

    def no_shutdown(self) -> None:
        """Administratively enable the interface."""
        self.admin_status = "UP"
        self.oper_status = "UP"

    def to_dict(self) -> Dict[str, Any]:
        """Convert interface attributes to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Interface:
        """Reconstruct Interface instance from dictionary."""
        return cls(**data)


@dataclass
class Vlan:
    """Represents an 802.1Q Virtual Local Area Network."""
    vlan_id: int
    name: str
    subnet: str
    gateway: str
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Vlan:
        return cls(**data)


@dataclass
class DhcpPool:
    """Represents a Cisco IOS DHCP server pool configuration."""
    name: str
    network: str
    netmask: str
    default_router: str
    dns_server: str = "8.8.8.8"
    excluded_addresses: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DhcpPool:
        return cls(**data)


@dataclass
class SshConfig:
    """Represents Cisco IOS Secure Shell (SSH) server configuration."""
    enabled: bool = False
    version: int = 2
    domain_name: str = "lab.local"
    rsa_key_size: int = 1024
    admin_user: str = "admin"
    vty_ssh_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SshConfig:
        return cls(**data)


@dataclass
class SnmpConfig:
    """Represents Cisco IOS Simple Network Management Protocol (SNMP) server configuration."""
    enabled: bool = False
    community: str = "public"
    mode: str = "RO"
    location: str = "Lab"
    contact: str = "Admin"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SnmpConfig:
        return cls(**data)


@dataclass
class Device:
    """Represents a network device (Cisco Router or Catalyst Switch)."""
    name: str
    aliases: List[str] = field(default_factory=list)
    device_type: str = "switch"     # "router" or "switch"
    hostname: str = ""
    primary_ip: str = ""
    management_vlan: Optional[int] = None
    is_reachable: bool = True
    uptime_ticks: int = 2089548     # hundredths of a second (sysUpTime)
    interfaces: Dict[str, Interface] = field(default_factory=dict)
    dhcp_pools: Dict[str, DhcpPool] = field(default_factory=dict)
    vlans: List[int] = field(default_factory=list)
    ssh_config: SshConfig = field(default_factory=SshConfig)
    snmp_config: SnmpConfig = field(default_factory=SnmpConfig)

    def matches_identifier(self, identifier: str) -> bool:
        """Check if an identifier (name, alias, hostname, IP) matches this device."""
        norm_id = identifier.strip().lower()
        if self.name.lower() == norm_id:
            return True
        if self.hostname.lower() == norm_id:
            return True
        if self.primary_ip == identifier.strip():
            return True
        for alias in self.aliases:
            if alias.lower() == norm_id:
                return True
        # Check subinterface / SVI IPs
        for iface in self.interfaces.values():
            if iface.ip_address and iface.ip_address == identifier.strip():
                return True
        return False

    def get_interface(self, name: str) -> Optional[Interface]:
        """Lookup interface by exact or normalized name."""
        if name in self.interfaces:
            return self.interfaces[name]
        norm = name.strip().lower()
        for if_name, iface in self.interfaces.items():
            if if_name.lower() == norm:
                return iface
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize device to dictionary."""
        return {
            "name": self.name,
            "aliases": self.aliases,
            "device_type": self.device_type,
            "hostname": self.hostname,
            "primary_ip": self.primary_ip,
            "management_vlan": self.management_vlan,
            "is_reachable": self.is_reachable,
            "uptime_ticks": self.uptime_ticks,
            "interfaces": {k: v.to_dict() for k, v in self.interfaces.items()},
            "dhcp_pools": {k: v.to_dict() for k, v in self.dhcp_pools.items()},
            "vlans": self.vlans,
            "ssh_config": self.ssh_config.to_dict(),
            "snmp_config": self.snmp_config.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Device:
        """Deserialize device from dictionary."""
        interfaces = {k: Interface.from_dict(v) for k, v in data.get("interfaces", {}).items()}
        dhcp_pools = {k: DhcpPool.from_dict(v) for k, v in data.get("dhcp_pools", {}).items()}
        ssh_config_data = data.get("ssh_config")
        ssh_config = SshConfig.from_dict(ssh_config_data) if ssh_config_data else SshConfig()
        snmp_config_data = data.get("snmp_config")
        snmp_config = SnmpConfig.from_dict(snmp_config_data) if snmp_config_data else SnmpConfig()
        return cls(
            name=data["name"],
            aliases=data.get("aliases", []),
            device_type=data.get("device_type", "switch"),
            hostname=data.get("hostname", ""),
            primary_ip=data.get("primary_ip", ""),
            management_vlan=data.get("management_vlan"),
            is_reachable=data.get("is_reachable", True),
            uptime_ticks=data.get("uptime_ticks", 2089548),
            interfaces=interfaces,
            dhcp_pools=dhcp_pools,
            vlans=data.get("vlans", []),
            ssh_config=ssh_config,
            snmp_config=snmp_config,
        )


@dataclass
class PingResult:
    """Structured result of a simulated network ping."""
    success: bool
    src_ip: str
    dst_ip: str
    packets_sent: int = 4
    packets_received: int = 4
    packet_loss_pct: float = 0.0
    avg_latency_ms: float = 1.0
    message: str = ""


@dataclass
class TracerouteHop:
    """Represents a single hop along a network traceroute path."""
    hop_number: int
    ip: str
    hostname: Optional[str] = None
    latency_ms: float = 1.0


@dataclass
class TracerouteResult:
    """Structured result of a simulated network traceroute."""
    success: bool
    src_ip: str
    dst_ip: str
    hops: List[TracerouteHop] = field(default_factory=list)
    message: str = ""
