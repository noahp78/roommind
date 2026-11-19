"""Verify electrical projection from the selected RoomMind MPC path."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant import loader
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_test_home_assistant

from custom_components.roommind.const import MODE_COOLING, MODE_HEATING, MODE_IDLE
from custom_components.roommind.control.mpc_optimizer import MPCPlan
from custom_components.roommind.electricity import (
    CONF_ELECTRICITY_FORECASTS,
    ElectricalSystem,
    RoomDemand,
    build_forecast,
    observed_scale,
    validate_systems,
)
from custom_components.roommind.sensor import RoomMindElectricityForecastSensor

NOW = datetime(2026, 11, 19, 16, 0, tzinfo=UTC)


def test_shared_heat_pump_projects_one_load_and_uses_actual_first_action():
    plan = MPCPlan(
        actions=[MODE_HEATING, MODE_HEATING, MODE_COOLING],
        temperatures=[19, 20, 20, 19],
        power_fractions=[1.0, 0.8, 0.6],
    )
    system = ElectricalSystem(
        ["one", "two"],
        2.4,
        standby_kw=0.03,
        heat_thermal_kw=6.0,
        cool_thermal_kw=4.0,
        heating_cop=3.0,
        heating_cop_per_degree=0.1,
        cooling_cop=4,
    )
    demand = RoomDemand(plan, [7, 2, 25], MODE_IDLE, 0.0)
    forecast = build_forecast("shared_heat_pump", system, {"one": demand, "two": demand}, NOW)
    assert [row["power_kw"] for row in forecast["forecast"]] == pytest.approx([0.03, 1.95, 0.63])
    assert forecast["source"] == "shared_heat_pump"
    assert forecast["forecast_interval_minutes"] == 5
    assert forecast["forecast"][1]["start"] == "2026-11-19T16:05:00+00:00"
    assert build_forecast("shared_heat_pump", system, {"one": demand}, NOW) is None


def test_measured_calibration_is_bounded_and_ignores_idle_samples():
    assert observed_scale(1.0, 0.02, 0.02, 1.0) == 1.0
    assert observed_scale(1.0, float("nan"), 0.02, 1.0) == 1.0
    assert observed_scale(1.0, 100, 0.02, 1.0) == pytest.approx(1.075)
    assert observed_scale(1.0, 1.52, 0.02, 1.0) == pytest.approx(1.05)


@pytest.mark.parametrize(
    "config",
    [
        {"rooms": ["one", "one"], "max_electrical_kw": 2.0},
        {"rooms": ["one"], "max_electrical_kw": None},
        {"rooms": ["one"], "max_electrical_kw": 2.0, "standby_kw": 2.0},
        {"rooms": ["one"], "max_electrical_kw": 2.0, "heating_cop": 0.5},
        {"rooms": ["one"], "max_electrical_kw": 2.0, "power_sensor": "switch.heat"},
    ],
)
def test_invalid_system(config):
    with pytest.raises(ValueError):
        validate_systems({"heat_pump": config})


def test_forecast_sensor_starts_unknown_and_publishes_v1_attributes():
    coordinator = MagicMock()
    coordinator.data = {}
    sensor = RoomMindElectricityForecastSensor(coordinator, "living_room")
    assert sensor.native_value is None
    plan = MPCPlan([MODE_HEATING], [19, 20], power_fractions=[0.5])
    demand = RoomDemand(plan, [10], MODE_HEATING, 0.5)
    forecast = build_forecast(
        "roommind_living_room",
        ElectricalSystem(["living_room"], 2.0),
        {"living_room": demand},
        NOW,
    )
    coordinator.data = {"electricity_forecasts": {"living_room": forecast}}
    assert sensor.native_value == 1.0
    assert sensor.extra_state_attributes["schema_version"] == 1
    assert sensor.entity_id == "sensor.roommind_living_room_electricity_forecast"


@pytest.mark.asyncio
async def test_roommind_options_validate_ownership(monkeypatch):
    monkeypatch.setattr("homeassistant.config_entries.async_process_deps_reqs", AsyncMock())
    monkeypatch.setattr("homeassistant.helpers.storage.Store.async_delay_save", MagicMock())
    async with async_test_home_assistant(asyncio.get_running_loop()) as hass:
        try:
            hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
            mock_config_entry = MockConfigEntry(domain="roommind")
            mock_config_entry.add_to_hass(hass)
            area = ar.async_get(hass).async_create("Living room")
            manager = hass.config_entries.options
            flow = await manager.async_init(mock_config_entry.entry_id)
            plant = {"rooms": [area.id], "max_electrical_kw": 2.0}
            invalid = await manager.async_configure(
                flow["flow_id"],
                user_input={
                    CONF_ELECTRICITY_FORECASTS: {"first": plant, "second": plant},
                },
            )
            assert invalid["errors"] == {"base": "invalid_electricity_forecasts"}
            result = await manager.async_configure(
                flow["flow_id"],
                user_input={
                    CONF_ELECTRICITY_FORECASTS: {"heat_pump": plant},
                },
            )
            assert result["type"] is FlowResultType.CREATE_ENTRY
            assert mock_config_entry.options[CONF_ELECTRICITY_FORECASTS]["heat_pump"] == plant
        finally:
            await hass.async_stop(force=True)
