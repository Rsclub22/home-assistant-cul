"""Constants for the CUL integration."""

DOMAIN = "cul"
CONF_FHTID = "fhtid"
CONF_MIGRATE = "migrate"
DATA_MIGRATED = "migrated"
OPT_TIMEOUT = "timeout"
DEFAULT_TIMEOUT = 7200
OPT_TIME_SYNC = "time_sync"
DEFAULT_PORT = 2323
EVENT_COMMAND_FAILED = "cul_command_failed"
EVENT_FHT_PAIRED = "cul_fht_paired"
EVENT_FHT_PAIR_FAILED = "cul_fht_pair_failed"
CONF_CONNECTION = "connection"
CONN_TCP = "tcp"
CONN_SERIAL = "serial"
CONF_DEVICE = "device"
CONF_BAUDRATE = "baudrate"
DEFAULT_BAUDRATE = 9600
PAIR_TIMEOUT = 900  # s: an FHT80b in CEnt "nA" picks up commands within ~2 min
STORAGE_VERSION = 1


def signal_new(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_new_device"


def signal_update(entry_id: str, device_key: str) -> str:
    return f"{DOMAIN}_{entry_id}_update_{device_key}"


def signal_cul(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_cul"
