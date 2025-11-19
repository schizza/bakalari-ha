"""Calendar platform for Bakalari - timetable per child (coordinator-backed).

Refactored to use BakalariCoordinator instead of direct API client:
- No direct HTTP/API calls from the entity.
- All timetable data are sourced from the coordinator's shared data snapshot.
- Events are rebuilt whenever the coordinator updates.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time
import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import BakalariCoordinator, Child
from .entity import BakalariEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bakalari calendar entities from a config entry via coordinator."""

    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coord: BakalariCoordinator = data["coordinator"]

    entities: list[BakalariTimetableCalendar] = [
        BakalariTimetableCalendar(coord, child) for child in coord.child_list
    ]

    async_add_entities(entities)


class BakalariTimetableCalendar(BakalariEntity, CalendarEntity):
    """Calendar entity representing child's school timetable (coordinator-backed)."""

    _attr_icon = "mdi:calendar-school"
    _attr_translation_key = "timetable"

    def __init__(self, coordinator: BakalariCoordinator, child: Child) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator, child)

        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}:{child.key}:timetable_calendar"
        )
        self._attr_name = f"Rozvrh - {child.short_name}"

        # Internal cache of CalendarEvent objects built from coordinator timetable weeks.
        self._events_cache: list[CalendarEvent] = []
        self._next_event: CalendarEvent | None = None
        self._last_source_version: int = 0  # simple monotonic marker we derive

    # ------------- CalendarEntity API -------------

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event (if any)."""
        return self._next_event

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        # Ensure cache is current with coordinator data
        self._ensure_events_current()

        start = dt_util.as_utc(start_date)
        end = dt_util.as_utc(end_date)

        result: list[CalendarEvent] = []
        for ev in self._events_cache:
            ev_start = _ensure_utc(ev.start)
            ev_end = _ensure_utc(ev.end) if ev.end else ev_start
            # Overlap test (inclusive)
            overlaps = (ev_start < end) and (ev_end > start)
            if overlaps:
                result.append(ev)

        result.sort(key=lambda e: _ensure_utc(e.start))
        return result

    async def async_update(self) -> None:
        """Manual update trigger (rare). Request coordinator refresh."""
        # We do NOT fetch directly; rely on coordinator refresh.
        await self.coordinator.async_request_refresh()

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        # Build initial cache from current coordinator data.
        self._rebuild_events()
        self._compute_next_event()

    # ------------- Coordinator callbacks -------------

    @callback
    def _handle_coordinator_update(self) -> None:
        """React to coordinator data changes."""
        self._rebuild_events()
        self._compute_next_event()
        self.async_write_ha_state()

    # ------------- Cache management -------------

    def _ensure_events_current(self) -> None:
        """Verify cached events align with current coordinator timetable snapshot."""
        # We derive a simple version number from object ids & lengths to detect change cheaply.
        weeks = self._get_child_weeks()
        version = _weeks_version_marker(weeks)
        if version != self._last_source_version:
            _LOGGER.debug(
                "[class=%s module=%s] Rebuilding events cache for child_key=%s (ver %s -> %s)",
                self.__class__.__name__,
                __name__,
                self.child.key,
                self._last_source_version,
                version,
            )
            self._rebuild_events(weeks=weeks, version=version)

    def _rebuild_events(
        self,
        *,
        weeks: list[Any] | None = None,
        version: int | None = None,
    ) -> None:
        """Rebuild events cache from coordinator weeks."""
        weeks = weeks if weeks is not None else self._get_child_weeks()
        try:
            events: list[CalendarEvent] = []
            for w in weeks:
                events.extend(_convert_week_to_events(w))
            # Deduplicate by (start,end,summary,location)
            dedup: dict[tuple[str, str, str, str], CalendarEvent] = {}
            for ev in events:
                k = (
                    _ensure_utc(ev.start).isoformat(),
                    _ensure_utc(ev.end).isoformat() if ev.end else "",
                    ev.summary or "",
                    ev.location or "",
                )
                # Keep earliest version if duplicates appear
                if k not in dedup:
                    dedup[k] = ev
            final_events = list(dedup.values())
            final_events.sort(key=lambda e: _ensure_utc(e.start))
            self._events_cache = final_events
            self._last_source_version = (
                version if version is not None else _weeks_version_marker(weeks)
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "[class=%s module=%s] Failed rebuilding events for child_key=%s:",
                self.__class__.__name__,
                __name__,
                self.child.key,
            )
            self._events_cache = []

    def _compute_next_event(self) -> None:
        """Compute the next upcoming event from cache."""
        now = dt_util.utcnow()
        upcoming = [ev for ev in self._events_cache if _ensure_utc(ev.start) >= now]
        upcoming.sort(key=lambda e: _ensure_utc(e.start))
        self._next_event = upcoming[0] if upcoming else None

    # ------------- Data extraction helpers -------------

    def _get_child_weeks(self) -> list[Any]:
        """Fetch raw timetable weeks list for the child from coordinator data."""
        data = self.coordinator.data or {}
        weeks = data.get("timetable_by_child", {}).get(self.child.key, [])
        if not isinstance(weeks, list):
            return []
        return weeks


# ---------------- Conversion helpers (adapted from legacy calendar) ----------------


def _convert_week_to_events(raw: Any) -> list[CalendarEvent]:
    """Convert a timetable week object into CalendarEvent list (delegates per atom)."""
    if raw is None:
        return []
    week = raw
    try:
        hours = getattr(week, "hours", {}) or {}
        days = getattr(week, "days", []) or []
    except Exception:  # noqa: BLE001
        _LOGGER.error("[module=%s] Timetable week structure invalid.", __name__)
        return []

    events: list[CalendarEvent] = []
    for day in days:
        date_part = getattr(day, "date", None)
        if date_part is None:
            continue
        day_date = date_part.date() if isinstance(date_part, datetime) else date_part
        atoms = getattr(day, "atoms", []) or []
        for atom in atoms:
            ev = _atom_to_event(day_date, atom, hours, week)
            if ev:
                events.append(ev)

    events.sort(key=lambda e: _ensure_utc(e.start))
    return events


def _atom_to_event(
    day_date: date | datetime,
    atom: Any,
    hours: dict[Any, Any],
    week: Any,
) -> CalendarEvent | None:
    """Build a CalendarEvent for a single timetable atom (reduced complexity)."""
    try:
        hour = _resolve_hour(atom, hours)
        if hour is None:
            return None
        times = _resolve_times(day_date, hour)
        if times is None:
            return None
        start, end = times
        subj, teach, room, groups = _safe_resolve_entities(week, atom)
        summary = _label_subject(subj) or "Hodina"
        description = _build_description(
            teach=teach,
            groups=groups,
            theme=getattr(atom, "theme", None),
            change=getattr(atom, "change", None),
        )
        location = _label_room(room)
        return CalendarEvent(
            start=start,
            end=end or start,
            summary=summary,
            description=description,
            location=location,
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "[module=%s] Skipping atom -> event due to error: %s",
            __name__,
            e,
        )
        return None


def _resolve_hour(atom: Any, hours: dict[Any, Any]) -> Any | None:
    """Return hour object for atom or None."""
    hour_id = getattr(atom, "hour_id", None)
    if hour_id is None:
        return None
    return hours.get(hour_id)


def _resolve_times(
    day_date: date | datetime, hour: Any
) -> tuple[datetime, datetime] | None:
    """Compute start/end UTC datetimes from hour item."""
    start = _combine_local_utc(day_date, getattr(hour, "begin_time", ""))
    if start is None:
        return None
    end = _combine_local_utc(day_date, getattr(hour, "end_time", ""))
    return (start, end or start)


def _safe_resolve_entities(week: Any, atom: Any) -> tuple[Any, Any, Any, list[Any]]:
    """Resolve (subject, teacher, room, groups) with error shielding."""
    try:
        subj, teach, room, groups = week.resolve(atom)  # type: ignore[attr-defined]
    except Exception:
        return None, None, None, []
    else:
        return subj, teach, room, groups


def _format_change(change: Any) -> str | None:
    """Format change object into a short label."""
    if change is None:
        return None
    ch_type = getattr(change, "change_type", None) or ""
    ch_desc = getattr(change, "description", None) or ""
    ch_time = getattr(change, "time", None)
    if not (ch_type or ch_desc or ch_time):
        return None
    label = f"Změna: {ch_type} | {ch_desc}".strip()
    if ch_time:
        label += f" ({ch_time})"
    return label


def _build_description(
    teach: Any,
    groups: list[Any],
    theme: Any,
    change: Any,
) -> str | None:
    """Compose description string from resolved entities."""
    parts: list[str] = []
    teach_label = _label_teacher(teach)
    if teach_label:
        parts.append(f"Učitel: {teach_label}")
    groups_label = _label_groups(groups)
    if groups_label:
        parts.append(f"Skupina: {groups_label}")
    if theme:
        parts.append(str(theme))
    change_label = _format_change(change)
    if change_label:
        parts.append(change_label)
    return " | ".join(parts) if parts else None


# ---------------- Utility functions (mostly unchanged) ----------------


def _combine_local_utc(d: date, hhmm: str) -> datetime | None:
    """Combine a date with HH:MM string and return timezone-aware UTC datetime."""
    try:
        parts = str(hhmm).split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        local = datetime.combine(d, time(hour=h, minute=m))
        local = local.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(local)
    except Exception:
        return None


def _label_subject(subj: Any) -> str | None:
    if subj is None:
        return None
    return getattr(subj, "abbrev", None) or getattr(subj, "name", None)


def _label_teacher(teach: Any) -> str | None:
    if teach is None:
        return None
    return getattr(teach, "abbrev", None) or getattr(teach, "name", None)


def _label_room(room: Any) -> str | None:
    if room is None:
        return None
    return getattr(room, "abbrev", None) or getattr(room, "name", None)


def _label_groups(groups: Any) -> str | None:
    try:
        items = [
            getattr(g, "abbrev", None) or getattr(g, "name", None) or ""
            for g in (groups or [])
        ]
        items = [i for i in items if i]
        return ",".join(items) if items else None
    except Exception:
        return None


def _ensure_utc(val: date | datetime) -> datetime:
    """Ensure date/datetime is timezone-aware UTC. Dates are treated as local midnight."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return dt_util.as_utc(val)
        return val.astimezone(dt_util.UTC)
    local = datetime.combine(val, time.min).replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(local)


def _weeks_version_marker(weeks: Iterable[Any]) -> int:
    """Create a lightweight monotonic-ish marker from list of week objects."""
    marker = 0
    for idx, w in enumerate(weeks):
        marker ^= (id(w) & 0xFFFF_FFFF) ^ (idx << 8)
    return marker & 0xFFFF_FFFF
