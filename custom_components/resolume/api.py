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
        # Track all parameter ids we've subscribed to so we can automatically
        # re-subscribe after the websocket connection is re-established.
        # Using a set avoids duplicate subscribe calls.
        self._subscriptions: set[int] = set()

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
        """Send a raw JSON message over the websocket.

        If the connection has gone away in between scheduling the send and the
        actual I/O operation we transparently wait for a reconnect **once** and
        retry.  The service call therefore succeeds as long as the websocket
        can be re-established within a reasonable amount of time (10 s).
        """

        payload = json.dumps(message)

        # We try to send at most twice: the initial attempt and – if that fails
        # because the connection closed – exactly one retry after the
        # reconnect.  This prevents endless loops while still masking the most
        # common transient failure.
        for attempt in (1, 2):
            await self._connected_event.wait()
            if self._ws is None:
                # Should not happen, but guard against race conditions.
                self._connected_event.clear()
                if attempt == 2:
                    raise ConnectionError("Resolume websocket not available")
                continue

            _LOGGER.debug(
                "Resolume send%s: %s", " (retry)" if attempt == 2 else "", payload
            )

            try:
                await self._ws.send(payload)
                return  # success
            except (websockets.ConnectionClosed, OSError) as exc:
                _LOGGER.warning("Send attempt %s failed: %s", attempt, exc)
                # Mark disconnected and kick the reconnect loop.
                self._connected_event.clear()
                asyncio.create_task(self.async_connect())

                if attempt == 2:
                    # Exhausted retries – propagate error.
                    raise

                # Wait a bit for a new connection; give up after 10 seconds so
                # we don't block Home Assistant's executor forever.
                try:
                    await asyncio.wait_for(self._connected_event.wait(), timeout=10)
                except asyncio.TimeoutError:
                    raise ConnectionError("Timed out waiting for Resolume reconnect")

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
        # Record the subscription before attempting to send so we do not lose
        # track of it if the connection drops between now and the send call.
        self._subscriptions.add(param_id)

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
        # Remove from local tracking once we have queued the unsubscribe.
        self._subscriptions.discard(param_id)

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

                    # Re-subscribe to any parameter ids that were already active
                    # before the previous disconnect so we continue receiving
                    # real-time updates after a reconnect.
                    if self._subscriptions:
                        _LOGGER.debug(
                            "Re-subscribing to %d parameter ids after reconnect",
                            len(self._subscriptions),
                        )
                        # We intentionally do not await the individual send
                        # operations concurrently; doing them in sequence keeps
                        # the code simple and the number of subscriptions is
                        # typically modest (< few hundred).
                        for pid in list(self._subscriptions):
                            try:
                                await self.async_subscribe_parameter(pid)
                            except Exception as exc:  # noqa: BLE001
                                # If one subscribe fails we log it but continue
                                # with the others – a failure here is not fatal
                                # and will be retried on the next reconnect.
                                _LOGGER.warning(
                                    "Failed to re-subscribe to parameter %s: %s",
                                    pid,
                                    exc,
                                )
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
