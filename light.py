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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.util.color import color_hs_to_RGB, color_RGB_to_hs

from .const import CONF_ADDRESS, DOMAIN
from .hello_fairy import HelloFairyLamp

_LOGGER = logging.getLogger(__name__)

ENTITY_ID_FORMAT = "light.{}"

LIGHT_EFFECT_LIST = ["none"]  # placeholder – you can add real effects later


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hello Fairy light entity from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data.get(CONF_NAME) or f"Hello Fairy {address[-5:]}"

    _LOGGER.debug(
        "Setting up Hello Fairy light for %s (%s) from entry %s",
        name,
        address,
        entry.entry_id,
    )

    lamp = HelloFairyLamp(hass, address)
    entity = HelloFairyLightEntity(hass, entry, lamp, name, address)
    async_add_entities([entity])


class HelloFairyLightEntity(LightEntity):
    """Representation of a Hello Fairy BLE light."""

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
        """Initialize the Hello Fairy light entity."""
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

        # Subscribe to lamp state changes (mainly connection/disconnect)
        self._lamp.add_callback_on_state_changed(self._async_lamp_state_changed)

    async def async_added_to_hass(self) -> None:
        """Run when entity is about to be added to hass."""
        # Clean up BLE connection on shutdown
        self.async_on_remove(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._async_ha_stop
            )
        )

    async def _async_ha_stop(self, _event: Any) -> None:
        """Handle Home Assistant stopping."""
        _LOGGER.debug("Home Assistant stopping – disconnecting Hello Fairy %s", self.unique_id)
        await self._lamp.disconnect()

    # ------------------------------------------------------------------
    # Device info & availability
    # ------------------------------------------------------------------
    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information for the registry."""
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Hello Fairy",
            "model": "Hello Fairy BLE String Lights",
        }

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return self._lamp.available

    # ------------------------------------------------------------------
    # Light properties
    # ------------------------------------------------------------------
    @property
    def is_on(self) -> bool:
        """Return true if the light is on."""
        return self._attr_is_on

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @callback
    def _async_lamp_state_changed(self) -> None:
        """Handle callbacks from the BLE lamp wrapper."""
        # Right now we only really use this for availability.
        self.async_write_ha_state()

    @staticmethod
    def _ha_brightness_to_pct(brightness: int) -> int:
        """Convert HA brightness 0–255 to 0–100%."""
        if brightness <= 0:
            return 0
        return max(1, min(100, round(brightness * 100.0 / 255.0)))

    @staticmethod
    def _pct_to_ha_brightness(pct: int) -> int:
        """Convert 0–100% to HA brightness 0–255."""
        pct = max(0, min(100, int(pct)))
        return int(round(pct * 2.55))

    # ------------------------------------------------------------------
    # Entity actions
    # ------------------------------------------------------------------
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        _LOGGER.debug("Turning on Hello Fairy %s with kwargs=%s", self.unique_id, kwargs)

        # Starting point: current state
        hs = kwargs.get(ATTR_HS_COLOR, self._attr_hs_color or (0.0, 0.0))
        brightness_ha = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255)
        brightness_pct = self._ha_brightness_to_pct(brightness_ha)

        # Convert HS → RGB
        red, green, blue = color_hs_to_RGB(*hs)

        # Send color+brightness (which implicitly turns it on)
        await self._lamp.set_color(red, green, blue, brightness=brightness_pct)

        # Assume success if we did not get an exception
        self._attr_is_on = True
        self._attr_brightness = brightness_ha
        self._attr_hs_color = hs

        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] in LIGHT_EFFECT_LIST:
            self._attr_effect = kwargs[ATTR_EFFECT]

        # Give the device a little time before HA might ask status again
        await asyncio.sleep(0.5)

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        _LOGGER.debug("Turning off Hello Fairy %s", self.unique_id)
        await self._lamp.turn_off()
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the entity.

        The device does not currently provide a proper 'get_state' mechanism in
        the BLE wrapper, so we mostly rely on assumed state and callbacks.
        """
        # No-op for now – all changes are driven by commands.
        return
