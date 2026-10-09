"""Dataset adapters convert source-specific formats into the canonical reading frame.

Canonical frame columns: ``unit_id``, ``timestamp`` (UTC), ``operating_mode``,
optional ``operating_hours``, one column per sensor of the equipment type, and
optional ``gt_*`` ground-truth columns used only for labels/evaluation.
"""

from .base import SensorDataAdapter
from .canonical_csv import CanonicalCsvAdapter
from .cmapss import CmapssAdapter

__all__ = ["SensorDataAdapter", "CanonicalCsvAdapter", "CmapssAdapter"]
