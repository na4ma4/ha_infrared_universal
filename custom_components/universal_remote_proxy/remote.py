"""Remote entity for Universal Remote Infrared Proxy."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any, override

from homeassistant.components import persistent_notification
from homeassistant.components.infrared import (
    InfraredEmitterConsumerEntity,
    InfraredReceivedSignal,
    async_subscribe_receiver,
)
from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_DEVICE,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_COMMAND
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.storage import Store

from .commands import normalize_timings, parse_command, timings_to_pronto_hex
from .const import (
    CODE_STORAGE_KEY,
    CODE_STORAGE_VERSION,
    CONF_INFRARED_EMITTER_ENTITY_ID,
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DEFAULT_LEARNING_TIMEOUT,
    DEFAULT_MODULATION_HZ,
    DOMAIN,
    RC6_MODULATION_HZ,
)
from .decoder import decode_rc6

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0

StoredCodes = dict[str, dict[str, list[str]]]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the remote entity when an emitter exists."""
    if emitter_id := entry.data.get(CONF_INFRARED_EMITTER_ENTITY_ID):
        async_add_entities(
            [
                UniversalRemoteProxyRemote(
                    entry,
                    emitter_id,
                    entry.data.get(CONF_INFRARED_RECEIVER_ENTITY_ID),
                    Store(
                        hass,
                        CODE_STORAGE_VERSION,
                        CODE_STORAGE_KEY.format(entry_id=entry.entry_id),
                        atomic_writes=True,
                    ),
                )
            ]
        )


class UniversalRemoteProxyRemote(InfraredEmitterConsumerEntity, RemoteEntity):
    """Send literal and learned commands through an infrared emitter."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        entry: ConfigEntry,
        emitter_entity_id: str,
        receiver_entity_id: str | None,
        code_store: Store[StoredCodes],
    ) -> None:
        """Initialize the remote entity."""
        self._infrared_emitter_entity_id = emitter_entity_id
        self._receiver_entity_id = receiver_entity_id
        self._code_store = code_store
        self._codes: StoredCodes = {}
        self._storage_loaded = False
        self._storage_lock = asyncio.Lock()
        self._attr_unique_id = f"{entry.entry_id}_remote"
        self._attr_is_on = True
        self._attr_supported_features = RemoteEntityFeature.DELETE_COMMAND
        if receiver_entity_id is not None:
            self._attr_supported_features |= RemoteEntityFeature.LEARN_COMMAND
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Universal Remote Infrared Proxy",
            manufacturer="Universal Remote",
        )

    async def _async_load_storage(self) -> None:
        """Load learned codes once."""
        if self._storage_loaded:
            return
        async with self._storage_lock:
            if not self._storage_loaded:
                self._codes = await self._code_store.async_load() or {}
                self._storage_loaded = True

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable command transmission."""
        self._attr_is_on = True
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable command transmission."""
        self._attr_is_on = False
        self.async_write_ha_state()

    def _resolve_command(self, value: str, device: str | None) -> list[str]:
        """Resolve a learned command or return a literal command."""
        if device is not None and value in self._codes.get(device, {}):
            return self._codes[device][value]
        try:
            parse_command(value)
        except ValueError as err:
            if device is None:
                raise HomeAssistantError(
                    f"A device is required to send learned command {value!r}"
                ) from err
            raise HomeAssistantError(
                f"Learned command {value!r} was not found for device {device!r}"
            ) from err
        return [value]

    @override
    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send literal or learned infrared commands."""
        if not self._attr_is_on:
            raise HomeAssistantError("The remote is turned off")
        await self._async_load_storage()
        device = kwargs.get(ATTR_DEVICE)
        repeat = int(kwargs.get(ATTR_NUM_REPEATS, 1))
        delay = float(kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS))
        if repeat < 1:
            raise HomeAssistantError("num_repeats must be at least 1")
        if delay < 0:
            raise HomeAssistantError("delay_secs must not be negative")

        literals = [
            literal
            for value in command
            for literal in self._resolve_command(value, device)
        ]
        sent = False
        for _ in range(repeat):
            for literal in literals:
                if sent:
                    await asyncio.sleep(delay)
                try:
                    infrared_command = parse_command(literal)
                except ValueError as err:
                    raise HomeAssistantError(
                        f"Invalid infrared command {literal!r}: {err}"
                    ) from err
                await self._send_command(infrared_command)
                sent = True

    @override
    async def async_learn_command(self, **kwargs: Any) -> None:
        """Learn one or more named infrared commands."""
        if self._receiver_entity_id is None:
            raise HomeAssistantError("This remote has no infrared receiver configured")
        device = self._require_device(kwargs)
        commands = self._require_commands(kwargs)
        timeout = int(kwargs.get("timeout", DEFAULT_LEARNING_TIMEOUT))
        await self._async_load_storage()

        duplicates = [name for name in commands if name in self._codes.get(device, {})]
        if duplicates:
            raise HomeAssistantError(
                f"Commands already exist for device {device!r}: {', '.join(duplicates)}"
            )

        learned: dict[str, list[str]] = {}
        for name in commands:
            signal = await self._async_capture_signal(device, name, timeout)
            timings = normalize_timings(signal.timings)
            modulation = signal.modulation or (
                RC6_MODULATION_HZ
                if decode_rc6(timings) is not None
                else DEFAULT_MODULATION_HZ
            )
            pronto = timings_to_pronto_hex(timings, modulation)
            if pronto is None:
                raise HomeAssistantError(
                    f"Could not convert learned command {name!r} to Pronto hex"
                )
            learned[name] = [pronto]

        async with self._storage_lock:
            # Recheck to prevent a concurrent learn from silently replacing data.
            duplicates = [
                name for name in commands if name in self._codes.get(device, {})
            ]
            if duplicates:
                raise HomeAssistantError(
                    f"Commands already exist for device {device!r}: "
                    f"{', '.join(duplicates)}"
                )
            self._codes.setdefault(device, {}).update(learned)
            await self._code_store.async_save(self._codes)

    async def _async_capture_signal(
        self, device: str, command: str, timeout: int
    ) -> InfraredReceivedSignal:
        """Wait for a single signal from the configured receiver."""
        assert self._receiver_entity_id is not None
        notification_id = f"{DOMAIN}_{self._attr_unique_id}_learn"
        persistent_notification.async_create(
            self.hass,
            f"Press the {command!r} button for device {device!r}.",
            title="Universal Remote Infrared Proxy learning",
            notification_id=notification_id,
        )
        future: asyncio.Future[InfraredReceivedSignal] = self.hass.loop.create_future()

        @callback
        def signal_received(signal: InfraredReceivedSignal) -> None:
            if not future.done():
                future.set_result(signal)

        unsubscribe = None
        try:
            unsubscribe = async_subscribe_receiver(
                self.hass, self._receiver_entity_id, signal_received
            )
            async with asyncio.timeout(timeout):
                return await future
        except TimeoutError as err:
            raise HomeAssistantError(
                f"Timed out learning command {command!r} for device {device!r}"
            ) from err
        finally:
            if unsubscribe is not None:
                unsubscribe()
            persistent_notification.async_dismiss(self.hass, notification_id)

    @override
    async def async_delete_command(self, **kwargs: Any) -> None:
        """Delete device-scoped learned commands."""
        device = self._require_device(kwargs)
        commands = self._require_commands(kwargs)
        await self._async_load_storage()
        async with self._storage_lock:
            missing = [
                name for name in commands if name not in self._codes.get(device, {})
            ]
            if missing:
                raise HomeAssistantError(
                    f"Commands not found for device {device!r}: {', '.join(missing)}"
                )
            for name in commands:
                del self._codes[device][name]
            if not self._codes[device]:
                del self._codes[device]
            await self._code_store.async_save(self._codes)

    @staticmethod
    def _require_device(kwargs: dict[str, Any]) -> str:
        device = kwargs.get(ATTR_DEVICE)
        if not isinstance(device, str) or not device.strip():
            raise HomeAssistantError("A non-empty device is required")
        return device.strip()

    @staticmethod
    def _require_commands(kwargs: dict[str, Any]) -> list[str]:
        value = kwargs.get(ATTR_COMMAND)
        if isinstance(value, str):
            commands = [value]
        elif value is not None:
            commands = list(value)
        else:
            commands = []
        commands = [
            str(command).strip() for command in commands if str(command).strip()
        ]
        if not commands:
            raise HomeAssistantError("At least one non-empty command name is required")
        if len(commands) != len(set(commands)):
            raise HomeAssistantError("Command names must be unique")
        return commands
