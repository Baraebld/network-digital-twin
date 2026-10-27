"""Network Digital Twin prototype module based on Golden State comparison.

Compares active network state against a known baseline model to detect
deviations and compute an integrity score.
"""

from .engine import DigitalTwinEngine
from .models import DeviationAlert, IntegrityCheckResult

__all__ = [
    "DeviationAlert",
    "DigitalTwinEngine",
    "IntegrityCheckResult",
]
