"""Hello Fairy integration init."""
from __future__ import annotations

import logging
from typing import Final

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: Final[list[Platform]] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hello Fairy from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    address = entry.data[CONF_ADDRESS].upper()

    _LOGGER.debug("Setting up Hello Fairy entry %s (%s)", entry.entry_id, address)

    hass.data[DOMAIN][entry.entry_id] = {
        CONF_ADDRESS: address,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Hello Fairy config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data and (address := entry_data.get(CONF_ADDRESS)):
            # Let HA rediscover this address again in the future
            bluetooth.async_rediscover_address(hass, address)
            _LOGGER.debug("Triggered rediscovery for %s", address)

    return unload_ok