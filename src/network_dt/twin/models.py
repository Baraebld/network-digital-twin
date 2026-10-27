"""Data models for the Network Digital Twin Golden State prototype."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class DeviationAlert:
    """Represents a detected deviation between the live state and the Golden State model."""
    device_name: str
    interface_name: str
    actual_status: str
    expected_status: str
    message: str


@dataclass
class IntegrityCheckResult:
    """Aggregated evaluation of live network integrity against the Golden State reference."""
    score: int                           # 0 to 100 percentage
    total_monitored: int                 # e.g., 50 interfaces in the canonical prototype model
    total_matching: int                  # e.g., 50 or 49
    is_healthy: bool                     # True if score == 100
    status_message: str                  # "SYSTEM HEALTHY - MATCHES TWIN MODEL" or "WARNING - DEVIATION DETECTED"
    alerts: List[DeviationAlert] = field(default_factory=list)
    analyzed_devices: List[str] = field(default_factory=list)

    @property
    def has_deviations(self) -> bool:
        """True if any deviations from the Golden State were detected."""
        return len(self.alerts) > 0
