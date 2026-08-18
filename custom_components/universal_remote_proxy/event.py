"""Received-command event entity for Universal Remote Infrared Proxy."""

from __future__ import annotations

import logging
from time import monotonic
from typing import override

from homeassistant.components.event import EventEntity
from homeassistant.components.infrared import (
    InfraredReceivedSignal,
    InfraredReceiverConsumerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from infrared_protocols.commands.nec import NECCommand

from .commands import normalize_timings, timings_to_pronto_hex
from .const import (
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DEFAULT_MODULATION_HZ,
    DOMAIN,
    EVENT_PRESS,
    EVENT_REPEAT,
    EVENT_TYPES,
    RC6_MODULATION_HZ,
    REPEAT_WINDOW_SECONDS,
)
from .decoder import decode_rc6

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the received-command event entity when a receiver exists."""
    if receiver_id := entry.data.get(CONF_INFRARED_RECEIVER_ENTITY_ID):
        async_add_entities([UniversalRemoteReceivedEvent(entry, receiver_id)])


class UniversalRemoteReceivedEvent(InfraredReceiverConsumerEntity, EventEntity):
    """Publish decoded and raw infrared receive events."""

    _attr_has_entity_name = True
    _attr_name = "Received command"
    _attr_translation_key = "received_command"
    _attr_event_types = EVENT_TYPES

    def __init__(self, entry: ConfigEntry, receiver_entity_id: str) -> None:
        """Initialize the received-command event entity."""
        self._infrared_receiver_entity_id = receiver_entity_id
        self._attr_unique_id = f"{entry.entry_id}_received_command"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Universal Remote Infrared Proxy",
            manufacturer="Universal Remote",
        )
        self._last_key: tuple[object, ...] | None = None
        self._last_key_time: float | None = None

    @callback
    @override
    def _handle_signal(self, signal: InfraredReceivedSignal) -> None:
        """Decode and publish any received infrared signal."""
        timings = normalize_timings(signal.timings)
        protocol = "unknown"
        repeat_key: tuple[object, ...] | None = None
        modulation = signal.modulation or DEFAULT_MODULATION_HZ
        attributes: dict[str, object] = {}

        rc6 = decode_rc6(timings)
        if rc6 is not None:
            protocol = "rc6"
            modulation = signal.modulation or RC6_MODULATION_HZ
            repeat_key = (protocol, rc6.mode, rc6.toggle, rc6.address, rc6.command)
            attributes.update(
                {
                    "mode": rc6.mode,
                    "toggle": rc6.toggle,
                    "address": rc6.address,
                    "command": rc6.command,
                    "address_hex": f"0x{rc6.address:02X}",
                    "command_hex": f"0x{rc6.command:02X}",
                }
            )
        else:
            nec = NECCommand.from_raw_timings(timings)
            if nec is None:
                return
            protocol = "nec"
            address_low = nec.address & 0xFF
            address_high = (nec.address >> 8) & 0xFF
            address = (
                address_low
                if address_low ^ address_high == 0xFF
                else nec.address
            )
            repeat_key = (protocol, address, nec.command, nec.subfunction)
            attributes.update(
                {
                    "address": address,
                    "command": nec.command,
                    "address_hex": (
                        f"0x{address:02X}"
                        if address <= 0xFF
                        else f"0x{address:04X}"
                    ),
                    "command_hex": f"0x{nec.command:02X}",
                }
            )

        now = monotonic()
        is_repeat = (
            repeat_key is not None
            and repeat_key == self._last_key
            and self._last_key_time is not None
            and now - self._last_key_time <= REPEAT_WINDOW_SECONDS
        )
        event_type = EVENT_REPEAT if is_repeat else EVENT_PRESS
        attributes.update(
            {
                "protocol": protocol,
                "pronto_hex": timings_to_pronto_hex(timings, modulation),
                "modulation": modulation,
                "timings": timings,
            }
        )

        _LOGGER.debug("Received %s IR %s: %s", protocol, event_type, attributes)
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
        self._last_key = repeat_key
        self._last_key_time = now if repeat_key is not None else None
