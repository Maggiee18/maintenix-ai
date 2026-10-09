"""Equipment type and sensor specifications.

Each equipment type declares its own sensor set. Models are trained per type,
so features never mix incompatible measurements (for example, motor current
and compressor discharge pressure).

These specs are the single source of truth: the backend seeds its
``equipment_types`` and ``sensor_definitions`` tables from them, and the
feature builder derives feature names from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OPERATING_MODES: tuple[str, ...] = ("normal", "high_load", "idle")


@dataclass(frozen=True)
class SensorSpec:
    name: str
    unit: str
    description: str
    valid_min: float  # physically plausible lower bound; values outside are rejected
    valid_max: float  # physically plausible upper bound
    normal_min: float  # typical healthy operating band (display only)
    normal_max: float
    required: bool = True


@dataclass(frozen=True)
class EquipmentTypeSpec:
    key: str
    display_name: str
    description: str
    sensors: tuple[SensorSpec, ...]
    rul_supported: bool
    sampling_interval_seconds: int = 3600
    failure_horizon_hours: int = 48
    data_note: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def sensor_names(self) -> list[str]:
        return [s.name for s in self.sensors]

    def sensor(self, name: str) -> SensorSpec:
        for s in self.sensors:
            if s.name == name:
                return s
        raise KeyError(name)


_VIBRATION = SensorSpec(
    "vibration", "mm/s", "Overall vibration velocity (RMS)", 0.0, 60.0, 0.5, 4.5
)

CENTRIFUGAL_PUMP = EquipmentTypeSpec(
    key="centrifugal_pump",
    display_name="Centrifugal Pump",
    description="Process water pump. Wear mode: bearing and impeller degradation.",
    sensors=(
        SensorSpec("temperature", "degC", "Bearing temperature", -20.0, 200.0, 40.0, 75.0),
        _VIBRATION,
        SensorSpec("pressure", "bar", "Discharge pressure", 0.0, 40.0, 6.0, 10.0),
        SensorSpec("rotational_speed", "rpm", "Shaft speed", 0.0, 4000.0, 2850.0, 3000.0),
        SensorSpec("power", "kW", "Electrical power draw", 0.0, 200.0, 25.0, 50.0),
    ),
    rul_supported=True,
    data_note="Simulated run-to-failure trajectories (bearing wear).",
)

ELECTRIC_MOTOR = EquipmentTypeSpec(
    key="electric_motor",
    display_name="Electric Motor",
    description="Induction motor driving a conveyor. Wear mode: insulation and bearing degradation.",
    sensors=(
        SensorSpec("temperature", "degC", "Winding temperature", -20.0, 220.0, 50.0, 95.0),
        _VIBRATION,
        SensorSpec("rotational_speed", "rpm", "Shaft speed", 0.0, 2000.0, 1440.0, 1500.0),
        SensorSpec("current", "A", "Phase current", 0.0, 500.0, 60.0, 115.0),
    ),
    rul_supported=True,
    data_note="Simulated run-to-failure trajectories (insulation and bearing wear).",
)

AIR_COMPRESSOR = EquipmentTypeSpec(
    key="air_compressor",
    display_name="Air Compressor",
    description="Rotary screw compressor. Fault mode: recoverable valve/cooling faults that end in a trip.",
    sensors=(
        SensorSpec("temperature", "degC", "Discharge temperature", -20.0, 250.0, 70.0, 100.0),
        _VIBRATION,
        SensorSpec("pressure", "bar", "Discharge pressure", 0.0, 20.0, 6.5, 9.0),
        SensorSpec("power", "kW", "Electrical power draw", 0.0, 300.0, 40.0, 80.0),
    ),
    # Faults are intermittent and repaired in place; there is no run-to-failure
    # trajectory, so a remaining-useful-life target cannot be defined honestly.
    rul_supported=False,
    data_note="Simulated intermittent fault episodes; no run-to-failure data, so RUL is unavailable.",
)

_CMAPSS_SENSORS = tuple(
    SensorSpec(f"s{i}", "-", f"C-MAPSS sensor {i}", -1e6, 1e6, -1e6, 1e6)
    for i in (2, 3, 4, 7, 8, 9, 11, 12, 13, 14, 15, 17, 20, 21)
)

TURBOFAN_ENGINE = EquipmentTypeSpec(
    key="turbofan_engine",
    display_name="Turbofan Engine (C-MAPSS)",
    description="NASA C-MAPSS FD001 turbofan simulation. One reading per operating cycle.",
    sensors=_CMAPSS_SENSORS,
    rul_supported=True,
    sampling_interval_seconds=3600,  # cycles are mapped to 1 hour for storage; see docs
    failure_horizon_hours=30,
    data_note="Requires the NASA C-MAPSS dataset downloaded locally (see datasets/README.md).",
)

EQUIPMENT_TYPES: dict[str, EquipmentTypeSpec] = {
    t.key: t for t in (CENTRIFUGAL_PUMP, ELECTRIC_MOTOR, AIR_COMPRESSOR, TURBOFAN_ENGINE)
}

#: Types the built-in simulator can generate.
SIMULATED_TYPES: tuple[str, ...] = ("centrifugal_pump", "electric_motor", "air_compressor")


def get_spec(key: str) -> EquipmentTypeSpec:
    try:
        return EQUIPMENT_TYPES[key]
    except KeyError as exc:  # pragma: no cover - trivial
        raise KeyError(f"Unknown equipment type '{key}'") from exc
