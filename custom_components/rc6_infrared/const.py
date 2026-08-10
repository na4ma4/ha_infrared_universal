"""Constants for the RC6 Infrared integration."""

DOMAIN = "rc6_infrared"
CONF_INFRARED_RECEIVER_ENTITY_ID = "infrared_receiver_entity_id"

EVENT_PRESS = "press"
EVENT_REPEAT = "repeat"
EVENT_TYPES = [EVENT_PRESS, EVENT_REPEAT]

# A held RC6 button normally repeats much faster than this. The toggle bit is the
# primary indication; the time window prevents an old identical frame being
# classified as a repeat if a remote does not toggle reliably.
REPEAT_WINDOW_SECONDS = 0.5
