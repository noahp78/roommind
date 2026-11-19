"""Sensor platform for RoomMind."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RoomMindCoordinator
from .utils.area_utils import rooms_with_area


def _create_room_entities(coordinator: RoomMindCoordinator, area_id: str) -> list[SensorEntity]:
    """Create the standard set of sensor entities for a room."""
    return [
        RoomMindTargetTemperatureSensor(coordinator, area_id),
        RoomMindModeSensor(coordinator, area_id),
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RoomMind sensor entities from a config entry."""
    coordinator: RoomMindCoordinator = hass.data[DOMAIN][entry.entry_id]
    store = hass.data[DOMAIN]["store"]

    # Store the callback on the coordinator so dynamic entity creation works
    coordinator.async_add_entities = async_add_entities

    # Create entities for rooms that already exist in the store
    rooms = rooms_with_area(hass, store.get_rooms())
    entities: list[SensorEntity] = []
    for area_id in rooms:
        entities.extend(_create_room_entities(coordinator, area_id))
        coordinator._entity_areas.add(area_id)
    entities.extend(
        RoomMindElectricityForecastSensor(coordinator, system_id) for system_id in coordinator.electrical_systems
    )
    if entities:
        async_add_entities(entities)


class _RoomMindBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for all RoomMind room sensors."""

    _attr_has_entity_name = True
    # Deprecated (#238): only rooms set up before 2.0 keep them enabled; HA applies this to new registry entries only
    _attr_entity_registry_enabled_default = False
    _data_key: str  # Key in the room state dict (e.g. "current_temp")

    def __init__(
        self,
        coordinator: RoomMindCoordinator,
        area_id: str,
        suffix: str,
        name_label: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._area_id = area_id
        self._attr_unique_id = f"{DOMAIN}_{area_id}_{suffix}"
        self._attr_name = f"{area_id} {name_label}"
        self.entity_id = f"sensor.{DOMAIN}_{area_id}_{suffix}"

    @property
    def native_value(self) -> float | str | None:
        """Return the sensor value from the coordinator data."""
        room = self.coordinator.data.get("rooms", {}).get(self._area_id)
        if room:
            val = room.get(self._data_key)
            return val if isinstance(val, (float, int, str)) else None
        return None


class RoomMindTargetTemperatureSensor(_RoomMindBaseSensor):
    """Sensor showing the target temperature for a RoomMind room."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _data_key = "target_temp"

    def __init__(self, coordinator: RoomMindCoordinator, area_id: str) -> None:
        super().__init__(coordinator, area_id, "target_temp", "Target Temperature")


class RoomMindModeSensor(_RoomMindBaseSensor):
    """Sensor showing the current mode for a RoomMind room."""

    _data_key = "mode"

    def __init__(self, coordinator: RoomMindCoordinator, area_id: str) -> None:
        super().__init__(coordinator, area_id, "mode", "Mode")

    @property
    def native_value(self) -> str | None:
        """Return the current mode, defaulting to 'idle'."""
        room = self.coordinator.data.get("rooms", {}).get(self._area_id)
        if room:
            val = room.get("mode", "idle")
            return str(val) if val is not None else "idle"
        return "idle"


class RoomMindElectricityForecastSensor(CoordinatorEntity, SensorEntity):
    """Publish the forecast of one physical heating/cooling system."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_translation_key = "electricity_forecast"
    _unrecorded_attributes = frozenset({"forecast", "generated_at", "valid_until"})

    def __init__(self, coordinator: RoomMindCoordinator, system_id: str) -> None:
        super().__init__(coordinator)
        self._system_id = system_id
        self._attr_unique_id = f"{DOMAIN}_{system_id}_electricity_forecast"
        self._attr_translation_placeholders = {"system": system_id.replace("_", " ")}
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the versioned forecast snapshot as state attributes."""
        data = self.coordinator.data or {}
        return dict(data.get("electricity_forecasts", {}).get(self._system_id, {}))

    @property
    def native_value(self) -> float | None:
        forecast = self.extra_state_attributes.get("forecast")
        return float(forecast[0]["power_kw"]) if forecast else None
