"""命令拒绝、回复竞态、事件历史与故障恢复的回归测试。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.lawn_mower import DATA_COMPONENT
from homeassistant.components.lawn_mower.const import LawnMowerActivity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.lawn_mower import (
    BackToStationReason,
    Mission,
    MissionState,
    TerraMowLawnMowerEntity,
)
from custom_components.terramow.select import TerraMowZoneSelect
from custom_components.terramow.sensor import TerraMowFeedbackSensor


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """真实实体方法配合内存 MQTT，避免测试控制实际设备。"""
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.86", ""), hass)
    entity.entity_id = "lawn_mower.test"
    entity.schedule_update_ha_state = MagicMock()
    entity.mqtt_client = MagicMock()
    entity.mqtt_client.is_connected.return_value = True
    entity.mqtt_client.publish.return_value = SimpleNamespace(rc=0)
    entity._last_control_time = -100
    entity.register_all_callbacks()
    return entity


async def test_service_propagates_start_rejection(hass: HomeAssistant) -> None:
    """通过 HA 服务入口验证拒绝能回到调用方，而非仅验证内部方法。"""
    await async_setup_component(hass, "lawn_mower", {})
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.86", ""), hass)
    entity.mqtt_client = MagicMock()
    entity.mqtt_client.is_connected.return_value = True
    entity._last_control_time = -100

    def publish(topic: str, payload: str) -> SimpleNamespace:
        data = json.loads(payload)
        hass.async_create_task(entity.feedback.on_event('{"int_value":135}', dp_id=114))
        hass.async_create_task(
            entity.feedback.on_reply(
                json.dumps({"seq": data["seq"], "ret": -3}), dp_id=103
            )
        )
        return SimpleNamespace(rc=0)

    entity.mqtt_client.publish.side_effect = publish
    await hass.data[DATA_COMPONENT].async_add_entities([entity])
    with pytest.raises(HomeAssistantError, match="ret=-3.*135"):
        await hass.services.async_call(
            "lawn_mower", "start_mowing", {"entity_id": entity.entity_id}, blocking=True
        )
    assert hass.states.get(entity.entity_id).state == "docked"


@pytest.mark.parametrize("reply", [{"ret": 0}, {}])
async def test_fast_success_reply(mower: TerraMowLawnMowerEntity, reply: dict) -> None:
    """发布当下就到达的回复仍能匹配；protobuf 默认 ret=0 允许省略。"""

    def publish(topic: str, payload: str) -> SimpleNamespace:
        mower.hass.async_create_task(
            mower.feedback.on_reply(
                json.dumps({**reply, "seq": json.loads(payload)["seq"]}), dp_id=103
            )
        )
        return SimpleNamespace(rc=0)

    mower.mqtt_client.publish.side_effect = publish
    await mower.async_start_mowing()
    assert mower.activity == LawnMowerActivity.DOCKED
    assert not mower.feedback._pending


async def test_wrong_dp_sequence_and_duplicate_replies(
    mower: TerraMowLawnMowerEntity,
) -> None:
    task = asyncio.create_task(mower.async_start_mowing())
    await asyncio.sleep(0)
    seq = json.loads(mower.mqtt_client.publish.call_args.args[1])["seq"]
    await mower.feedback.on_reply(json.dumps({"seq": seq + 1, "ret": -3}), dp_id=103)
    await mower.feedback.on_reply(json.dumps({"seq": seq, "ret": -3}), dp_id=106)
    assert not task.done()
    await mower.feedback.on_reply(json.dumps({"seq": seq, "ret": 0}), dp_id=103)
    await mower.feedback.on_reply(json.dumps({"seq": seq, "ret": -3}), dp_id=103)
    await task
    assert not mower.feedback._pending


async def test_timeout_is_unconfirmed_and_does_not_retry(
    mower: TerraMowLawnMowerEntity,
) -> None:
    with (
        patch("custom_components.terramow.feedback.COMMAND_REPLY_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError, match="did not confirm"),
    ):
        await mower.async_start_mowing()
    mower.mqtt_client.publish.assert_called_once()
    assert not mower.feedback._pending


@pytest.mark.parametrize("rc", [1, 4])
async def test_publish_failure(mower: TerraMowLawnMowerEntity, rc: int) -> None:
    mower.mqtt_client.publish.return_value.rc = rc
    with pytest.raises(HomeAssistantError, match="publish failed"):
        await mower.async_start_mowing()
    assert not mower.feedback._pending


async def test_missing_publish_result_finishes_pending(
    mower: TerraMowLawnMowerEntity,
) -> None:
    """发布入口没有返回发送结果时，应报连接错误并清理等待者。"""
    with (
        patch.object(mower, "publish_data_point", return_value=None),
        pytest.raises(HomeAssistantError, match="MQTT client is not initialized"),
    ):
        await mower.async_start_mowing()
    assert not mower.feedback._pending


async def test_disconnected_client_does_not_publish(
    mower: TerraMowLawnMowerEntity,
) -> None:
    mower.mqtt_client.is_connected.return_value = False
    with pytest.raises(HomeAssistantError, match="not connected"):
        await mower.async_start_mowing()
    mower.mqtt_client.publish.assert_not_called()


async def test_mqtt_thread_disconnect_finishes_pending(
    mower: TerraMowLawnMowerEntity,
) -> None:
    task = asyncio.create_task(mower.async_start_mowing())
    await asyncio.sleep(0)
    await mower.hass.async_add_executor_job(mower.on_mqtt_disconnect, None, None, 1)
    with pytest.raises(HomeAssistantError, match="disconnected"):
        await task
    assert not mower.feedback._pending


@pytest.mark.parametrize(
    ("method", "mission", "state", "dp_id"),
    [
        (
            "async_start_mowing",
            Mission.MISSION_GLOBAL_CLEAN,
            MissionState.MISSION_STATE_PAUSE,
            106,
        ),
        (
            "async_pause",
            Mission.MISSION_GLOBAL_CLEAN,
            MissionState.MISSION_STATE_RUNNING,
            105,
        ),
        ("async_dock", Mission.MISSION_IDLE, MissionState.MISSION_STATE_IDLE, 103),
    ],
)
async def test_control_routes_wait_for_reply(
    mower: TerraMowLawnMowerEntity,
    method: str,
    mission: Mission,
    state: MissionState,
    dp_id: int,
) -> None:
    mower.mission, mower.mission_state = mission, state
    task = asyncio.create_task(getattr(mower, method)())
    await asyncio.sleep(0)
    topic, payload = mower.mqtt_client.publish.call_args.args
    assert topic == f"data_point/{dp_id}/app"
    await mower.feedback.on_reply(
        json.dumps({"seq": json.loads(payload)["seq"], "ret": -3}), dp_id=dp_id
    )
    with pytest.raises(HomeAssistantError, match="ret=-3"):
        await task


async def test_region_selection_does_not_change_on_rejection(
    mower: TerraMowLawnMowerEntity,
) -> None:
    selector = TerraMowZoneSelect(mower.basic_data, mower.hass)
    selector._options = ["Front (ID: 1)", "Back (ID: 2)"]
    selector._current_option = "Front (ID: 1)"
    task = asyncio.create_task(selector.async_select_option("Back (ID: 2)"))
    await asyncio.sleep(0)
    data = json.loads(mower.mqtt_client.publish.call_args.args[1])
    assert data["select_region_clean"]["region_ids"] == [2]
    await mower.feedback.on_reply(
        json.dumps({"seq": data["seq"], "ret": -3}), dp_id=103
    )
    with pytest.raises(HomeAssistantError, match="ret=-3"):
        await task
    assert selector.current_option == "Front (ID: 1)"


async def test_current_fault_snapshot_overrides_pause_and_clears(
    mower: TerraMowLawnMowerEntity,
) -> None:
    await mower.on_mission_status(
        '{"mission":"MISSION_GLOBAL_CLEAN","state":"MISSION_STATE_PAUSE","has_error":false,"back_to_station_reason":"BACK_TO_STATION_REASON_NIGHT_TIME"}'
    )
    await mower.feedback.on_error_list(
        '{"error_list":[{"code":903,"time":"2026-09-29T14:00:00Z"}]}'
    )
    assert mower.activity == LawnMowerActivity.ERROR
    sensor = TerraMowFeedbackSensor(mower.basic_data, "active_fault")
    assert sensor.native_value == 903
    assert (
        mower.extra_state_attributes["back_to_station_reason"]
        == BackToStationReason.BACK_TO_STATION_REASON_NIGHT_TIME.value
    )
    await mower.feedback.on_error_list("{}")
    assert mower.activity == LawnMowerActivity.PAUSED
    assert sensor.native_value == 0


async def test_retained_single_error_does_not_relatch_cleared_fault(
    mower: TerraMowLawnMowerEntity,
) -> None:
    await mower.feedback.on_error_list("{}")
    await mower.feedback.on_error('{"int_value":903}', retained=True)
    assert mower.activity == LawnMowerActivity.DOCKED
    await mower.feedback.on_error('{"int_value":903}')
    assert mower.activity == LawnMowerActivity.ERROR


async def test_event_history_is_not_a_current_fault(
    mower: TerraMowLawnMowerEntity,
) -> None:
    await mower.feedback.on_event(
        '{"event_list":[{"code":95,"time":"2026-09-28T16:37:24Z"},{"code":135,"time":"2026-09-28T17:13:45Z"}]}',
        retained=True,
        dp_id=123,
    )
    sensor = TerraMowFeedbackSensor(mower.basic_data, "last_event")
    assert sensor.native_value == 135
    assert sensor.extra_state_attributes["time"] == "2026-09-28T17:13:45Z"
    assert mower.activity == LawnMowerActivity.DOCKED
    assert mower.feedback._last_live_event is None
    await mower.feedback.on_event(
        '{"event_list":[{"code":95,"time":"2026-09-28T16:37:24Z"}]}', dp_id=123
    )
    assert sensor.native_value == 135


@pytest.mark.parametrize(
    "payload",
    ["not json", "[]", '{"error_list":"bad"}', '{"error_list":[{"code":"903"}]}'],
)
async def test_invalid_fault_payload_preserves_current_fault(
    mower: TerraMowLawnMowerEntity, payload: str
) -> None:
    await mower.feedback.on_error_list('{"error_list":[{"code":903}]}')
    await mower.feedback.on_error_list(payload)
    assert mower.activity == LawnMowerActivity.ERROR


async def test_sequence_wraps_at_protocol_uint32(
    mower: TerraMowLawnMowerEntity,
) -> None:
    mower.cmd_seq = 0xFFFFFFFF
    assert mower.get_cmd_seq() == 0


async def test_old_history_after_live_event_does_not_replace_reason(
    mower: TerraMowLawnMowerEntity,
) -> None:
    """123 历史基线不能被 114 实时通知打断。"""
    history = '{"event_list":[{"code":95,"time":"2026-09-28T16:37:24Z"}]}'
    await mower.feedback.on_event(history, retained=True, dp_id=123)
    await mower.feedback.on_event('{"int_value":135}', dp_id=114)
    await mower.feedback.on_event(history, dp_id=123)
    assert mower.feedback.latest_event["code"] == 135
    assert mower.feedback._last_live_event[1] == 135


async def test_history_without_baseline_is_not_current_command_reason(
    mower: TerraMowLawnMowerEntity,
) -> None:
    task = asyncio.create_task(mower.async_start_mowing())
    await asyncio.sleep(0)
    seq = json.loads(mower.mqtt_client.publish.call_args.args[1])["seq"]
    await mower.feedback.on_event(
        '{"event_list":[{"code":95,"time":"2026-09-28T16:37:24Z"}]}', dp_id=123
    )
    await mower.feedback.on_reply(json.dumps({"seq": seq, "ret": -3}), dp_id=103)
    with pytest.raises(HomeAssistantError, match="ret=-3") as err:
        await task
    assert "event=" not in str(err.value)


async def test_event_times_without_timezone_are_ignored(
    mower: TerraMowLawnMowerEntity,
) -> None:
    await mower.feedback.on_event(
        '{"event_list":[{"code":95,"time":"2026-09-28T16:37:24"},{"code":135,"time":"2026-09-28T17:13:45Z"}]}',
        dp_id=123,
    )
    assert mower.feedback.latest_event["code"] == 135


async def test_nearby_different_history_does_not_replace_live_event(
    mower: TerraMowLawnMowerEntity,
) -> None:
    """补齐时间的传输容忍窗只适用于同码事件。"""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    await mower.feedback.on_event('{"int_value":135}', dp_id=114)
    old = (dt_util.utcnow() - timedelta(seconds=1)).isoformat()
    await mower.feedback.on_event(
        json.dumps({"event_list": [{"code": 95, "time": old}]}), dp_id=123
    )
    assert mower.feedback.latest_event["code"] == 135
    assert mower.feedback._last_live_event[1] == 135
