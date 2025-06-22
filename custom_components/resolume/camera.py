from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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

    entities: list[ResolumeClipCamera] = []

    # wait for push update

    new_entities = _add_clip_cameras(coordinator, entities, entry.data)

    if new_entities:
        async_add_entities(new_entities)

    @callback
    def _handle_new_data():
        added = _add_clip_cameras(coordinator, entities, entry.data)
        if added:
            async_add_entities(added)

    coordinator.async_add_listener(_handle_new_data)


@callback
def _add_clip_cameras(
    coordinator: ResolumeCoordinator, entities: list, cfg: dict[str, Any]
) -> list:
    new = []
    current_ids = {e.unique_id for e in entities}
    composition = coordinator.data or {}
    host = cfg["host"]
    port = cfg["port"]
    for index, layer in enumerate(composition.get("layers", []), start=1):
        for clip in layer.get("clips", []):
            clip_id = clip["id"]
            uid = f"resolume_clip_{clip_id}_preview"
            if uid not in current_ids:
                ent = ResolumeClipCamera(
                    coordinator,
                    clip,
                    host,
                    port,
                    layer["id"],
                    layer_index=index,
                    layer_name=layer.get("name", {}).get("value", f"Layer {index}"),
                )
                entities.append(ent)
                new.append(ent)
                current_ids.add(uid)
    return new


class ResolumeClipCamera(CoordinatorEntity[ResolumeCoordinator], Camera):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ResolumeCoordinator,
        clip_info: dict,
        host: str,
        port: int,
        layer_id: int,
        layer_index: int,
        layer_name: str,
    ):
        super().__init__(coordinator)
        Camera.__init__(self)
        self._clip_id = clip_info["id"]
        self._layer_id = layer_id
        self._host = host
        self._port = port
        self._attr_unique_id = f"resolume_clip_{self._clip_id}_preview"
        name_val = clip_info.get("name", {}).get("value", str(self._clip_id))
        self._attr_name = f"Preview: {name_val}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"layer_{self._layer_id}")},
            "name": layer_name.replace("#", str(layer_index)),
            "manufacturer": "Resolume",
            "model": "Layer",
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:  # noqa: D401
        clip_info = self._get_clip()
        if not clip_info:
            return None
        thumbnail = clip_info.get("thumbnail", {})
        last_update = thumbnail.get("last_update", "0")
        if last_update == "0":
            url = f"http://{self._host}:{self._port}/api/v1/composition/thumbnail/dummy"
        else:
            url = f"http://{self._host}:{self._port}/api/v1/composition/clips/by-id/{self._clip_id}/thumbnail/{last_update}"

        session = async_get_clientsession(self.hass)
        try:
            resp = await session.get(url)
            resp.raise_for_status()
            return await resp.read()
        except (ClientError, OSError):
            _LOGGER.debug(
                "Could not fetch Resolume clip thumbnail for %s", self._clip_id
            )
            return None

    # ------------------------------------------------------------------
    def _get_clip(self):
        composition = self.coordinator.data or {}
        for layer in composition.get("layers", []):
            for clip in layer.get("clips", []):
                if clip["id"] == self._clip_id:
                    return clip
        return None
