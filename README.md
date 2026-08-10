# RC6 Infrared for Home Assistant

Experimental Home Assistant custom integration that consumes a Home Assistant
`infrared` **receiver** entity and exposes decoded **RC6 Mode 0** commands as a
single `event` entity.

It is intended for ESPHome `ir_rf_proxy` receivers, including ESP32/KinCony IR
hardware.

## What you get

A single event entity such as:

```text
event.rc6_infrared_remote_received_command
```

A new physical button press produces:

```yaml
event_type: press
protocol: rc6
mode: 0
toggle: 1
address: 0
command: 12
address_hex: "0x00"
command_hex: "0x0C"
```

A held button using the same RC6 toggle value produces `event_type: repeat`.

## Requirements

- Home Assistant 2026.6 or newer receiver-side infrared API.
- An `infrared` receiver entity. ESPHome can provide this via `ir_rf_proxy`.
- An RC6 Mode 0 remote.

## ESPHome example

Replace the GPIO with the IR receiver pin used by your KinCony board.

```yaml
remote_receiver:
  id: ir_rx
  pin:
    number: GPIO1
    inverted: true
  dump:
    - rc6

infrared:
  - platform: ir_rf_proxy
    name: IR Receiver
    remote_receiver_id: ir_rx
    receiver_frequency: 36kHz
```

Keeping `dump: rc6` enabled initially is useful because it lets you compare
ESPHome's decoder output with the Home Assistant event entity.

## Install manually

Copy:

```text
custom_components/rc6_infrared/
```

to:

```text
/config/custom_components/rc6_infrared/
```

Restart Home Assistant, then go to **Settings → Devices & services → Add
integration → RC6 Infrared** and select the KinCony/ESPHome infrared receiver.

## Automation example

Use a state trigger on the event entity and inspect its event attributes:

```yaml
triggers:
  - trigger: state
    entity_id: event.rc6_infrared_remote_received_command
conditions:
  - condition: template
    value_template: >-
      {{ trigger.to_state.attributes.event_type == 'press'
         and trigger.to_state.attributes.address == 0
         and trigger.to_state.attributes.command == 12 }}
actions:
  - action: light.toggle
    target:
      entity_id: light.example
```

Home Assistant's newer `event` entity automation UI may generate a more concise
trigger for you. The important attributes are `event_type`, `address`, `command`
and `toggle`.

## Debugging

Add:

```yaml
logger:
  logs:
    custom_components.rc6_infrared: debug
```

Successful frames are logged as:

```text
Received RC6 press: mode=0 toggle=1 address=0x00 command=0x0C
```

Signals that do not decode as RC6 Mode 0 are logged at debug level with their
raw timings.

## Decoder scope

This first version deliberately supports **RC6 Mode 0 only**, matching the mode
ESPHome's own RC6 decoder currently accepts. It uses the fixed RC6 444 us timing unit and evaluates ambiguous 1T/2T/3T run interpretations against the complete frame. This avoids a shortened 3T run being greedily mistaken for 2T and shifting the decoded command. Ambiguous captures are rejected instead of emitting a potentially wrong button event.

The decoder itself has no Home Assistant dependency and lives in `decoder.py`,
so it can later be moved into `infrared-protocols` if this graduates into an
upstream contribution.

## Tests

The decoder tests are standalone:

```bash
python -m pytest tests/test_decoder.py
```

They cover known frames, toggle values, unsigned captures, timing jitter,
non-zero modes, and invalid leaders.

## Status

Experimental. The Home Assistant integration structure follows the current
2026 receiver API and the official LG infrared consumer pattern, but this has
not yet been exercised against a real KinCony receiver. That hardware test is
the useful next step.


## 0.2.0 decoder changes

- Replaced greedy half-bit reconstruction with whole-frame candidate decoding.
- Handles ambiguous 2T/3T runs caused by demodulator timing distortion.
- Rejects near-tied interpretations rather than publishing a wrong command.
- Added repeated-capture and asymmetric mark/space distortion tests.
