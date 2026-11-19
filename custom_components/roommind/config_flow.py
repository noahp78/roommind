"""Config flow for RoomMind integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback, valid_entity_id
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import ObjectSelector

from .const import DOMAIN
from .electricity import CONF_ELECTRICITY_FORECASTS, validate_systems


class RoomMindConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle the config flow for RoomMind."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, str] | None = None) -> ConfigFlowResult:
        """Handle the initial step – just confirm setup."""
        if user_input is not None:
            # Prevent multiple instances
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="RoomMind", data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Open the electrical forecast options."""
        return RoomMindElectricityOptions()


class RoomMindElectricityOptions(OptionsFlow):
    """Configure forecast systems without changing room control settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        value = self.config_entry.options.get(CONF_ELECTRICITY_FORECASTS, {})
        if user_input is not None:
            value = user_input.get(CONF_ELECTRICITY_FORECASTS, {})
            try:
                systems = validate_systems(value)
                areas = ar.async_get(self.hass)
                if any(areas.async_get_area(room) is None for system in systems.values() for room in system["rooms"]):
                    raise ValueError("Unknown room")
                if any(
                    (meter := system.get("power_sensor")) and not valid_entity_id(meter) for system in systems.values()
                ):
                    raise ValueError("Invalid power sensor")
            except (TypeError, ValueError):
                errors["base"] = "invalid_electricity_forecasts"
            else:
                return self.async_create_entry(
                    title="",
                    data={**self.config_entry.options, CONF_ELECTRICITY_FORECASTS: systems},
                )
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ELECTRICITY_FORECASTS,
                        description={"suggested_value": value},
                    ): ObjectSelector(),
                }
            ),
        )
