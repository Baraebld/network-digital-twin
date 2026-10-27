"""Network SNMP monitoring service.

Periodically collects device availability, uptime, and interface operational status
from the shared StateEngine via the SimulatedSnmpProvider.
"""

from __future__ import annotations

import datetime
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core.state_engine import StateEngine
from .snmp_provider import (
    OID_IF_DESCR,
    OID_IF_STATUS,
    OID_SYS_NAME,
    OID_SYS_UPTIME,
    SimulatedSnmpProvider,
    SnmpError,
    SnmpTimeoutError,
)


@dataclass
class InterfacePollResult:
    """Status record for a single monitored interface."""
    if_index: int
    name: str
    status_code: int           # 1 = UP, 2 = DOWN
    status_text: str           # "UP (OK)" or "DOWN (FAIL)"
    is_up: bool


@dataclass
class DevicePollResult:
    """Aggregated SNMP monitoring record for a device."""
    device_name: str
    device_ip: str
    is_reachable: bool
    sys_name: str = ""
    sys_uptime: int = 0
    interfaces: List[InterfacePollResult] = field(default_factory=list)
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def up_interfaces_count(self) -> int:
        return sum(1 for iface in self.interfaces if iface.is_up)

    @property
    def down_interfaces_count(self) -> int:
        return sum(1 for iface in self.interfaces if not iface.is_up)


@dataclass
class MonitoringEvent:
    """Structured event log entry generated during monitoring."""
    timestamp: str
    event_type: str            # e.g., "INTERFACE_DOWN", "INTERFACE_UP", "DEVICE_UNREACHABLE"
    device_name: str
    target: str
    message: str
    level: str = "INFO"        # "INFO", "WARNING", "ERROR"


class MonitoringService:
    """Periodic SNMP monitoring service with change detection and event logging."""

    DEFAULT_REFRESH_INTERVAL = 10.0  # Documented 10-second refresh in Section 3.4

    def __init__(self, state_engine: Optional[StateEngine] = None):
        self.state = state_engine if state_engine is not None else StateEngine()
        self.provider = SimulatedSnmpProvider(state_engine=self.state)
        self.events_log: List[MonitoringEvent] = []
        self._previous_states: Dict[str, Dict[str, str]] = {}
        self._stop_event = threading.Event()

    def record_event(
        self,
        event_type: str,
        device_name: str,
        target: str,
        message: str,
        level: str = "INFO",
    ) -> MonitoringEvent:
        """Append an event to the monitoring log."""
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        evt = MonitoringEvent(
            timestamp=ts,
            event_type=event_type,
            device_name=device_name,
            target=target,
            message=message,
            level=level,
        )
        self.events_log.append(evt)
        return evt

    def poll_device(self, device_id_or_ip: str) -> DevicePollResult:
        """Query a single device via SNMP, detecting reachability and interface status changes."""
        device = self.state.get_device(device_id_or_ip)
        if not device:
            err_msg = f"Device '{device_id_or_ip}' does not exist in state."
            self.record_event("DEVICE_NOT_FOUND", device_id_or_ip, device_id_or_ip, err_msg, level="ERROR")
            return DevicePollResult(
                device_name=device_id_or_ip,
                device_ip="",
                is_reachable=False,
                error=err_msg,
            )

        target_ip = device.primary_ip or device_id_or_ip

        # 1. Check reachability / SNMP responsiveness
        try:
            sys_name = self.provider.get(target_ip, OID_SYS_NAME)
            uptime_str = self.provider.get(target_ip, OID_SYS_UPTIME)
            sys_uptime = int(uptime_str) if uptime_str.isdigit() else device.uptime_ticks
        except SnmpTimeoutError as exc:
            err_msg = f"[!] {device.name} ({target_ip}) is UNREACHABLE! Check connection."
            self.record_event("DEVICE_UNREACHABLE", device.name, target_ip, err_msg, level="ERROR")
            return DevicePollResult(
                device_name=device.name,
                device_ip=target_ip,
                is_reachable=False,
                error=err_msg,
            )

        # 2. Walk interfaces and retrieve status (Section 3.3, Figure 11)
        raw_interfaces = self.provider.snmp_walk_interfaces(target_ip)
        ifaces: List[InterfacePollResult] = []

        # Previous state map for this device
        prev_ifaces = self._previous_states.setdefault(device.name, {})

        for idx, (if_name, status_text) in enumerate(raw_interfaces, start=1):
            is_up = status_text == "UP (OK)"
            status_code = 1 if is_up else 2
            ifaces.append(InterfacePollResult(
                if_index=idx,
                name=if_name,
                status_code=status_code,
                status_text=status_text,
                is_up=is_up,
            ))

            # Detect and log state transitions
            prev_status = prev_ifaces.get(if_name)
            if prev_status is not None and prev_status != status_text:
                if status_text == "DOWN (FAIL)":
                    self.record_event(
                        "INTERFACE_DOWN",
                        device.name,
                        if_name,
                        f"Interface {if_name} on {device.name} changed status to DOWN (FAIL).",
                        level="WARNING",
                    )
                elif status_text == "UP (OK)":
                    self.record_event(
                        "INTERFACE_UP",
                        device.name,
                        if_name,
                        f"Interface {if_name} on {device.name} recovered to UP (OK).",
                        level="INFO",
                    )

            prev_ifaces[if_name] = status_text

        return DevicePollResult(
            device_name=device.name,
            device_ip=target_ip,
            is_reachable=True,
            sys_name=sys_name,
            sys_uptime=sys_uptime,
            interfaces=ifaces,
        )

    def poll_all_devices(self, reload_state: bool = True) -> List[DevicePollResult]:
        """Poll all devices configured in the network topology."""
        if reload_state:
            # Re-read persistent state so external changes (e.g. CLI shutdowns) are picked up
            self.state.load()

        targets = ["ROUTER-GW", "SWITCH-A", "SWITCH-B"]
        results: List[DevicePollResult] = []
        for target in targets:
            results.append(self.poll_device(target))
        return results

    def run_monitoring_cycle(self) -> List[DevicePollResult]:
        """Execute a single complete monitoring scan cycle."""
        return self.poll_all_devices(reload_state=True)

    def start_periodic(
        self,
        interval_seconds: float = DEFAULT_REFRESH_INTERVAL,
        max_cycles: Optional[int] = None,
        callback: Optional[Callable[[List[DevicePollResult]], None]] = None,
    ) -> None:
        """Run the periodic polling loop until stopped or max_cycles reached."""
        self._stop_event.clear()
        cycles = 0

        while not self._stop_event.is_set():
            results = self.run_monitoring_cycle()
            cycles += 1
            if callback:
                callback(results)

            if max_cycles is not None and cycles >= max_cycles:
                break

            self._stop_event.wait(timeout=interval_seconds)

    def stop(self) -> None:
        """Stop an active periodic monitoring loop."""
        self._stop_event.set()
