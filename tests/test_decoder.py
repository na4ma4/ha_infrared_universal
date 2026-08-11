"""Tests for the standalone RC6 decoder."""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

DECODER_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "universal_remote_proxy"
    / "decoder.py"
)
spec = importlib.util.spec_from_file_location("rc6_decoder", DECODER_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
decode_rc6 = module.decode_rc6

T = 444


def _bit_levels(bit: int) -> list[bool]:
    return [True, False] if bit else [False, True]


def _encode(address: int, command: int, toggle: int = 0, mode: int = 0) -> list[int]:
    levels: list[bool] = []
    for bit in [1, (mode >> 2) & 1, (mode >> 1) & 1, mode & 1]:
        levels.extend(_bit_levels(bit))
    levels.extend([True, True, False, False] if toggle else [False, False, True, True])
    raw = (address << 8) | command
    for shift in range(15, -1, -1):
        levels.extend(_bit_levels((raw >> shift) & 1))

    timings = [6 * T, -(2 * T)]
    for level in levels:
        value = T if level else -T
        if timings and (timings[-1] > 0) == (value > 0):
            timings[-1] += value
        else:
            timings.append(value)
    return timings


def test_decode_known_frame() -> None:
    frame = decode_rc6(_encode(0x00, 0x0C, toggle=1))
    assert frame is not None
    assert frame.mode == 0
    assert frame.toggle == 1
    assert frame.address == 0x00
    assert frame.command == 0x0C


def test_decode_arbitrary_frame() -> None:
    frame = decode_rc6(_encode(0x7A, 0xE1, toggle=0))
    assert frame is not None
    assert (frame.address, frame.command, frame.toggle) == (0x7A, 0xE1, 0)


def test_accepts_unsigned_alternating_timings() -> None:
    timings = [abs(value) for value in _encode(0x12, 0x34, toggle=1)]
    frame = decode_rc6(timings)
    assert frame is not None
    assert (frame.address, frame.command) == (0x12, 0x34)


def test_tolerates_realistic_jitter() -> None:
    random.seed(6)
    timings = _encode(0x21, 0x9A, toggle=1)
    jittered = [
        int(value * random.uniform(0.90, 1.10))
        for value in timings
    ]
    frame = decode_rc6(jittered)
    assert frame is not None
    assert (frame.address, frame.command, frame.toggle) == (0x21, 0x9A, 1)


def test_rejects_nonzero_mode() -> None:
    assert decode_rc6(_encode(0x00, 0x0C, mode=1)) is None


def test_rejects_bad_leader() -> None:
    timings = _encode(0x00, 0x0C)
    timings[0] = 1000
    assert decode_rc6(timings) is None


def test_many_repeated_captures_decode_identically() -> None:
    """Same physical command should survive independently jittered captures."""
    expected = (0x00, 0x5A)
    for toggle in (0, 1):
        for seed in range(100):
            random.seed(seed + toggle * 1000)
            timings = _encode(*expected, toggle=toggle)
            # Independent run jitter is much nastier than scaling the whole
            # frame equally and better approximates demodulator captures.
            jittered = [
                int(value * random.uniform(0.82, 1.18))
                for value in timings
            ]
            frame = decode_rc6(jittered)
            assert frame is not None, (seed, toggle, jittered)
            assert (frame.address, frame.command, frame.toggle) == (*expected, toggle)


def test_asymmetric_mark_space_distortion() -> None:
    """IR demodulators commonly stretch one polarity and shrink the other."""
    timings = _encode(0x34, 0xA7, toggle=1)
    distorted = [
        int(value * (1.12 if value > 0 else 0.88))
        for value in timings
    ]
    frame = decode_rc6(distorted)
    assert frame is not None
    assert (frame.address, frame.command, frame.toggle) == (0x34, 0xA7, 1)


def test_terminal_space_merged_into_idle_gap() -> None:
    """A long idle gap may contain the last space of an odd command."""
    timings = _encode(0x3B, 0x1D, toggle=0)
    assert timings[-1] < 0
    timings[-1] = -10_000

    frame = decode_rc6(timings)

    assert frame is not None
    assert (frame.address, frame.command, frame.toggle) == (0x3B, 0x1D, 0)


def test_real_button_2_capture_with_terminal_idle_gap() -> None:
    timings = [
        2756,
        -891,
        435,
        -902,
        480,
        -453,
        435,
        -476,
        434,
        -925,
        903,
        -458,
        456,
        -454,
        903,
        -457,
        457,
        -453,
        457,
        -902,
        903,
        -458,
        457,
        -903,
        433,
        -478,
        455,
        -454,
        903,
        -457,
        457,
        -454,
        457,
        -903,
        903,
        -10_000,
    ]

    frame = decode_rc6(timings)

    assert frame is not None
    assert (frame.address, frame.command, frame.toggle) == (0x3B, 0x1D, 0)


def test_idle_gap_does_not_complete_a_short_noise_capture() -> None:
    assert decode_rc6([171, -10_000]) is None
