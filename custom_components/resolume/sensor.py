from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ResolumeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ResolumeCoordinator = data["coordinator"]

    entities: list[SensorEntity] = []
    _add_active_clip_sensors(coordinator, entities)

    if entities:
        async_add_entities(entities)

    @callback
    def _handle_new_data():
        added = _add_active_clip_sensors(coordinator, entities)
        if added:
            async_add_entities(added)

    coordinator.async_add_listener(_handle_new_data)


@callback
def _add_active_clip_sensors(
    coordinator: ResolumeCoordinator, entities: list
) -> list[SensorEntity]:
    new: list[SensorEntity] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    for index, layer in enumerate(composition.get("layers", []), start=1):
        active_clip = None
        for clip in layer.get("clips", []):
            # connected.index >= 3 is connected + maybe previewing
            conn = clip.get("connected", {})
            if conn and conn.get("index", 0) >= 3:
                active_clip = clip
                break
        uid = f"resolume_layer_{layer['id']}_active_clip"
        if uid in current_ids:
            # existing sensor will update automatically via coordinator
            continue
        raw_name = layer.get("name", {}).get("value", f"Layer {index}")
        name = raw_name.replace("#", str(index))
        sensor = ActiveClipSensor(coordinator, layer["id"], name)
        entities.append(sensor)
        new.append(sensor)
        current_ids.add(uid)
    return new


class ActiveClipSensor(CoordinatorEntity[ResolumeCoordinator], SensorEntity):
    """Sensor that exposes the currently active clip on a layer."""

    _attr_icon = "mdi:filmstrip"

    def __init__(
        self, coordinator: ResolumeCoordinator, layer_id: int, layer_name: str
    ):
        super().__init__(coordinator)
        self._layer_id = layer_id
        self._layer_name = layer_name
        self._attr_unique_id = f"resolume_layer_{layer_id}_active_clip"
        self._attr_name = f"{layer_name} Active Clip"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{layer_id}")},
            "name": layer_name,
            "manufacturer": "Resolume",
            "model": "Layer",
        }

    @property
    def state(self) -> str | None:  # type: ignore[override]
        composition = self.coordinator.data or {}
        for layer in composition.get("layers", []):
            if layer["id"] != self._layer_id:
                continue
            for clip in layer.get("clips", []):
                if clip.get("connected", {}).get("index", 0) >= 3:
                    return clip.get("name", {}).get("value")
        return None
