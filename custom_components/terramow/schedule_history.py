"""Persist calendar presentation and run-once dates absent from DP122."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .schedule_model import (
    DEVICE_WEEK_DAYS,
    GLOBAL_SCHEDULE_V2,
    GlobalTimeSlot,
    next_window,
)

_LOGGER = logging.getLogger(__name__)


def history_store(hass: HomeAssistant, stable_id: str) -> Store[dict[str, Any]]:
    """Key history by the same stable mower identity as its calendar."""
    key = sha256(stable_id.encode()).hexdigest()
    return Store(hass, 1, f"terramow.schedule_history.{key}")


@dataclass(frozen=True)
class OneTimeOccurrence:
    """An observed planned window, not evidence that mowing actually happened."""

    slot: GlobalTimeSlot
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CalendarMetadata:
    """HA-only fields and the device configuration supporting display hints."""

    slot: GlobalTimeSlot
    summary: str = "Global mowing"
    location: str | None = None
    description: str | None = None
    all_day: bool = False
    daily: bool = False


class OneTimeScheduleHistory:
    """Retain calendar metadata through refresh, reconnect and HA restart."""

    def __init__(self, hass: HomeAssistant, stable_id: str) -> None:
        self._store = history_store(hass, stable_id)
        self._records: dict[int, OneTimeOccurrence] = {}
        self._metadata: dict[int, CalendarMetadata] = {}
        self._loaded = False
        self._changed = False
        self._load_lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Load once before accepting the first device snapshot."""
        async with self._load_lock:
            if self._loaded:
                return
            try:
                data = await self._store.async_load()
            except (HomeAssistantError, OSError) as err:
                _LOGGER.warning("Unable to restore calendar details: %s", err)
                data = None
            self._loaded = True
            if not isinstance(data, dict):
                return
            metadata = data.get("metadata", {})
            if isinstance(metadata, dict):
                for key, value in metadata.items():
                    try:
                        item_id = int(key)
                        if str(item_id) != key or not 0 <= item_id <= 0x7FFFFFFF:
                            continue
                        slot = GlobalTimeSlot.from_payload(value["slot"])
                        summary = value["summary"]
                        location = value.get("location")
                        description = value.get("description")
                        all_day = value.get("all_day", False)
                        daily = value.get("daily", False)
                        if (
                            not isinstance(summary, str)
                            or (location is not None and not isinstance(location, str))
                            or (
                                description is not None
                                and not isinstance(description, str)
                            )
                            or type(all_day) is not bool
                            or type(daily) is not bool
                        ):
                            continue
                        self._metadata[item_id] = CalendarMetadata(
                            slot, summary, location, description, all_day, daily
                        )
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
            records = data.get("items", {})
            if not isinstance(records, dict):
                return
            for key, value in records.items():
                try:
                    item_id = int(key)
                    slot = GlobalTimeSlot.from_payload(value["slot"])
                    start = dt_util.parse_datetime(value["start"])
                    end = dt_util.parse_datetime(value["end"])
                    if (
                        str(item_id) != key
                        or not 0 <= item_id <= 0x7FFFFFFF
                        or not slot.run_once
                        or start is None
                        or end is None
                        or start.tzinfo is None
                        or end.tzinfo is None
                        or end <= start
                    ):
                        continue
                    start, end = dt_util.as_local(start), dt_util.as_local(end)
                    if (
                        start.date() != end.date()
                        or DEVICE_WEEK_DAYS[start.weekday()] not in slot.week_days
                        or start.hour * 60 + start.minute != slot.start
                        or end.hour * 60 + end.minute != slot.end
                        or start.second
                        or start.microsecond
                        or end.second
                        or end.microsecond
                    ):
                        continue
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                self._records[item_id] = OneTimeOccurrence(slot, start, end)

    def sync(
        self,
        items: dict[int, dict[str, Any]],
        enabled: bool,
        disabled_days: frozenset[str],
    ) -> None:
        """Only a valid GET can change history; missing items were deleted.

        A disabled flag alone cannot reveal a past execution date. Keep a known
        window, but never invent one for an item first observed disabled. An
        observed re-enable or time/rule change starts a new planned occurrence.
        """
        records: dict[int, OneTimeOccurrence] = {}
        metadata: dict[int, CalendarMetadata] = {}
        for item_id, item in items.items():
            if item.get("schedule_type") != GLOBAL_SCHEDULE_V2:
                continue
            slot = GlobalTimeSlot.from_payload(item["global_schedule_v2"])
            if (previous_metadata := self._metadata.get(item_id)) is not None:
                # Never let stale local hints conceal a device-side change.
                metadata[item_id] = replace(
                    previous_metadata,
                    slot=slot,
                    all_day=previous_metadata.all_day
                    and slot.start == 0
                    and slot.end == 1439,
                    daily=previous_metadata.daily
                    and not slot.run_once
                    and set(slot.week_days) == set(DEVICE_WEEK_DAYS),
                )
            if not slot.run_once:
                continue
            previous = self._records.get(item_id)
            if (
                previous is not None
                and replace(previous.slot, disabled=False)
                == replace(slot, disabled=False)
                and not (previous.slot.disabled and not slot.disabled)
            ):
                records[item_id] = replace(previous, slot=slot)
            elif not slot.disabled and enabled:
                window = next_window(slot, dt_util.now(), disabled_days)
                if window is not None:
                    records[item_id] = OneTimeOccurrence(slot, *window)
        if records != self._records or metadata != self._metadata:
            self._records = records
            self._metadata = metadata
            self._changed = True
            self._store.async_delay_save(self._serialize, 1)

    async def async_flush(self) -> None:
        """Flush pending details before unload so an immediate reload sees them."""
        if self._changed:
            await self._async_save()
            self._changed = False

    async def _async_save(self) -> None:
        data = self._serialize()
        await self._store.async_save(data)
        # Store logs some disk errors instead of raising. Read the persisted
        # value back before reporting that the HA-only fields were saved.
        if await self._store.async_load() != data:
            raise HomeAssistantError("HA could not persist calendar details")

    def get(self, item_id: int) -> OneTimeOccurrence | None:
        return self._records.get(item_id)

    def metadata(self, item_id: int) -> CalendarMetadata | None:
        """Return only hints reconciled with the latest valid device snapshot."""
        return self._metadata.get(item_id)

    async def async_set_metadata(
        self, item_id: int, metadata: CalendarMetadata
    ) -> None:
        """Commit after device verification, or after a read for local-only edits."""
        previous = self._metadata.get(item_id)
        self._metadata[item_id] = metadata
        try:
            await self._async_save()
        except (HomeAssistantError, OSError) as err:
            if previous is None:
                self._metadata.pop(item_id, None)
            else:
                self._metadata[item_id] = previous
            raise HomeAssistantError(
                "Device schedule is confirmed, but HA could not save calendar details; "
                "refresh before retrying"
            ) from err
        self._changed = False

    def _serialize(self) -> dict[str, Any]:
        return {
            "items": {
                str(item_id): {
                    "slot": record.slot.as_payload(),
                    "start": record.start.isoformat(),
                    "end": record.end.isoformat(),
                }
                for item_id, record in self._records.items()
            },
            "metadata": {
                str(item_id): {
                    "slot": metadata.slot.as_payload(),
                    "summary": metadata.summary,
                    "location": metadata.location,
                    "description": metadata.description,
                    "all_day": metadata.all_day,
                    "daily": metadata.daily,
                }
                for item_id, metadata in self._metadata.items()
            },
        }
