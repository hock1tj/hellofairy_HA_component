"""Light platform for Hello Fairy."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.components.bluetooth import async_last_service_info
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_RGB_to_hs,
)

from .const import CONF_ADDRESS, DOMAIN
from .hello_fairy import HelloFairyLamp

_LOGGER = logging.getLogger(__name__)

ENTITY_ID_FORMAT = "light.{}"
LIGHT_EFFECT_LIST = ["none"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hello Fairy light entity from config entry."""
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data.get(CONF_NAME) or f"Hello Fairy {address[-5:]}"
    lamp = HelloFairyLamp(hass, address)
    async_add_entities([HelloFairyLightEntity(hass, entry, lamp, name, address)])


class HelloFairyLightEntity(LightEntity):
    """Representation of a Hello Fairy BLE light."""

    # FORCE Home Assistant to use async_turn_on/async_turn_off
    _enable_turn_on_off_backwards_compatibility = False

    _attr_should_poll = False
    _attr_supported_color_modes = {ColorMode.HS}
    _attr_color_mode = ColorMode.HS
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        lamp: HelloFairyLamp,
        name: str,
        address: str,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._lamp = lamp

        self._attr_name = name
        self._attr_unique_id = address
        self._attr_effect_list = LIGHT_EFFECT_LIST
        self._attr_effect = "none"
        self._attr_is_on = False
        self._attr_brightness = 255
        self._attr_hs_color = (0.0, 0.0)

        self.entity_id = generate_entity_id(ENTITY_ID_FORMAT, self._attr_name, [])

        self._lamp.add_callback_on_state_changed(self._async_lamp_state_changed)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added."""
        self.async_on_remove(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._async_ha_stop
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect BLE when entity is removed."""
        await self._lamp.disconnect()

    async def _async_ha_stop(self, _) -> None:
        """Handle HA shutdown."""
        await self._lamp.disconnect()

    # -----------------------------------
    # Availability based on BLE discovery
    # -----------------------------------

    def _is_ble_nearby(self) -> bool:
        """Return True if HA recently saw BLE advertisements from this device."""
        info = async_last_service_info(self.hass, self.unique_id)
        return info is not None

    @property
    def available(self) -> bool:
        """Available if advertisements seen or if BLE connected."""
        if self._is_ble_nearby():
            return True
        return self._lamp.available

    # -----------------------------------
    # Sync methods must not be used
    # -----------------------------------

    def turn_on(self, **kwargs):
        raise NotImplementedError("Sync turn_on() should never be called.")

    def turn_off(self, **kwargs):
        raise NotImplementedError("Sync turn_off() should never be called.")

    # -----------------------------------
    # ASYNC TURN_ON / TURN_OFF
    # -----------------------------------

    @callback
    def _async_lamp_state_changed(self) -> None:
        self.async_write_ha_state()

    @staticmethod
    def _ha_brightness_to_pct(brightness: int) -> int:
        return max(1, min(100, round(brightness * 100 / 255)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn light on with optional color and brightness."""
        _LOGGER.debug("Async turn_on with kwargs=%s", kwargs)

        # Handle incoming parameters
        hs = kwargs.get(ATTR_HS_COLOR, self._attr_hs_color)
        brightness_ha = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness)
        brightness_pct = self._ha_brightness_to_pct(brightness_ha)
        red, green, blue = color_hs_to_RGB(*hs)

        await self._lamp.set_color(red, green, blue, brightness_pct)

        self._attr_is_on = True
        self._attr_brightness = brightness_ha
        self._attr_hs_color = hs

        if ATTR_EFFECT in kwargs:
            self._attr_effect = kwargs[ATTR_EFFECT]

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn light off."""
        _LOGGER.debug("Async turn_off")
        await self._lamp.turn_off()
        self._attr_is_on = False
        self.async_write_ha_state()
