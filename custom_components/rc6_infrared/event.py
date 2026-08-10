"""Event platform for RC6 Infrared."""

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

from .const import (
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DOMAIN,
    EVENT_PRESS,
    EVENT_REPEAT,
    EVENT_TYPES,
    REPEAT_WINDOW_SECONDS,
)
from .decoder import RC6Frame, decode_rc6

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the RC6 event entity."""
    async_add_entities(
        [
            RC6ReceivedCommandEvent(
                entry,
                entry.data[CONF_INFRARED_RECEIVER_ENTITY_ID],
            )
        ]
    )


class RC6ReceivedCommandEvent(InfraredReceiverConsumerEntity, EventEntity):
    """Event entity that decodes RC6 Mode 0 commands."""

    _attr_has_entity_name = True
    _attr_name = "Received command"
    _attr_event_types = EVENT_TYPES

    def __init__(self, entry: ConfigEntry, receiver_entity_id: str) -> None:
        """Initialize the event entity."""
        self._infrared_receiver_entity_id = receiver_entity_id
        self._attr_unique_id = f"{entry.entry_id}_received_command"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="RC6 Infrared Remote",
            manufacturer="RC6",
        )
        self._last_frame: RC6Frame | None = None
        self._last_frame_time: float | None = None

    @callback
    @override
    def _handle_signal(self, signal: InfraredReceivedSignal) -> None:
        """Decode and publish a received RC6 signal."""
        frame = decode_rc6(signal.timings)
        if frame is None:
            _LOGGER.debug("Ignoring non-RC6 Mode 0 IR signal: %s", signal.timings)
            return

        now = monotonic()
        is_repeat = (
            self._last_frame is not None
            and self._last_frame.address == frame.address
            and self._last_frame.command == frame.command
            and self._last_frame.toggle == frame.toggle
            and self._last_frame_time is not None
            and now - self._last_frame_time <= REPEAT_WINDOW_SECONDS
        )

        event_type = EVENT_REPEAT if is_repeat else EVENT_PRESS
        attributes = {
            "protocol": "rc6",
            "mode": frame.mode,
            "toggle": frame.toggle,
            "address": frame.address,
            "command": frame.command,
            "address_hex": f"0x{frame.address:02X}",
            "command_hex": f"0x{frame.command:02X}",
        }

        _LOGGER.debug(
            "Received RC6 %s: mode=%d toggle=%d address=0x%02X command=0x%02X",
            event_type,
            frame.mode,
            frame.toggle,
            frame.address,
            frame.command,
        )
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()

        self._last_frame = frame
        self._last_frame_time = now
