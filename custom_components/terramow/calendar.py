"""Expose global mowing time slots through Home Assistant's calendar API."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.components.calendar.const import EVENT_END, EVENT_START
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DOMAIN, TerraMowBasicData
from .schedule import SCHEDULE_ADD, SCHEDULE_DELETE, SCHEDULE_MODIFY, TerraMowSchedule
from .schedule_history import CalendarMetadata
from .schedule_model import (
    DEVICE_WEEK_DAYS,
    GLOBAL_SCHEDULE_V2,
    GlobalTimeSlot,
    next_window,
    real_wall_time,
    wall_time,
)

SCAN_INTERVAL = timedelta(seconds=300)
SUMMARY = "Global mowing"
ICAL_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
UID_PATTERN = re.compile(r"global-(0|[1-9][0-9]*)")


def _recurrence_days(rule: Any, start: datetime) -> tuple[str, ...]:
    if not isinstance(rule, str):
        raise ServiceValidationError("Use FREQ=DAILY or FREQ=WEEKLY with INTERVAL=1")
    fields: dict[str, str] = {}
    for part in rule.upper().removeprefix("RRULE:").split(";"):
        pair = part.split("=")
        if len(pair) != 2 or pair[0] in fields:
            raise ServiceValidationError("Invalid recurrence rule")
        fields[pair[0]] = pair[1]
    if (
        fields.get("FREQ") not in ("DAILY", "WEEKLY")
        or fields.get("INTERVAL", "1") != "1"
        or set(fields) - {"FREQ", "BYDAY", "INTERVAL", "WKST"}
        or fields.get("WKST", "MO") not in ICAL_DAYS
    ):
        raise ServiceValidationError(
            "Only daily or weekly recurrence with INTERVAL=1 and no end is supported"
        )
    if fields["FREQ"] == "DAILY":
        if "BYDAY" in fields:
            raise ServiceValidationError("Daily recurrence cannot filter weekdays")
        return DEVICE_WEEK_DAYS
    days = fields.get("BYDAY", ICAL_DAYS[start.weekday()]).split(",")
    if (
        not days
        or any(day not in ICAL_DAYS for day in days)
        or ICAL_DAYS[start.weekday()] not in days
    ):
        raise ServiceValidationError(
            "BYDAY must contain valid weekdays including the start day"
        )
    return tuple(DEVICE_WEEK_DAYS[i] for i, day in enumerate(ICAL_DAYS) if day in days)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create exactly one calendar for each mower, without waiting for MQTT."""
    async_add_entities(
        [TerraMowCalendar(hass.data[DOMAIN][config_entry.entry_id], hass)]
    )


class TerraMowCalendar(CalendarEntity):
    """A global schedule is a series; its occurrences share the device ID."""

    _attr_has_entity_name = True
    _attr_translation_key = "global_schedule"
    _attr_icon = "mdi:calendar-clock"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
    )
    # Calendar polling also picks up edits from clients that do not send an ACK
    # to this MQTT connection. State alarms themselves use the cached snapshot.
    _attr_should_poll = True

    def __init__(self, basic_data: TerraMowBasicData, hass: HomeAssistant) -> None:
        self.basic_data = basic_data
        self.hass = hass

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.calendar"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)}
        )

    @property
    def _schedule(self) -> TerraMowSchedule:
        mower = self.basic_data.lawn_mower
        if mower is None:
            raise HomeAssistantError("TerraMow has not connected")
        return mower.schedule

    @property
    def available(self) -> bool:
        mower = self.basic_data.lawn_mower
        return mower is not None and mower.schedule.calendar_available

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"terramow_{self.basic_data.host}_schedule",
                self.async_write_ha_state,
            )
        )

    async def async_update(self) -> None:
        """Retry DP122 while connected, even before the first valid snapshot."""
        if self.basic_data.lawn_mower is not None and self._schedule.available:
            await self._schedule.async_refresh()

    def _events(self, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        if not self.available:
            return []
        start_date, end_date = dt_util.as_local(start_date), dt_util.as_local(end_date)
        if end_date <= start_date:
            return []
        result = []

        def append_event(
            uid: str,
            metadata: CalendarMetadata | None,
            start: datetime,
            end: datetime,
            rule: str | None = None,
        ) -> None:
            event = CalendarEvent(
                start=start.date() if metadata and metadata.all_day else start,
                end=end.date() + timedelta(days=1)
                if metadata and metadata.all_day
                else end,
                summary=metadata.summary if metadata else SUMMARY,
                location=metadata.location if metadata else None,
                description=metadata.description if metadata else None,
                uid=uid,
                # Omit occurrence IDs: edits target the entire device rule.
                rrule=rule,
            )
            if (
                event.start_datetime_local < end_date
                and event.end_datetime_local > start_date
            ):
                result.append(event)

        for item_id, item in self._schedule.items.items():
            if item.get("schedule_type") != GLOBAL_SCHEDULE_V2:
                continue
            slot = GlobalTimeSlot.from_payload(item["global_schedule_v2"])
            uid = f"global-{item_id}"
            metadata = self._schedule.history.metadata(item_id)

            if slot.run_once:
                # Keep the date observed while enabled, even after the device
                # disables the item. A GET has no execution date to reconstruct.
                occurrence = self._schedule.history.get(item_id)
                if occurrence is not None:
                    append_event(uid, metadata, occurrence.start, occurrence.end)
                continue
            rule = "FREQ=WEEKLY;BYDAY=" + ",".join(
                ICAL_DAYS[DEVICE_WEEK_DAYS.index(day)] for day in slot.week_days
            )
            if metadata and metadata.daily:
                rule = "FREQ=DAILY"
            day = start_date.date()
            while day <= end_date.date():
                if DEVICE_WEEK_DAYS[day.weekday()] in slot.week_days:
                    start, end = wall_time(day, slot.start), wall_time(day, slot.end)
                    if real_wall_time(start) and real_wall_time(end):
                        append_event(uid, metadata, start, end, rule)
                day += timedelta(days=1)
        return sorted(result, key=lambda event: (event.start_datetime_local, event.uid))

    @property
    def event(self) -> CalendarEvent | None:
        """Return a current or next occurrence without doing network I/O."""
        now = dt_util.now()
        events = self._events(now, now + timedelta(days=8))
        return events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Refresh actual device data, then expand only the requested range."""
        await self._schedule.async_refresh()
        if not self.available:
            raise HomeAssistantError(
                "Global calendar requires a valid time-slot schedule list"
            )
        return self._events(start_date, end_date)

    @staticmethod
    def _item_id(
        uid: str, recurrence_id: str | None, recurrence_range: str | None
    ) -> int:
        if recurrence_id or recurrence_range:
            raise ServiceValidationError(
                "The mower only supports the entire series; "
                "refresh the calendar and edit or delete the device schedule"
            )
        match = UID_PATTERN.fullmatch(uid)
        if match is None or int(match[1]) > 0x7FFFFFFF:
            raise ServiceValidationError("Invalid global schedule UID")
        return int(match[1])

    def _build_slot(
        self,
        event: dict[str, Any],
        current: GlobalTimeSlot | None,
        original_start: datetime | None = None,
        original_all_day: bool = False,
    ) -> GlobalTimeSlot:
        unsupported = set(event) - {
            EVENT_START,
            EVENT_END,
            "summary",
            "description",
            "location",
            "rrule",
        }
        if unsupported:
            raise ServiceValidationError(
                f"Unsupported calendar event fields: {sorted(unsupported)}"
            )
        for field in ("summary", "location", "description"):
            if field in event and not (
                isinstance(event[field], str)
                or (field != "summary" and event[field] is None)
            ):
                raise ServiceValidationError(f"Calendar {field} must be text")
        start, end = event.get(EVENT_START), event.get(EVENT_END)
        all_day = type(start) is date and type(end) is date
        if all_day:
            if end != start + timedelta(days=1):
                raise ServiceValidationError(
                    "Only single-day all-day events are supported; "
                    "choose one calendar day"
                )
            start, end = wall_time(start, 0), wall_time(start, 1439)
        if (
            not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is None
            or end.tzinfo is None
        ):
            raise ServiceValidationError(
                "Use timezone-aware times or a single-day all-day event"
            )
        start, end = dt_util.as_local(start), dt_util.as_local(end)
        if (
            start.second
            or start.microsecond
            or end.second
            or end.microsecond
            or start.date() != end.date()
            or end <= start
            or not real_wall_time(start)
            or not real_wall_time(end)
            or start.fold != 0
            or end.fold != 0
        ):
            raise ServiceValidationError(
                "Use whole minutes with end after start on the same local day"
            )
        rule = event.get("rrule")
        once = not rule
        days = (
            (DEVICE_WEEK_DAYS[start.weekday()],)
            if once
            else _recurrence_days(rule, start)
        )
        slot = GlobalTimeSlot(
            days,
            start.hour * 60 + start.minute,
            end.hour * 60 + end.minute,
            disabled=current.disabled if current else False,
            run_once=once,
            repeat_until_end_time=current.repeat_until_end_time if current else False,
        )
        unchanged = current == slot
        if (
            current is not None
            and current.run_once
            and current.disabled
            and (
                not unchanged
                or (
                    original_start is not None and start.date() != original_start.date()
                )
                or all_day != original_all_day
            )
        ):
            raise ServiceValidationError(
                "This one-time schedule is disabled; only its title, description "
                "and location can be changed. Create a new event to schedule mowing again"
            )
        if (
            once
            and unchanged
            and original_start is not None
            and start.date() != original_start.date()
        ):
            raise ServiceValidationError(
                "The mower stores weekdays, not dates; an unchanged one-time "
                "schedule must keep its recorded date"
            )
        local_only = unchanged and (not once or original_start is not None)
        if (
            once
            and not local_only
            and (
                slot.disabled
                or not self._schedule.enabled
                or days[0] in (self._schedule.disabled_week_days or ())
            )
        ):
            raise ServiceValidationError(
                "Enable the schedule and its weekday before saving a one-time event"
            )
        if current is None or (once and not local_only):
            # No DTSTART/date is stored. A delayed first occurrence would run
            # early; reject it rather than silently discarding the chosen date.
            now = dt_util.now()
            if once and start <= now:
                raise ServiceValidationError(
                    "A one-time event must start in the future; choose a future start time"
                )
            window = next_window(slot, now)
            # A recurring window already in progress can be saved, but the
            # mower will not catch up; subsequent matching windows can run.
            if window is None or window[0] != start:
                raise ServiceValidationError(
                    "The mower stores weekdays, not dates; choose the next matching occurrence"
                )
        return slot

    def _metadata(
        self, item_id: int, slot: GlobalTimeSlot, event: dict[str, Any]
    ) -> CalendarMetadata:
        previous = self._schedule.history.metadata(item_id)
        return CalendarMetadata(
            slot=slot,
            summary=event.get("summary", previous.summary if previous else SUMMARY),
            location=event.get("location", previous.location if previous else None),
            description=event.get(
                "description", previous.description if previous else None
            ),
            all_day=type(event[EVENT_START]) is date,
            daily=bool(event.get("rrule"))
            and "FREQ=DAILY"
            in event["rrule"].upper().removeprefix("RRULE:").split(";"),
        )

    async def async_create_event(self, **kwargs: Any) -> None:
        # The standard action handler forwards its routing fields as well.
        event = {
            key: value
            for key, value in kwargs.items()
            if key not in cv.ENTITY_SERVICE_FIELDS
        }
        await self._schedule.async_edit_global(
            SCHEDULE_ADD,
            build_slot=lambda _: self._build_slot(event, None),
            build_metadata=lambda item_id, slot: self._metadata(item_id, slot, event),
        )

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        item_id = self._item_id(uid, recurrence_id, recurrence_range)

        # HA supplies a complete event. Retain the original rule if an API
        # client omits it, so a recurring schedule never becomes one-time by accident.
        values = dict(event)

        def build(current: GlobalTimeSlot) -> GlobalTimeSlot:
            metadata = self._schedule.history.metadata(item_id)
            if "rrule" not in values and not current.run_once:
                values["rrule"] = "FREQ=WEEKLY;BYDAY=" + ",".join(
                    ICAL_DAYS[DEVICE_WEEK_DAYS.index(day)] for day in current.week_days
                )
                if metadata and metadata.daily:
                    values["rrule"] = "FREQ=DAILY"
            occurrence = self._schedule.history.get(item_id)
            return self._build_slot(
                values,
                current,
                occurrence.start if occurrence else None,
                metadata.all_day if metadata else False,
            )

        await self._schedule.async_edit_global(
            SCHEDULE_MODIFY,
            item_id,
            build,
            build_metadata=lambda item_id, slot: self._metadata(item_id, slot, values),
        )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        await self._schedule.async_edit_global(
            SCHEDULE_DELETE, self._item_id(uid, recurrence_id, recurrence_range)
        )
