"""Tests for standalone infrared command parsing and encoding."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from infrared_protocols.commands.nec import NECCommand

COMPONENT_PATH = (
    Path(__file__).parents[1] / "custom_components" / "universal_remote_proxy"
)

# Load dependency-free component modules without importing the HA-dependent package
# __init__.py. This keeps protocol tests fast and runnable outside Home Assistant.
package = types.ModuleType("universal_remote_proxy")
package.__path__ = [str(COMPONENT_PATH)]
sys.modules.setdefault("universal_remote_proxy", package)
for module_name in ("const", "decoder", "commands"):
    spec = importlib.util.spec_from_file_location(
        f"universal_remote_proxy.{module_name}", COMPONENT_PATH / f"{module_name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from universal_remote_proxy.commands import (  # noqa: E402
    ProntoHexCommand,
    RawCommand,
    RC6Command,
    is_pronto_hex,
    parse_command,
    timings_to_pronto_hex,
)
from universal_remote_proxy.decoder import decode_rc6  # noqa: E402


def test_pronto_round_trip() -> None:
    timings = [9000, -4500, 562, -562]
    pronto = timings_to_pronto_hex(timings, 38_000)
    assert pronto is not None
    assert is_pronto_hex(pronto)

    parsed = parse_command(pronto)
    assert isinstance(parsed, ProntoHexCommand)
    assert parsed.to_pronto_hex() == pronto
    assert parse_command(f"pronto:{pronto}").to_pronto_hex() == pronto


def test_repeat_only_pronto_from_home_assistant_runtime_error() -> None:
    pronto = (
        "0000 0068 0000 0022 0168 00B4 0016 0043 0016 0016 0016 0043 "
        "0016 0016 0016 0016 0016 0043 0016 0016 0016 0043 0016 0016 "
        "0016 0043 0016 0016 0016 0043 0016 0043 0016 0016 0016 0043 "
        "0016 0016 0016 0016 0016 0043 0016 0016 0016 0043 0016 0016 "
        "0016 0016 0016 0016 0016 0016 0016 0043 0016 0016 0016 0043 "
        "0016 0016 0016 0043 0016 0043 0016 0043 0016 0043 0016 03DD"
    )

    parsed = parse_command(pronto)

    assert isinstance(parsed, ProntoHexCommand)
    assert parsed.modulation == pytest.approx(39_857, abs=1)
    assert len(parsed.get_raw_timings()) == 68
    assert parsed.to_pronto_hex() == pronto


def test_odd_receive_timings_are_safely_trimmed() -> None:
    pronto = timings_to_pronto_hex([9000, -4500, 562], 38_000)
    assert pronto is not None
    assert len(parse_command(pronto).get_raw_timings()) == 2


def test_raw_passthrough_and_unsigned_normalization() -> None:
    command = parse_command("raw:9000, 4500 562 562")
    assert isinstance(command, RawCommand)
    assert command.modulation == 38_000
    assert command.get_raw_timings() == [9000, -4500, 562, -562]


@pytest.mark.parametrize(
    "literal",
    ["", "unknown", "sony:1:2", "nec:1", "rc6:1:2:3", "raw:0,0"],
)
def test_invalid_formats_raise(literal: str) -> None:
    with pytest.raises(ValueError):
        parse_command(literal)


def test_nec_encode_decode() -> None:
    encoded = parse_command("nec:0x12:0xA5")
    assert isinstance(encoded, NECCommand)
    decoded = NECCommand.from_raw_timings(encoded.get_raw_timings())
    assert decoded is not None
    assert decoded.command == 0xA5
    assert decoded.address & 0xFF == 0x12


@pytest.mark.parametrize("toggle", [0, 1])
def test_rc6_encode_decodes_mode_zero(toggle: int) -> None:
    encoded = parse_command(f"rc6:0:{toggle}:0x7A:0xE1")
    assert isinstance(encoded, RC6Command)
    decoded = decode_rc6(encoded.get_raw_timings())
    assert decoded is not None
    assert (decoded.mode, decoded.toggle, decoded.address, decoded.command) == (
        0,
        toggle,
        0x7A,
        0xE1,
    )


def test_rc6_short_form_defaults_to_mode_and_toggle_zero() -> None:
    encoded = parse_command("rc6:1:2")
    assert isinstance(encoded, RC6Command)
    assert (encoded.mode, encoded.toggle, encoded.address, encoded.command) == (
        0,
        0,
        1,
        2,
    )


def test_rc6_repeat_period_is_about_114_ms() -> None:
    single_duration = sum(
        abs(value) for value in RC6Command(address=1, command=2).get_raw_timings()
    )
    encoded = RC6Command(address=1, command=2, repeat_count=1)
    timings = encoded.get_raw_timings()
    assert sum(abs(value) for value in timings) == pytest.approx(
        114_000 + single_duration, abs=500
    )


@pytest.mark.parametrize(
    "literal",
    ["nec:0x10000:1", "nec:1:0x100", "rc6:8:0:1:2", "rc6:0:2:1:2"],
)
def test_protocol_ranges_are_validated(literal: str) -> None:
    with pytest.raises(ValueError):
        parse_command(literal)
