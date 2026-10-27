"""Simulated SNMP provider implementing standard MIB-II OIDs.

Resolves SNMP queries against the shared virtual network state in pure Python,
faithfully mimicking PySNMP behavior without contacting real equipment.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..core.models import Device, Interface
from ..core.state_engine import StateEngine

# Standard MIB-II Object Identifiers documented in Section 3.2, Figure 10
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
OID_SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
OID_IF_STATUS = "1.3.6.1.2.1.2.2.1.8"           # ifOperStatus: 1=UP, 2=DOWN
OID_IF_ADMIN_STATUS = "1.3.6.1.2.1.2.2.1.7"     # ifAdminStatus: 1=UP, 2=DOWN


class SnmpError(Exception):
    """Base exception for simulated SNMP operations."""
    pass


class SnmpTimeoutError(SnmpError):
    """Raised when an SNMP target is unreachable or does not respond."""
    pass


class SimulatedSnmpProvider:
    """Emulates a standard SNMPv2c agent for all simulated network devices."""

    def __init__(self, state_engine: Optional[StateEngine] = None):
        self.state = state_engine if state_engine is not None else StateEngine()

    def _resolve_device(self, device_ip_or_name: str) -> Optional[Device]:
        """Lookup device by IP address, canonical name, or alias."""
        return self.state.get_device(device_ip_or_name)

    def _get_ordered_interfaces(self, device: Device) -> List[Tuple[int, str, Interface]]:
        """Return deterministic (index, name, Interface) mappings for the device.
        
        Indexes are 1-based integers conforming to standard ifIndex numbering.
        """
        # Deterministic sorting: physical ports first, subinterfaces, then SVIs
        def sort_key(name: str) -> Tuple[int, int, str]:
            if name.startswith("GigabitEthernet0/0.") or name.startswith("GigabitEthernet0/1."):
                sub_id = int(name.split(".")[-1]) if name.split(".")[-1].isdigit() else 0
                return (2, sub_id, name)
            if name.startswith("GigabitEthernet1/0/"):
                port_id = int(name.split("/")[-1]) if name.split("/")[-1].isdigit() else 0
                return (1, port_id, name)
            if name.startswith("GigabitEthernet0/"):
                port_id = int(name.split("/")[-1]) if name.split("/")[-1].isdigit() else 0
                return (0, port_id, name)
            if name.startswith("Vlan"):
                vlan_id = int(name.replace("Vlan", "")) if name.replace("Vlan", "").isdigit() else 0
                return (3, vlan_id, name)
            return (4, 0, name)

        sorted_names = sorted(device.interfaces.keys(), key=sort_key)
        return [(idx + 1, name, device.interfaces[name]) for idx, name in enumerate(sorted_names)]

    def get(self, device_target: str, oid: str, community: str = "public") -> str:
        """Simulate an SNMP GET operation.
        
        Args:
            device_target: Target IP address or device identifier.
            oid: Fully qualified OID string.
            community: SNMP community string (defaults to 'public').
            
        Returns:
            String value of the requested MIB object.
            
        Raises:
            SnmpTimeoutError: If device is unreachable, SNMP disabled, or community invalid.
            SnmpError: If OID is not found.
        """
        device = self._resolve_device(device_target)
        if not device or not device.is_reachable or not device.snmp_config.enabled:
            raise SnmpTimeoutError(f"Target '{device_target}' is UNREACHABLE or SNMP agent disabled.")

        if device.snmp_config.community != community:
            raise SnmpTimeoutError(f"SNMP community authentication failed for '{device_target}'.")

        # 1. System MIB scalar objects
        if oid == OID_SYS_NAME:
            return device.hostname or device.name
        if oid == OID_SYS_UPTIME:
            return str(device.uptime_ticks)
        if oid == OID_SYS_CONTACT:
            return device.snmp_config.contact
        if oid == OID_SYS_LOCATION:
            return device.snmp_config.location

        # 2. Interface table lookups
        ordered_ifaces = self._get_ordered_interfaces(device)

        # ifDescr: 1.3.6.1.2.1.2.2.1.2.<index>
        if oid.startswith(f"{OID_IF_DESCR}."):
            idx_str = oid.split(".")[-1]
            if idx_str.isdigit():
                idx = int(idx_str)
                for if_idx, name, _ in ordered_ifaces:
                    if if_idx == idx:
                        return name
            raise SnmpError(f"No such instance at this OID: {oid}")

        # ifOperStatus: 1.3.6.1.2.1.2.2.1.8.<index> (1=UP, 2=DOWN)
        if oid.startswith(f"{OID_IF_STATUS}."):
            idx_str = oid.split(".")[-1]
            if idx_str.isdigit():
                idx = int(idx_str)
                for if_idx, _, iface in ordered_ifaces:
                    if if_idx == idx:
                        return "1" if iface.oper_status.upper() == "UP" else "2"
            raise SnmpError(f"No such instance at this OID: {oid}")

        # ifAdminStatus: 1.3.6.1.2.1.2.2.1.7.<index> (1=UP, 2=DOWN)
        if oid.startswith(f"{OID_IF_ADMIN_STATUS}."):
            idx_str = oid.split(".")[-1]
            if idx_str.isdigit():
                idx = int(idx_str)
                for if_idx, _, iface in ordered_ifaces:
                    if if_idx == idx:
                        return "1" if iface.admin_status.upper() == "UP" else "2"
            raise SnmpError(f"No such instance at this OID: {oid}")

        raise SnmpError(f"OID not supported in simulated MIB: {oid}")

    def walk(self, device_target: str, root_oid: str, community: str = "public") -> List[Tuple[str, str]]:
        """Simulate an SNMP WALK (getNext sequence) over a MIB subtree."""
        device = self._resolve_device(device_target)
        if not device or not device.is_reachable or not device.snmp_config.enabled:
            raise SnmpTimeoutError(f"Target '{device_target}' is UNREACHABLE or SNMP agent disabled.")

        if device.snmp_config.community != community:
            raise SnmpTimeoutError(f"SNMP community authentication failed for '{device_target}'.")

        results: List[Tuple[str, str]] = []
        ordered_ifaces = self._get_ordered_interfaces(device)

        if root_oid == OID_IF_DESCR:
            for if_idx, name, _ in ordered_ifaces:
                results.append((f"{OID_IF_DESCR}.{if_idx}", name))
            return results

        if root_oid == OID_IF_STATUS:
            for if_idx, _, iface in ordered_ifaces:
                val = "1" if iface.oper_status.upper() == "UP" else "2"
                results.append((f"{OID_IF_STATUS}.{if_idx}", val))
            return results

        raise SnmpError(f"Subtree walk not supported for OID: {root_oid}")

    def snmp_walk_interfaces(self, device_target: str, community: str = "public") -> List[Tuple[str, str]]:
        """Walk and collect all interface statuses matching Figure 11 of the report.
        
        Algorithm:
        1. Query OID_IF_DESCR subtree to discover all interfaces and their indexes.
        2. For each interface index, query OID_IF_STATUS.<index>.
        3. Translate '1' -> 'UP (OK)', '2' -> 'DOWN (FAIL)', else -> 'UNKNOWN'.
        
        Reference: Section 3.3, Figure 11 of Rapport_TP_Reseau.pdf.
        """
        results: List[Tuple[str, str]] = []
        try:
            var_binds = self.walk(device_target, OID_IF_DESCR, community=community)
        except SnmpTimeoutError:
            raise

        for oid, if_name in var_binds:
            if_index = oid.split(".")[-1]
            try:
                status_val = self.get(device_target, f"{OID_IF_STATUS}.{if_index}", community=community)
            except SnmpError:
                status_val = "0"

            if status_val == "1":
                status_text = "UP (OK)"
            elif status_val == "2":
                status_text = "DOWN (FAIL)"
            else:
                status_text = "UNKNOWN"

            results.append((if_name, status_text))

        return results
