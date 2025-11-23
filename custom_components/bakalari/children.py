"""Children class for Bakalari."""

from dataclasses import dataclass
import logging

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CHILDREN,
    CONF_NAME,
    CONF_REFRESH_TOKEN,
    CONF_SCHOOL,
    CONF_SERVER,
    CONF_SURNAME,
    CONF_USER_ID,
    CONF_USERNAME,
    ChildRecord,
    ChildrenMap,
)
from .utils import ensure_children_dict, make_child_key

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Child:
    """Child class for Bakalari."""

    key: str
    user_id: str
    server: str
    display_name: str
    short_name: str


class ChildrenIndex:
    """Index of children for Bakalari."""

    def __init__(self, children_map: ChildrenMap):
        """Initialize the ChildrenIndex."""
        self.children_map = children_map
        self._by_key: dict[str, ChildRecord] = {}
        self._optkey_by_childkey: dict[str, str] = {}
        self._list: list[Child] = []

    @classmethod
    def from_entry(cls, entry) -> "ChildrenIndex":
        """Create a ChildrenIndex from a dictionary entry."""
        raw: ChildrenMap = ensure_children_dict(entry.options.get(CONF_CHILDREN, {}))

        by_key: dict[str, ChildRecord] = {}
        opt_map: dict[str, str] = {}
        lst: list[Child] = []

        for opt_key, cr in raw.items():
            server = (cr.get(CONF_SERVER) or "").strip()
            user_id = (cr.get(CONF_USER_ID) or str(opt_key)).strip()
            if not server or not user_id:
                _LOGGER.warning(
                    "[class=%s module=%s] Skipping child with missing server/user_id: %s",
                    __class__.__name__,
                    __name__,
                    cr,
                )
                continue
            ck = make_child_key(server, user_id)
            opt_map[ck] = str(opt_key)

            tmp: ChildRecord = {
                "user_id": user_id,
                "username": str(cr.get(CONF_USERNAME, "") or ""),
                "name": str(cr.get(CONF_NAME, "") or ""),
                "surname": str(cr.get(CONF_SURNAME, "") or ""),
                "school": str(cr.get(CONF_SCHOOL)),
                "server": server,
            }

            at = cr.get(CONF_ACCESS_TOKEN)
            rt = cr.get(CONF_REFRESH_TOKEN)

            if at:
                tmp[CONF_ACCESS_TOKEN] = at
            if rt:
                tmp[CONF_REFRESH_TOKEN] = rt

            by_key[ck] = tmp
            display = f"{cr.get('name', '')} {cr.get('surname', '')} ({cr.get('school', '')})".strip()
            lst.append(
                Child(
                    key=ck,
                    user_id=user_id,
                    server=server,
                    display_name=display,
                    short_name=str(cr.get("name") or "").strip() or user_id,
                )
            )
        inst = cls(raw)
        inst._by_key = by_key
        inst._optkey_by_childkey = opt_map
        inst._list = lst
        return inst

    @property
    def children(self) -> list[Child]:
        """Returns a list of children."""
        return list(self._list)

    def option_key_for_child(self, child_key: str) -> str | None:
        """Return the option key for a child."""
        return self._optkey_by_childkey.get(child_key)

    def child_by_key(self, key: str) -> Child:
        """Return a child by its key."""
        for ch in self._list:
            if ch.key == key:
                return ch
        raise KeyError(key)
