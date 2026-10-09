from __future__ import annotations

from typing import Protocol

import pandas as pd

from ..equipment_types import EquipmentTypeSpec


class SensorDataAdapter(Protocol):
    """Common ingestion interface. Implementations must not invent values."""

    name: str
    spec: EquipmentTypeSpec

    def load(self) -> pd.DataFrame:
        """Return the canonical reading frame (see package docstring)."""
        ...
