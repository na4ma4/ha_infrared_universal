# Universal Remote Infrared Proxy for Home Assistant

Universal Remote Infrared Proxy connects Home Assistant's `remote` and `event`
entities to ESPHome infrared proxies, including the `infrared` entities exposed by
ESPHome `ir_rf_proxy`.

It can send Pronto, NEC, RC6, and raw timing commands, learn signals into named
Pronto codes, and publish every received signal. RC6 Mode 0 and NEC signals also
receive decoded address and command attributes.

## Requirements

- Home Assistant 2026.6.0 or newer.
- An ESPHome or other Home Assistant `infrared` emitter and/or receiver entity.

## Installation

Install with HACS as a custom repository, or copy
`custom_components/universal_remote_proxy/` to the matching directory under your
Home Assistant configuration. Restart Home Assistant, then add **Universal Remote
Infrared Proxy** from **Settings → Devices & services**.

Each integration entry can use an emitter, a receiver, or both. Distinct hardware
combinations can be configured as separate entries.

### Breaking change from RC6 Infrared

Version 0.3.0 changes the integration domain from `rc6_infrared` to
`universal_remote_proxy`. Remove the old integration, replace its component
directory, restart Home Assistant, and add the renamed integration. Existing
entity IDs and config entries are not migrated automatically.

## Sending commands

Call `remote.send_command` with one or more strings in these formats:

| Format | Example |
| --- | --- |
| Pronto hex | `0000 006D 0001 0000 015B 00AC` |
| Explicit Pronto | `pronto:0000 006D 0001 0000 015B 00AC` |
| NEC | `nec:0x12:0xA5` |
| RC6 Mode 0 | `rc6:0x00:0x0C` |
| Explicit RC6 fields | `rc6:0:1:0x00:0x0C` |
| Raw timings | `raw:9000,-4500,562,-562` |

Numeric protocol fields accept decimal or Python-style `0x` hexadecimal values.
RC6 uses 36 kHz; NEC, raw commands, and received signals without a known carrier
default to 38 kHz.

```yaml
action: remote.send_command
target:
  entity_id: remote.universal_remote_infrared_proxy
data:
  command:
    - "nec:0x12:0xA5"
  num_repeats: 2
  delay_secs: 0.4
```

`num_repeats` is the total number of sends. Repeats are sent separately so learned
Pronto codes do not need a Pronto repeat sequence.

## Learning and deleting named commands

Learning requires an entry configured with both an emitter and receiver. A
non-empty `device` namespace is mandatory. Existing names are rejected; delete a
name before learning it again.

```yaml
action: remote.learn_command
target:
  entity_id: remote.universal_remote_infrared_proxy
data:
  device: television
  command: power
```

Press the requested physical button while the persistent notification is shown.
The capture is stored as Pronto hex under that config entry. Send it by name:

```yaml
action: remote.send_command
target:
  entity_id: remote.universal_remote_infrared_proxy
data:
  device: television
  command: power
```

Delete it with `remote.delete_command`, supplying the same `device` and `command`.

## Received events

The receiver-side event entity publishes `press` or `repeat` events with:

- `protocol`: `rc6`, `nec`, or `unknown`
- `pronto_hex`: a Pronto representation of the raw capture when conversion succeeds
- `modulation` and signed `timings`
- decoded `mode`, `toggle`, `address`, and `command` fields when applicable

RC6 and NEC commands repeated within 0.5 seconds produce `repeat`. Unknown signals
always produce `press`, because capture jitter makes timing-only matching unsafe.
Pronto is an interchange representation rather than a decoded protocol: all usable
captures can be represented as Pronto even when their protocol is unknown.

## ESPHome example

```yaml
remote_transmitter:
  id: ir_tx
  pin: GPIO2
  carrier_duty_percent: 50%

remote_receiver:
  id: ir_rx
  pin:
    number: GPIO1
    inverted: true

infrared:
  - platform: ir_rf_proxy
    name: IR Proxy
    remote_transmitter_id: ir_tx
    remote_receiver_id: ir_rx
    receiver_frequency: 38kHz
```

Adjust IDs, pins, and ESPHome options for your hardware.

## Development

Open the repository in its VS Code devcontainer, or install
[uv](https://docs.astral.sh/uv/) locally and run:

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
```

The protocol tests are standalone. Home Assistant smoke tests use mocked infrared
entities; real emitter/receiver validation still requires ESPHome hardware.
