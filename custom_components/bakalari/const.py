"""Constants for the Bakalari integration."""

from typing import Final, NotRequired, Required, TypedDict

DOMAIN = "bakalari"

PLATFORMS = ["sensor", "calendar"]
MANUFACTURER = "Bakaláři pro HomeAssistant"
MODEL = "Bakaláři backend"

LIB_VERSION: Final = "1.5.0"
API_VERSION: Final = "0.10.0"
SW_VERSION: Final = f"API: {API_VERSION} Library: {LIB_VERSION}"
CONF_CHILDREN: Final = "children"
CONF_CREDENTIALS: Final = "credentials"
CONF_USER_ID: Final = "user_id"
CONF_USERNAME: Final = "username"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_SERVER: Final = "server"
CONF_NAME: Final = "name"
CONF_SURNAME: Final = "surname"
CONF_SCHOOL: Final = "school"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SCHOOL_YEAR_START_DAY: Final = 1
CONF_SCHOOL_YEAR_START_MONTH: Final = 9
DEFAULT_SCAN_INTERVAL: Final = 900


class ChildRecord(TypedDict, total=False):
    """Child record."""

    user_id: Required[str]
    username: Required[str]
    name: Required[str]
    surname: Required[str]
    school: Required[str]
    server: Required[str]
    access_token: NotRequired[str]
    refresh_token: NotRequired[str]


ChildrenMap = dict[str, ChildRecord]

SCHOOLS_CACHE_FILE: Final = "schools_cache.json"
RATE_LIMIT_EXCEEDED: Final = "If the server returns a `Connection error`, you may have exceeded the request limit. Try again later or increase the polling interval."
