"""Mower event entity: one event per transition, none for replayed state."""

import json
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.event import (
    EVENT_TYPES,
    TerraMowMowerEvent,
    async_setup_entry,
)
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity

IDLE = ("MISSION_IDLE", "SUB_MISSION_IDLE", "MISSION_STATE_IDLE")
MOWING = ("MISSION_GLOBAL_CLEAN", "SUB_MISSION_IDLE", "MISSION_STATE_RUNNING")
PAUSED = ("MISSION_GLOBAL_CLEAN", "SUB_MISSION_IDLE", "MISSION_STATE_PAUSE")
STATION_WAIT = (
    "MISSION_GLOBAL_CLEAN",
    "SUB_MISSION_FLEXIBLE_STATION_WAIT",
    "MISSION_STATE_RUNNING",
)
SAVING_MAP = ("MISSION_GLOBAL_CLEAN", "SUB_MISSION_SAVING_MAP", "MISSION_STATE_RUNNING")
COMPLETE = ("MISSION_GLOBAL_CLEAN", "SUB_MISSION_IDLE", "MISSION_STATE_COMPLETE")
RETURNING = ("MISSION_RECHARGE", "SUB_MISSION_RETURN_TO_BASE", "MISSION_STATE_RUNNING")
RETURN_DONE = ("MISSION_RECHARGE", "SUB_MISSION_IDLE", "MISSION_STATE_COMPLETE")
MAPPING = ("MISSION_BACKUP_MAP", "SUB_MISSION_IDLE", "MISSION_STATE_RUNNING")


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.77", ""), hass)
    entity.schedule_update_ha_state = MagicMock()
    entity.mqtt_connected = True
    entity.register_all_callbacks()
    return entity


@pytest.fixture
async def event_entity(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> TerraMowMowerEvent:
    entity = TerraMowMowerEvent(mower.basic_data, hass)
    entity.entity_id = "event.terramow_mower_event"
    entity.async_write_ha_state = callback(MagicMock())
    entity.fired = []
    real_trigger = entity._trigger_event

    def record(event_type: str, attributes: dict | None = None) -> None:
        entity.fired.append((event_type, attributes))
        real_trigger(event_type, attributes)

    entity._trigger_event = record
    await entity.async_added_to_hass()
    return entity


async def _report(
    mower: TerraMowLawnMowerEntity, status: tuple, has_error: bool = False
) -> None:
    mission, sub_mission, state = status
    await mower.on_mission_status(
        json.dumps(
            {
                "mission": mission,
                "sub_mission": sub_mission,
                "state": state,
                "has_error": has_error,
            }
        )
    )


async def _faults(mower: TerraMowLawnMowerEntity, *codes: int) -> None:
    await mower.feedback.on_error_list(
        json.dumps({"error_list": [{"code": code} for code in codes]})
        if codes
        else "{}"
    )


def _types(entity: TerraMowMowerEvent) -> list[str]:
    return [event_type for event_type, _ in entity.fired]


async def test_entity_is_registered(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    (entity,) = add_entities.call_args.args[0]
    assert isinstance(entity, TerraMowMowerEvent)
    assert entity.unique_id == (
        f"lawn_mower.terramow@{mower.basic_data.stable_id}.mower_event"
    )
    assert entity.translation_key == "mower_event"
    assert entity.event_types == EVENT_TYPES
    assert entity.device_info["identifiers"] == {
        ("TerraMowLawnMower", mower.basic_data.stable_id)
    }


async def test_nothing_fires_until_mission_and_fault_snapshot_arrive(
    mower: TerraMowLawnMowerEntity, event_entity: TerraMowMowerEvent
) -> None:
    await _report(mower, MOWING)
    await _faults(mower)  # baseline taken here: mowing, no event
    assert event_entity.fired == []

    await _report(mower, PAUSED)
    assert _types(event_entity) == ["paused"]


async def test_fault_snapshot_alone_does_not_set_the_baseline(
    mower: TerraMowLawnMowerEntity, event_entity: TerraMowMowerEvent
) -> None:
    await _faults(mower)
    await _report(mower, MOWING)  # first complete picture: baseline
    await _report(mower, MOWING)
    assert event_entity.fired == []


async def test_each_transition_fires_once(
    mower: TerraMowLawnMowerEntity, event_entity: TerraMowMowerEvent
) -> None:
    await _report(mower, IDLE)
    await _faults(mower)

    for status in (
        MOWING,
        MOWING,  # repeated report: no new event
        PAUSED,
        MOWING,
        STATION_WAIT,
        MOWING,
        RETURNING,
        IDLE,
        MOWING,
        SAVING_MAP,
        MOWING,
        COMPLETE,
        IDLE,  # still docked after completion: no event
        MAPPING,  # running a non-mowing mission is not mowing
    ):
        await _report(mower, status)

    assert _types(event_entity) == [
        "mowing_started",
        "paused",
        "mowing_started",
        "paused",
        "mowing_started",
        "returning",
        "docked",
        "mowing_started",
        "docked",
        "mowing_started",
        "mowing_completed",
    ]


async def test_completion_of_a_return_is_not_a_mowing_completion(
    mower: TerraMowLawnMowerEntity, event_entity: TerraMowMowerEvent
) -> None:
    await _report(mower, RETURNING)
    await _faults(mower)
    await _report(mower, RETURN_DONE)
    assert _types(event_entity) == ["docked"]


async def test_faults_fire_error_and_clearing_returns_to_the_phase(
    mower: TerraMowLawnMowerEntity, event_entity: TerraMowMowerEvent
) -> None:
    await _report(mower, MOWING)
    await _faults(mower)

    await mower.feedback.on_error('{"int_value": 903}')  # live single fault
    await _faults(mower, 903)  # same fault in the snapshot: no new event
    await _faults(mower)  # cleared
    await _report(mower, MOWING, has_error=True)  # dp_107 error flag
    await _report(mower, MOWING)

    assert _types(event_entity) == [
        "error",
        "mowing_started",
        "error",
        "mowing_started",
    ]
    _, attributes = event_entity.fired[0]
    assert attributes["active_faults"] == [903]


async def test_event_attributes_carry_the_mission_fields(
    mower: TerraMowLawnMowerEntity, event_entity: TerraMowMowerEvent
) -> None:
    await _report(mower, MOWING)
    await _faults(mower)
    await mower.on_mission_status(
        json.dumps(
            {
                "mission": "MISSION_RECHARGE",
                "sub_mission": "SUB_MISSION_RETURN_TO_BASE",
                "state": "MISSION_STATE_RUNNING",
                "back_to_station_reason": "BACK_TO_STATION_REASON_RAINING",
            }
        )
    )

    assert event_entity.fired == [
        (
            "returning",
            {
                "mission": "MISSION_RECHARGE",
                "sub_mission": "SUB_MISSION_RETURN_TO_BASE",
                "state": "MISSION_STATE_RUNNING",
                "back_to_station_reason": "BACK_TO_STATION_REASON_RAINING",
                "active_faults": [],
            },
        )
    ]
    event_entity.async_write_ha_state.assert_called()


async def test_reconnect_does_not_replay_events(
    hass: HomeAssistant,
    mower: TerraMowLawnMowerEntity,
    event_entity: TerraMowMowerEvent,
) -> None:
    await _report(mower, IDLE)
    await _faults(mower, 903)  # baseline: error
    assert event_entity.fired == []

    mower.on_mqtt_disconnect(None, None, 1)
    await hass.async_block_till_done()
    with (
        patch.object(mower, "_request_compatibility_info"),
        patch.object(mower.schedule, "request_refresh"),
    ):
        mower.on_mqtt_connect(MagicMock(), None, None, 0)
        await hass.async_block_till_done()

    # Retained reports of the new connection set a new baseline silently.
    await _report(mower, IDLE)
    await _faults(mower, 903)
    assert event_entity.fired == []

    await _faults(mower)
    assert _types(event_entity) == ["docked"]


async def test_reports_while_disconnected_are_ignored(
    hass: HomeAssistant,
    mower: TerraMowLawnMowerEntity,
    event_entity: TerraMowMowerEvent,
) -> None:
    await _report(mower, MOWING)
    await _faults(mower)
    mower.on_mqtt_disconnect(None, None, 1)
    await hass.async_block_till_done()

    await _report(mower, PAUSED)
    assert event_entity.fired == []


async def test_restart_with_an_active_fault_does_not_fire(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    # Reports delivered before the entity existed are not events either.
    await mower.feedback.on_error('{"int_value": 903}')
    entity = TerraMowMowerEvent(mower.basic_data, hass)
    entity.entity_id = "event.terramow_mower_event"
    entity.async_write_ha_state = callback(MagicMock())
    entity._trigger_event = MagicMock()
    await entity.async_added_to_hass()

    await _report(mower, IDLE)
    await _faults(mower, 903)

    entity._trigger_event.assert_not_called()


async def test_reports_without_a_mower_are_ignored(hass: HomeAssistant) -> None:
    entity = TerraMowMowerEvent(TerraMowBasicData("192.0.2.78", ""), hass)
    entity._trigger_event = MagicMock()
    entity._async_mission_updated()
    entity._async_feedback_updated()
    entity._trigger_event.assert_not_called()
