from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ResolumeAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ResolumeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage Resolume websocket data."""

    def __init__(self, hass: HomeAssistant, api: ResolumeAPI) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # push mode
        )
        self.api = api

    async def async_start(self) -> None:
        """Begin connection and setup listeners."""
        await self.api.async_connect()
        self._remove_cb = self.api.register_callback(self._handle_ws_message)

    async def async_stop(self) -> None:
        """Clean up when integration is unloaded."""
        self._remove_cb()
        await self.api.async_close()

    # ------------------------------------------------------------------
    # Websocket message processing
    # ------------------------------------------------------------------

    @callback
    def _handle_ws_message(self, msg: dict) -> None:
        """Handle incoming websocket message."""
        # If the message contains 'columns' and 'layers', treat it as full composition.
        if isinstance(msg, dict) and "columns" in msg and "layers" in msg:
            # push new data
            self.async_set_updated_data(msg)
        elif isinstance(msg, dict) and msg.get("type") in {
            "sources_update",
            "effects_update",
        }:
            # include these updates as well under specific keys.
            current = self.data or {}
            if msg["type"] == "sources_update":
                current = {**current, "sources": msg.get("value")}
            elif msg["type"] == "effects_update":
                current = {**current, "effects": msg.get("value")}
            self.async_set_updated_data(current)

    @property
    def resolume_api(self) -> ResolumeAPI:
        """Return API instance (backwards compat)."""
        return self.api
