from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, Coroutine, Dict, List, Optional

import websockets
import random

_LOGGER = logging.getLogger(__name__)


class ResolumeAPI:
    """Simple async client talking to the Resolume websocket API."""

    def __init__(self, host: str, port: int = 8080) -> None:
        self._host = host
        self._port = port
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._listeners: List[Callable[[dict], None]] = []
        self._connected_event = asyncio.Event()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._closing = False

    # ---------------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------------

    async def async_connect(self) -> None:
        """Connect to the server and start listener task."""
        if self._listen_task and not self._listen_task.done():
            return

        self._listen_task = asyncio.create_task(
            self._connect_loop(), name="resolume_ws_listen"
        )

    async def async_close(self) -> None:
        """Close the websocket and cancel tasks."""
        self._closing = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self._listen_task:
            self._listen_task.cancel()
        if self._ws:
            # websockets ≥11 returns ClientConnection which exposes .close() but may not have .closed
            try:
                await self._ws.close()
            except AttributeError:
                # Fallback for older versions
                pass

    async def async_send(self, message: dict[str, Any]) -> None:
        """Send a raw JSON message over the websocket."""
        await self._connected_event.wait()
        assert self._ws is not None
        payload = json.dumps(message)
        _LOGGER.debug("Resolume send: %s", payload)
        try:
            await self._ws.send(payload)
        except (websockets.ConnectionClosed, OSError) as exc:
            # Underlying connection broke between the wait() above and the send().
            _LOGGER.warning("Send failed, will retry after reconnect: %s", exc)
            self._connected_event.clear()
            # Ensure the reconnect loop is running.
            asyncio.create_task(self.async_connect())
            raise

    # ---------------------------------------------------------------------
    # Convenience helpers used by entities
    # ---------------------------------------------------------------------
    async def async_trigger_clip(self, clip_id: int, connect: bool = True) -> None:
        """Trigger a clip by id."""
        await self.async_send(
            {
                "action": "trigger",
                "parameter": f"/composition/clips/by-id/{clip_id}/connect",
                "value": connect,
            }
        )

    async def async_select_layer(self, layer_id: int) -> None:
        """Select a layer by id."""
        await self.async_send(
            {
                "action": "trigger",
                "parameter": f"/composition/layers/by-id/{layer_id}/select",
                "value": True,
            }
        )

    async def async_set_bpm(self, bpm: float) -> None:
        """Set global tempo/BPM."""
        await self.async_send(
            {
                "action": "set",
                "parameter": "/composition/tempocontroller/tempo",
                "value": bpm,
            }
        )

    # ------------------------------------------------------------------
    # Generic parameter helpers
    # ------------------------------------------------------------------

    async def async_set_parameter(self, param_id: int, value: Any) -> None:
        """Set parameter value by numeric id (as exposed in websocket state)."""
        await self.async_send(
            {
                "action": "set",
                "parameter": f"/parameter/by-id/{param_id}",
                "value": value,
            }
        )

    async def async_subscribe_parameter(self, param_id: int) -> None:
        """Request updates for a specific parameter id."""
        await self.async_send(
            {
                "action": "subscribe",
                "parameter": f"/parameter/by-id/{param_id}",
            }
        )

    async def async_unsubscribe_parameter(self, param_id: int) -> None:
        await self.async_send(
            {
                "action": "unsubscribe",
                "parameter": f"/parameter/by-id/{param_id}",
            }
        )

    # ---------------------------------------------------------------------
    # Listener registration
    # ---------------------------------------------------------------------

    def register_callback(
        self, cb: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Register a callback for incoming messages.

        Returns a function that can be called to remove the listener.
        """
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    async def _connect_loop(self) -> None:
        reconnect_delay = 1
        while not self._closing:
            try:
                uri = f"ws://{self._host}:{self._port}/api/v1"
                _LOGGER.debug("Connecting to Resolume websocket at %s", uri)
                async with websockets.connect(
                    uri, ping_interval=20, ping_timeout=20
                ) as ws:
                    self._ws = ws
                    self._connected_event.set()
                    reconnect_delay = 1  # reset delay on successful connect
                    _LOGGER.info("Connected to Resolume at %s", uri)
                    try:
                        await self._read_loop()
                    finally:
                        # Ensure we always clear the connected flag when the connection ends –
                        # even if the websocket closed cleanly without an exception.
                        self._connected_event.clear()
                        self._ws = None
            except (OSError, websockets.WebSocketException) as exc:
                if self._closing:
                    # If we are shutting down we do not need to log/retry.
                    break
                _LOGGER.warning("Resolume websocket connection lost: %s", exc)
                self._connected_event.clear()
                self._ws = None

            # Add a small random jitter (±10%) to avoid multiple clients reconnecting at once.
            jitter = reconnect_delay * 0.1 * (random.random() - 0.5)
            await asyncio.sleep(reconnect_delay + jitter)
            reconnect_delay = min(reconnect_delay * 2, 60)

    async def _read_loop(self) -> None:
        assert self._ws is not None
        async for message in self._ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                _LOGGER.debug("Ignoring non-json message: %s", message)
                continue

            for listener in list(self._listeners):
                try:
                    _LOGGER.debug("Resolume received: %s", data)
                    listener(data)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Error in Resolume listener")

        _LOGGER.debug("Resolume websocket closed")

    async def async_click(self, parameter_path: str) -> None:
        """Simulate mouse click: send true then false."""
        await self.async_send(
            {
                "action": "trigger",
                "parameter": parameter_path,
                "value": True,
            }
        )

        # schedule release without blocking
        async def _release():
            await asyncio.sleep(0)
            await self.async_send(
                {
                    "action": "trigger",
                    "parameter": parameter_path,
                    "value": False,
                }
            )

        asyncio.create_task(_release())
