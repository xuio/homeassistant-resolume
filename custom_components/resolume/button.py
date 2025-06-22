from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ResolumeAPI
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

    entities: list[ButtonEntity] = []

    # Data will arrive via websocket push

    new_entities = []

    # Add layer group clear buttons
    new_entities.extend(_add_layer_group_buttons(coordinator, entities))
    new_entities.extend(_add_layer_clear_buttons(coordinator, entities))

    # Add master fader button (deck play?) maybe not but we can add BPM tap button
    bpm_button = BpmTapButton(coordinator)
    entities.append(bpm_button)
    new_entities.append(bpm_button)

    if new_entities:
        async_add_entities(new_entities)

    @callback
    def _handle_new_data():
        pass

    coordinator.async_add_listener(_handle_new_data)


class ClipTriggerButton(CoordinatorEntity[ResolumeCoordinator], ButtonEntity):
    """Button to trigger a clip."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        clip_info: dict,
        layer_id: int,
        layer_index: int,
        layer_name: str,
    ):
        super().__init__(coordinator)
        self._clip_id = clip_info["id"]
        self._layer_id = layer_id
        name_val = clip_info.get("name", {}).get("value", str(self._clip_id))
        self._attr_unique_id = f"resolume_clip_{self._clip_id}_trigger"
        self._attr_name = f"Clip: {name_val}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{self._layer_id}")},
            "name": layer_name.replace("#", str(layer_index)),
            "manufacturer": "Resolume",
            "model": "Layer",
        }

    async def async_press(self) -> None:
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        # send press and release similar to UI click
        await api.async_send(
            {
                "action": "trigger",
                "parameter": f"/composition/clips/by-id/{self._clip_id}/connect",
                "value": True,
            }
        )

        async def _release():
            await api.async_send(
                {
                    "action": "trigger",
                    "parameter": f"/composition/clips/by-id/{self._clip_id}/connect",
                    "value": False,
                }
            )

        self.coordinator.hass.async_create_task(_release())


class BpmTapButton(CoordinatorEntity[ResolumeCoordinator], ButtonEntity):
    """Simple tap button to push tempo (BPM tap)."""

    _attr_unique_id = "resolume_bpm_tap"
    _attr_name = "Resolume BPM Tap"

    async def async_press(self) -> None:
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_send(
            {
                "action": "trigger",
                "parameter": "/composition/tempocontroller/tap",
                "value": True,
            }
        )


@callback
def _add_layer_group_buttons(
    coordinator: ResolumeCoordinator, entities: list
) -> list[ButtonEntity]:
    """Add clear buttons for each layer group."""
    new: list[ButtonEntity] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    for index, lg in enumerate(composition.get("layergroups", []), start=1):
        uid = f"resolume_layergroup_{lg['id']}_clear"
        if uid in current_ids:
            continue
        raw_name = lg.get("name", {}).get("value", f"Group {index}")
        name = raw_name.replace("#", str(index))
        ent = LayerGroupClearButton(coordinator, lg["id"], index, name)
        entities.append(ent)
        new.append(ent)
        current_ids.add(uid)
    return new


class LayerGroupClearButton(CoordinatorEntity[ResolumeCoordinator], ButtonEntity):
    """Button to clear a layer group."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        group_id: int,
        index: int,
        group_name: str,
    ):
        super().__init__(coordinator)
        self._group_id = group_id
        self._index = index
        self._attr_unique_id = f"resolume_layergroup_{group_id}_clear"
        self._attr_name = f"{group_name} Clear"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layergroup_{group_id}")},
            "name": group_name,
            "manufacturer": "Resolume",
            "model": "Layer Group",
        }

    async def async_press(self) -> None:
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_send(
            {
                "action": "trigger",
                "parameter": f"/composition/layergroups/by-id/{self._group_id}/clear",
                "value": True,
            }
        )


@callback
def _add_layer_clear_buttons(
    coordinator: ResolumeCoordinator, entities: list
) -> list[ButtonEntity]:
    new: list[ButtonEntity] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    for index, layer in enumerate(composition.get("layers", []), start=1):
        uid = f"resolume_layer_{layer['id']}_clear"
        if uid in current_ids:
            continue
        raw_name = layer.get("name", {}).get("value", f"Layer {index}")
        name = raw_name.replace("#", str(index))
        ent = LayerClearButton(coordinator, layer["id"], name)
        entities.append(ent)
        new.append(ent)
        current_ids.add(uid)
    return new


class LayerClearButton(CoordinatorEntity[ResolumeCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ResolumeCoordinator, layer_id: int, layer_name: str
    ):
        super().__init__(coordinator)
        self._layer_id = layer_id
        self._attr_unique_id = f"resolume_layer_{layer_id}_clear"
        self._attr_name = f"{layer_name} Clear"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{layer_id}")},
            "name": layer_name,
            "manufacturer": "Resolume",
            "model": "Layer",
        }

    async def async_press(self) -> None:
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_send(
            {
                "action": "trigger",
                "parameter": f"/composition/layers/by-id/{self._layer_id}/clear",
                "value": True,
            }
        )
