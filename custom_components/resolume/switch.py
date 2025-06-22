from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ResolumeAPI
from .const import DOMAIN
from .coordinator import ResolumeCoordinator
from .param_entity import ParamSubscriptionMixin

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up layer switches from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ResolumeCoordinator = data["coordinator"]

    entities: list[ResolumeLayerBypassSwitch] = []

    # we rely on push updates; entities will be added when data arrives

    new_entities = _add_layer_entities(coordinator, entities)
    new_entities.extend(_add_layer_solo_entities(coordinator, entities))
    new_entities.extend(_add_layergroup_switches(coordinator, entities))
    new_entities.extend(_add_clip_entities(coordinator, entities))
    new_entities.extend(_add_clip_switches(coordinator, entities))

    if new_entities:
        async_add_entities(new_entities)

    @callback
    def _handle_new_data():
        if coordinator.data is None:
            return
        added = []
        added.extend(_add_layer_entities(coordinator, entities))
        added.extend(_add_layer_solo_entities(coordinator, entities))
        added.extend(_add_layergroup_switches(coordinator, entities))
        added.extend(_add_clip_entities(coordinator, entities))
        added.extend(_add_clip_switches(coordinator, entities))
        if added:
            async_add_entities(added)

    coordinator.async_add_listener(_handle_new_data)


@callback
def _add_layer_entities(
    coordinator: ResolumeCoordinator, entities: list
) -> list[ResolumeLayerBypassSwitch]:
    """Add new layer switch entities if needed and return them."""
    new: list[ResolumeLayerBypassSwitch] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    for index, layer in enumerate(composition.get("layers", []), start=1):
        uid = f"resolume_layer_{layer['id']}_bypass"
        if uid not in current_ids:
            ent = ResolumeLayerBypassSwitch(coordinator, layer, index)
            entities.append(ent)
            new.append(ent)
            current_ids.add(uid)
    return new


@callback
def _add_layer_solo_entities(
    coordinator: ResolumeCoordinator, entities: list
) -> list[SwitchEntity]:
    new: list[SwitchEntity] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    for index, layer in enumerate(composition.get("layers", []), start=1):
        uid = f"resolume_layer_{layer['id']}_solo"
        if uid in current_ids:
            continue
        solo_param = layer.get("solo")
        if not solo_param:
            continue
        ent = LayerSoloSwitch(coordinator, layer, index)
        entities.append(ent)
        new.append(ent)
        current_ids.add(uid)
    return new


@callback
def _add_layergroup_switches(
    coordinator: ResolumeCoordinator, entities: list
) -> list[SwitchEntity]:
    new: list[SwitchEntity] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    for index, lg in enumerate(composition.get("layergroups", []), start=1):
        # Solo switch
        solo_param = lg.get("solo")
        if solo_param:
            uid = f"resolume_layergroup_{lg['id']}_solo"
            if uid not in current_ids:
                ent = LayerGroupSoloSwitch(coordinator, lg, index)
                entities.append(ent)
                new.append(ent)
                current_ids.add(uid)

        # Bypass/Blank switch assumed via 'bypassed' key similar to layer
        bypass_param = lg.get("bypassed")
        if bypass_param:
            uidb = f"resolume_layergroup_{lg['id']}_bypass"
            if uidb not in current_ids:
                ent = LayerGroupBypassSwitch(coordinator, lg, index)
                entities.append(ent)
                new.append(ent)
                current_ids.add(uidb)
    return new


@callback
def _add_clip_entities(
    coordinator: ResolumeCoordinator, entities: list
) -> list[SwitchEntity]:
    new: list[SwitchEntity] = []
    existing_ids = {e.unique_id for e in entities}
    comp = coordinator.data or {}
    for layer in comp.get("layers", []):
        for clip in layer.get("clips", []):
            conn = clip.get("connected")
            if not conn:
                continue
            uid = f"resolume_clip_{clip['id']}_switch"
            if uid in existing_ids:
                continue
            clip_idx = layer.get("clips", []).index(clip) + 1
            raw = clip.get("name", {}).get("value")
            name = raw if raw else f"Clip {clip_idx}"
            ent = ClipSwitch(coordinator, conn["id"], clip["id"], name, layer["id"])
            entities.append(ent)
            new.append(ent)
            existing_ids.add(uid)
    return new


@callback
def _add_clip_switches(
    coordinator: ResolumeCoordinator, entities: list
) -> list[SwitchEntity]:
    new: list[SwitchEntity] = []
    existing_ids = {e.unique_id for e in entities}
    comp = coordinator.data or {}
    for layer in comp.get("layers", []):
        for clip in layer.get("clips", []):
            conn = clip.get("connected")
            if not conn:
                continue
            uid = f"resolume_clip_{clip['id']}_switch"
            if uid in existing_ids:
                continue
            clip_idx = layer.get("clips", []).index(clip) + 1
            raw = clip.get("name", {}).get("value")
            name = raw if raw else f"Clip {clip_idx}"
            ent = ClipSwitch(coordinator, conn["id"], clip["id"], name, layer["id"])
            entities.append(ent)
            new.append(ent)
            existing_ids.add(uid)
    return new


class ResolumeLayerBypassSwitch(
    ParamSubscriptionMixin, CoordinatorEntity[ResolumeCoordinator], SwitchEntity
):
    """Representation of a Resolume Layer bypass state."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ResolumeCoordinator, layer_info: dict, index: int):
        super().__init__(coordinator)
        self._layer_id = layer_info["id"]
        self._attr_unique_id = f"resolume_layer_{self._layer_id}_bypass"
        raw_name = layer_info.get("name", {}).get("value", f"Layer {index}")
        name = raw_name.replace("#", str(index))
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{self._layer_id}")},
            "name": name,
            "manufacturer": "Resolume",
            "model": "Layer",
        }
        self._attr_name = f"{name} Bypass"
        self._param_id = layer_info.get("bypassed", {}).get("id")
        self._pending = None

    # ------------------------------------------------------------------
    # Entity state
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool | None:
        # 'On' means the layer is bypassed (hidden). Resolume reports bypass as
        # a boolean where True = bypass active.
        if hasattr(self, "_last_value") and self._last_value is not None:
            return bool(self._last_value)

        layer = self._get_layer()
        if layer is None:
            return None
        return layer.get("bypassed", {}).get("value", False)

    async def async_turn_on(self, **kwargs):  # type: ignore[override]
        # Activate bypass => set parameter True
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        if self._pending is True:
            return
        self._pending = True
        await api.async_set_parameter(self._param_id, True)

    async def async_turn_off(self, **kwargs):  # type: ignore[override]
        # Deactivate bypass => set parameter False
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        if self._pending is False:
            return
        self._pending = False
        await api.async_set_parameter(self._param_id, False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_layer(self) -> dict | None:
        composition = self.coordinator.data or {}
        for layer in composition.get("layers", []):
            if layer["id"] == self._layer_id:
                return layer
        return None


class LayerSoloSwitch(
    ParamSubscriptionMixin, CoordinatorEntity[ResolumeCoordinator], SwitchEntity
):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ResolumeCoordinator, layer_info: dict, index: int):
        super().__init__(coordinator)
        self._layer_id = layer_info["id"]
        self._attr_unique_id = f"resolume_layer_{self._layer_id}_solo"
        raw_name = layer_info.get("name", {}).get("value", f"Layer {index}")
        name = raw_name.replace("#", str(index))
        self._attr_name = f"{name} Solo"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{self._layer_id}")},
            "name": name,
            "manufacturer": "Resolume",
            "model": "Layer",
        }
        self._param_id = layer_info.get("solo", {}).get("id")
        self._pending = None

    @property
    def is_on(self):
        if hasattr(self, "_last_value") and self._last_value is not None:
            return bool(self._last_value)

        layer = self._get_layer()
        if layer is None:
            return None
        return layer.get("solo", {}).get("value", False)

    async def async_turn_on(self, **kwargs):
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        if self._pending is True:
            return
        self._pending = True
        await api.async_set_parameter(self._param_id, True)

    async def async_turn_off(self, **kwargs):
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        if self._pending is False:
            return
        self._pending = False
        await api.async_set_parameter(self._param_id, False)

    def _get_layer(self):
        composition = self.coordinator.data or {}
        for layer in composition.get("layers", []):
            if layer["id"] == self._layer_id:
                return layer
        return None


class LayerGroupSoloSwitch(
    ParamSubscriptionMixin, CoordinatorEntity[ResolumeCoordinator], SwitchEntity
):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ResolumeCoordinator, lg_info: dict, index: int):
        super().__init__(coordinator)
        self._group_id = lg_info["id"]
        self._attr_unique_id = f"resolume_layergroup_{self._group_id}_solo"
        raw_name = lg_info.get("name", {}).get("value", f"Group {index}")
        name = raw_name.replace("#", str(index))
        self._attr_name = f"{name} Solo"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layergroup_{self._group_id}")},
            "name": name,
            "manufacturer": "Resolume",
            "model": "Layer Group",
        }
        self._param_id = lg_info.get("solo", {}).get("id")
        self._pending = None

    @property
    def is_on(self):
        if hasattr(self, "_last_value") and self._last_value is not None:
            return bool(self._last_value)

        lg = self._get_group()
        if lg is not None:
            return lg.get("solo", {}).get("value", False)
        return None

    async def async_turn_on(self, **kwargs):
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        if self._pending is True:
            return
        self._pending = True
        await api.async_set_parameter(self._param_id, True)

    async def async_turn_off(self, **kwargs):
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        if self._pending is False:
            return
        self._pending = False
        await api.async_set_parameter(self._param_id, False)

    def _get_group(self):
        composition = self.coordinator.data or {}
        for lg in composition.get("layergroups", []):
            if lg["id"] == self._group_id:
                return lg
        return None


class LayerGroupBypassSwitch(
    ParamSubscriptionMixin, CoordinatorEntity[ResolumeCoordinator], SwitchEntity
):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ResolumeCoordinator, lg_info: dict, index: int):
        super().__init__(coordinator)
        self._group_id = lg_info["id"]
        self._attr_unique_id = f"resolume_layergroup_{self._group_id}_bypass"
        raw_name = lg_info.get("name", {}).get("value", f"Group {index}")
        name = raw_name.replace("#", str(index))
        self._attr_name = f"{name} Bypass"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layergroup_{self._group_id}")},
            "name": name,
            "manufacturer": "Resolume",
            "model": "Layer Group",
        }
        self._param_id = lg_info.get("bypassed", {}).get("id")
        self._pending = None

    @property
    def is_on(self):
        # 'On' = group bypassed
        if hasattr(self, "_last_value") and self._last_value is not None:
            return bool(self._last_value)

        lg = self._get_group()
        if lg is not None:
            return lg.get("bypassed", {}).get("value", False)
        return None

    async def async_turn_on(self, **kwargs):
        # Activate bypass
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        if self._pending is True:
            return
        self._pending = True
        await api.async_set_parameter(self._param_id, True)

    async def async_turn_off(self, **kwargs):
        # Deactivate bypass
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        if self._pending is False:
            return
        self._pending = False
        await api.async_set_parameter(self._param_id, False)

    def _get_group(self):
        composition = self.coordinator.data or {}
        for lg in composition.get("layergroups", []):
            if lg["id"] == self._group_id:
                return lg
        return None


class ClipSwitch(
    ParamSubscriptionMixin, CoordinatorEntity[ResolumeCoordinator], SwitchEntity
):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        param_id: int,
        clip_id: int,
        name: str,
        layer_id: int,
    ):
        super().__init__(coordinator)
        self._param_id = param_id
        self._clip_id = clip_id
        self._layer_id = layer_id
        self._attr_unique_id = f"resolume_clip_{clip_id}_switch"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{layer_id}")},
        }

    # state
    @property
    def is_on(self):
        val = getattr(self, "_last_value", None)
        if isinstance(val, str):
            return val.startswith("Connected")
        if isinstance(val, int):
            return val >= 3
        # fallback composition
        comp = self.coordinator.data or {}
        for layer in comp.get("layers", []):
            for clip in layer.get("clips", []):
                if clip["id"] == self._clip_id:
                    return clip.get("connected", {}).get("index", 0) >= 3
        return False

    async def async_turn_on(self, **kwargs):
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_send(
            {
                "action": "trigger",
                "parameter": f"/composition/clips/by-id/{self._clip_id}/connect",
                "value": True,
            }
        )

    async def async_turn_off(self, **kwargs):
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_send(
            {
                "action": "trigger",
                "parameter": f"/composition/clips/by-id/{self._clip_id}/connect",
                "value": False,
            }
        )
