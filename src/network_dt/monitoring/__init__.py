"""SNMP Monitoring module for virtual network infrastructure.

Implements pure-Python SNMP agent simulation, standard MIB OID handling,
and periodic monitoring services without contacting real physical equipment.
"""

from .service import DevicePollResult, InterfacePollResult, MonitoringEvent, MonitoringService
from .snmp_provider import (
    OID_IF_ADMIN_STATUS,
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

__all__ = [
    "DevicePollResult",
    "InterfacePollResult",
    "MonitoringEvent",
    "MonitoringService",
    "OID_IF_ADMIN_STATUS",
    "OID_IF_DESCR",
    "OID_IF_STATUS",
    "OID_SYS_CONTACT",
    "OID_SYS_LOCATION",
    "OID_SYS_NAME",
    "OID_SYS_UPTIME",
    "SimulatedSnmpProvider",
    "SnmpError",
    "SnmpTimeoutError",
]
