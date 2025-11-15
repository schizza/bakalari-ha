"""Calendar platform for Bakalari - timetable per child."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import BakalariClient
from .const import CONF_CHILDREN
from .utils import ensure_children_dict, redact_child_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1
SCAN_INTERVAL = timedelta(minutes=120)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bakalari calendar entities from a config entry."""

    children = ensure_children_dict(entry.options.get(CONF_CHILDREN, {}))
    entities: list[BakalariTimetableCalendar] = []
    for child_id, child_info in children.items():
        _LOGGER.warning(
            "Setting up Bakalari timetable calendar for child %s with child_info: %s",
            child_id,
            redact_child_info(child_info),
        )
        entities.append(
            BakalariTimetableCalendar(
                hass,
                entry,
                child_id=child_id,
                child_name=child_info.get("name", child_id),
            )
        )

    async_add_entities(entities, update_before_add=True)


class BakalariTimetableCalendar(CalendarEntity):
    """Calendar entity representing child's school timetable."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: config_entries.ConfigEntry,
        child_id: str,
        child_name: str,
    ) -> None:
        """Initialize the calendar entity."""
        self._hass = hass
        self._entry = entry
        self._child_id = child_id
        self._child_name = child_name

        self._attr_name = f"Bakaláři rozvrh {child_name}"
        self._attr_unique_id = f"bakalari_{child_id}_timetable_calendar"
        self._attr_icon = "mdi:calendar-school"

        self._client = BakalariClient(hass, entry, child_id)

        self._events_cache: list[CalendarEvent] = []
        self._cache_ts: datetime | None = None
        self._cache_ttl = SCAN_INTERVAL

        self._next_event: CalendarEvent | None = None

    @property
    def event(self) -> CalendarEvent:
        """Return the next upcoming event."""
        # Try refresh cache lazily; HA may call event often.

        now = dt_util.utcnow()
        if self._cache_ts is None or (now - self._cache_ts) > self._cache_ttl:
            pass
        return self._next_event

    async def async_update(self) -> None:
        """Periodic update to refresh cached events and next event."""

        await self._ensure_events_loaded()
        self._compute_next_event()

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        await self._ensure_events_loaded()

        # Filter cached events by range
        start = dt_util.as_utc(start_date)
        end = dt_util.as_utc(end_date)

        in_range: list[CalendarEvent] = []
        for ev in self._events_cache:
            ev_start = _ensure_utc(ev.start)
            ev_end = _ensure_utc(ev.end) if ev.end else None

            # If no end, treat as instant event at start
            overlaps = False
            if ev_end:
                overlaps = (ev_start < end) and (ev_end > start)
            else:
                overlaps = start <= ev_start <= end

            if overlaps:
                in_range.append(ev)

        in_range.sort(key=lambda e: _ensure_utc(e.start))
        return in_range

    async def _ensure_events_loaded(self) -> None:
        """Load timetable and build the events cache if expired."""
        now = dt_util.utcnow()
        if (
            self._cache_ts
            and (now - self._cache_ts) <= self._cache_ttl
            and self._events_cache
        ):
            return

        _LOGGER.warning(
            "[calendar.ensure_events_loaded] unique_id=%s child_id=%s",
            self._attr_unique_id,
            self._child_id,
        )

        week = await self._client.async_get_timetable_actual(for_date=now.date())
        self._events_cache = self._convert_to_events(week) if week is not None else []
        self._cache_ts = now

        # Recompute next event after refresh
        self._compute_next_event()

    def _compute_next_event(self) -> None:
        """Compute the next upcoming event from cache."""
        now = dt_util.utcnow()
        upcoming = [ev for ev in self._events_cache if _ensure_utc(ev.start) >= now]
        upcoming.sort(key=lambda e: _ensure_utc(e.start))
        self._next_event = upcoming[0] if upcoming else None

    # Conversion helpers

    def _convert_to_events(self, raw: Any) -> list[CalendarEvent]:  # noqa: C901
        """Convert TimetableWeek to calendar events via entity resolution."""
        if raw is None:
            return []
        week = raw
        events: list[CalendarEvent] = []
        try:
            hours = getattr(week, "hours", {}) or {}
            days = getattr(week, "days", []) or []
            for day in days:
                date_part = getattr(day, "date", None)
                if date_part is None:
                    continue
                day_date = (
                    date_part.date() if isinstance(date_part, datetime) else date_part
                )
                atoms = getattr(day, "atoms", []) or []
                for atom in atoms:
                    hour_id = getattr(atom, "hour_id", None)
                    if hour_id is None:
                        continue
                    hour = hours.get(hour_id)
                    if hour is None:
                        continue
                    start = _combine_local_utc(
                        day_date, getattr(hour, "begin_time", "")
                    )
                    end = _combine_local_utc(day_date, getattr(hour, "end_time", ""))
                    if start is None:
                        continue
                    # resolve entities for labels
                    try:
                        subj, teach, room, groups = week.resolve(atom)  # type: ignore[attr-defined]
                    except Exception:
                        subj = teach = room = None
                        groups = []
                    summary = _label_subject(subj) or "Hodina"
                    description_parts: list[str] = []
                    teach_label = _label_teacher(teach)
                    if teach_label:
                        description_parts.append(f"Učitel: {teach_label}")
                    groups_label = _label_groups(groups)
                    if groups_label:
                        description_parts.append(f"Skupina: {groups_label}")
                    theme = getattr(atom, "theme", None)
                    if theme:
                        description_parts.append(str(theme))
                    change = getattr(atom, "change", None)
                    if change:
                        ch_type = getattr(change, "change_type", None) or ""
                        ch_desc = getattr(change, "description", None) or ""
                        ch_time = getattr(change, "time", None)
                        ch_label = f"Změna: {ch_type} | {ch_desc}".strip()
                        if ch_time:
                            ch_label += f" ({ch_time})"
                        description_parts.append(ch_label)
                    description = (
                        " | ".join([p for p in description_parts if p]) or None
                    )
                    location = _label_room(room)
                    events.append(
                        CalendarEvent(
                            start=start,
                            end=end,
                            summary=summary,
                            description=description,
                            location=location,
                        )
                    )
        except Exception as e:
            _LOGGER.error("Failed to build events from TimetableWeek: %s", e)
        events.sort(key=lambda e: _ensure_utc(e.start))
        return events

    def _lesson_to_event(self, item: dict[str, Any]) -> CalendarEvent:
        """Convert a single lesson-like dict into CalendarEvent."""
        # Resolve start/end
        start = _first_parse_datetime(item, ["start", "since", "from", "begin"])
        end = _first_parse_datetime(item, ["end", "till", "to", "finish"])

        if start is None:
            # Without start we cannot create an event
            return None

        # Try to build a summary/description/location from common keys
        summary = (
            _first_str(item, ["subject", "caption", "name", "title", "subject_name"])
            or "Lekce"
        )
        teacher = _first_str(item, ["teacher", "teacher_name", "tutor", "lector"])
        room = _first_str(item, ["room", "classroom", "room_name", "classroom_name"])
        group = _first_str(item, ["group", "class", "class_name", "group_name"])
        note = _first_str(item, ["note", "description", "desc", "info"])

        description_parts: list[str] = []
        if teacher:
            description_parts.append(f"Učitel: {teacher}")
        if group:
            description_parts.append(f"Třída/Skupina: {group}")
        if note:
            description_parts.append(str(note))
        description = " | ".join(description_parts) if description_parts else None

        location = room or None

        return CalendarEvent(
            start=start,
            end=end,
            summary=summary,
            description=description,
            location=location,
        )


# Utility functions


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


def _first_parse_datetime(item: dict[str, Any], keys: list[str]) -> datetime | None:
    """Try parsing the first datetime-like value by keys."""
    for k in keys:
        if k not in item:
            continue
        val = item.get(k)
        if isinstance(val, (int | float)):
            # Epoch seconds
            dt = dt_util.utc_from_timestamp(float(val))
            if dt:
                return dt
        if isinstance(val, str):
            # Try ISO or common formats via dt_util
            dt = dt_util.parse_datetime(val)
            if dt:
                # Ensure timezone-aware in UTC
                return dt_util.as_utc(dt)
    return None


def _first_str(item: dict[str, Any], keys: list[str]) -> str | None:
    """Return first non-empty string value for given keys."""
    for k in keys:
        if k in item and isinstance(item[k], str) and item[k].strip():
            return item[k].strip()
    return None


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt_util.as_utc(dt)
    return dt.astimezone(dt_util.UTC)
