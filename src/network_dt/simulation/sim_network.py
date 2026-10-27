"""Simulated network behavior engine.

Implements pure-software connectivity verification (ping, traceroute) and in-process
Cisco IOS command execution against the shared StateEngine.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..core.models import Interface, PingResult, TracerouteHop, TracerouteResult
from ..core.state_engine import StateEngine


class SimulatedNetwork:
    """Orchestrates simulated connectivity and CLI operations across the virtual topology."""

    def __init__(self, state_engine: Optional[StateEngine] = None):
        self.state = state_engine if state_engine is not None else StateEngine()

    def _resolve_ip(self, ip_str: str) -> Optional[Tuple[str, Optional[str], Optional[int]]]:
        """Resolve an IP address to (device_name_or_host, interface_name_or_none, vlan_id).
        
        Returns:
            Tuple of (owner_name, port_or_iface_name, vlan_id) or None.
        """
        ip = ip_str.strip()

        # Check configured hosts first
        if ip in self.state.hosts:
            host_info = self.state.hosts[ip]
            return host_info["device"], host_info["port"], host_info["vlan"]

        # Check router subinterfaces and SVIs
        for dev_name, device in self.state.devices.items():
            for if_name, iface in device.interfaces.items():
                if iface.ip_address == ip:
                    vlan = iface.dot1q_vlan or iface.access_vlan or (10 if "Vlan10" in if_name else 30 if "Vlan30" in if_name else None)
                    return dev_name, if_name, vlan

        return None

    def ping(self, src_ip: str, dst_ip: str, count: int = 4) -> PingResult:
        """Simulate ICMP Echo Request and Echo Reply in pure software.
        
        Evaluates physical port status, 802.1Q trunking, router subinterfaces,
        and device availability without issuing OS ping commands or network sockets.
        """
        src = src_ip.strip()
        dst = dst_ip.strip()

        src_res = self._resolve_ip(src)
        dst_res = self._resolve_ip(dst)

        if not src_res:
            return PingResult(
                success=False,
                src_ip=src,
                dst_ip=dst,
                packets_sent=count,
                packets_received=0,
                packet_loss_pct=100.0,
                message=f"Source IP {src} is not configured on any host or interface.",
            )

        if not dst_res:
            return PingResult(
                success=False,
                src_ip=src,
                dst_ip=dst,
                packets_sent=count,
                packets_received=0,
                packet_loss_pct=100.0,
                message=f"Destination IP {dst} is unreachable: Unknown IP address.",
            )

        src_dev_name, src_port, src_vlan = src_res
        dst_dev_name, dst_port, dst_vlan = dst_res

        # 1. Verify source device and port operational state
        src_dev = self.state.get_device(src_dev_name)
        if not src_dev or not src_dev.is_reachable:
            return PingResult(
                success=False,
                src_ip=src,
                dst_ip=dst,
                packets_sent=count,
                packets_received=0,
                packet_loss_pct=100.0,
                message=f"Source device {src_dev_name} is UNREACHABLE.",
            )

        if src_port:
            src_iface = src_dev.get_interface(src_port)
            if not src_iface or not src_iface.is_operational:
                return PingResult(
                    success=False,
                    src_ip=src,
                    dst_ip=dst,
                    packets_sent=count,
                    packets_received=0,
                    packet_loss_pct=100.0,
                    message=f"Source port {src_dev_name}:{src_port} is DOWN.",
                )

        # 2. Verify destination device and port operational state
        dst_dev = self.state.get_device(dst_dev_name)
        if not dst_dev or not dst_dev.is_reachable:
            return PingResult(
                success=False,
                src_ip=src,
                dst_ip=dst,
                packets_sent=count,
                packets_received=0,
                packet_loss_pct=100.0,
                message=f"Destination device {dst_dev_name} is UNREACHABLE.",
            )

        if dst_port:
            dst_iface = dst_dev.get_interface(dst_port)
            if not dst_iface or not dst_iface.is_operational:
                return PingResult(
                    success=False,
                    src_ip=src,
                    dst_ip=dst,
                    packets_sent=count,
                    packets_received=0,
                    packet_loss_pct=100.0,
                    message=f"Destination port {dst_dev_name}:{dst_port} is DOWN.",
                )

        # 3. Path evaluation: Intra-VLAN vs Inter-VLAN
        if src_vlan == dst_vlan and src_dev_name == dst_dev_name:
            # Local intra-switch delivery
            return PingResult(
                success=True,
                src_ip=src,
                dst_ip=dst,
                packets_sent=count,
                packets_received=count,
                packet_loss_pct=0.0,
                avg_latency_ms=1.0,
                message="Intra-VLAN local delivery successful.",
            )

        # Inter-VLAN or Inter-Switch: Requires Router R1
        router = self.state.get_device("ROUTER-GW")
        if not router or not router.is_reachable:
            return PingResult(
                success=False,
                src_ip=src,
                dst_ip=dst,
                packets_sent=count,
                packets_received=0,
                packet_loss_pct=100.0,
                message="Inter-VLAN routing failed: ROUTER-GW is UNREACHABLE.",
            )

        # Check source switch trunk to R1 (if source is on a switch)
        if src_dev.device_type == "switch":
            src_trunk = src_dev.get_interface("GigabitEthernet1/0/1")
            if not src_trunk or not src_trunk.is_operational:
                return PingResult(
                    success=False,
                    src_ip=src,
                    dst_ip=dst,
                    packets_sent=count,
                    packets_received=0,
                    packet_loss_pct=100.0,
                    message=f"Trunk link on {src_dev_name} is DOWN.",
                )
            if src_vlan and src_vlan not in src_trunk.allowed_vlans:
                return PingResult(
                    success=False,
                    src_ip=src,
                    dst_ip=dst,
                    packets_sent=count,
                    packets_received=0,
                    packet_loss_pct=100.0,
                    message=f"Trunk on {src_dev_name} drops VLAN {src_vlan}: Not in allowed list.",
                )

        # Check router subinterface for source VLAN
        if src_vlan:
            src_subif_name = f"GigabitEthernet0/0.{src_vlan}" if src_vlan in [10, 20] else f"GigabitEthernet0/1.{src_vlan}"
            src_subif = router.get_interface(src_subif_name)
            if not src_subif or not src_subif.is_operational:
                return PingResult(
                    success=False,
                    src_ip=src,
                    dst_ip=dst,
                    packets_sent=count,
                    packets_received=0,
                    packet_loss_pct=100.0,
                    message=f"Router gateway subinterface {src_subif_name} is DOWN.",
                )

        # Check router subinterface for destination VLAN
        if dst_vlan:
            dst_subif_name = f"GigabitEthernet0/0.{dst_vlan}" if dst_vlan in [10, 20] else f"GigabitEthernet0/1.{dst_vlan}"
            dst_subif = router.get_interface(dst_subif_name)
            if not dst_subif or not dst_subif.is_operational:
                return PingResult(
                    success=False,
                    src_ip=src,
                    dst_ip=dst,
                    packets_sent=count,
                    packets_received=0,
                    packet_loss_pct=100.0,
                    message=f"Router destination subinterface {dst_subif_name} is DOWN.",
                )

        # Check destination switch trunk from R1 (if destination is on a switch)
        if dst_dev.device_type == "switch":
            dst_trunk = dst_dev.get_interface("GigabitEthernet1/0/1")
            if not dst_trunk or not dst_trunk.is_operational:
                return PingResult(
                    success=False,
                    src_ip=src,
                    dst_ip=dst,
                    packets_sent=count,
                    packets_received=0,
                    packet_loss_pct=100.0,
                    message=f"Trunk link on {dst_dev_name} is DOWN.",
                )
            if dst_vlan and dst_vlan not in dst_trunk.allowed_vlans:
                return PingResult(
                    success=False,
                    src_ip=src,
                    dst_ip=dst,
                    packets_sent=count,
                    packets_received=0,
                    packet_loss_pct=100.0,
                    message=f"Trunk on {dst_dev_name} drops VLAN {dst_vlan}: Not in allowed list.",
                )

        # Inter-VLAN delivery successful
        return PingResult(
            success=True,
            src_ip=src,
            dst_ip=dst,
            packets_sent=count,
            packets_received=count,
            packet_loss_pct=0.0,
            avg_latency_ms=1.0,
            message="Inter-VLAN routing delivery successful (0% loss, ~1ms latency).",
        )

    def traceroute(self, src_ip: str, dst_ip: str) -> TracerouteResult:
        """Simulate network traceroute reproducing Section 2.5 Figure 8."""
        ping_res = self.ping(src_ip, dst_ip, count=1)
        if not ping_res.success:
            return TracerouteResult(
                success=False,
                src_ip=src_ip,
                dst_ip=dst_ip,
                message=f"Traceroute failed: {ping_res.message}",
            )

        src_res = self._resolve_ip(src_ip)
        dst_res = self._resolve_ip(dst_ip)
        _, _, src_vlan = src_res  # type: ignore
        _, _, dst_vlan = dst_res  # type: ignore

        hops: List[TracerouteHop] = []

        if src_vlan != dst_vlan:
            # Hop 1: Default Gateway on Router R1
            vlan_obj = self.state.get_vlan(src_vlan) if src_vlan else None
            gateway_ip = vlan_obj.gateway if vlan_obj else "192.168.30.1"
            hops.append(TracerouteHop(hop_number=1, ip=gateway_ip, hostname="R1.lab.local", latency_ms=1.0))

        # Final Hop: Destination Host
        hops.append(TracerouteHop(hop_number=len(hops) + 1, ip=dst_ip, hostname=f"Host-{dst_ip}", latency_ms=1.0))

        return TracerouteResult(
            success=True,
            src_ip=src_ip,
            dst_ip=dst_ip,
            hops=hops,
            message="Trace complete.",
        )

    def execute_cisco_command(self, device_id: str, command: str) -> str:
        """Execute Cisco IOS commands against the virtual device."""
        device = self.state.get_device(device_id)
        if not device:
            return f"% Device '{device_id}' not found."

        cmd = command.strip().lower()

        # 1. show ip interface brief
        if cmd.startswith("show ip int"):
            lines = ["Interface                  IP-Address      OK? Method Status                Protocol"]
            for if_name, iface in device.interfaces.items():
                ip = iface.ip_address or "unassigned"
                status = "up" if iface.admin_status == "UP" else "administratively down"
                proto = "up" if iface.oper_status == "UP" else "down"
                lines.append(f"{if_name:<26} {ip:<15} YES manual {status:<21} {proto}")
            return "\n".join(lines)

        # 2. show interfaces status
        if cmd.startswith("show int") and "status" in cmd:
            lines = ["Port      Name               Status       Vlan       Duplex  Speed Type"]
            for if_name, iface in device.interfaces.items():
                status = "connected" if iface.is_operational else "disabled" if iface.admin_status == "DOWN" else "notconnect"
                vlan_str = str(iface.access_vlan) if iface.mode == "access" and iface.access_vlan else "trunk" if iface.mode == "trunk" else "routed"
                lines.append(f"{if_name:<9} {'':<18} {status:<12} {vlan_str:<10} a-full  a-1000 10/100/1000BaseTX")
            return "\n".join(lines)

        # 2b. show interfaces <interface_name> (Section 4.1.3)
        show_if_match = re.match(r"show\s+interfaces?\s+([a-zA-Z0-9/.]+)", command, re.IGNORECASE)
        if show_if_match and not ("status" in cmd or "trunk" in cmd):
            target_if_name = show_if_match.group(1)
            iface = device.get_interface(target_if_name)
            if not iface:
                return f"% Interface {target_if_name} not found."
            line_status = "up" if iface.admin_status == "UP" else "administratively down"
            proto_status = "up" if iface.oper_status == "UP" else "down"
            hardware_type = "Gigabit Ethernet" if "Gigabit" in iface.name else "FastEthernet" if "Fast" in iface.name else "SVI"
            return (
                f"{iface.name} is {line_status}, line protocol is {proto_status}\n"
                f"  Hardware is {hardware_type}, address is 0019.e86b.7380 (bia 0019.e86b.7380)\n"
                f"  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec\n"
                f"  Encapsulation ARPA, loopback not set\n"
                f"  Full-duplex, 1000Mb/s, media type is 10/100/1000BaseTX\n"
                f"  5 minute input rate 1000 bits/sec, 2 packets/sec\n"
                f"  5 minute output rate 1000 bits/sec, 2 packets/sec"
            )

        # 3. show vlan brief
        if cmd.startswith("show vlan"):
            lines = ["VLAN Name                             Status    Ports", "---- -------------------------------- --------- -------------------------------"]
            for vlan_id, vlan in self.state.vlans.items():
                ports = [if_name for if_name, iface in device.interfaces.items() if iface.access_vlan == vlan_id]
                lines.append(f"{vlan_id:<4} {vlan.name:<32} active    {', '.join(ports)}")
            return "\n".join(lines)

        # 4. show interfaces trunk
        if cmd.startswith("show int") and "trunk" in cmd:
            lines = [
                "Port        Mode             Encapsulation  Status        Native vlan",
                "Port        Vlans allowed on trunk",
            ]
            for if_name, iface in device.interfaces.items():
                if iface.mode == "trunk":
                    vlans_str = ",".join(str(v) for v in iface.allowed_vlans)
                    lines.append(f"{if_name:<11} on               802.1q         trunking      1")
                    lines.append(f"{if_name:<11} {vlans_str}")
            return "\n".join(lines)

        # 5. Interface shutdown / no shutdown
        shutdown_match = re.search(r"interface\s+(\S+)\s+(?:no\s+)?shutdown", command, re.IGNORECASE)
        if shutdown_match:
            port_name = shutdown_match.group(1)
            is_no = "no shutdown" in command.lower()
            iface = device.get_interface(port_name)
            if iface:
                if is_no:
                    iface.no_shutdown()
                else:
                    iface.shutdown()
                self.state.save()
                return f"% Interface {port_name} changed state to {'up' if is_no else 'administratively down'}."

        return f"% Command '{command}' accepted."
