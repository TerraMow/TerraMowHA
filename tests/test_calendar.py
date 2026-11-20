"""Global calendar mapping, protocol transactions and failure consistency."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.components.calendar import CalendarEntityFeature
from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import PLATFORMS, TerraMowBasicData
from custom_components.terramow.calendar import (
    SUMMARY,
    TerraMowCalendar,
    async_setup_entry,
)
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import (
    Mission,
    MissionState,
    TerraMowLawnMowerEntity,
)
from custom_components.terramow.schedule import (
    SCHEDULE_ADD,
    SCHEDULE_DELETE,
    SCHEDULE_GET,
    SCHEDULE_MODIFY,
    TerraMowSchedule,
)
from custom_components.terramow.schedule_history import history_store
from custom_components.terramow.schedule_model import (
    DEVICE_WEEK_DAYS,
    GLOBAL_SCHEDULE_V2,
    GlobalTimeSlot,
)


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def set_now(monkeypatch, text: str) -> None:
    monkeypatch.setattr(
        dt_util,
        "now",
        lambda time_zone=None: instant(text).astimezone(
            time_zone or dt_util.DEFAULT_TIME_ZONE
        ),
    )


def item(
    item_id: int = 7,
    *,
    days: tuple[int, ...] = (2, 4),
    start: int = 540,
    end: int = 600,
    **flags,
) -> dict:
    return {
        "id": item_id,
        "schedule_type": GLOBAL_SCHEDULE_V2,
        "global_schedule_v2": GlobalTimeSlot(
            tuple(DEVICE_WEEK_DAYS[i] for i in days), start, end, **flags
        ).as_payload(),
    }


@pytest.fixture
def device(hass, monkeypatch):
    """In-memory device applies writes, then emits independent ACK and GET replies."""
    monkeypatch.setattr(
        dt_util,
        "now",
        lambda time_zone=None: instant("2026-11-17T08:00:00Z").astimezone(
            time_zone or dt_util.DEFAULT_TIME_ZONE
        ),
    )
    dt_util.set_default_time_zone(dt_util.get_time_zone("UTC"))
    mower = TerraMowLawnMowerEntity(
        TerraMowBasicData("192.0.2.69", "", identity_key="serial-334"), hass
    )
    mower.mqtt_connected = True
    mower.mqtt_client = MagicMock()
    mower.mqtt_client.is_connected.return_value = True
    mower._can_accept_command = MagicMock(return_value=True)
    state = SimpleNamespace(
        items=[],
        global_disabled=False,
        disabled_week_days=[],
        commands=[],
        published=asyncio.Queue(),
        code=0,
        apply=True,
        omit_defaults=False,
        concurrent=False,
        reads=0,
        drop=None,
        malformed=False,
        schedule_mode="SCHEDULE_MODE_TIME_SLOT",
    )

    def publish(topic: str, payload: str):
        assert topic == "data_point/122/app"
        command = json.loads(payload)
        state.commands.append(command)
        state.published.put_nowait((len(state.commands), command))
        cmd = command["cmd_type"]
        reply = {
            "cmd_type": cmd,
            "seq": command["seq"],
            "code": state.code if cmd != SCHEDULE_GET else 0,
        }
        if cmd == SCHEDULE_GET:
            state.reads += 1
            reply["schedule_list"] = {
                "items": deepcopy(state.items),
                "global_disabled": state.global_disabled,
                "disabled_week_days": state.disabled_week_days,
                "schedule_mode": state.schedule_mode,
            }
            if state.malformed:
                reply["schedule_list"]["items"] = "invalid"
        elif state.apply and state.code == 0:
            if cmd == SCHEDULE_ADD:
                new_id = (
                    max((entry.get("id", 0) for entry in state.items), default=0) + 1
                )
                state.items.append({"id": new_id, **deepcopy(command["add_param"])})
                if state.concurrent:
                    state.items.append(item(new_id + 1, start=660, end=720))
            elif cmd == SCHEDULE_MODIFY:
                updated = deepcopy(command["modify_param"])
                state.items = [
                    updated if entry["id"] == updated["id"] else entry
                    for entry in state.items
                ]
            elif cmd == SCHEDULE_DELETE:
                state.items = [
                    entry
                    for entry in state.items
                    if entry["id"] != command["delete_param"]["id"]
                ]
        if state.omit_defaults:
            reply.pop("code", None)
            if cmd == SCHEDULE_GET:
                reply.pop("cmd_type", None)
                for entry in reply["schedule_list"]["items"]:
                    if entry.get("schedule_type") == GLOBAL_SCHEDULE_V2:
                        config = entry["global_schedule_v2"]
                        for key in ("disabled", "run_once"):
                            if not config["basic_config"].get(key):
                                config["basic_config"].pop(key, None)
                        if not config.get("repeat_until_end_time"):
                            config.pop("repeat_until_end_time", None)
        if cmd != state.drop:
            hass.async_create_task(mower.schedule.on_reply(json.dumps(reply)))
        return SimpleNamespace(rc=0)

    mower.mqtt_client.publish.side_effect = publish
    return mower, TerraMowCalendar(mower.basic_data, hass), state


def new_event(**changes):
    return {
        "dtstart": instant("2026-11-18T09:00:00Z"),
        "dtend": instant("2026-11-18T10:00:00Z"),
        "summary": SUMMARY,
        "rrule": "FREQ=WEEKLY;BYDAY=WE,FR",
        **changes,
    }


async def wait_for_command(state, cmd_type, *, after=0):
    """Wait for an observed publish, including any preceding baseline GET."""
    async with asyncio.timeout(5):
        while True:
            index, command = await state.published.get()
            if index > after and command["cmd_type"] == cmd_type:
                return command


async def test_platform_and_identity(hass, device):
    mower, _, _ = device
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add = MagicMock()
    await async_setup_entry(hass, entry, add)
    assert Platform.CALENDAR in PLATFORMS
    assert len(add.call_args.args[0]) == 1
    calendar = add.call_args.args[0][0]
    assert isinstance(calendar, TerraMowCalendar)
    assert calendar.unique_id == "lawn_mower.terramow@serial-334.calendar"
    assert calendar.device_info["identifiers"] == {("TerraMowLawnMower", "serial-334")}
    assert calendar.supported_features == (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
    )
    assert not calendar.available
    await mower.schedule.async_refresh()
    assert calendar.available
    assert calendar.event is None
    mower.basic_data.lawn_mower = None
    assert not calendar.available
    await calendar.async_update()


@pytest.mark.parametrize("failure", ["timeout", "malformed"])
async def test_initial_get_failure_can_recover_by_polling(
    hass, device, monkeypatch, failure
):
    """No DP127 report is needed to retry the first read or enable the calendar."""
    mower, calendar, state = device
    monkeypatch.setattr(
        "custom_components.terramow.schedule.SCHEDULE_REPLY_TIMEOUT", 0.01
    )
    state.drop = SCHEDULE_GET if failure == "timeout" else None
    state.malformed = failure == "malformed"
    mower.schedule.request_refresh()
    assert mower.schedule._refresh_task is not None
    await mower.schedule._refresh_task
    await hass.async_block_till_done()
    assert not calendar.available
    assert mower.schedule.items is None
    state.drop = None
    state.malformed = False
    state.items = [item()]
    await calendar.async_update()
    assert calendar.available
    assert calendar.event.uid == "global-7"
    assert [command["cmd_type"] for command in state.commands] == [
        SCHEDULE_GET,
        SCHEDULE_GET,
    ]


@pytest.mark.parametrize(
    "reply,retained",
    [
        ({"seq": 1, "code": -1, "schedule_list": {}}, False),
        ({"seq": 1, "schedule_list": {}}, True),
        ({"seq": 1}, False),
        ({"seq": 1, "schedule_list": {"items": "invalid"}}, False),
        (
            {"seq": 1, "schedule_list": {"schedule_mode": "SCHEDULE_MODE_FREQUENCY"}},
            False,
        ),
    ],
)
async def test_initial_unusable_reply_does_not_enable_calendar(device, reply, retained):
    mower, calendar, _ = device
    await mower.schedule.on_reply(json.dumps(reply), retained=retained)
    assert not calendar.available


async def test_compatibility_report_does_not_gate_or_refresh_schedule(device):
    """DP127 remains available to other features but cannot change DP122 state."""
    mower, calendar, state = device
    await mower.on_compatibility_info('{"module":{"schedule":1}}')
    assert not calendar.available
    assert not state.commands
    await calendar.async_update()
    assert calendar.available
    for report in ("{}", '{"module":{"schedule":0}}'):
        await mower.on_compatibility_info(report)
        assert calendar.available
    assert len(state.commands) == 1


async def test_expand_range_and_cache_only_event(hass, device):
    mower, calendar, state = device
    state.items = [item(), {"id": 8, "schedule_type": "SCHEDULE_TYPE_SELECT_REGION"}]
    events = await calendar.async_get_events(
        hass, instant("2026-11-18T09:30:00Z"), instant("2026-11-25T09:00:00Z")
    )
    assert [event.start.day for event in events] == [18, 20]
    assert all(event.uid == "global-7" for event in events)
    assert events[0].recurrence_id is None
    assert all(event.description is None for event in events)
    assert events[0].rrule == "FREQ=WEEKLY;BYDAY=WE,FR"
    assert calendar.event.start == instant("2026-11-18T09:00:00Z")
    assert len(state.commands) == 1
    assert (
        calendar._events(
            instant("2026-11-18T10:00:00Z"), instant("2026-11-20T09:00:00Z")
        )
        == []
    )
    mower.schedule.reset_connection()
    assert not calendar.available
    assert calendar.event is None


async def test_local_timezone_and_dst(hass, device):
    mower, calendar, state = device
    dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/Berlin"))
    state.items = [item(days=(6,), start=150, end=210)]
    # 02:30 does not exist on spring-forward Sunday. No invented UTC time.
    events = await calendar.async_get_events(
        hass, instant("2026-03-22T00:00:00Z"), instant("2026-04-06T00:00:00Z")
    )
    assert [event.start.day for event in events] == [22, 5]
    assert [event.start.utcoffset() for event in events] == [
        timedelta(hours=1),
        timedelta(hours=2),
    ]
    assert all(event.start.hour == 2 for event in events)
    # Fall-back is represented once, using the first local occurrence.
    events = await calendar.async_get_events(
        hass, instant("2026-10-25T00:00:00Z"), instant("2026-10-26T00:00:00Z")
    )
    assert len(events) == 1
    assert events[0].start.fold == 0
    assert events[0].start.utcoffset() == timedelta(hours=2)


async def test_disabled_configuration_remains_visible(hass, device):
    mower, calendar, state = device
    state.items = [item(disabled=True, repeat_until_end_time=True)]
    await mower.schedule.async_refresh()
    mower.schedule.enabled = False
    mower.schedule.disabled_week_days = frozenset({DEVICE_WEEK_DAYS[2]})
    assert calendar.event is not None
    assert calendar.event.description is None
    assert calendar.event.uid == "global-7"
    assert (
        mower.schedule.items[7]["global_schedule_v2"]
        == state.items[0]["global_schedule_v2"]
    )


async def test_create_update_delete_verified_round_trip(hass, device):
    mower, calendar, state = device
    state.omit_defaults = True
    await calendar.async_create_event(**new_event())
    assert [entry["cmd_type"] for entry in state.commands] == [
        SCHEDULE_GET,
        SCHEDULE_ADD,
        SCHEDULE_GET,
    ]
    assert len({entry["seq"] for entry in state.commands}) == 3
    assert calendar.event.uid == "global-1"
    assert calendar.event.end.hour == 10
    await calendar.async_update_event(
        "global-1", new_event(dtend=instant("2026-11-18T11:00:00Z"))
    )
    assert calendar.event.end.hour == 11
    assert state.commands[-2]["modify_param"]["id"] == 1
    await calendar.async_delete_event("global-1")
    assert calendar.event is None
    assert mower.schedule.items == {}
    assert [entry["cmd_type"] for entry in state.commands[-3:]] == [
        SCHEDULE_GET,
        SCHEDULE_DELETE,
        SCHEDULE_GET,
    ]


async def test_update_preserves_device_fields_and_rule(device):
    mower, calendar, state = device
    state.items = [item(disabled=True, repeat_until_end_time=True)]
    state.items[0]["global_schedule_v2"]["future_field"] = {"opaque": 1}
    values = new_event(dtend=instant("2026-11-18T11:00:00Z"))
    values.pop("rrule")
    await calendar.async_update_event("global-7", values)
    updated = state.commands[-2]["modify_param"]["global_schedule_v2"]
    assert updated["basic_config"]["disabled"] is True
    assert updated["basic_config"]["run_once"] is False
    assert updated["repeat_until_end_time"] is True
    assert updated["future_field"] == {"opaque": 1}
    assert updated["basic_config"]["week_days"] == [
        DEVICE_WEEK_DAYS[2],
        DEVICE_WEEK_DAYS[4],
    ]


async def test_one_time_next_occurrence_only(hass, device):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    assert (
        state.commands[-2]["add_param"]["global_schedule_v2"]["basic_config"][
            "run_once"
        ]
        is True
    )
    events = await calendar.async_get_events(
        hass, instant("2026-11-17T00:00:00Z"), instant("2026-12-01T00:00:00Z")
    )
    assert len(events) == 1
    assert events[0].rrule is None
    assert events[0].recurrence_id is None
    assert events[0].start == instant("2026-11-18T09:00:00Z")
    state.items[0]["global_schedule_v2"]["basic_config"]["disabled"] = True
    await mower.schedule.async_refresh()
    assert calendar.event.start == events[0].start
    assert calendar.event.description is None
    assert mower.schedule.items[1]["global_schedule_v2"]["basic_config"]["disabled"]


@pytest.mark.parametrize("rule", ["FREQ=WEEKLY;BYDAY=WE,FR", "FREQ=DAILY"])
@pytest.mark.parametrize("all_day", [False, True])
async def test_create_recurring_window_already_started(
    device, monkeypatch, rule, all_day
):
    """A saved recurring window is not a request to start mowing immediately."""
    mower, calendar, state = device
    set_now(monkeypatch, "2026-11-18T09:30:00Z")
    values = new_event(rrule=rule)
    if all_day:
        values.update(dtstart=date(2026, 11, 18), dtend=date(2026, 11, 19))
    await calendar.async_create_event(**values)
    assert [command["cmd_type"] for command in state.commands] == [
        SCHEDULE_GET,
        SCHEDULE_ADD,
        SCHEDULE_GET,
    ]
    assert not state.items[0]["global_schedule_v2"]["basic_config"].get(
        "run_once", False
    )
    assert calendar.event.start == values["dtstart"]
    assert calendar.event.end == values["dtend"]
    assert calendar.event.all_day == all_day
    future = calendar._events(
        instant("2026-11-25T00:00:00Z"), instant("2026-11-26T00:00:00Z")
    )
    assert len(future) == 1
    assert future[0].uid == "global-1"
    assert mower.mission == Mission.MISSION_IDLE


@pytest.mark.parametrize("now", ["09:00:00", "09:30:00", "10:00:00"])
async def test_one_time_start_must_still_be_in_the_future(device, monkeypatch, now):
    _, calendar, state = device
    set_now(monkeypatch, f"2026-11-18T{now}Z")
    with pytest.raises(
        ServiceValidationError, match="one-time event must start in the future"
    ):
        await calendar.async_create_event(**new_event(rrule=None))
    assert [command["cmd_type"] for command in state.commands] == [SCHEDULE_GET]
    assert not state.items


async def test_enabled_one_time_update_cannot_move_start_into_past(device, monkeypatch):
    _, calendar, state = device
    await calendar.async_create_event(
        **new_event(rrule=None, dtstart=instant("2026-11-18T09:45:00Z"))
    )
    set_now(monkeypatch, "2026-11-18T09:30:00Z")
    before = deepcopy(state.items)
    state.commands.clear()
    with pytest.raises(
        ServiceValidationError, match="one-time event must start in the future"
    ):
        await calendar.async_update_event("global-1", new_event(rrule=None))
    assert state.items == before
    assert [command["cmd_type"] for command in state.commands] == [SCHEDULE_GET]


async def test_finished_recurring_window_is_not_shifted_to_next_week(
    device, monkeypatch
):
    _, calendar, state = device
    set_now(monkeypatch, "2026-11-18T10:00:00Z")
    with pytest.raises(ServiceValidationError, match="next matching occurrence"):
        await calendar.async_create_event(**new_event())
    assert [command["cmd_type"] for command in state.commands] == [SCHEDULE_GET]


@pytest.mark.parametrize("pause", [None, "global", "weekday"])
async def test_running_weekly_edit_only_updates_schedule(device, monkeypatch, pause):
    """Neither mission state nor pause switches freeze a weekly device rule."""
    mower, calendar, state = device
    state.items = [item()]
    state.global_disabled = pause == "global"
    state.disabled_week_days = [DEVICE_WEEK_DAYS[2]] if pause == "weekday" else []
    mower.mission = Mission.MISSION_SCHEDULE_GLOBAL_CLEAN
    mower.mission_state = MissionState.MISSION_STATE_RUNNING
    set_now(monkeypatch, "2026-11-18T09:30:00Z")
    await calendar.async_update_event(
        "global-7", new_event(dtend=instant("2026-11-18T11:00:00Z"))
    )
    assert [command["cmd_type"] for command in state.commands] == [
        SCHEDULE_GET,
        SCHEDULE_MODIFY,
        SCHEDULE_GET,
    ]
    assert mower.schedule.items == {7: item(end=660)}
    assert mower.mission == Mission.MISSION_SCHEDULE_GLOBAL_CLEAN
    assert mower.mission_state == MissionState.MISSION_STATE_RUNNING
    assert state.global_disabled == (pause == "global")
    assert state.disabled_week_days == (
        [DEVICE_WEEK_DAYS[2]] if pause == "weekday" else []
    )


@pytest.mark.parametrize("disabled", [True, False])
async def test_expired_one_time_stays_on_original_date(
    hass, device, monkeypatch, disabled
):
    """Disabled or overdue records never roll into a second weekly occurrence."""
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    set_now(monkeypatch, "2026-11-26T08:00:00Z")
    state.items[0]["global_schedule_v2"]["basic_config"]["disabled"] = disabled
    events = await calendar.async_get_events(
        hass, instant("2026-11-01T00:00:00Z"), instant("2026-12-01T00:00:00Z")
    )
    assert len(events) == 1
    assert events[0].start == instant("2026-11-18T09:00:00Z")
    assert events[0].end == instant("2026-11-18T10:00:00Z")
    assert events[0].rrule is None
    assert events[0].description is None
    assert (
        mower.schedule.items[1]["global_schedule_v2"]["basic_config"]["disabled"]
        is disabled
    )
    assert calendar.event is None  # Historical entries are not the next event.
    assert not await calendar.async_get_events(
        hass, instant("2026-11-25T00:00:00Z"), instant("2026-12-02T00:00:00Z")
    )
    # Exclusive range bounds still apply to retained history.
    assert not calendar._events(
        instant("2026-11-18T10:00:00Z"), instant("2026-11-19T00:00:00Z")
    )


async def test_one_time_history_survives_reconnect_and_reload(
    hass, device, monkeypatch
):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    await mower.schedule.history.async_flush()
    set_now(monkeypatch, "2026-11-26T08:00:00Z")
    state.items[0]["global_schedule_v2"]["basic_config"]["disabled"] = True
    mower.mqtt_connected = False
    mower.schedule.reset_connection()
    assert not calendar.available
    mower.mqtt_connected = True
    mower.schedule = TerraMowSchedule(mower)
    calendar = TerraMowCalendar(mower.basic_data, hass)
    assert not calendar.available  # Stored dates do not replace a fresh GET.
    events = await calendar.async_get_events(
        hass, instant("2026-11-01T00:00:00Z"), instant("2026-12-01T00:00:00Z")
    )
    assert len(events) == 1
    assert events[0].start == instant("2026-11-18T09:00:00Z")
    assert events[0].description is None
    assert mower.schedule.items[1]["global_schedule_v2"]["basic_config"]["disabled"]
    await mower.schedule.history.async_flush()
    mower.schedule = TerraMowSchedule(mower)
    await calendar.async_update()
    assert (
        calendar._events(
            instant("2026-11-18T00:00:00Z"), instant("2026-11-19T00:00:00Z")
        )[0].start
        == events[0].start
    )


@pytest.mark.parametrize("pause", ["global", "weekday"])
async def test_pause_keeps_known_one_time_date(hass, device, pause):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    state.global_disabled = pause == "global"
    state.disabled_week_days = [DEVICE_WEEK_DAYS[2]] if pause == "weekday" else []
    await calendar.async_update()
    assert calendar.event.start == instant("2026-11-18T09:00:00Z")
    await mower.schedule.history.async_flush()


async def test_unknown_disabled_one_time_has_no_fabricated_history(hass, device):
    mower, calendar, state = device
    state.items = [item(days=(2,), disabled=True, run_once=True)]
    events = await calendar.async_get_events(
        hass, instant("2026-11-01T00:00:00Z"), instant("2026-12-01T00:00:00Z")
    )
    assert calendar.available
    assert 7 in mower.schedule.items
    assert not events
    assert mower.schedule.history.get(7) is None


async def test_historical_one_time_delete_and_id_reuse(hass, device, monkeypatch):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    set_now(monkeypatch, "2026-11-19T08:00:00Z")
    state.items[0]["global_schedule_v2"]["basic_config"]["disabled"] = True
    await calendar.async_update()
    await calendar.async_delete_event("global-1", recurrence_range="")
    assert mower.schedule.history.get(1) is None
    assert not calendar._events(
        instant("2026-11-01T00:00:00Z"), instant("2026-12-01T00:00:00Z")
    )
    state.items = [item(1, days=(4,), start=660, end=720, run_once=True)]
    await calendar.async_update()
    assert calendar.event.start == instant("2026-11-20T11:00:00Z")


async def test_one_time_reenable_or_edit_reanchors_date(device, monkeypatch):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    set_now(monkeypatch, "2026-11-19T08:00:00Z")
    config = state.items[0]["global_schedule_v2"]["basic_config"]
    config["disabled"] = True
    await calendar.async_update()
    assert mower.schedule.history.get(1).start == instant("2026-11-18T09:00:00Z")
    config["disabled"] = False
    await calendar.async_update()
    assert calendar.event.start == instant("2026-11-25T09:00:00Z")
    config["start_time"]["hour"] = 8
    await calendar.async_update()
    assert calendar.event.start == instant("2026-11-25T08:00:00Z")


async def test_failed_get_does_not_erase_history(hass, device):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    before = mower.schedule.history.get(1)
    state.malformed = True
    with pytest.raises(HomeAssistantError, match="valid"):
        await calendar.async_update()
    assert mower.schedule.history.get(1) == before
    assert calendar.event.start == before.start


@pytest.mark.parametrize("failure", ["ack", "readback"])
async def test_unconfirmed_one_time_write_does_not_create_history(
    device, monkeypatch, failure
):
    mower, calendar, state = device
    monkeypatch.setattr(
        "custom_components.terramow.schedule.SCHEDULE_REPLY_TIMEOUT", 0.01
    )
    original = mower.mqtt_client.publish.side_effect

    def publish(topic, payload):
        if json.loads(payload)["cmd_type"] == SCHEDULE_ADD:
            state.drop = SCHEDULE_ADD if failure == "ack" else SCHEDULE_GET
        return original(topic, payload)

    mower.mqtt_client.publish.side_effect = publish
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await calendar.async_create_event(**new_event(rrule=None))
    assert len(state.items) == 1  # Device may have applied the unconfirmed write.
    assert mower.schedule.history.get(1) is None
    assert calendar.event is None


async def test_history_storage_isolated_and_removed_with_entry(hass, device):
    from custom_components.terramow import async_remove_entry
    from custom_components.terramow.const import CONF_IDENTITY_KEY

    mower, calendar, _ = device
    await calendar.async_create_event(**new_event(rrule=None))
    await mower.schedule.history.async_flush()
    store = history_store(hass, mower.basic_data.stable_id)
    assert "1" in (await store.async_load())["items"]
    assert await history_store(hass, "different-mower").async_load() is None
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: mower.host, CONF_IDENTITY_KEY: mower.basic_data.stable_id},
    )
    await async_remove_entry(hass, entry)
    assert await history_store(hass, mower.basic_data.stable_id).async_load() is None


async def test_corrupt_history_does_not_guess_disabled_dates(hass, device):
    mower, calendar, state = device
    slot = item(days=(2,), run_once=True, disabled=True)["global_schedule_v2"]
    await history_store(hass, mower.basic_data.stable_id).async_save(
        {
            "items": {
                "7": {"slot": slot, "start": "invalid", "end": "2026-11-18T10:00:00Z"},
                "8": {
                    "slot": slot,
                    "start": "2026-11-18T09:00:00",
                    "end": "2026-11-18T10:00:00",
                },
                "9": {
                    "slot": slot,
                    "start": "2026-11-18T11:00:00Z",
                    "end": "2026-11-18T10:00:00Z",
                },
                "10": None,
            }
        }
    )
    state.items = [
        item(i, days=(2,), run_once=True, disabled=True) for i in range(7, 11)
    ]
    await calendar.async_update()
    assert calendar.available
    assert not calendar._events(
        instant("2026-11-01T00:00:00Z"), instant("2026-12-01T00:00:00Z")
    )


@pytest.mark.parametrize("blocked", ["global", "weekday", "item"])
async def test_paused_one_time_event_is_not_silently_deferred(device, blocked):
    _, calendar, state = device
    state.global_disabled = blocked == "global"
    state.disabled_week_days = [DEVICE_WEEK_DAYS[2]] if blocked == "weekday" else []
    if blocked == "item":
        state.items = [item(disabled=True)]
    with pytest.raises(ServiceValidationError, match="Enable the schedule"):
        if blocked == "item":
            await calendar.async_update_event("global-7", new_event(rrule=None))
        else:
            await calendar.async_create_event(**new_event(rrule=None))
    assert all(command["cmd_type"] == SCHEDULE_GET for command in state.commands)


@pytest.mark.parametrize("actual_end", [600, 630])
async def test_mismatched_readback_displays_device_state(hass, device, actual_end):
    mower, calendar, state = device
    state.items = [item()]
    state.apply = False
    await mower.schedule.async_refresh()
    original = mower.mqtt_client.publish.side_effect

    def publish(topic, payload):
        info = original(topic, payload)
        if json.loads(payload)["cmd_type"] == SCHEDULE_MODIFY:
            # Another client may change the item while our edit is being verified.
            state.items = [item(end=actual_end)]
        return info

    mower.mqtt_client.publish.side_effect = publish
    snapshots = []

    @callback
    def capture_snapshot():
        snapshots.append(deepcopy(mower.schedule.items))

    unsubscribe = async_dispatcher_connect(
        hass, mower.schedule.signal, capture_snapshot
    )
    try:
        with pytest.raises(HomeAssistantError, match="readback differs"):
            await calendar.async_update_event(
                "global-7", new_event(dtend=instant("2026-11-18T11:00:00Z"))
            )
        await hass.async_block_till_done()
        actual = {7: item(end=actual_end)}
        assert snapshots == ([actual] if actual_end != 600 else [])
        assert mower.schedule.items == actual
        assert calendar.available
        assert calendar.event.end == instant("2026-11-18T00:00:00Z") + timedelta(
            minutes=actual_end
        )
        assert not mower.schedule._editing
    finally:
        unsubscribe()


@pytest.mark.parametrize(
    "changes",
    [
        {"dtstart": date(2026, 11, 18), "dtend": date(2026, 11, 20)},
        {"dtend": instant("2026-11-19T10:00:00Z")},
        {"dtend": instant("2026-11-18T08:00:00Z")},
        {"dtstart": instant("2026-11-18T09:00:01Z")},
        {"dtstart": datetime(2026, 11, 18, 9)},
        {"summary": 123},
        {"location": []},
        {"description": {}},
        {"rrule": "FREQ=MONTHLY"},
        {"rrule": "FREQ=YEARLY"},
        {"rrule": "FREQ=DAILY;INTERVAL=3"},
        {"rrule": "FREQ=DAILY;COUNT=3"},
        {"rrule": "FREQ=DAILY;BYDAY=WE"},
        {"rrule": "FREQ=WEEKLY;INTERVAL=2"},
        {"rrule": "FREQ=WEEKLY;UNTIL=20261201T000000Z"},
        {"rrule": "FREQ=WEEKLY;COUNT=2"},
        {"rrule": "FREQ=WEEKLY;BYDAY=1WE"},
        {"rrule": "FREQ=WEEKLY;BYDAY=MO"},
        {"rrule": "FREQ=WEEKLY;FREQ=WEEKLY"},
        {"rrule": "invalid"},
        {
            "dtstart": instant("2026-11-25T09:00:00Z"),
            "dtend": instant("2026-11-25T10:00:00Z"),
            "rrule": None,
        },
        {
            "dtstart": instant("2026-11-25T09:00:00Z"),
            "dtend": instant("2026-11-25T10:00:00Z"),
        },
    ],
)
async def test_unsupported_event_never_writes(device, changes):
    _, calendar, state = device
    with pytest.raises(ServiceValidationError):
        await calendar.async_create_event(**new_event(**changes))
    assert all(entry["cmd_type"] == SCHEDULE_GET for entry in state.commands)


@pytest.mark.parametrize("method", ["async_update_event", "async_delete_event"])
@pytest.mark.parametrize(
    "recurrence",
    [{"recurrence_id": "2026-11-18T09:00:00Z"}, {"recurrence_range": "THISANDFUTURE"}],
)
async def test_occurrence_edits_never_modify_entire_series(device, method, recurrence):
    _, calendar, state = device
    kwargs = {"event": new_event()} if method == "async_update_event" else {}
    with pytest.raises(ServiceValidationError, match="entire series"):
        await getattr(calendar, method)("global-7", **kwargs, **recurrence)
    assert state.commands == []


@pytest.mark.parametrize("method", ["async_update_event", "async_delete_event"])
@pytest.mark.parametrize(
    "recurrence_id,recurrence_range", [(None, None), (None, ""), ("", "")]
)
async def test_calendar_ui_edits_device_rule(
    device, method, recurrence_id, recurrence_range
):
    """HA sends empty recurrence fields for events without an occurrence ID."""
    mower, calendar, state = device
    state.items = [item(), item(8, days=(0,), start=660, end=720)]
    await mower.schedule.async_refresh()
    events = calendar._events(
        instant("2026-11-18T00:00:00Z"), instant("2026-11-21T00:00:00Z")
    )
    assert len(events) == 2
    assert all(
        event.uid == "global-7" and event.recurrence_id is None for event in events
    )
    assert all(event.rrule == "FREQ=WEEKLY;BYDAY=WE,FR" for event in events)
    state.commands.clear()
    kwargs = (
        {"event": new_event(dtend=instant("2026-11-18T11:00:00Z"))}
        if method == "async_update_event"
        else {}
    )
    await getattr(calendar, method)(
        events[0].uid,
        recurrence_id=recurrence_id,
        recurrence_range=recurrence_range,
        **kwargs,
    )
    assert state.items[-1] == item(8, days=(0,), start=660, end=720)
    if method == "async_update_event":
        assert state.items[0] == item(end=660)
        expected = SCHEDULE_MODIFY
    else:
        assert len(state.items) == 1
        expected = SCHEDULE_DELETE
    assert [entry["cmd_type"] for entry in state.commands] == [
        SCHEDULE_GET,
        expected,
        SCHEDULE_GET,
    ]


@pytest.mark.parametrize(
    "uid", ["7", "global--1", "global-01", "global-2147483648", "zone-7"]
)
async def test_uid_validation(device, uid):
    _, calendar, state = device
    with pytest.raises(ServiceValidationError, match="UID"):
        await calendar.async_delete_event(uid)
    assert not state.commands


async def test_frequency_mode_is_unavailable(device):
    mower, calendar, state = device
    state.schedule_mode = "SCHEDULE_MODE_FREQUENCY"
    await mower.schedule.async_refresh()
    assert not calendar.available
    with pytest.raises(HomeAssistantError, match="time-slot"):
        await calendar.async_create_event(**new_event())
    assert all(command["cmd_type"] == SCHEDULE_GET for command in state.commands)


async def test_error_and_readback_disagreement(device):
    mower, calendar, state = device
    state.code = -1
    with pytest.raises(HomeAssistantError, match="code=-1"):
        await calendar.async_create_event(**new_event())
    assert len(state.commands) == 2
    assert calendar.available
    assert mower.schedule.items == {}
    state.code = 0
    state.apply = False
    with pytest.raises(HomeAssistantError, match="identify"):
        await calendar.async_create_event(**new_event())
    assert calendar.available
    assert mower.schedule.items == {}
    state.items = [item()]
    with pytest.raises(HomeAssistantError, match="differs"):
        await calendar.async_update_event(
            "global-7", new_event(dtend=instant("2026-11-18T11:00:00Z"))
        )
    with pytest.raises(HomeAssistantError, match="still contains"):
        await calendar.async_delete_event("global-7")
    assert calendar.available
    assert mower.schedule.items == {7: item()}
    assert calendar.event.end.hour == 10


async def test_ambiguous_concurrent_create_is_not_success(device):
    _, calendar, state = device
    state.concurrent = True
    with pytest.raises(HomeAssistantError, match="unambiguously"):
        await calendar.async_create_event(**new_event())
    assert calendar.available
    assert calendar._schedule.items == {entry["id"]: entry for entry in state.items}
    assert (
        len(state.items) == 2
    )  # No unsafe retry or rollback deleting another client's item.


async def test_missing_or_unrelated_item_is_not_modified(device):
    _, calendar, state = device
    state.items = [{"id": 7, "schedule_type": "SCHEDULE_TYPE_SELECT_REGION"}]
    with pytest.raises(ServiceValidationError, match="no longer exists"):
        await calendar.async_delete_event("global-7")
    assert all(entry["cmd_type"] == SCHEDULE_GET for entry in state.commands)


async def test_timeout_disconnect_and_publish_failure(device, monkeypatch):
    mower, calendar, state = device
    monkeypatch.setattr(
        "custom_components.terramow.schedule.SCHEDULE_REPLY_TIMEOUT", 0.01
    )
    state.drop = SCHEDULE_ADD
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await calendar.async_create_event(**new_event())
    assert calendar.available
    assert mower.schedule.items == {}
    assert calendar.event is None
    assert len(state.items) == 1  # Applied, but ACK lost: HA must report failure.
    assert len(state.commands) == 2
    await mower.schedule.async_refresh()
    assert calendar.event is not None
    mower.mqtt_client.publish.side_effect = None
    mower.mqtt_client.publish.return_value = SimpleNamespace(rc=1)
    with pytest.raises(HomeAssistantError, match="could not be sent"):
        await calendar.async_delete_event("global-1")
    assert calendar.available
    assert calendar.event.uid == "global-1"


async def test_ack_and_readback_must_each_match_request(hass, device):
    mower, calendar, state = device
    state.drop = SCHEDULE_ADD
    task = asyncio.create_task(calendar.async_create_event(**new_event()))
    command = await wait_for_command(state, SCHEDULE_ADD)
    assert calendar.event is None  # No optimistic event from the sent command.
    pending = mower.schedule._pending
    assert pending is not None
    for reply, retained in (
        ({"cmd_type": SCHEDULE_ADD, "seq": command["seq"]}, True),
        ({"cmd_type": SCHEDULE_ADD, "seq": command["seq"] + 1}, False),
        ({"cmd_type": SCHEDULE_GET, "seq": command["seq"]}, False),
    ):
        await mower.schedule.on_reply(json.dumps(reply), retained=retained)
        assert not pending[2].done()
        assert not task.done()
    await mower.schedule.on_reply(
        json.dumps({"cmd_type": SCHEDULE_ADD, "seq": command["seq"]})
    )
    await task
    await hass.async_block_till_done()
    assert calendar.event is not None
    assert state.commands[-1]["cmd_type"] == SCHEDULE_GET


async def test_invalid_snapshot_and_duplicate_ids(hass, device):
    mower, calendar, state = device
    for entries in ([item(), item()], [{"id": True}], [item(start=700, end=600)]):
        state.items = entries
        with pytest.raises(HomeAssistantError, match="valid"):
            await mower.schedule.async_refresh()
        assert not calendar.available
        with pytest.raises(HomeAssistantError, match="valid"):
            await calendar.async_get_events(
                hass, instant("2026-11-17T00:00:00Z"), instant("2026-11-24T00:00:00Z")
            )


async def test_weekly_create_omits_unused_optional_fields(device):
    _, calendar, state = device
    await calendar.async_create_event(**new_event())
    payload = state.commands[-2]["add_param"]["global_schedule_v2"]
    assert "repeat_until_end_time" not in payload
    assert "run_once" not in payload["basic_config"]
    assert calendar.event.rrule == "FREQ=WEEKLY;BYDAY=WE,FR"


async def test_readback_timeout_does_not_save(device, monkeypatch):
    mower, calendar, state = device
    monkeypatch.setattr(
        "custom_components.terramow.schedule.SCHEDULE_REPLY_TIMEOUT", 0.01
    )
    original = mower.mqtt_client.publish.side_effect

    def publish(topic, payload):
        if json.loads(payload)["cmd_type"] == SCHEDULE_ADD:
            state.drop = SCHEDULE_GET
        return original(topic, payload)

    mower.mqtt_client.publish.side_effect = publish
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await calendar.async_create_event(**new_event())
    assert [entry["cmd_type"] for entry in state.commands] == [
        SCHEDULE_GET,
        SCHEDULE_ADD,
        SCHEDULE_GET,
    ]
    assert calendar.available
    assert mower.schedule.items == {}
    assert calendar.event is None
    assert len(state.items) == 1


@pytest.mark.parametrize("phase", ["refresh", "baseline", "ack", "readback"])
@pytest.mark.parametrize("failure", ["timeout", "malformed", "rejected", "publish"])
async def test_read_and_edit_failures_preserve_cached_events(
    hass, device, monkeypatch, phase, failure
):
    mower, calendar, state = device
    state.items = [item()]
    await mower.schedule.async_refresh()
    cached = deepcopy(mower.schedule.items)
    monkeypatch.setattr(
        "custom_components.terramow.schedule.SCHEDULE_REPLY_TIMEOUT", 0.01
    )
    original = mower.mqtt_client.publish.side_effect
    reads = 0

    def publish(topic, payload):
        nonlocal reads
        command = json.loads(payload)
        cmd = command["cmd_type"]
        if cmd == SCHEDULE_GET:
            reads += 1
        target = (
            (phase in ("refresh", "baseline") and reads == 1)
            or (phase == "ack" and cmd == SCHEDULE_MODIFY)
            or (phase == "readback" and reads == 2)
        )
        if not target:
            return original(topic, payload)
        if failure == "publish":
            return SimpleNamespace(rc=1)
        if failure == "malformed":
            hass.async_create_task(mower.schedule.on_reply("not json"))
        elif failure == "rejected":
            hass.async_create_task(
                mower.schedule.on_reply(
                    json.dumps({"seq": command["seq"], "cmd_type": cmd, "code": -1})
                )
            )
        return SimpleNamespace(rc=0)

    mower.mqtt_client.publish.side_effect = publish
    message = {
        "timeout": "did not confirm",
        "malformed": "did not confirm",
        "rejected": "code=-1",
        "publish": "could not be sent",
    }[failure]
    with pytest.raises(HomeAssistantError, match=message):
        if phase == "refresh":
            await mower.schedule.async_refresh()
        else:
            await calendar.async_update_event(
                "global-7", new_event(dtend=instant("2026-11-18T11:00:00Z"))
            )
    assert mower.schedule.items == cached
    assert calendar.available
    assert calendar.event.end == instant("2026-11-18T10:00:00Z")
    assert mower.schedule._pending is None
    assert not mower.schedule._editing


@pytest.mark.parametrize(
    "entries",
    ["invalid", [None], [item(), item()], [{"id": True}], [item(start=700, end=600)]],
)
@pytest.mark.parametrize("phase", ["refresh", "baseline", "readback"])
async def test_malformed_item_list_preserves_valid_snapshot(device, entries, phase):
    mower, calendar, state = device
    state.items = [item()]
    await mower.schedule.async_refresh()
    original = mower.mqtt_client.publish.side_effect

    def publish(topic, payload):
        if json.loads(payload)["cmd_type"] == SCHEDULE_MODIFY:
            state.items = deepcopy(entries)
        return original(topic, payload)

    if phase == "readback":
        state.apply = False
        mower.mqtt_client.publish.side_effect = publish
    else:
        state.items = deepcopy(entries)
    with pytest.raises(HomeAssistantError, match="valid"):
        if phase == "refresh":
            await mower.schedule.async_refresh()
        else:
            await calendar.async_update_event(
                "global-7", new_event(dtend=instant("2026-11-18T11:00:00Z"))
            )
    assert mower.schedule.items == {7: item()}
    assert calendar.available
    assert calendar.event.end == instant("2026-11-18T10:00:00Z")


async def test_disconnect_cancels_pending_edit(device):
    mower, calendar, state = device
    state.drop = SCHEDULE_ADD
    task = asyncio.create_task(calendar.async_create_event(**new_event()))
    await wait_for_command(state, SCHEDULE_ADD)
    assert mower.schedule._pending is not None
    assert mower.schedule._pending[1] == SCHEDULE_ADD
    mower.mqtt_connected = False
    mower.schedule.reset_connection()
    with pytest.raises(HomeAssistantError, match="disconnected"):
        await task
    assert not calendar.available
    assert mower.schedule._pending is None


async def test_get_mismatch_cannot_replace_current_snapshot(device):
    mower, calendar, state = device
    state.items = [item()]
    await mower.schedule.async_refresh()
    state.drop = SCHEDULE_GET
    sent = len(state.commands)
    task = asyncio.create_task(mower.schedule.async_refresh())
    command = await wait_for_command(state, SCHEDULE_GET, after=sent)
    seq = command["seq"]
    await mower.schedule.on_reply(json.dumps({"seq": seq + 1, "schedule_list": {}}))
    assert calendar.event.uid == "global-7"
    assert mower.schedule._pending is not None
    assert not mower.schedule._pending[2].done()
    assert not task.done()
    await mower.schedule.on_reply(json.dumps({"seq": seq, "schedule_list": {}}))
    await task
    assert calendar.event is None


async def test_duplicate_matching_content_under_new_id_is_ambiguous(device):
    mower, calendar, state = device
    original = mower.mqtt_client.publish.side_effect

    def publish(topic, payload):
        info = original(topic, payload)
        if json.loads(payload)["cmd_type"] == SCHEDULE_ADD:
            state.items.append({**deepcopy(state.items[-1]), "id": 2})
        return info

    mower.mqtt_client.publish.side_effect = publish
    with pytest.raises(HomeAssistantError, match="unambiguously"):
        await calendar.async_create_event(**new_event())
    assert calendar.available
    assert mower.schedule.items == {entry["id"]: entry for entry in state.items}


async def test_standard_calendar_service_and_lifecycle(
    hass, device, monkeypatch, hass_ws_client
):
    """Exercise the real HA calendar platform, service conversion and listeners."""
    from homeassistant.const import Platform
    from homeassistant.helpers import entity_registry as er
    from homeassistant.setup import async_setup_component

    import custom_components.terramow as integration

    mower, calendar, state = device
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    monkeypatch.setattr(integration, "PLATFORMS", [Platform.CALENDAR])
    monkeypatch.setattr(
        integration, "TerraMowBasicData", lambda **kwargs: mower.basic_data
    )
    assert await async_setup_component(hass, "calendar", {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "calendar", DOMAIN, calendar.unique_id
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "unavailable"
    await mower.schedule.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": entity_id,
            "summary": SUMMARY,
            "start_date_time": "2026-11-18T09:00:00+00:00",
            "end_date_time": "2026-11-18T10:00:00+00:00",
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(state.items) == 1
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": "2026-11-18T00:00:00+00:00",
            "end_date_time": "2026-11-19T00:00:00+00:00",
        },
        blocking=True,
        return_response=True,
    )
    assert response[entity_id]["events"][0]["summary"] == SUMMARY
    assert not response[entity_id]["events"][0].get("description")

    # Exercise the actual WebSocket schema with the frontend's empty recurrence
    # fields, and verify an explicit occurrence still cannot delete a whole rule.
    state.items = [item(), item(8, days=(0,), start=660, end=720)]
    await mower.schedule.async_refresh()
    state.commands.clear()
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "calendar/event/delete",
            "entity_id": entity_id,
            "uid": "global-7",
            "recurrence_id": "2026-11-18T09:00:00+00:00",
            "recurrence_range": "",
        }
    )
    result = await client.receive_json()
    assert not result["success"]
    assert not state.commands
    await client.send_json(
        {
            "id": 2,
            "type": "calendar/event/update",
            "entity_id": entity_id,
            "uid": "global-7",
            "recurrence_id": "",
            "recurrence_range": "",
            "event": {
                **new_event(),
                "dtstart": "2026-11-18T09:00:00+00:00",
                "dtend": "2026-11-18T11:00:00+00:00",
            },
        }
    )
    result = await client.receive_json()
    assert result["success"], result
    assert state.items[0] == item(end=660)
    await client.send_json(
        {
            "id": 3,
            "type": "calendar/event/delete",
            "entity_id": entity_id,
            "uid": "global-7",
            "recurrence_id": "",
            "recurrence_range": "",
        }
    )
    result = await client.receive_json()
    assert result["success"], result
    assert state.items == [item(8, days=(0,), start=660, end=720)]
    assert [entry["cmd_type"] for entry in state.commands] == [
        SCHEDULE_GET,
        SCHEDULE_MODIFY,
        SCHEDULE_GET,
        SCHEDULE_GET,
        SCHEDULE_DELETE,
        SCHEDULE_GET,
    ]
    # Native frontend sends ISO dates for all-day events. HA must convert them
    # to date objects and return the same presentation on readback.
    await client.send_json(
        {
            "id": 4,
            "type": "calendar/event/create",
            "entity_id": entity_id,
            "event": {
                "dtstart": "2026-11-18",
                "dtend": "2026-11-19",
                "summary": "All day lawn",
                "location": "Garden",
                "description": "Local notes",
                "rrule": "FREQ=WEEKLY;BYDAY=WE,FR;INTERVAL=1",
            },
        }
    )
    result = await client.receive_json()
    assert result["success"], result
    new_id = max(entry["id"] for entry in state.items)
    assert mower.schedule.history.metadata(new_id).all_day
    assert any(
        e.all_day and e.summary == "All day lawn"
        for e in calendar._events(
            instant("2026-11-18T00:00:00Z"), instant("2026-11-19T00:00:00Z")
        )
    )
    await client.send_json(
        {
            "id": 5,
            "type": "calendar/event/update",
            "entity_id": entity_id,
            "uid": f"global-{new_id}",
            "recurrence_id": "",
            "recurrence_range": "",
            "event": {
                "dtstart": "2026-11-18",
                "dtend": "2026-11-19",
                "summary": "All day daily",
                "rrule": "FREQ=DAILY;INTERVAL=1",
            },
        }
    )
    result = await client.receive_json()
    assert result["success"], result
    assert mower.schedule.history.metadata(new_id).daily
    assert mower.schedule.history.metadata(new_id).all_day
    assert mower.schedule.history.metadata(new_id).description == "Local notes"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unavailable"
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    # Removed entities must not receive state writes from the shared manager.
    async_dispatcher_send(hass, mower.schedule.signal)
    await hass.async_block_till_done()


@pytest.mark.parametrize("all_day", [False, True])
async def test_daily_metadata_survives_reload_and_stays_out_of_mqtt(
    hass, device, all_day
):
    mower, calendar, state = device
    # DAILY starts on the next day only while today's window is already over.
    if all_day:
        from unittest.mock import patch

        now = instant("2026-11-17T23:59:30Z")
        with patch.object(dt_util, "now", return_value=now):
            await calendar.async_create_event(
                **new_event(
                    dtstart=date(2026, 11, 18),
                    dtend=date(2026, 11, 19),
                    summary="Front lawn",
                    location="Home",
                    description="Keep gate open",
                    rrule="FREQ=DAILY;INTERVAL=1",
                )
            )
    else:
        await calendar.async_create_event(
            **new_event(
                dtstart=instant("2026-11-17T09:00:00Z"),
                dtend=instant("2026-11-17T10:00:00Z"),
                summary="Front lawn",
                location="Home",
                description="Keep gate open",
                rrule="FREQ=DAILY;INTERVAL=1",
            )
        )
    assert [c["cmd_type"] for c in state.commands] == [
        SCHEDULE_GET,
        SCHEDULE_ADD,
        SCHEDULE_GET,
    ]
    config = state.items[0]["global_schedule_v2"]["basic_config"]
    assert config["week_days"] == list(DEVICE_WEEK_DAYS)
    assert not config.get("run_once", False)
    payload = json.dumps(state.commands)
    assert all(
        value not in payload for value in ("Front lawn", "Home", "Keep gate open")
    )
    mower.schedule = TerraMowSchedule(mower)
    assert not calendar.available
    events = await calendar.async_get_events(
        hass, instant("2026-11-18T00:00:00Z"), instant("2026-11-21T00:00:00Z")
    )
    assert len(events) == 3
    assert all(
        e.summary == "Front lawn"
        and e.location == "Home"
        and e.description == "Keep gate open"
        and e.rrule == "FREQ=DAILY"
        and e.all_day == all_day
        for e in events
    )
    if all_day:
        assert events[0].start == date(2026, 11, 18)
        assert events[0].end == date(2026, 11, 19)
        assert config["start_time"] == {"hour": 0, "minute": 0}
        assert config["end_time"] == {"hour": 23, "minute": 59}


async def test_all_day_once_mixed_sorting_and_exclusive_midnight(device):
    mower, calendar, state = device
    await calendar.async_create_event(
        **new_event(dtstart=date(2026, 11, 18), dtend=date(2026, 11, 19), rrule=None)
    )
    state.items.append(item(7))
    await calendar.async_update()
    events = calendar._events(
        instant("2026-11-18T00:00:00Z"), instant("2026-11-19T00:00:00Z")
    )
    assert len(events) == 2
    assert events[0].all_day and not events[1].all_day
    assert calendar.event.start == date(2026, 11, 18)
    # All-day UI ends at midnight although the device window ends at 23:59.
    assert (
        len(
            calendar._events(
                instant("2026-11-18T23:59:30Z"), instant("2026-11-19T00:00:00Z")
            )
        )
        == 1
    )
    assert not calendar._events(
        instant("2026-11-19T00:00:00Z"), instant("2026-11-20T00:00:00Z")
    )
    config = state.items[0]["global_schedule_v2"]["basic_config"]
    assert config["run_once"]


async def test_today_all_day_and_mixed_date_types_are_not_silently_shifted(device):
    _, calendar, state = device
    for start, end in (
        (date(2026, 11, 17), date(2026, 11, 18)),
        (date(2026, 11, 18), instant("2026-11-19T00:00:00Z")),
        (instant("2026-11-18T00:00:00Z"), date(2026, 11, 19)),
    ):
        with pytest.raises(ServiceValidationError):
            await calendar.async_create_event(
                **new_event(dtstart=start, dtend=end, rrule=None)
            )
    assert all(c["cmd_type"] == SCHEDULE_GET for c in state.commands)


async def test_external_device_changes_override_display_hints_but_keep_text(device):
    mower, calendar, state = device
    await calendar.async_create_event(
        **new_event(
            dtstart=date(2026, 11, 18),
            dtend=date(2026, 11, 19),
            summary="Saved locally",
            location="Garden",
            description="Notes",
        )
    )
    assert calendar.event.all_day
    state.items = [item(1, days=(3,), start=540, end=600)]
    await calendar.async_update()
    event = calendar.event
    assert not event.all_day
    assert event.start == instant("2026-11-19T09:00:00Z")
    assert event.rrule == "FREQ=WEEKLY;BYDAY=TH"
    assert (event.summary, event.location, event.description) == (
        "Saved locally",
        "Garden",
        "Notes",
    )
    # Once invalidated, returning to midnight does not resurrect an old UI choice.
    state.items = [item(1, days=(3,), start=0, end=1439)]
    await calendar.async_update()
    assert not calendar.event.all_day
    state.items = [item(1, days=(2,), start=540, end=600)]
    await calendar.async_update_event(
        "global-1",
        new_event(
            dtstart=instant("2026-11-17T09:00:00Z"),
            dtend=instant("2026-11-17T10:00:00Z"),
            rrule="FREQ=DAILY",
        ),
    )
    assert calendar.event.rrule == "FREQ=DAILY"
    state.items = [item(1, days=(0, 2))]
    await calendar.async_update()
    assert calendar.event.rrule == "FREQ=WEEKLY;BYDAY=MO,WE"


@pytest.mark.parametrize("external", [False, True, "changed_type"])
async def test_delete_cleans_metadata_and_confirmed_id_reuse_falls_back(
    hass, device, external
):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(summary="Old text"))
    if external:
        state.items = (
            []
            if external is True
            else [{"id": 1, "schedule_type": "SCHEDULE_TYPE_SELECT_REGION"}]
        )
        await calendar.async_update()
        await mower.schedule.history.async_flush()
    else:
        await calendar.async_delete_event("global-1")
    assert mower.schedule.history.metadata(1) is None
    stored = await history_store(hass, mower.basic_data.stable_id).async_load()
    assert stored["metadata"] == {}
    state.items = [item(1)]
    await calendar.async_update()
    assert calendar.event.summary == SUMMARY


async def test_metadata_only_edit_refreshes_without_device_modify(device):
    mower, calendar, state = device
    await calendar.async_create_event(
        **new_event(summary="First", description="Old", location="Home")
    )
    state.commands.clear()
    await calendar.async_update_event(
        "global-1", new_event(summary="Renamed", description="", location="")
    )
    assert [c["cmd_type"] for c in state.commands] == [SCHEDULE_GET]
    assert (
        calendar.event.summary,
        calendar.event.description,
        calendar.event.location,
    ) == ("Renamed", "", "")
    # An omitted local field is preserved rather than reset to the fallback.
    await calendar.async_update_event(
        "global-1", {k: v for k, v in new_event().items() if k != "summary"}
    )
    assert calendar.event.summary == "Renamed"
    assert mower.schedule.history.metadata(1).summary == "Renamed"


@pytest.mark.parametrize("now", ["2026-11-18T09:30:00Z", "2026-11-26T08:00:00Z"])
async def test_disabled_one_time_text_edit_does_not_rearm_or_move_date(
    device, monkeypatch, now
):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    state.items[0]["global_schedule_v2"]["basic_config"]["disabled"] = True
    set_now(monkeypatch, now)
    # Do not refresh first: saving must discover disable in its baseline GET.
    state.commands.clear()
    await calendar.async_update_event(
        "global-1",
        new_event(
            summary="Saved appointment",
            description="Notes",
            location="Garden",
            rrule=None,
        ),
    )
    assert [c["cmd_type"] for c in state.commands] == [SCHEDULE_GET]
    metadata = mower.schedule.history.metadata(1)
    assert (metadata.summary, metadata.description, metadata.location) == (
        "Saved appointment",
        "Notes",
        "Garden",
    )
    assert mower.schedule.history.get(1).start == instant("2026-11-18T09:00:00Z")
    assert state.items[0]["global_schedule_v2"]["basic_config"]["disabled"]
    with pytest.raises(ServiceValidationError, match="one-time schedule is disabled"):
        await calendar.async_update_event(
            "global-1",
            new_event(
                dtstart=instant("2026-12-02T09:00:00Z"),
                dtend=instant("2026-12-02T10:00:00Z"),
                rrule=None,
            ),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"dtstart": instant("2026-11-18T09:45:00Z")},
        {"dtend": instant("2026-11-18T11:00:00Z")},
        {
            "dtstart": instant("2026-11-19T09:00:00Z"),
            "dtend": instant("2026-11-19T10:00:00Z"),
        },
        {
            "dtstart": instant("2026-11-25T09:00:00Z"),
            "dtend": instant("2026-11-25T10:00:00Z"),
        },
        {"rrule": "FREQ=WEEKLY;BYDAY=WE"},
        {"rrule": "FREQ=DAILY"},
        {"dtstart": date(2026, 11, 18), "dtend": date(2026, 11, 19)},
    ],
)
async def test_disabled_one_time_rejects_schedule_changes_without_partial_save(
    device, monkeypatch, changes
):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None, summary="Original"))
    state.items[0]["global_schedule_v2"]["basic_config"]["disabled"] = True
    before = deepcopy(state.items)
    set_now(monkeypatch, "2026-11-18T09:30:00Z")
    state.commands.clear()
    with pytest.raises(ServiceValidationError, match="one-time schedule is disabled"):
        await calendar.async_update_event(
            "global-1", new_event(**{"rrule": None, "summary": "Not saved", **changes})
        )
    assert [command["cmd_type"] for command in state.commands] == [SCHEDULE_GET]
    assert state.items == before
    assert mower.schedule.history.metadata(1).summary == "Original"
    assert mower.schedule.history.get(1).start == instant("2026-11-18T09:00:00Z")
    assert calendar.available
    # Freeze edits only; deletion still requires device ACK and absence on GET.
    await calendar.async_delete_event("global-1")
    assert [command["cmd_type"] for command in state.commands[-3:]] == [
        SCHEDULE_GET,
        SCHEDULE_DELETE,
        SCHEDULE_GET,
    ]
    assert not mower.schedule.items
    assert mower.schedule.history.get(1) is None


@pytest.mark.parametrize("all_day", [False, True])
async def test_disabled_one_time_keeps_all_day_display_choice(device, all_day):
    mower, calendar, state = device
    values = new_event(
        rrule=None,
        dtstart=date(2026, 11, 18) if all_day else instant("2026-11-18T00:00:00Z"),
        dtend=date(2026, 11, 19) if all_day else instant("2026-11-18T23:59:00Z"),
    )
    await calendar.async_create_event(**values)
    state.items[0]["global_schedule_v2"]["basic_config"]["disabled"] = True
    state.commands.clear()
    await calendar.async_update_event("global-1", {**values, "summary": "Renamed"})
    assert [command["cmd_type"] for command in state.commands] == [SCHEDULE_GET]
    assert mower.schedule.history.metadata(1).all_day == all_day
    opposite = {
        "dtstart": instant("2026-11-18T00:00:00Z") if all_day else date(2026, 11, 18),
        "dtend": instant("2026-11-18T23:59:00Z") if all_day else date(2026, 11, 19),
    }
    with pytest.raises(ServiceValidationError, match="one-time schedule is disabled"):
        await calendar.async_update_event("global-1", {**values, **opposite})
    assert all(command["cmd_type"] == SCHEDULE_GET for command in state.commands)


@pytest.mark.parametrize("failure", ["error", "timeout", "readback", "mismatch"])
async def test_failed_edit_never_commits_requested_metadata(
    device, monkeypatch, failure
):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(summary="Original"))
    monkeypatch.setattr(
        "custom_components.terramow.schedule.SCHEDULE_REPLY_TIMEOUT", 0.01
    )
    original = mower.mqtt_client.publish.side_effect

    def publish(topic, payload):
        if json.loads(payload)["cmd_type"] == SCHEDULE_MODIFY:
            if failure == "error":
                state.code = -1
            elif failure == "timeout":
                state.drop = SCHEDULE_MODIFY
            elif failure == "readback":
                state.drop = SCHEDULE_GET
            else:
                state.apply = False
        return original(topic, payload)

    mower.mqtt_client.publish.side_effect = publish
    with pytest.raises(HomeAssistantError):
        await calendar.async_update_event(
            "global-1",
            new_event(summary="Not committed", dtend=instant("2026-11-18T11:00:00Z")),
        )
    assert calendar.event.summary == "Original"
    assert mower.schedule.history.metadata(1).summary == "Original"
    assert calendar.available


async def test_missing_metadata_has_timed_weekly_fallback_even_at_midnight(
    hass, device
):
    mower, calendar, state = device
    await calendar.async_create_event(
        **new_event(
            dtstart=date(2026, 11, 18), dtend=date(2026, 11, 19), summary="Lost"
        )
    )
    await history_store(hass, mower.basic_data.stable_id).async_remove()
    mower.schedule = TerraMowSchedule(mower)
    state.items = [item(1, days=tuple(range(7)), start=0, end=1439)]
    await calendar.async_update()
    event = calendar.event
    assert not event.all_day
    assert event.summary == SUMMARY
    assert event.description is None and event.location is None
    assert event.rrule == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU"
    assert event.start == instant("2026-11-17T00:00:00Z")


async def test_corrupt_metadata_is_ignored_without_losing_valid_dates(hass, device):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(rrule=None))
    store = history_store(hass, mower.basic_data.stable_id)
    data = await store.async_load()
    data["metadata"]["1"]["summary"] = []
    data["metadata"]["invalid"] = None
    await store.async_save(data)
    mower.schedule = TerraMowSchedule(mower)
    await calendar.async_update()
    assert calendar.event.summary == SUMMARY
    assert calendar.event.start == instant("2026-11-18T09:00:00Z")


@pytest.mark.parametrize("device_edit", [False, True])
async def test_local_storage_failure_is_reported_with_device_snapshot_preserved(
    device, monkeypatch, device_edit
):
    from homeassistant.util.file import WriteError

    mower, calendar, state = device
    await calendar.async_create_event(**new_event(summary="Original"))

    async def fail_write(*args):
        raise WriteError("Disk full")

    # Real Store catches WriteError internally; readback must detect it anyway.
    with monkeypatch.context() as context:
        context.setattr(mower.schedule.history._store, "_async_write_data", fail_write)
        with pytest.raises(HomeAssistantError, match="could not save calendar details"):
            await calendar.async_update_event(
                "global-1",
                new_event(
                    summary="Not saved",
                    dtend=instant("2026-11-18T11:00:00Z")
                    if device_edit
                    else instant("2026-11-18T10:00:00Z"),
                ),
            )
    assert calendar.available
    assert calendar.event.summary == "Original"
    assert calendar.event.end.hour == (11 if device_edit else 10)
    assert not mower.schedule._editing


@pytest.mark.parametrize(
    "day,now,hours",
    [
        (date(2026, 3, 29), "2026-03-28T08:00:00Z", 23),
        (date(2026, 10, 25), "2026-10-24T08:00:00Z", 25),
    ],
)
async def test_all_day_uses_local_dates_across_dst(
    device, monkeypatch, day, now, hours
):
    _, calendar, _ = device
    dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/London"))
    set_now(monkeypatch, now)
    await calendar.async_create_event(
        **new_event(
            dtstart=day, dtend=day + timedelta(days=1), rrule="FREQ=WEEKLY;BYDAY=SU"
        )
    )
    event = calendar.event
    assert event.all_day and event.start == day and event.end == day + timedelta(days=1)
    elapsed = dt_util.as_utc(event.end_datetime_local) - dt_util.as_utc(
        event.start_datetime_local
    )
    assert elapsed == timedelta(hours=hours)


async def test_metadata_only_edit_requires_a_valid_fresh_get(device):
    mower, calendar, state = device
    await calendar.async_create_event(**new_event(summary="Original"))
    state.commands.clear()
    state.malformed = True
    with pytest.raises(HomeAssistantError, match="valid"):
        await calendar.async_update_event("global-1", new_event(summary="Unconfirmed"))
    assert calendar.event.summary == "Original"
    assert all(c["cmd_type"] == SCHEDULE_GET for c in state.commands)
    assert mower.schedule.history.metadata(1).summary == "Original"
