from __future__ import annotations

from homeassistant.core import callback


class ParamSubscriptionMixin:
    """Mixin to automatically subscribe/unsubscribe to a Resolume parameter id.

    Subclasses must define:
      * self.coordinator  (ResolumeCoordinator)
      * self._param_id    (int)
    """

    _param_id: int  # set by subclass after construction
    _last_value: object | None = None
    _pending: object | None = None

    async def async_added_to_hass(self):  # type: ignore[override]
        await super().async_added_to_hass()  # type: ignore[misc]
        if getattr(self, "_param_id", None) is None:
            return
        api = self.coordinator.resolume_api  # type: ignore[attr-defined]
        # subscribe in background
        self.hass.async_create_task(api.async_subscribe_parameter(self._param_id))

        @callback
        def _param_callback(msg: dict):
            if msg.get("id") != self._param_id or "value" not in msg:
                return
            # store latest value
            self._last_value = msg["value"]
            # clear pending if matches or timeout
            if self._pending is not None and self._pending == self._last_value:
                self._pending = None
            if hasattr(self, "_handle_param"):
                try:
                    self._handle_param(msg)
                except Exception:  # noqa: BLE001
                    pass
            self.async_write_ha_state()

        self._remove_param_cb = api.register_callback(_param_callback)  # type: ignore[attr-defined]

    async def async_will_remove_from_hass(self):  # type: ignore[override]
        if hasattr(self, "_remove_param_cb"):
            self._remove_param_cb()
        if getattr(self, "_param_id", None) is not None:
            await self.coordinator.resolume_api.async_unsubscribe_parameter(
                self._param_id
            )  # type: ignore[attr-defined]
        await super().async_will_remove_from_hass()  # type: ignore[misc]
