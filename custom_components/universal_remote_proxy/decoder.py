"""Robust RC6 Mode 0 decoder for Home Assistant raw IR timings.

RC6 uses Manchester/biphase coding with a double-width trailer/toggle bit. At
bit boundaries, equal-polarity half-bits merge into longer runs. Real IR
demodulators can distort those runs enough that a duration may plausibly be
both 2T and 3T. Classifying each run greedily can therefore shift the bitstream
and produce a *valid-looking but wrong* command.

This decoder keeps all plausible 1T/2T/3T interpretations for each run, scores
them against the nominal 444 us RC6 time unit, validates complete Mode 0
frames, and returns a frame only when the best interpretation is unambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Iterable

RC6_NOMINAL_UNIT_US = 444
RC6_NOMINAL_FREQUENCY_HZ = 36_000

_HEADER_TOLERANCE = 0.30
# Intentionally broad at the candidate stage. Ambiguous buckets are resolved by
# whole-frame validation rather than a greedy local choice.
_RUN_CANDIDATE_TOLERANCE = 0.40
_REQUIRED_HALF_UNITS_MODE0 = 44
# If two different valid commands have almost indistinguishable timing scores,
# reject the capture rather than emitting a potentially wrong automation event.
_AMBIGUITY_SCORE_MARGIN = 0.015
_MAX_STATES = 512


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

    if all(value > 0 for value in values):
        values = [value if i % 2 == 0 else -value for i, value in enumerate(values)]

    while values and values[0] < 0:
        values.pop(0)
    if not values:
        return []

    merged: list[int] = []
    for value in values:
        if merged and (merged[-1] > 0) == (value > 0):
            merged[-1] += value
        else:
            merged.append(value)
    return merged


def _within(value: float, expected: float, tolerance: float) -> bool:
    return abs(value - expected) <= expected * tolerance


def _candidate_units(value: int) -> list[tuple[int, float]]:
    """Return plausible run lengths and a normalized squared-error score."""
    duration = abs(value)
    candidates: list[tuple[int, float]] = []
    for units in (1, 2, 3):
        expected = units * RC6_NOMINAL_UNIT_US
        relative_error = abs(duration - expected) / expected
        if relative_error <= _RUN_CANDIDATE_TOLERANCE:
            candidates.append((units, relative_error * relative_error))
    return candidates


def _decode_biphase(first: bool, second: bool) -> int | None:
    if first and not second:
        return 1
    if not first and second:
        return 0
    return None


def _decode_levels(levels: tuple[bool, ...]) -> RC6Frame | None:
    if len(levels) != _REQUIRED_HALF_UNITS_MODE0:
        return None

    header: list[int] = []
    for offset in range(0, 8, 2):
        bit = _decode_biphase(levels[offset], levels[offset + 1])
        if bit is None:
            return None
        header.append(bit)

    if header[0] != 1:
        return None
    mode = (header[1] << 2) | (header[2] << 1) | header[3]
    if mode != 0:
        return None

    toggle_levels = levels[8:12]
    if toggle_levels == (True, True, False, False):
        toggle = 1
    elif toggle_levels == (False, False, True, True):
        toggle = 0
    else:
        return None

    raw = 0
    for offset in range(12, 44, 2):
        bit = _decode_biphase(levels[offset], levels[offset + 1])
        if bit is None:
            return None
        raw = (raw << 1) | bit

    return RC6Frame(
        mode=mode,
        toggle=toggle,
        address=(raw >> 8) & 0xFF,
        command=raw & 0xFF,
    )


def decode_rc6(timings: Iterable[int]) -> RC6Frame | None:
    """Decode an RC6 Mode 0 frame, rejecting ambiguous captures."""
    values = _normalise_timings(timings)
    if len(values) < 4:
        return None

    unit = float(RC6_NOMINAL_UNIT_US)
    if values[0] <= 0 or values[1] >= 0:
        return None
    if not _within(values[0], 6 * unit, _HEADER_TOLERANCE):
        return None
    if not _within(abs(values[1]), 2 * unit, _HEADER_TOLERANCE):
        return None

    # State = (expanded levels, accumulated timing error). We keep a modest
    # beam because RC6 captures have very few genuinely ambiguous runs.
    states: list[tuple[tuple[bool, ...], float]] = [((), 0.0)]
    completed: list[tuple[RC6Frame, float]] = []

    for run in values[2:]:
        run_candidates = _candidate_units(run)
        if not run_candidates:
            # A trailing idle gap can include the final space half-bit. This
            # occurs when an RC6 payload ends in 1: the receiver reports the
            # final protocol space and the following idle period as one long
            # negative duration. Only use it to finish a frame that is exactly
            # one half-unit short; never guess a larger missing suffix.
            if run < 0:
                for levels, score in states:
                    if len(levels) != _REQUIRED_HALF_UNITS_MODE0 - 1:
                        continue
                    frame = _decode_levels(levels + (False,))
                    if frame is not None:
                        completed.append((frame, score))

            # A long trailing idle gap after a complete frame is harmless.
            if completed:
                break
            return None

        next_states: list[tuple[tuple[bool, ...], float]] = []
        level = run > 0

        for levels, score in states:
            for units, error in run_candidates:
                new_len = len(levels) + units
                if new_len > _REQUIRED_HALF_UNITS_MODE0:
                    continue
                new_levels = levels + (level,) * units
                new_score = score + error
                if new_len == _REQUIRED_HALF_UNITS_MODE0:
                    frame = _decode_levels(new_levels)
                    if frame is not None:
                        completed.append((frame, new_score))
                else:
                    next_states.append((new_levels, new_score))

        # Lowest-error candidates first. In practice this remains tiny, but the
        # cap prevents pathological/noisy captures from doing excessive work.
        next_states.sort(key=lambda item: item[1])
        states = next_states[:_MAX_STATES]

        if not states and completed:
            break
        if not states and not completed:
            return None

    if not completed:
        return None

    # Multiple timing paths can resolve to the same semantic frame. Collapse
    # those first, retaining only each frame's best timing score.
    best_by_frame: dict[RC6Frame, float] = {}
    for frame, score in completed:
        best_by_frame[frame] = min(score, best_by_frame.get(frame, inf))

    ranked = sorted(best_by_frame.items(), key=lambda item: item[1])
    best_frame, best_score = ranked[0]
    if len(ranked) > 1:
        second_frame, second_score = ranked[1]
        if second_frame != best_frame and second_score - best_score < _AMBIGUITY_SCORE_MARGIN:
            return None

    return best_frame
