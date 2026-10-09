from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..equipment_types import EquipmentTypeSpec


@dataclass
class CanonicalCsvAdapter:
    """CSV already in canonical layout (header row with canonical column names).

    ``equipment_column`` lets uploads use ``equipment_code`` instead of ``unit_id``.
    Values are read as strings and left to ``validate_readings`` to coerce, so
    type errors are reported rather than silently converted.
    """

    source: Path | bytes
    spec: EquipmentTypeSpec
    equipment_column: str = "unit_id"
    name: str = "canonical_csv"

    def load(self) -> pd.DataFrame:
        buf = io.BytesIO(self.source) if isinstance(self.source, bytes) else self.source
        df = pd.read_csv(buf, dtype=str, keep_default_na=True, na_values=[""], skipinitialspace=True)
        df.columns = [str(c).strip() for c in df.columns]
        if self.equipment_column != "unit_id" and self.equipment_column in df:
            df = df.rename(columns={self.equipment_column: "unit_id"})
        return df
