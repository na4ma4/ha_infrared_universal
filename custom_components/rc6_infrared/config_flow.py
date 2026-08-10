"""Config flow for RC6 Infrared."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol

from homeassistant.components.infrared import DOMAIN as INFRARED_DOMAIN, async_get_receivers
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import CONF_INFRARED_RECEIVER_ENTITY_ID, DOMAIN


class RC6InfraredConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the RC6 Infrared config flow."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select an infrared receiver."""
        receiver_entity_ids = async_get_receivers(self.hass)
        if not receiver_entity_ids:
            return self.async_abort(reason="no_infrared_receivers")

        if user_input is not None:
            receiver_entity_id = user_input[CONF_INFRARED_RECEIVER_ENTITY_ID]
            self._async_abort_entries_match(
                {CONF_INFRARED_RECEIVER_ENTITY_ID: receiver_entity_id}
            )

            entity_registry = er.async_get(self.hass)
            entity_entry = entity_registry.async_get(receiver_entity_id)
            receiver_name = (
                entity_entry.name
                or entity_entry.original_name
                or receiver_entity_id
                if entity_entry
                else receiver_entity_id
            )
            return self.async_create_entry(
                title=f"RC6 via {receiver_name}",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INFRARED_RECEIVER_ENTITY_ID): EntitySelector(
                        EntitySelectorConfig(
                            domain=INFRARED_DOMAIN,
                            include_entities=receiver_entity_ids,
                        )
                    )
                }
            ),
        )
