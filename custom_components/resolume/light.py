from __future__ import annotations

import logging
import asyncio
import math

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    LightEntity,
    ColorMode,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .param_entity import ParamSubscriptionMixin

from .coordinator import ResolumeCoordinator
from .api import ResolumeAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_MAX = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ResolumeCoordinator = data["coordinator"]

    entities: list[LightEntity] = []

    _add_layer_lights(coordinator, entities)
    _add_layergroup_lights(coordinator, entities)
    _add_composition_light(coordinator, entities)

    if entities:
        async_add_entities(entities)

    @callback
    def _handle_update() -> None:
        added: list[LightEntity] = []
        added.extend(_add_layer_lights(coordinator, entities))
        added.extend(_add_layergroup_lights(coordinator, entities))
        added.extend(_add_composition_light(coordinator, entities))
        if added:
            async_add_entities(added)

    coordinator.async_add_listener(_handle_update)


# ---------------------------------------------------------------------------
# Helpers to build entity lists
# ---------------------------------------------------------------------------


def _add_layer_lights(
    coordinator: ResolumeCoordinator, entities: list
) -> list[LightEntity]:
    new: list[LightEntity] = []
    existing_ids = {e.unique_id for e in entities}
    comp = coordinator.data or {}
    for idx, layer in enumerate(comp.get("layers", []), start=1):
        param = layer.get("video", {}).get("opacity")
        if not param:
            continue
        uid = f"resolume_layer_{layer['id']}_opacity"
        if uid in existing_ids:
            continue
        name_raw = layer.get("name", {}).get("value", f"Layer {idx}")
        name = name_raw.replace("#", str(idx))
        ent = _ResolumeParamLight(
            coordinator,
            param_id=param["id"],
            unique_id=uid,
            friendly=name,
            device_id=(DOMAIN, f"layer_{layer['id']}"),
        )
        entities.append(ent)
        new.append(ent)
    return new


def _add_layergroup_lights(
    coordinator: ResolumeCoordinator, entities: list
) -> list[LightEntity]:
    new: list[LightEntity] = []
    existing_ids = {e.unique_id for e in entities}
    comp = coordinator.data or {}
    for idx, lg in enumerate(comp.get("layergroups", []), start=1):
        param = lg.get("master")
        if not param:
            continue
        uid = f"resolume_layergroup_{lg['id']}_level"
        if uid in existing_ids:
            continue
        name_raw = lg.get("name", {}).get("value", f"Group {idx}")
        name = name_raw.replace("#", str(idx))
        ent = _ResolumeParamLight(
            coordinator,
            param_id=param["id"],
            unique_id=uid,
            friendly=name,
            device_id=(DOMAIN, f"layergroup_{lg['id']}"),
        )
        entities.append(ent)
        new.append(ent)
    return new


def _add_composition_light(
    coordinator: ResolumeCoordinator, entities: list
) -> list[LightEntity]:
    new: list[LightEntity] = []
    if any(e.unique_id == "resolume_composition_master" for e in entities):
        return new
    comp = coordinator.data or {}
    param = (
        comp.get("master")
        or comp.get("video", {}).get("master")
        or comp.get("video", {}).get("opacity")
    )
    if not param:
        return new
    ent = _ResolumeParamLight(
        coordinator,
        param_id=param["id"],
        unique_id="resolume_composition_master",
        friendly="Composition Master",
        device_id=(DOMAIN, "composition"),
        has_entity_name=False,
    )
    entities.append(ent)
    new.append(ent)
    return new


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------


class _ResolumeParamLight(
    ParamSubscriptionMixin, CoordinatorEntity[ResolumeCoordinator], LightEntity
):
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_features = LightEntityFeature.TRANSITION
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        param_id: int,
        unique_id: str,
        friendly: str,
        device_id: tuple[str, str],
        *,
        has_entity_name: bool = True,
    ) -> None:
        super().__init__(coordinator)
        self._param_id = param_id
        self._attr_unique_id = unique_id
        self._attr_name = friendly if not has_entity_name else None
        self._attr_has_entity_name = has_entity_name
        self._attr_device_info = {
            "identifiers": {device_id},
            "name": friendly,
            "manufacturer": "Resolume",
        }

        self._value: float | None = None  # cache last known 0..1 value
        self._pending: float | None = None

        # Task used when a fade (transition) is in progress
        self._fade_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    @property
    def is_on(self) -> bool | None:
        value = self._current_value()
        if value is None:
            return None
        return value > 0

    @property
    def brightness(self) -> int | None:
        value = self._current_value()
        if value is None:
            return None
        return int(value * BRIGHTNESS_MAX)

    @property
    def color_mode(self):
        return ColorMode.BRIGHTNESS

    async def async_turn_on(self, **kwargs):
        transition = float(kwargs.get(ATTR_TRANSITION, 0))
        level = kwargs.get(ATTR_BRIGHTNESS, BRIGHTNESS_MAX) / BRIGHTNESS_MAX

        # Cancel any ongoing fade
        if self._fade_task:
            self._fade_task.cancel()

        await self._fade_to(level, transition)

    async def async_turn_off(self, **kwargs):
        transition = float(kwargs.get(ATTR_TRANSITION, 0))

        # Cancel any ongoing fade
        if self._fade_task:
            self._fade_task.cancel()

        await self._fade_to(0.0, transition)

    async def _fade_to(self, target: float, transition: float) -> None:
        """Fade linearly to *target* over *transition* seconds."""

        # Immediate change if no transition or same value requested
        start_value = self._current_value() or 0.0
        if transition <= 0 or start_value == target:
            self._value = target
            self._attr_is_on = target > 0
            self._attr_brightness = int(target * BRIGHTNESS_MAX)
            self.async_write_ha_state()
            await self.coordinator.resolume_api.async_set_parameter(
                self._param_id, target
            )
            self._pending = target
            return

        steps = max(int(transition * 25), 1)  # ~25 updates / second
        step_time = transition / steps
        delta = target - start_value

        async def _run():
            try:
                for i in range(1, steps + 1):
                    progress = i / steps  # 0..1
                    eased = -(math.cos(math.pi * progress) - 1) / 2  # ease-in-out-sine
                    value = start_value + delta * eased
                    self._value = value
                    self._attr_is_on = value > 0
                    self._attr_brightness = int(value * BRIGHTNESS_MAX)
                    self.async_write_ha_state()
                    await self.coordinator.resolume_api.async_set_parameter(
                        self._param_id, value
                    )
                    self._pending = value
                    await asyncio.sleep(step_time)
            except asyncio.CancelledError:
                # Fade interrupted by another command
                pass
            finally:
                self._fade_task = None

        # Run the fade without blocking the service call
        self._fade_task = self.hass.async_create_task(_run())

    async def async_will_remove_from_hass(self) -> None:
        """Handle removal - cancel any running fade."""
        if self._fade_task:
            self._fade_task.cancel()
        await super().async_will_remove_from_hass()

    # ------------------------------------------------------------------
    def _current_value(self):
        if self._value is not None:
            return self._value

        def search_params(obj):
            if isinstance(obj, dict):
                if obj.get("id") == self._param_id:
                    return obj.get("value")
                for v in obj.values():
                    res = search_params(v)
                    if res is not None:
                        return res
            elif isinstance(obj, list):
                for itm in obj:
                    res = search_params(itm)
                    if res is not None:
                        return res
            return None

        val = search_params(self.coordinator.data)
        if isinstance(val, (int, float)):
            self._value = float(val)
        return val

    # ParamSubscriptionMixin handles removal
