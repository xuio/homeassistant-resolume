from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import ResolumeAPI
from .const import CONF_HOST, CONF_PORT, DOMAIN
from .coordinator import ResolumeCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = [
    "switch",  # layer bypass
    "button",  # clip trigger, master controls
    "camera",  # clip previews
    "number",  # BPM (and misc numbers)
    "select",  # mixing modes, crossfader group
    "light",  # Opacity / master as dimmable lights
]


async def async_setup(_hass: HomeAssistant, _config: dict) -> bool:  # noqa: D401, D401: we want to indicate not config.yaml
    """Set up via config flow only."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Resolume integration from a config entry."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]

    api = ResolumeAPI(host, port)
    coordinator = ResolumeCoordinator(hass, api)

    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    # Forward entry setup to platforms.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Resolume config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    data = hass.data[DOMAIN].pop(entry.entry_id)
    await data["coordinator"].async_stop()

    return unload_ok
