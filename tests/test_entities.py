"""Home Assistant entity smoke tests."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.infrared import InfraredReceivedSignal
from homeassistant.components.remote import ATTR_DEVICE, ATTR_NUM_REPEATS
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.universal_remote_proxy import (
    async_setup_entry as async_setup_integration_entry,
)
from custom_components.universal_remote_proxy import (
    async_unload_entry as async_unload_integration_entry,
)
from custom_components.universal_remote_proxy.commands import (
    parse_command,
    timings_to_pronto_hex,
)
from custom_components.universal_remote_proxy.const import (
    CONF_INFRARED_EMITTER_ENTITY_ID,
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DOMAIN,
    EVENT_PRESS,
    EVENT_REPEAT,
)
from custom_components.universal_remote_proxy.event import (
    UniversalRemoteReceivedEvent,
)
from custom_components.universal_remote_proxy.event import (
    async_setup_entry as async_setup_event_entry,
)
from custom_components.universal_remote_proxy.remote import (
    UniversalRemoteProxyRemote,
)
from custom_components.universal_remote_proxy.remote import (
    async_setup_entry as async_setup_remote_entry,
)


class MemoryStore:
    """Minimal Store substitute for entity smoke tests."""

    def __init__(self, data=None) -> None:
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data) -> None:
        self.data = data


async def test_integration_forwards_and_unloads_platforms(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    with (
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as forward,
        patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ) as unload,
    ):
        assert await async_setup_integration_entry(hass, entry)
        assert await async_unload_integration_entry(hass, entry)

    forward.assert_awaited_once()
    unload.assert_awaited_once()


async def test_platforms_only_add_entities_for_configured_hardware(hass) -> None:
    emitter_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INFRARED_EMITTER_ENTITY_ID: "infrared.emitter"},
    )
    receiver_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INFRARED_RECEIVER_ENTITY_ID: "infrared.receiver"},
    )
    add_remote = Mock()
    add_event = Mock()

    await async_setup_remote_entry(hass, emitter_entry, add_remote)
    await async_setup_event_entry(hass, emitter_entry, add_event)
    assert isinstance(add_remote.call_args.args[0][0], UniversalRemoteProxyRemote)
    add_event.assert_not_called()

    add_remote.reset_mock()
    await async_setup_remote_entry(hass, receiver_entry, add_remote)
    await async_setup_event_entry(hass, receiver_entry, add_event)
    add_remote.assert_not_called()
    assert isinstance(add_event.call_args.args[0][0], UniversalRemoteReceivedEvent)


async def test_remote_sends_literal_and_learned_commands(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    remote = UniversalRemoteProxyRemote(
        entry,
        "infrared.emitter",
        None,
        MemoryStore({"television": {"power": ["nec:1:2"]}}),
    )
    remote.hass = hass
    remote._send_command = AsyncMock()

    await remote.async_send_command(
        ["power", "rc6:3:4"],
        **{ATTR_DEVICE: "television", ATTR_NUM_REPEATS: 1},
    )

    assert remote._send_command.await_count == 2
    first, second = [call.args[0] for call in remote._send_command.await_args_list]
    assert (first.address, first.command) == (1, 2)
    assert (second.address, second.command) == (3, 4)


async def test_duplicate_learn_name_is_rejected(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    remote = UniversalRemoteProxyRemote(
        entry,
        "infrared.emitter",
        "infrared.receiver",
        MemoryStore({"television": {"power": ["nec:1:2"]}}),
    )
    remote.hass = hass

    with pytest.raises(Exception, match="already exist"):
        await remote.async_learn_command(device="television", command=["power"])


async def test_learning_rc6_without_carrier_uses_36_khz(hass) -> None:
    from custom_components.universal_remote_proxy.commands import RC6Command

    entry = MockConfigEntry(domain=DOMAIN, data={})
    store = MemoryStore()
    remote = UniversalRemoteProxyRemote(
        entry,
        "infrared.emitter",
        "infrared.receiver",
        store,
    )
    remote.hass = hass
    remote._async_capture_signal = AsyncMock(
        return_value=InfraredReceivedSignal(
            RC6Command(address=1, command=2).get_raw_timings()
        )
    )

    await remote.async_learn_command(device="television", command=["power"])

    pronto = store.data["television"]["power"][0]
    assert parse_command(pronto).modulation == pytest.approx(36_000, abs=100)


def test_event_decodes_nec_and_generates_pronto() -> None:
    from infrared_protocols.commands.nec import NECCommand

    entry = MockConfigEntry(domain=DOMAIN, data={})
    event = UniversalRemoteReceivedEvent(entry, "infrared.receiver")
    event._trigger_event = Mock()
    event.async_write_ha_state = Mock()
    timings = NECCommand(address=0x12, command=0xA5).get_raw_timings()
    signal = InfraredReceivedSignal(timings)

    event._handle_signal(signal)
    event._handle_signal(signal)

    first = event._trigger_event.call_args_list[0].args
    second = event._trigger_event.call_args_list[1].args
    assert first[0] == EVENT_PRESS
    assert first[1]["protocol"] == "nec"
    assert first[1]["address"] == 0x12
    assert first[1]["command"] == 0xA5
    assert first[1]["pronto_hex"] == timings_to_pronto_hex(timings, 38_000)
    assert second[0] == EVENT_REPEAT


def test_unknown_event_is_always_press_with_pronto() -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    event = UniversalRemoteReceivedEvent(entry, "infrared.receiver")
    event._trigger_event = Mock()
    event.async_write_ha_state = Mock()
    signal = InfraredReceivedSignal([1000, -1000, 500, -500])

    event._handle_signal(signal)
    event._handle_signal(signal)

    for call in event._trigger_event.call_args_list:
        assert call.args[0] == EVENT_PRESS
        assert call.args[1]["protocol"] == "unknown"
        assert call.args[1]["pronto_hex"] is not None
