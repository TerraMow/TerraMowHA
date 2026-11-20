"""Validate the device's global time-slot model without inventing calendar fields."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

GLOBAL_SCHEDULE_V2 = "SCHEDULE_TYPE_GLOBAL_V2"
DEVICE_WEEK_DAYS = tuple(
    f"WEEK_DAY_{day}"
    for day in (
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    )
)


def wall_time(day: date, minute: int) -> datetime:
    """Use the HA local zone, which must match the mower's local zone."""
    return datetime.combine(
        day, time(minute // 60, minute % 60), dt_util.DEFAULT_TIME_ZONE
    )


def real_wall_time(value: datetime) -> bool:
    """A nonexistent spring DST time cannot represent a device execution."""
    return dt_util.as_local(dt_util.as_utc(value)).replace(
        tzinfo=None
    ) == value.replace(tzinfo=None)


def next_window(
    slot: GlobalTimeSlot, now: datetime, disabled_days: frozenset[str] = frozenset()
) -> tuple[datetime, datetime] | None:
    """Find the next eligible window, including one currently in progress."""
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        week_day = DEVICE_WEEK_DAYS[day.weekday()]
        if week_day not in slot.week_days or week_day in disabled_days:
            continue
        start, end = wall_time(day, slot.start), wall_time(day, slot.end)
        if end > now and real_wall_time(start) and real_wall_time(end):
            return start, end
    return None


def _minute(value: Any) -> int:
    if not isinstance(value, dict):
        raise ValueError("Schedule time must be an object")
    hour, minute = value.get("hour", 0), value.get("minute", 0)
    if (
        type(hour) is not int
        or type(minute) is not int
        or not 0 <= hour <= 23
        or not 0 <= minute <= 59
    ):
        raise ValueError("Schedule time must be between 00:00 and 23:59")
    return hour * 60 + minute


@dataclass(frozen=True)
class GlobalTimeSlot:
    """Canonical fields used for rendering and readback comparison."""

    week_days: tuple[str, ...]
    start: int
    end: int
    disabled: bool = False
    run_once: bool = False
    repeat_until_end_time: bool = False

    @classmethod
    def from_payload(cls, value: Any) -> GlobalTimeSlot:
        """Accept protobuf's omitted scalar defaults; reject malformed schedules."""
        if not isinstance(value, dict) or not isinstance(
            value.get("basic_config"), dict
        ):
            raise ValueError("Missing global schedule basic_config")
        basic = value["basic_config"]
        days = basic.get("week_days")
        if (
            not isinstance(days, list)
            or not days
            or any(type(day) is not str or day not in DEVICE_WEEK_DAYS for day in days)
        ):
            raise ValueError("Schedule requires valid week_days")
        flags = (
            basic.get("disabled", False),
            basic.get("run_once", False),
            value.get("repeat_until_end_time", False),
        )
        if any(type(flag) is not bool for flag in flags):
            raise ValueError("Schedule flags must be boolean")
        start, end = (
            _minute(basic.get("start_time", {})),
            _minute(basic.get("end_time", {})),
        )
        if end <= start:
            raise ValueError("Schedule end must be after start on the same day")
        return cls(
            tuple(day for day in DEVICE_WEEK_DAYS if day in days), start, end, *flags
        )

    def as_payload(self) -> dict[str, Any]:
        """Build the GLOBAL_V2 parameter, including explicit boolean values."""
        return {
            "basic_config": {
                "week_days": list(self.week_days),
                "start_time": {"hour": self.start // 60, "minute": self.start % 60},
                "end_time": {"hour": self.end // 60, "minute": self.end % 60},
                "disabled": self.disabled,
                "run_once": self.run_once,
            },
            "repeat_until_end_time": self.repeat_until_end_time,
        }
