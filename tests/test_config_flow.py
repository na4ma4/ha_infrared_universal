"""Home Assistant config flow smoke tests."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.universal_remote_proxy.const import (
    CONF_INFRARED_EMITTER_ENTITY_ID,
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DOMAIN,
)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_no_hardware_aborts(hass) -> None:
    with (
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_emitters",
            return_value=[],
        ),
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_receivers",
            return_value=[],
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_infrared_hardware"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_empty_selection_is_rejected(hass) -> None:
    with (
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_emitters",
            return_value=["infrared.emitter"],
        ),
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_receivers",
            return_value=["infrared.receiver"],
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "nothing_selected"}


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    "selection",
    [
        {CONF_INFRARED_EMITTER_ENTITY_ID: "infrared.emitter"},
        {CONF_INFRARED_RECEIVER_ENTITY_ID: "infrared.receiver"},
        {
            CONF_INFRARED_EMITTER_ENTITY_ID: "infrared.emitter",
            CONF_INFRARED_RECEIVER_ENTITY_ID: "infrared.receiver",
        },
    ],
)
async def test_hardware_combinations_create_entries(hass, selection) -> None:
    with (
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_emitters",
            return_value=["infrared.emitter"],
        ),
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_receivers",
            return_value=["infrared.receiver"],
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=selection
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == selection


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_duplicate_hardware_tuple_aborts(hass) -> None:
    selection = {CONF_INFRARED_EMITTER_ENTITY_ID: "infrared.emitter"}
    MockConfigEntry(domain=DOMAIN, data=selection).add_to_hass(hass)

    with (
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_emitters",
            return_value=["infrared.emitter"],
        ),
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_receivers",
            return_value=["infrared.receiver"],
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=selection
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_subset_of_existing_hardware_pair_is_allowed(hass) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_INFRARED_EMITTER_ENTITY_ID: "infrared.emitter",
            CONF_INFRARED_RECEIVER_ENTITY_ID: "infrared.receiver",
        },
    ).add_to_hass(hass)

    with (
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_emitters",
            return_value=["infrared.emitter"],
        ),
        patch(
            "custom_components.universal_remote_proxy.config_flow.async_get_receivers",
            return_value=["infrared.receiver"],
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_INFRARED_EMITTER_ENTITY_ID: "infrared.emitter"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
