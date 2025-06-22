from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ResolumeAPI
from .const import DOMAIN
from .coordinator import ResolumeCoordinator

_LOGGER = logging.getLogger(__name__)

OPTIONS = ["Off", "A", "B"]

BLEND_MODES = [
    "50 Add",
    "50 Burn",
    "50 Difference",
    "50 Distance",
    "50 Dodge",
    "50 Lighten",
    "50 Mask",
    "50 Multiply",
    "50 Overlay",
    "50 Subtract",
    "Add",
    "Alpha",
    "B&W",
    "Bumper",
    "Burn",
    "Chaser",
    "Cube",
    "Cut",
    "Darken",
    "Difference",
    "Difference I",
    "Displace",
    "Dissolve",
    "Dodge",
    "Exclusion",
    "Hard Light",
    "JitterBug",
    "Lighten",
    "LoRez",
    "Luma Is Alpha",
    "Luma Key",
    "Luma Key I",
    "Mask",
    "Meta Mix",
    "Multi Task",
    "Multiply",
    "Noisy",
    "Overlay",
    "Parts",
    "PiP",
    "Push Down",
    "Push Left",
    "Push Right",
    "Push Up",
    "RGB",
    "Rotate X",
    "Rotate Y",
    "Screen",
    "Shift RGB",
    "Side by Side",
    "Soft Light",
    "Static",
    "Subtract",
    "Tile",
    "TimeSwitcher",
    "Twitch",
    "Wipe Ellipse",
    "Zoom In",
    "Zoom Out",
    "to Black",
    "to Color",
    "to White",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ResolumeCoordinator = data["coordinator"]

    entities: list[SelectEntity] = []
    _add_layer_blend_selects(coordinator, entities)

    if entities:
        async_add_entities(entities)

    @callback
    def _handle_new_data():
        added = []
        added.extend(_add_layer_blend_selects(coordinator, entities))
        if added:
            async_add_entities(added)

    coordinator.async_add_listener(_handle_new_data)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _add_layer_blend_selects(
    coordinator: ResolumeCoordinator, entities: list
) -> list[SelectEntity]:
    new: list[SelectEntity] = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    for index, layer in enumerate(composition.get("layers", []), start=1):
        # find blend mode param in video.mixer param list (ParamChoice with many options)
        mixer_params = [
            p
            for p in layer.get("video", {}).get("mixer", [])
            if isinstance(p, dict) and p.get("valuetype") == "ParamChoice"
        ]
        blend = None
        # First try by name
        for p in mixer_params:
            if str(p.get("name", "")).lower().startswith("blend"):
                blend = p
                break
        # Fallback: first large option list
        if not blend:
            for p in mixer_params:
                if len(p.get("options", [])) > 10:
                    blend = p
                    break
        # Fallback: first ParamChoice
        if not blend and mixer_params:
            blend = mixer_params[0]
        if not blend:
            continue
        uid = f"resolume_layer_{layer['id']}_blend_mode"
        if uid in current_ids:
            continue
        raw_name = layer.get("name", {}).get("value", f"Layer {index}")
        name = raw_name.replace("#", str(index))
        ent = LayerBlendModeSelect(coordinator, blend, layer["id"], name, index)
        entities.append(ent)
        new.append(ent)
        current_ids.add(uid)
    return new


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class _BaseMixSelect(CoordinatorEntity[ResolumeCoordinator], SelectEntity):
    _attr_options = OPTIONS
    _attr_has_entity_name = True

    def __init__(self, coordinator: ResolumeCoordinator, param_id: int):
        super().__init__(coordinator)
        self._param_id = param_id

    @property
    def current_option(self) -> str | None:  # type: ignore[override]
        index = self._get_index()
        if index is None:
            return None
        return OPTIONS[index]

    async def async_select_option(self, option: str) -> None:  # type: ignore[override]
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, OPTIONS.index(option))

    # implemented by subclass
    def _get_index(self) -> int | None:  # noqa: D401
        raise NotImplementedError


class LayerBlendModeSelect(CoordinatorEntity[ResolumeCoordinator], SelectEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        param: dict,
        layer_id: int,
        layer_name: str,
        index: int,
    ):
        super().__init__(coordinator)
        self._layer_id = layer_id
        self._param_id = param["id"]
        opts = param.get("options", [])
        # If API returns insufficient list, fallback to full constant list
        self._options = opts if len(opts) > 5 else BLEND_MODES
        self._attr_options = self._options
        self._attr_unique_id = f"resolume_layer_{layer_id}_blend_mode"
        self._attr_name = f"{layer_name} Blend Mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{layer_id}")},
            "name": layer_name,
            "manufacturer": "Resolume",
            "model": "Layer",
        }

    @property
    def current_option(self):  # type: ignore[override]
        param = self._get_param()
        if not param:
            return None

        # Newer API exposes 'value' with the option string; older API uses 'index'
        if "value" in param and param["value"] in self._options:
            return param["value"]

        idx = param.get("index")
        if idx is not None and idx < len(self._options):
            return self._options[idx]
        return None

    async def async_select_option(self, option: str):  # type: ignore[override]
        if option not in self._options:
            return
        api: ResolumeAPI = self.coordinator.api  # type: ignore[attr-defined]
        await api.async_set_parameter(self._param_id, self._options.index(option))

    def _get_param(self):
        composition = self.coordinator.data or {}
        for layer in composition.get("layers", []):
            if layer["id"] != self._layer_id:
                continue
            for p in layer.get("video", {}).get("mixer", []):
                if isinstance(p, dict) and p.get("id") == self._param_id:
                    return p
        return None
