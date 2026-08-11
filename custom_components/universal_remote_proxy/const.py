"""Constants for Universal Remote Infrared Proxy."""

DOMAIN = "universal_remote_proxy"

CONF_INFRARED_EMITTER_ENTITY_ID = "infrared_emitter_entity_id"
CONF_INFRARED_RECEIVER_ENTITY_ID = "infrared_receiver_entity_id"

EVENT_PRESS = "press"
EVENT_REPEAT = "repeat"
EVENT_TYPES = [EVENT_PRESS, EVENT_REPEAT]
REPEAT_WINDOW_SECONDS = 0.5

DEFAULT_MODULATION_HZ = 38_000
RC6_MODULATION_HZ = 36_000
RC6_FRAME_PERIOD_US = 114_000

CODE_STORAGE_VERSION = 1
CODE_STORAGE_KEY = "universal_remote_proxy_{entry_id}_codes"
DEFAULT_LEARNING_TIMEOUT = 30
