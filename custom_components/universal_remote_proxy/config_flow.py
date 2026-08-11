"""Config flow for Universal Remote Infrared Proxy."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol
from homeassistant.components.infrared import DOMAIN as INFRARED_DOMAIN
from homeassistant.components.infrared import async_get_emitters, async_get_receivers
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CONF_INFRARED_EMITTER_ENTITY_ID,
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DOMAIN,
)


class UniversalRemoteProxyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Universal Remote Infrared Proxy config flow."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select an infrared emitter, receiver, or both."""
        emitter_ids = async_get_emitters(self.hass)
        receiver_ids = async_get_receivers(self.hass)
        if not emitter_ids and not receiver_ids:
            return self.async_abort(reason="no_infrared_hardware")

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = {key: value for key, value in user_input.items() if value}
            if not selected:
                errors["base"] = "nothing_selected"
            else:
                if any(
                    dict(entry.data) == selected
                    for entry in self._async_current_entries(include_ignore=False)
                ):
                    return self.async_abort(reason="already_configured")
                names = [
                    self._entity_name(entity_id) for entity_id in selected.values()
                ]
                return self.async_create_entry(
                    title=f"Infrared proxy via {' / '.join(names)}",
                    data=selected,
                )

        schema: dict[vol.Marker, EntitySelector] = {}
        if emitter_ids:
            schema[vol.Optional(CONF_INFRARED_EMITTER_ENTITY_ID)] = EntitySelector(
                EntitySelectorConfig(
                    domain=INFRARED_DOMAIN, include_entities=emitter_ids
                )
            )
        if receiver_ids:
            schema[vol.Optional(CONF_INFRARED_RECEIVER_ENTITY_ID)] = EntitySelector(
                EntitySelectorConfig(
                    domain=INFRARED_DOMAIN, include_entities=receiver_ids
                )
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    def _entity_name(self, entity_id: str) -> str:
        """Return a friendly registry name for an infrared entity."""
        entity_entry = er.async_get(self.hass).async_get(entity_id)
        if entity_entry is None:
            return entity_id
        return entity_entry.name or entity_entry.original_name or entity_id
