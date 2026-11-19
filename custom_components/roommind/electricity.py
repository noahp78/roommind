"""Translate the climate controller's existing MPC plan into a load forecast."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any

from .const import MODE_COOLING, MODE_HEATING, MODE_IDLE
from .control.mpc_optimizer import MPCPlan

CONF_ELECTRICITY_FORECASTS = "electricity_forecasts"


@dataclass(frozen=True)
class ElectricalSystem:
    """One physical electrical load, possibly shared by multiple rooms."""

    rooms: list[str]
    max_electrical_kw: float
    standby_kw: float = 0.0
    heat_thermal_kw: float | None = None
    cool_thermal_kw: float | None = None
    heating_cop: float = 3.0
    heating_cop_per_degree: float = 0.0
    cooling_cop: float = 3.0
    power_sensor: str | None = None

    def variable_kw(self, mode: str, fraction: float, outdoor_c: float | None) -> float:
        """Estimate draw above standby from modulation and equipment ratings."""
        maximum = self.max_electrical_kw - self.standby_kw
        if mode == MODE_HEATING and self.heat_thermal_kw is not None:
            outdoor = outdoor_c if outdoor_c is not None else 7.0
            maximum = self.heat_thermal_kw / max(1.0, self.heating_cop + self.heating_cop_per_degree * (outdoor - 7))
        elif mode == MODE_COOLING and self.cool_thermal_kw is not None:
            maximum = self.cool_thermal_kw / self.cooling_cop
        elif mode not in (MODE_HEATING, MODE_COOLING):
            return 0.0
        return maximum * min(1.0, max(0.0, fraction))


def validate_systems(data: object) -> dict[str, dict[str, Any]]:
    """Validate options while keeping them JSON serializable."""
    if not isinstance(data, dict):
        raise ValueError("Expected a mapping of systems")
    rooms: set[str] = set()
    meters: set[str] = set()
    for key, config in data.items():
        if (
            not isinstance(key, str)
            or not key
            or not key.isascii()
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in key)
        ):
            raise ValueError("Use a system ID formed from lowercase letters, digits and underscores")
        system = ElectricalSystem(**config)
        if (
            not isinstance(system.rooms, list)
            or not system.rooms
            or any(not isinstance(room, str) or not room for room in system.rooms)
            or len(set(system.rooms)) != len(system.rooms)
            or rooms.intersection(system.rooms)
        ):
            raise ValueError("Each room must belong to exactly one configured electrical system")
        rooms.update(system.rooms)
        values = [system.max_electrical_kw, system.standby_kw, system.heating_cop, system.cooling_cop]
        values.extend(value for value in (system.heat_thermal_kw, system.cool_thermal_kw) if value is not None)
        for value in values:
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError("Power and COP values must be finite and nonnegative")
        if (
            system.max_electrical_kw <= 0
            or system.standby_kw >= system.max_electrical_kw
            or system.heating_cop < 1
            or system.cooling_cop < 1
            or type(system.heating_cop_per_degree) not in (int, float)
            or not isfinite(system.heating_cop_per_degree)
        ):
            raise ValueError("Invalid power cap, standby power or COP")
        if system.power_sensor is not None:
            meter = system.power_sensor
            if not isinstance(meter, str) or not meter.startswith("sensor.") or meter in meters:
                raise ValueError("Assign a dedicated power sensor to at most one system")
            meters.add(meter)
    return data


@dataclass(frozen=True)
class RoomDemand:
    """The MPC trajectory and the first action after RoomMind's runtime checks."""

    plan: MPCPlan
    outdoor_c: list[float]
    mode: str
    fraction: float

    def power(self, system: ElectricalSystem, block: int) -> float:
        """Infer draw for a given block without rerunning the optimizer."""
        if block == 0:
            mode, fraction = self.mode, self.fraction
        else:
            mode = self.plan.actions[block]
            fraction = (
                self.plan.power_fractions[block] if block < len(self.plan.power_fractions) else float(mode != MODE_IDLE)
            )
        outdoor = self.outdoor_c[block] if block < len(self.outdoor_c) else None
        return system.variable_kw(mode, fraction, outdoor)


def observed_scale(previous: float, measured_kw: float, standby_kw: float, nominal_kw: float) -> float:
    """Update a bounded estimate slowly from dedicated meter observations."""
    if not isfinite(measured_kw) or measured_kw <= standby_kw + 0.03 or nominal_kw < 0.15:
        return previous
    ratio = max(0.45, min(1.75, (measured_kw - standby_kw) / nominal_kw))
    return 0.9 * previous + 0.1 * ratio


def build_forecast(
    source: str,
    system: ElectricalSystem,
    demands: Mapping[str, RoomDemand],
    now: datetime,
    scale: float = 1.0,
) -> dict[str, Any] | None:
    """Publish one schedule per system, using the highest simultaneous room call."""
    plans = [demands[room] for room in system.rooms if room in demands]
    if len(plans) != len(system.rooms):
        return None
    blocks = min(len(demand.plan.actions) for demand in plans)
    minutes = plans[0].plan.dt_minutes
    if not blocks or minutes <= 0 or any(demand.plan.dt_minutes != minutes for demand in plans):
        return None
    interval = timedelta(minutes=minutes)
    periods: list[dict[str, str | float]] = []
    # MPC re-evaluates on a rolling horizon. Round its start to the minute
    # to avoid emitting a new subsecond timestamp at every update.
    start = now.replace(second=0, microsecond=0)
    for block in range(blocks):
        variable = max(demand.power(system, block) for demand in plans)
        kw = min(system.max_electrical_kw, system.standby_kw + variable * scale)
        end = start + interval
        periods.append({"start": start.isoformat(), "end": end.isoformat(), "power_kw": round(kw, 3)})
        start = end
    return {
        "schema_version": 1,
        "source": source,
        "generated_at": now.isoformat(),
        "valid_until": (now + timedelta(minutes=15)).isoformat(),
        "unit": "kW",
        "forecast_interval_minutes": int(minutes),
        "forecast": periods,
        "estimated": True,
        "calibration_scale": round(scale, 3),
        "rooms": system.rooms,
    }
