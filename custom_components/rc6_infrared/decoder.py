"""RC6 Mode 0 decoder for raw mark/space timings.

The decoder consumes Home Assistant's raw IR representation: positive durations
are marks and negative durations are spaces. For convenience/testing it also
accepts an all-positive alternating mark/space sequence beginning with a mark.

RC6 Mode 0 uses a nominal 444 us time unit, a 6T mark / 2T space leader,
Manchester encoded start+mode and data bits, and a double-width toggle bit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

RC6_NOMINAL_UNIT_US = 444
RC6_NOMINAL_FREQUENCY_HZ = 36_000

# Broad enough for demodulator/ESP timing jitter while still rejecting unrelated
# protocols. The actual T is estimated from the leader rather than hard-coded.
_HEADER_RATIO_TOLERANCE = 0.30
_UNIT_TOLERANCE = 0.30
_MIN_UNIT_US = 300.0
_MAX_UNIT_US = 600.0
_REQUIRED_HALF_UNITS_MODE0 = 44


@dataclass(frozen=True, slots=True)
class RC6Frame:
    """A decoded RC6 Mode 0 frame."""

    mode: int
    toggle: int
    address: int
    command: int


def _normalise_timings(timings: Iterable[int]) -> list[int]:
    values = [int(value) for value in timings if int(value) != 0]
    if not values:
        return []

    # Some raw IR formats represent alternating mark/space durations without
    # signs. HA/ESPHome uses signed timings, but accepting both makes diagnostics
    # and captured test vectors easier to work with.
    if all(value > 0 for value in values):
        values = [value if index % 2 == 0 else -value for index, value in enumerate(values)]

    # The signal should start with a mark. Ignore a leading idle-space fragment.
    while values and values[0] < 0:
        values.pop(0)
    if not values:
        return []

    # Merge adjacent entries of the same polarity. This protects against capture
    # sources that split a long mark/space into multiple chunks.
    merged: list[int] = []
    for value in values:
        if merged and (merged[-1] > 0) == (value > 0):
            merged[-1] += value
        else:
            merged.append(value)
    return merged


def _within(value: float, expected: float, tolerance: float) -> bool:
    return abs(value - expected) <= expected * tolerance


def _estimate_unit(header_mark: int, header_space: int) -> float | None:
    if header_mark <= 0 or header_space >= 0:
        return None

    mark_unit = header_mark / 6.0
    space_unit = abs(header_space) / 2.0
    if not (_MIN_UNIT_US <= mark_unit <= _MAX_UNIT_US):
        return None
    if not (_MIN_UNIT_US <= space_unit <= _MAX_UNIT_US):
        return None

    unit = (mark_unit + space_unit) / 2.0
    if not _within(mark_unit, unit, _HEADER_RATIO_TOLERANCE):
        return None
    if not _within(space_unit, unit, _HEADER_RATIO_TOLERANCE):
        return None
    return unit


def _expand_half_units(timings: list[int], unit_us: float) -> list[bool] | None:
    """Expand merged timings to one boolean per nominal T interval.

    True is carrier/mark, False is space. Standard RC6 biphase halves are 1T.
    The trailer/toggle bit uses 2T halves. Same-polarity halves at bit boundaries
    may merge, so captured entries commonly measure 2T or 3T.
    """
    levels: list[bool] = []
    for value in timings:
        duration = abs(value)
        units = round(duration / unit_us)
        if units < 1:
            return None

        # Ignore a trailing idle gap once a complete Mode 0 frame is available.
        if units > 4:
            if len(levels) >= _REQUIRED_HALF_UNITS_MODE0:
                break
            return None

        expected = units * unit_us
        if not _within(duration, expected, _UNIT_TOLERANCE):
            return None

        levels.extend([value > 0] * units)
        if len(levels) >= _REQUIRED_HALF_UNITS_MODE0:
            break

    if len(levels) < _REQUIRED_HALF_UNITS_MODE0:
        return None
    return levels[:_REQUIRED_HALF_UNITS_MODE0]


def _decode_biphase_bit(first: bool, second: bool) -> int | None:
    if first and not second:
        return 1
    if not first and second:
        return 0
    return None


def decode_rc6(timings: Iterable[int]) -> RC6Frame | None:
    """Decode an RC6 Mode 0 frame from raw timings.

    Returns ``None`` when the timings are not a valid RC6 Mode 0 frame.
    """
    values = _normalise_timings(timings)
    if len(values) < 3:
        return None

    unit_us = _estimate_unit(values[0], values[1])
    if unit_us is None:
        return None

    levels = _expand_half_units(values[2:], unit_us)
    if levels is None:
        return None

    # Start bit + three mode bits: four normal biphase bits = 8 half units.
    header_bits: list[int] = []
    for offset in range(0, 8, 2):
        bit = _decode_biphase_bit(levels[offset], levels[offset + 1])
        if bit is None:
            return None
        header_bits.append(bit)

    if header_bits[0] != 1:
        return None
    mode = (header_bits[1] << 2) | (header_bits[2] << 1) | header_bits[3]
    if mode != 0:
        # This implementation intentionally mirrors ESPHome's currently tested
        # decoder and only accepts RC6 Mode 0.
        return None

    # Toggle/trailer bit: two T of first polarity followed by two T of the other.
    toggle_levels = levels[8:12]
    if toggle_levels == [True, True, False, False]:
        toggle = 1
    elif toggle_levels == [False, False, True, True]:
        toggle = 0
    else:
        return None

    data_levels = levels[12:44]
    bits: list[int] = []
    for offset in range(0, len(data_levels), 2):
        bit = _decode_biphase_bit(data_levels[offset], data_levels[offset + 1])
        if bit is None:
            return None
        bits.append(bit)

    if len(bits) != 16:
        return None

    raw = 0
    for bit in bits:
        raw = (raw << 1) | bit

    return RC6Frame(
        mode=mode,
        toggle=toggle,
        address=(raw >> 8) & 0xFF,
        command=raw & 0xFF,
    )
