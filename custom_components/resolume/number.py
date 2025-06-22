from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
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
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ResolumeCoordinator = data["coordinator"]

    entities: list[NumberEntity] = []

    # Add BPM entity if initial data already available
    _add_bpm_entity(coordinator, entities)

    if entities:
        async_add_entities(entities)

    @callback
    def _handle_new_data():
        added = _add_bpm_entity(coordinator, entities)
        if added:
            async_add_entities(added)

    coordinator.async_add_listener(_handle_new_data)


# ---------------------------------------------------------------------------
# BPM entity with real-time subscription
# ---------------------------------------------------------------------------


class ResolumeBpmNumber(
    ParamSubscriptionMixin, CoordinatorEntity[ResolumeCoordinator], NumberEntity
):
    """Entity representing global BPM."""

    _attr_unique_id = "resolume_global_bpm"
    _attr_name = "Composition BPM"
    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = "BPM"
    _attr_native_min_value = 20
    _attr_native_max_value = 400
    _attr_native_step = 0.1

    def __init__(self, coordinator: ResolumeCoordinator, param_id: int):
        super().__init__(coordinator)
        self._param_id = param_id
        self._pending = None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "composition")},
            "name": "Composition",
            "manufacturer": "Resolume",
            "model": "Composition",
        }

    # ------------------------------------------------------------------
    @property
    def native_value(self) -> float | None:  # type: ignore[override]
        # Prefer last pushed value
        if getattr(self, "_last_value", None) is not None:
            return float(self._last_value)

        composition = self.coordinator.data or {}
        tempoc = composition.get("tempocontroller", {})
        return tempoc.get("tempo", {}).get("value")

    async def async_set_native_value(self, value: float) -> None:  # type: ignore[override]
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_bpm(value)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


@callback
def _add_bpm_entity(
    coordinator: ResolumeCoordinator, entities: list
) -> list[NumberEntity]:
    new: list[NumberEntity] = []
    if any(isinstance(e, ResolumeBpmNumber) for e in entities):
        return new

    comp = coordinator.data or {}
    tempo_param = comp.get("tempocontroller", {}).get("tempo")
    if not tempo_param:
        return new

    param_id = tempo_param.get("id")
    if param_id is None:
        return new

    entity = ResolumeBpmNumber(coordinator, param_id)
    entities.append(entity)
    new.append(entity)
    return new


@callback
def _add_layer_master_numbers(
    coordinator: ResolumeCoordinator, entities: list
) -> list[NumberEntity]:
    """Create number entities for each layer master level."""
    new: list[NumberEntity] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}

    for index, layer in enumerate(composition.get("layers", []), start=1):
        # Prefer video.opacity over legacy master parameter
        video_opacity_param = layer.get("video", {}).get("opacity")
        param_dict = video_opacity_param if video_opacity_param else layer.get("master")
        if not param_dict:
            continue
        param_id = param_dict.get("id")
        if param_id is None:
            continue
        uid = f"resolume_layer_{layer['id']}_opacity"
        if uid in current_ids:
            continue

        raw_name = layer.get("name", {}).get("value", f"Layer {index}")
        name = raw_name.replace("#", str(index))
        entity = LayerOpacityNumber(coordinator, param_id, layer["id"], name)
        entities.append(entity)
        new.append(entity)
        current_ids.add(uid)

    return new


class LayerOpacityNumber(CoordinatorEntity[ResolumeCoordinator], NumberEntity):
    """Number entity controlling a layer opacity (0-100 %)."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        param_id: int,
        layer_id: int,
        layer_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._param_id = param_id
        self._layer_id = layer_id
        self._layer_name = layer_name
        self._attr_unique_id = f"resolume_layer_{layer_id}_opacity"
        self._attr_name = f"{layer_name} Opacity"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{layer_id}")},
            "name": layer_name,
            "manufacturer": "Resolume",
            "model": "Layer",
        }

    # ------------------------------------------------------------------
    @property
    def native_value(self) -> float | None:  # type: ignore[override]
        layer = self._get_layer()
        if not layer:
            return None
        value_dict = layer.get("video", {}).get("opacity", {}) or layer.get(
            "master", {}
        )
        raw = value_dict.get("value")
        if raw is None:
            return None
        return round(raw * 100, 1)

    async def async_set_native_value(self, value: float) -> None:  # type: ignore[override]
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, value / 100)

    # ------------------------------------------------------------------
    def _get_layer(self):
        composition = self.coordinator.data or {}
        for layer in composition.get("layers", []):
            if layer["id"] == self._layer_id:
                return layer
        return None


@callback
def _add_composition_numbers(
    coordinator: ResolumeCoordinator, entities: list
) -> list[NumberEntity]:
    new: list[NumberEntity] = []
    current_ids = {e.unique_id for e in entities}
    comp = coordinator.data or {}
    crossfader = comp.get("crossfader", {})
    phase = crossfader.get("phase")
    if phase:
        uid = "resolume_composition_crossfader_phase"
        if uid not in current_ids:
            entity = CompositionCrossfaderNumber(coordinator, phase["id"])
            entities.append(entity)
            new.append(entity)
            current_ids.add(uid)

    # Composition master level (video master).
    master = comp.get("master")
    param_dict = None
    if master and isinstance(master, dict):
        param_dict = master
    else:
        # fallback older schema
        param_dict = comp.get("video", {}).get("master") or comp.get("video", {}).get(
            "opacity"
        )

    if param_dict:
        uid = "resolume_composition_master_level"
        if uid not in current_ids:
            entity = CompositionMasterLevelNumber(coordinator, param_dict["id"])
            entities.append(entity)
            new.append(entity)
            current_ids.add(uid)

    # Composition audio volume master
    audio = comp.get("audio", {})
    if audio:
        volume = audio.get("volume")
        if volume:
            uid = "resolume_composition_audio_volume"
            if uid not in current_ids:
                entity = CompositionAudioVolumeNumber(coordinator, volume["id"])
                entities.append(entity)
                new.append(entity)
                current_ids.add(uid)
    return new


class CompositionCrossfaderNumber(CoordinatorEntity[ResolumeCoordinator], NumberEntity):
    _attr_unique_id = "resolume_composition_crossfader_phase"
    _attr_name = "Composition Crossfader Phase"
    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    def __init__(self, coordinator: ResolumeCoordinator, param_id: int):
        super().__init__(coordinator)
        self._param_id = param_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "composition")},
            "name": "Composition",
            "manufacturer": "Resolume",
            "model": "Composition",
        }

    @property
    def native_value(self):  # type: ignore[override]
        comp = self.coordinator.data or {}
        raw = comp.get("crossfader", {}).get("phase", {}).get("value")
        if raw is None:
            return None
        return round(raw * 100, 1)

    async def async_set_native_value(self, value):  # type: ignore[override]
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, value / 100)


class _BaseCompNumber(CoordinatorEntity[ResolumeCoordinator], NumberEntity):
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        param_id: int,
        name: str,
        unit: str,
        min_v: float,
        max_v: float,
        step: float,
    ):
        super().__init__(coordinator)
        self._param_id = param_id
        self._attr_unique_id = f"resolume_composition_{name.lower().replace(' ', '_')}"
        self._attr_name = f"Composition {name}"
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = min_v
        self._attr_native_max_value = max_v
        self._attr_native_step = step
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "composition")},
            "name": "Composition",
            "manufacturer": "Resolume",
            "model": "Composition",
        }

    async def async_set_native_value(self, value):  # type: ignore[override]
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, value)


class CompositionMasterLevelNumber(_BaseCompNumber):
    def __init__(self, coordinator: ResolumeCoordinator, param_id: int):
        super().__init__(coordinator, param_id, "Master Level", "%", 0, 100, 1)
        self._attr_unique_id = "resolume_composition_master_level"

    @property
    def native_value(self):  # type: ignore[override]
        comp = self.coordinator.data or {}
        raw = comp.get("master", {}).get("value")
        if raw is None:
            return None
        return round(raw * 100, 1)

    async def async_set_native_value(self, value):  # type: ignore[override]
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, value / 100)


class CompositionAudioVolumeNumber(_BaseCompNumber):
    def __init__(self, coordinator: ResolumeCoordinator, param_id: int):
        super().__init__(coordinator, param_id, "Audio Volume", "dB", -60, 6, 0.1)

    @property
    def native_value(self):  # type: ignore[override]
        comp = self.coordinator.data or {}
        return comp.get("audio", {}).get("volume", {}).get("value")


@callback
def _add_layergroup_master_numbers(
    coordinator: ResolumeCoordinator, entities: list
) -> list[NumberEntity]:
    new: list[NumberEntity] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    for index, lg in enumerate(composition.get("layergroups", []), start=1):
        master_param = lg.get("master")
        if not master_param:
            continue
        param_id = master_param.get("id")
        if param_id is None:
            continue
        uid = f"resolume_layergroup_{lg['id']}_master_level"
        if uid in current_ids:
            continue
        raw_name = lg.get("name", {}).get("value", f"Group {index}")
        name = raw_name.replace("#", str(index))
        entity = LayerGroupMasterNumber(coordinator, param_id, lg["id"], name)
        entities.append(entity)
        new.append(entity)
        current_ids.add(uid)
    return new


class LayerGroupMasterNumber(CoordinatorEntity[ResolumeCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        param_id: int,
        group_id: int,
        group_name: str,
    ):
        super().__init__(coordinator)
        self._param_id = param_id
        self._group_id = group_id
        self._attr_unique_id = f"resolume_layergroup_{group_id}_master_level"
        self._attr_name = f"{group_name} Level"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layergroup_{group_id}")},
            "name": group_name,
            "manufacturer": "Resolume",
            "model": "Layer Group",
        }

    @property
    def native_value(self):  # type: ignore[override]
        comp = self.coordinator.data or {}
        for lg in comp.get("layergroups", []):
            if lg["id"] == self._group_id:
                raw = lg.get("master", {}).get("value")
                if raw is None:
                    return None
                return round(raw * 100, 1)
        return None

    async def async_set_native_value(self, value):  # type: ignore[override]
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, value / 100)
