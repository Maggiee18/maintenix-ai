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

# C-MAPSS FD001 sensors that vary (constant ones are dropped). Names and units follow the
# dataset documentation (Saxena et al., 2008). "Normal" bands are the 1st to 99th percentile
# of the first 20 % of cycles of the 100 training engines; valid ranges are generous bounds
# used only to reject corrupt values.
def _cm(name: str, unit: str, desc: str, lo: float, hi: float, nlo: float, nhi: float) -> SensorSpec:
    return SensorSpec(name, unit, desc, lo, hi, nlo, nhi)


_CMAPSS_SENSORS = (
    _cm("s2", "degR", "T24 total temperature at LPC outlet", 580, 710, 641.5, 643.24),
    _cm("s3", "degR", "T30 total temperature at HPC outlet", 1400, 1800, 1575.94, 1597.26),
    _cm("s4", "degR", "T50 total temperature at LPT outlet", 1240, 1590, 1390.08, 1415.51),
    _cm("s7", "psia", "P30 total pressure at HPC outlet", 490, 615, 552.57, 555.29),
    _cm("s8", "rpm", "Nf physical fan speed", 2140, 2630, 2387.95, 2388.18),
    _cm("s9", "rpm", "Nc physical core speed", 8100, 10200, 9038.02, 9073.67),
    _cm("s11", "psia", "Ps30 static pressure at HPC outlet", 42, 54, 46.99, 47.72),
    _cm("s12", "pps/psi", "phi ratio of fuel flow to Ps30", 465, 580, 520.81, 522.97),
    _cm("s13", "rpm", "NRf corrected fan speed", 2140, 2630, 2387.94, 2388.17),
    _cm("s14", "rpm", "NRc corrected core speed", 7280, 9130, 8120.18, 8153.84),
    _cm("s15", "-", "BPR bypass ratio", 7.4, 9.5, 8.359, 8.4795),
    _cm("s17", "-", "htBleed bleed enthalpy", 340, 440, 390, 395),
    _cm("s20", "lbm/s", "W31 HPT coolant bleed", 34, 44, 38.64, 39.23),
    _cm("s21", "lbm/s", "W32 LPT coolant bleed", 20, 26, 23.18, 23.53),
)

TURBOFAN_ENGINE = EquipmentTypeSpec(
    key="turbofan_engine",
    display_name="Turbofan Engine (C-MAPSS)",
    description="NASA C-MAPSS FD001 turbofan degradation data (real benchmark dataset). One reading per flight cycle.",
    sensors=_CMAPSS_SENSORS,
    rul_supported=True,
    sampling_interval_seconds=3600,  # cycles are mapped to 1 hour for storage; see docs
    failure_horizon_hours=30,
    data_note="NASA C-MAPSS FD001 (public domain). Cycles are stored as hourly timestamps, so hours below mean flight cycles.",
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
