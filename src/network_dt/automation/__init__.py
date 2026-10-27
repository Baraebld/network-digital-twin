"""Network automation module.

Simulates Netmiko-style automated provisioning of Cisco routers and Catalyst switches
over the shared virtual network state.
"""

from .deploy import (
    AutomationDeployer,
    DeploymentAction,
    DeviceInventory,
    VerificationCheck,
    VerificationReport,
)

__all__ = [
    "AutomationDeployer",
    "DeploymentAction",
    "DeviceInventory",
    "VerificationCheck",
    "VerificationReport",
]
