"""Parse and encode commands for Universal Remote Infrared Proxy."""

from __future__ import annotations

import re
from collections.abc import Iterable

from infrared_protocols.commands import Command
from infrared_protocols.commands.nec import NECCommand

from .const import DEFAULT_MODULATION_HZ, RC6_FRAME_PERIOD_US, RC6_MODULATION_HZ

PRONTO_PATTERN = re.compile(r"^[0-9a-fA-F]{4}(?:\s+[0-9a-fA-F]{4})*$")
PRONTO_REFERENCE_FREQUENCY = 4_145_146
RC6_UNIT_US = 444


def normalize_timings(timings: Iterable[int], *, even: bool = False) -> list[int]:
    """Normalize raw timings to alternating signed mark/space durations."""
    values = [int(value) for value in timings if int(value) != 0]
    if not values:
        return []
    if all(value > 0 for value in values):
        values = [
            value if index % 2 == 0 else -value
            for index, value in enumerate(values)
        ]
    while values and values[0] < 0:
        values.pop(0)
    merged: list[int] = []
    for value in values:
        if merged and (merged[-1] > 0) == (value > 0):
            merged[-1] += value
        else:
            merged.append(value)
    if even and len(merged) % 2:
        merged.pop()
    return merged


class RawCommand(Command):
    """Infrared command that sends supplied raw timings unchanged."""

    def __init__(
        self,
        timings: Iterable[int],
        *,
        modulation: int = DEFAULT_MODULATION_HZ,
        repeat_count: int = 0,
    ) -> None:
        values = normalize_timings(timings)
        if not values:
            raise ValueError("raw command must contain at least one non-zero timing")
        if modulation <= 0:
            raise ValueError("modulation must be positive")
        if repeat_count < 0:
            raise ValueError("repeat_count must be non-negative")
        super().__init__(modulation=modulation, repeat_count=repeat_count)
        self.timings = values

    def get_raw_timings(self) -> list[int]:
        """Return raw timings, repeating the complete capture if requested."""
        return self.timings * (self.repeat_count + 1)


class ProntoHexCommand(RawCommand):
    """Version-independent command parsed from learned Pronto hex."""

    def __init__(self, pronto_hex: str, *, repeat_count: int = 0) -> None:
        words = [int(word, 16) for word in pronto_hex.split()]
        if len(words) < 4:
            raise ValueError("pronto code must start with a 4 word preamble")
        if words[0] != 0:
            raise ValueError("only learned pronto codes (token 0000) are supported")
        frequency_word, once_pairs, repeat_pairs = words[1:4]
        if frequency_word == 0:
            raise ValueError("pronto frequency word must not be zero")
        timing_words = words[4:]
        if len(timing_words) != (once_pairs + repeat_pairs) * 2:
            raise ValueError(
                "pronto timing data does not match the preamble burst pair counts"
            )
        if not timing_words:
            raise ValueError("pronto code must contain at least one burst pair")
        if any(word == 0 for word in timing_words):
            raise ValueError("pronto timing words must not be zero")
        if repeat_count > 0 and repeat_pairs == 0:
            raise ValueError("pronto code has no repeat sequence to repeat")

        modulation = round(PRONTO_REFERENCE_FREQUENCY / frequency_word)
        time_base = 1_000_000 / modulation
        once_word_count = once_pairs * 2

        def words_to_timings(values: list[int]) -> list[int]:
            return [
                duration
                for index, word in enumerate(values)
                for duration in [
                    min(round(word * time_base), 0xFFFF)
                    * (1 if index % 2 == 0 else -1)
                ]
            ]

        once_timings = words_to_timings(timing_words[:once_word_count])
        repeat_timings = words_to_timings(timing_words[once_word_count:])
        timings = (once_timings or repeat_timings) + repeat_timings * repeat_count
        super().__init__(timings, modulation=modulation)
        self.pronto_hex = " ".join(f"{word:04X}" for word in words)

    def to_pronto_hex(self) -> str:
        """Return the canonical Pronto representation supplied by the caller."""
        return self.pronto_hex


def _append_duration(timings: list[int], duration: int) -> None:
    """Append a signed duration, merging adjacent values of one polarity."""
    if duration == 0:
        return
    if timings and (timings[-1] > 0) == (duration > 0):
        timings[-1] += duration
    else:
        timings.append(duration)


def _bit_levels(bit: int) -> tuple[bool, bool]:
    return (True, False) if bit else (False, True)


def encode_rc6(
    address: int,
    command: int,
    *,
    mode: int = 0,
    toggle: int = 0,
    repeat_count: int = 0,
) -> list[int]:
    """Encode an RC6 frame into signed raw timings."""
    if not 0 <= mode <= 0b111:
        raise ValueError(f"mode must be a 3-bit value (0-7), got {mode}")
    if toggle not in (0, 1):
        raise ValueError(f"toggle must be 0 or 1, got {toggle}")
    if not 0 <= address <= 0xFF:
        raise ValueError(f"address must be an 8-bit value (0-0xFF), got {address:#x}")
    if not 0 <= command <= 0xFF:
        raise ValueError(f"command must be an 8-bit value (0-0xFF), got {command:#x}")
    if repeat_count < 0:
        raise ValueError("repeat_count must be non-negative")

    levels: list[bool] = []
    for bit in (1, (mode >> 2) & 1, (mode >> 1) & 1, mode & 1):
        levels.extend(_bit_levels(bit))
    levels.extend((True, True, False, False) if toggle else (False, False, True, True))
    data = (address << 8) | command
    for shift in range(15, -1, -1):
        levels.extend(_bit_levels((data >> shift) & 1))

    frame = [6 * RC6_UNIT_US, -(2 * RC6_UNIT_US)]
    for level in levels:
        _append_duration(frame, RC6_UNIT_US if level else -RC6_UNIT_US)

    timings = frame.copy()
    gap = max(RC6_UNIT_US, RC6_FRAME_PERIOD_US - sum(abs(value) for value in frame))
    for _ in range(repeat_count):
        _append_duration(timings, -gap)
        for value in frame:
            _append_duration(timings, value)
    return timings


class RC6Command(Command):
    """RC6 infrared command."""

    def __init__(
        self,
        *,
        address: int,
        command: int,
        mode: int = 0,
        toggle: int = 0,
        modulation: int = RC6_MODULATION_HZ,
        repeat_count: int = 0,
    ) -> None:
        # Validate all protocol fields immediately.
        encode_rc6(
            address,
            command,
            mode=mode,
            toggle=toggle,
            repeat_count=repeat_count,
        )
        super().__init__(modulation=modulation, repeat_count=repeat_count)
        self.address = address
        self.command = command
        self.mode = mode
        self.toggle = toggle

    def get_raw_timings(self) -> list[int]:
        """Return encoded RC6 timings."""
        return encode_rc6(
            self.address,
            self.command,
            mode=self.mode,
            toggle=self.toggle,
            repeat_count=self.repeat_count,
        )


def is_pronto_hex(command: str) -> bool:
    """Return whether a string has the lexical form of Pronto hex."""
    return PRONTO_PATTERN.fullmatch(command.strip()) is not None


def _parse_int(value: str, field: str) -> int:
    try:
        return int(value, 0)
    except ValueError as err:
        raise ValueError(f"{field} must be an integer, got {value!r}") from err


def parse_command(command: str, repeat_count: int = 0) -> Command:
    """Parse a literal command string into an infrared command."""
    value = command.strip()
    if not value:
        raise ValueError("command must not be empty")
    if repeat_count < 0:
        raise ValueError("repeat_count must be non-negative")

    if is_pronto_hex(value):
        return ProntoHexCommand(value, repeat_count=repeat_count)

    prefix, separator, payload = value.partition(":")
    if not separator:
        raise ValueError(
            f"unknown named command {value!r}; specify a device or use a literal format"
        )
    prefix = prefix.lower()

    if prefix == "pronto":
        pronto_hex = payload.strip()
        if not is_pronto_hex(pronto_hex):
            raise ValueError("pronto words must each contain exactly 4 hex digits")
        return ProntoHexCommand(pronto_hex, repeat_count=repeat_count)
    if prefix == "raw":
        parts = payload.replace(",", " ").split()
        if not parts:
            raise ValueError("raw command must contain timings")
        return RawCommand(
            (_parse_int(part, "timing") for part in parts),
            repeat_count=repeat_count,
        )
    if prefix == "nec":
        parts = payload.split(":")
        if len(parts) != 2:
            raise ValueError("NEC format is nec:<address>:<command>")
        return NECCommand(
            address=_parse_int(parts[0], "address"),
            command=_parse_int(parts[1], "command"),
            repeat_count=repeat_count,
        )
    if prefix == "rc6":
        parts = payload.split(":")
        if len(parts) == 2:
            mode, toggle, address, command_value = 0, 0, parts[0], parts[1]
        elif len(parts) == 4:
            mode = _parse_int(parts[0], "mode")
            toggle = _parse_int(parts[1], "toggle")
            address, command_value = parts[2], parts[3]
        else:
            raise ValueError(
                "RC6 format is rc6:<address>:<command> or "
                "rc6:<mode>:<toggle>:<address>:<command>"
            )
        return RC6Command(
            mode=mode,
            toggle=toggle,
            address=_parse_int(address, "address"),
            command=_parse_int(command_value, "command"),
            repeat_count=repeat_count,
        )
    raise ValueError(f"unsupported command format {prefix!r}")


def timings_to_pronto_hex(
    timings: Iterable[int], modulation: int | None = None
) -> str | None:
    """Convert raw timings to Pronto hex, returning None for unusable input."""
    values = normalize_timings(timings, even=True)
    if not values:
        return None
    try:
        modulation = modulation or DEFAULT_MODULATION_HZ
        if modulation <= 0:
            return None
        time_base = 1_000_000 / modulation
        timing_words = []
        for timing in values:
            compensated = timing - 20 if timing > 0 else -timing + 20
            word = round((compensated + time_base / 2) / time_base)
            if not 0 < word <= 0xFFFF:
                return None
            timing_words.append(word)
        frequency_word = round(PRONTO_REFERENCE_FREQUENCY / modulation)
        if not 0 < frequency_word <= 0xFFFF:
            return None
        words = [0, frequency_word, len(values) // 2, 0, *timing_words]
        return " ".join(f"{word:04X}" for word in words)
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
