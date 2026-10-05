"""Konstanty integrace PID Departure Boards."""

DOMAIN = "pid_departure_boards"

# entry.data
CONF_API_KEY = "api_key"

# entry.options
CONF_SCAN_INTERVAL = "scan_interval"

# subentry.data
CONF_STOP_ID = "stop_id"  # GTFS stop_id nástupiště
CONF_STOP_NAME = "stop_name"
CONF_PLATFORM = "platform"
CONF_ROUTES = "routes"
CONF_LIMIT = "limit"
CONF_NAME = "name"

SUBENTRY_TYPE_STOP = "stop"

DEFAULT_SCAN_INTERVAL = 60  # s
MIN_SCAN_INTERVAL = 30  # s — rate limit Golemio je 20 req / 8 s na token
MAX_SCAN_INTERVAL = 3600
DEFAULT_LIMIT = 5
MAX_LIMIT = 20

API_BASE_URL = "https://api.golemio.cz"
API_KEYS_URL = "https://api.golemio.cz/api-keys"

# Kolik minut dopředu se odjezdy stahují
MINUTES_AFTER = 240
# Linky filtrujeme na klientu, proto se z API žádá víc záznamů než limit
FETCH_LIMIT_FACTOR = 4
MIN_FETCH_LIMIT = 20

STOPS_STORAGE_VERSION = 1
STOPS_MAX_AGE_DAYS = 7

SERVICE_REFRESH = "refresh"
SERVICE_GET_DEPARTURES = "get_departures"

# GTFS route_type
ROUTE_TYPES: dict[int, str] = {
    0: "tram",
    1: "metro",
    2: "train",
    3: "bus",
    4: "ferry",
    7: "funicular",
    11: "trolleybus",
}
