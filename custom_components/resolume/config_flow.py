from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            int, vol.Range(min=1, max=65535)
        ),
    }
)


class ResolumeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Resolume."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):  # type: ignore[override]
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Resolume {user_input[CONF_HOST]}", data=user_input
            )

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):  # noqa: D401
        """Return the options flow handler."""
        return ResolumeOptionsFlowHandler(config_entry)


class ResolumeOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Resolume."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None):  # type: ignore[override]
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=self.config_entry.data[CONF_HOST]
                    ): str,
                    vol.Required(
                        CONF_PORT, default=self.config_entry.data[CONF_PORT]
                    ): vol.All(int, vol.Range(min=1, max=65535)),
                }
            ),
        )
