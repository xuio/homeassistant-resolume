from __future__ import annotations

import logging

from homeassistant.components.light import ATTR_BRIGHTNESS, LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ResolumeCoordinator
from .api import ResolumeAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_FACTOR = 255 / 100  # convert 0-100% to 0-255


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


class _ResolumeParamLight(CoordinatorEntity[ResolumeCoordinator], LightEntity):
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

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
            "name": friendly if not has_entity_name else device_id[1].replace("_", " "),
            "manufacturer": "Resolume",
        }

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
        return int(value * BRIGHTNESS_FACTOR)

    async def async_turn_on(self, **kwargs):  # type: ignore[override]
        if (b := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            pct = b / BRIGHTNESS_FACTOR
        else:
            pct = 100
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, pct / 100)

    async def async_turn_off(self, **kwargs):  # type: ignore[override]
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, 0)

    # ------------------------------------------------------------------
    def _current_value(self):
        # traverse coordinator data to locate param by id
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

        return search_params(self.coordinator.data)
