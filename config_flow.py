"""Config flow for Hello Fairy."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_ADDRESS, DOMAIN

DEFAULT_NAME = "Hello Fairy"


class HelloFairyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hello Fairy."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return HelloFairyOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step initiated by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].upper()
            name = user_input.get(CONF_NAME) or DEFAULT_NAME

            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                },
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_bluetooth(self, discovery_info):
        """Handle a flow initialized by Bluetooth discovery."""
        self._discovery_info = discovery_info

        address = discovery_info.address.upper()
        name = discovery_info.name or DEFAULT_NAME

        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {"name": name}

        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        """Confirm adding the device."""
        if user_input is not None:
            address = self._discovery_info.address.upper()
            name = self._discovery_info.name or DEFAULT_NAME

            return self.async_create_entry(
                title=name,
                data={CONF_ADDRESS: address},
            )

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._discovery_info.name or DEFAULT_NAME
            }
        )




class HelloFairyOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Hello Fairy (currently empty, placeholder)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options flow."""
        # No options for now – just close.
        return self.async_create_entry(title="", data=self._entry.options)
