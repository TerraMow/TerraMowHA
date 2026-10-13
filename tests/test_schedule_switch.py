"""修剪计划总开关的命令、设备状态和连接生命周期测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity
from custom_components.terramow.schedule import (
    SCHEDULE_GET,
    SCHEDULE_MODE_TIME_SLOT,
    SCHEDULE_SET_DISABLED_WEEK_DAYS,
    SCHEDULE_SET_GLOBAL_DISABLED,
    WEEK_DAYS,
)
from custom_components.terramow.switch import (
    TerraMowScheduleSwitch,
    TerraMowWeekdayScheduleSwitch,
    async_setup_entry,
)


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """使用内存 MQTT 替身，不连接或控制实际设备。"""
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.69", ""), hass)
    entity.mqtt_connected = True
    entity.mqtt_client = MagicMock()
    entity.mqtt_client.is_connected.return_value = True
    entity.mqtt_client.publish.return_value = SimpleNamespace(rc=0)
    entity._last_control_time = -100
    entity.schedule.version = 2
    return entity


async def test_platform_adds_stable_switch(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """开关在同一设备下使用稳定身份，且无需等待割草机平台创建。"""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    entities = add_entities.call_args.args[0]
    switch = entities[0]
    assert isinstance(switch, TerraMowScheduleSwitch)
    assert switch.unique_id == f"lawn_mower.terramow@{mower.host}.schedule"
    assert switch.device_info["identifiers"] == {("TerraMowLawnMower", mower.host)}
    assert switch.available
    assert switch.is_on is None
    assert switch.entity_category is None
    assert len(entities) == 8
    assert [entity.day for entity in entities[1:]] == list(WEEK_DAYS)
    assert len({entity.unique_id for entity in entities}) == 8
    assert all(
        isinstance(entity, TerraMowWeekdayScheduleSwitch) for entity in entities[1:]
    )
    assert all(
        entity.entity_category == EntityCategory.CONFIG for entity in entities[1:]
    )
    assert all(not entity.available for entity in entities[1:])


async def test_switch_round_trip_uses_reported_state(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """关闭和打开都先等设置回复，再读回设备实际状态。"""
    switch = TerraMowScheduleSwitch(mower.basic_data, hass)
    commands: list[dict] = []
    disabled = False

    def publish(topic: str, payload: str) -> SimpleNamespace:
        nonlocal disabled
        assert topic == "data_point/122/app"
        command = json.loads(payload)
        commands.append(command)
        if command["cmd_type"] == SCHEDULE_SET_GLOBAL_DISABLED:
            disabled = command["set_global_disabled_param"]["global_disabled"]
            reply = {"cmd_type": command["cmd_type"], "seq": command["seq"]}
        else:
            reply = {
                "seq": command["seq"],
                "schedule_list": {"global_disabled": disabled},
            }
        hass.async_create_task(mower.schedule.on_reply(json.dumps(reply)))
        return SimpleNamespace(rc=0)

    mower.mqtt_client.publish.side_effect = publish
    mower.cmd_seq = 0x7FFFFFFE
    await mower.schedule.async_refresh()
    assert switch.is_on is True
    await switch.async_turn_off()
    assert switch.is_on is False
    mower._last_control_time = -100
    await switch.async_turn_on()
    assert switch.is_on is True
    assert [command["cmd_type"] for command in commands] == [
        SCHEDULE_GET,
        SCHEDULE_SET_GLOBAL_DISABLED,
        SCHEDULE_GET,
        SCHEDULE_SET_GLOBAL_DISABLED,
        SCHEDULE_GET,
    ]
    assert commands[1]["set_global_disabled_param"] == {"global_disabled": True}
    assert commands[3]["set_global_disabled_param"] == {"global_disabled": False}
    assert all(0 < command["seq"] <= 0x7FFFFFFF for command in commands)


async def test_rejected_or_mismatched_reply_does_not_change_switch(
    mower: TerraMowLawnMowerEntity,
) -> None:
    """设备拒绝和错误序号不能让 HA 显示未经确认的新值。"""
    mower.schedule.enabled = True
    task = asyncio.create_task(mower.schedule.async_set_enabled(False))
    await asyncio.sleep(0)
    command = json.loads(mower.mqtt_client.publish.call_args.args[1])
    await mower.schedule.on_reply(
        json.dumps(
            {"cmd_type": command["cmd_type"], "seq": command["seq"] + 1, "code": -1}
        )
    )
    assert not task.done()
    await mower.schedule.on_reply(
        json.dumps({"cmd_type": command["cmd_type"], "seq": command["seq"], "code": -1})
    )
    with pytest.raises(HomeAssistantError, match="code=-1"):
        await task
    assert mower.schedule.enabled is None
    mower.mqtt_client.publish.assert_called_once()


async def test_readback_disagreement_is_an_error(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """设备回读值与目标不同时，显示回读值并向服务调用方报错。"""

    def publish(_topic: str, payload: str) -> SimpleNamespace:
        command = json.loads(payload)
        reply = {"cmd_type": command["cmd_type"], "seq": command["seq"]}
        if command["cmd_type"] == SCHEDULE_GET:
            reply["schedule_list"] = {"global_disabled": False}
        hass.async_create_task(mower.schedule.on_reply(json.dumps(reply)))
        return SimpleNamespace(rc=0)

    mower.mqtt_client.publish.side_effect = publish
    with pytest.raises(HomeAssistantError, match="different"):
        await mower.schedule.async_set_enabled(False)
    assert mower.schedule.enabled is True


async def test_unsupported_or_disconnected_switch_does_not_send(
    mower: TerraMowLawnMowerEntity,
) -> None:
    """协议版本不足与断线时都不发送设置命令。"""
    mower.schedule.version = 1
    with pytest.raises(ServiceValidationError, match="version 2"):
        await mower.schedule.async_set_enabled(False)
    mower.schedule.version = 2
    mower.mqtt_connected = False
    with pytest.raises(HomeAssistantError, match="not connected"):
        await mower.schedule.async_set_enabled(False)
    mower.mqtt_client.publish.assert_not_called()


async def test_reconnect_waits_for_fresh_get(
    mower: TerraMowLawnMowerEntity,
) -> None:
    """断线清除旧状态；保留的旧回复与畸形读取都不能恢复开关。"""
    mower.schedule.enabled = True
    mower.schedule.reset_connection()
    assert mower.schedule.enabled is None
    assert not mower.schedule.available
    await mower.schedule.on_reply(
        json.dumps(
            {
                "cmd_type": SCHEDULE_GET,
                "seq": 1,
                "schedule_list": {"global_disabled": True},
            }
        ),
        retained=True,
    )
    assert mower.schedule.enabled is None
    mower.schedule.version = 2
    await mower.schedule.on_reply("not json")
    await mower.schedule.on_reply(
        json.dumps({"cmd_type": SCHEDULE_GET, "seq": 2, "schedule_list": []})
    )
    assert mower.schedule.enabled is None
    await mower.schedule.on_reply(
        json.dumps(
            {
                "cmd_type": SCHEDULE_GET,
                "seq": 3,
                "schedule_list": {"global_disabled": True},
            }
        )
    )
    assert mower.schedule.enabled is False


async def test_pending_request_finishes_on_disconnect(
    mower: TerraMowLawnMowerEntity,
) -> None:
    """连接中断立即终止等待，移除后不留下旧请求。"""
    task = asyncio.create_task(mower.schedule.async_refresh())
    await asyncio.sleep(0)
    mower.schedule.reset_connection()
    with pytest.raises(HomeAssistantError, match="disconnected"):
        await task
    assert mower.schedule._pending is None


async def test_version_report_refreshes_schedule_once(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """只有报告支持总开关的版本后，才主动读取设备设置。"""
    mower.schedule.reset_connection()
    mower.schedule.update_version({"module": {"schedule": 1}})
    assert not mower.schedule.available
    mower.mqtt_client.publish.assert_not_called()

    def publish(topic: str, payload: str) -> SimpleNamespace:
        assert topic == "data_point/122/app"
        command = json.loads(payload)
        hass.async_create_task(
            mower.schedule.on_reply(
                json.dumps(
                    {
                        "cmd_type": SCHEDULE_GET,
                        "seq": command["seq"],
                        "schedule_list": {},
                    }
                )
            )
        )
        return SimpleNamespace(rc=0)

    mower.mqtt_client.publish.side_effect = publish
    mower.schedule.update_version({"module": {"schedule": "2"}})
    await hass.async_block_till_done()
    assert mower.schedule.available
    assert mower.schedule.enabled is True
    mower.mqtt_client.publish.assert_called_once()


async def test_switch_listener_is_removed(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """重载或移除开关后不留下重复的状态监听。"""
    switch = TerraMowScheduleSwitch(mower.basic_data, hass)
    switch.entity_id = "switch.test_schedule"
    switch.async_write_ha_state = MagicMock()
    await switch.async_added_to_hass()
    async_dispatcher_send(hass, mower.schedule.signal)
    switch.async_write_ha_state.assert_called_once()
    await switch.async_remove(force_remove=True)
    async_dispatcher_send(hass, mower.schedule.signal)
    switch.async_write_ha_state.assert_called_once()


async def test_weekday_state_preserves_choices_under_master_switch(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """总开关覆盖执行，但不改写每一天已保存的开关状态。"""
    monday = TerraMowWeekdayScheduleSwitch(mower.basic_data, hass, "monday")
    tuesday = TerraMowWeekdayScheduleSwitch(mower.basic_data, hass, "tuesday")
    schedule_list = {
        "global_disabled": False,
        "disabled_week_days": [WEEK_DAYS["monday"]],
        "schedule_mode": SCHEDULE_MODE_TIME_SLOT,
    }
    await mower.schedule.on_reply(
        json.dumps({"seq": 1, "schedule_list": schedule_list})
    )
    assert monday.available and tuesday.available
    assert monday.is_on is False
    assert tuesday.is_on is True

    schedule_list["global_disabled"] = True
    await mower.schedule.on_reply(
        json.dumps({"seq": 2, "schedule_list": schedule_list})
    )
    assert mower.schedule.enabled is False
    assert monday.is_on is False
    assert tuesday.is_on is True

    schedule_list["schedule_mode"] = "SCHEDULE_MODE_FREQUENCY"
    await mower.schedule.on_reply(
        json.dumps({"seq": 3, "schedule_list": schedule_list})
    )
    assert mower.schedule.available
    assert not monday.available and not tuesday.available
    with pytest.raises(ServiceValidationError, match="time-slot"):
        await monday.async_turn_on()
    mower.mqtt_client.publish.assert_not_called()


async def test_weekday_round_trip_changes_only_selected_day(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """设置某一天后重新读取禁用集合，其余星期与总开关保持原值。"""
    monday = TerraMowWeekdayScheduleSwitch(mower.basic_data, hass, "monday")
    tuesday = TerraMowWeekdayScheduleSwitch(mower.basic_data, hass, "tuesday")
    disabled_days = {WEEK_DAYS["monday"]}
    commands: list[dict] = []
    mower.schedule.version = 5
    await mower.schedule.on_reply(
        json.dumps(
            {
                "seq": 1,
                "schedule_list": {
                    "global_disabled": True,
                    "disabled_week_days": sorted(disabled_days),
                    "schedule_mode": SCHEDULE_MODE_TIME_SLOT,
                },
            }
        )
    )

    def publish(topic: str, payload: str) -> SimpleNamespace:
        assert topic == "data_point/122/app"
        command = json.loads(payload)
        commands.append(command)
        reply = {"seq": command["seq"], "cmd_type": command["cmd_type"]}
        if command["cmd_type"] == SCHEDULE_SET_DISABLED_WEEK_DAYS:
            setting = command["set_disabled_week_days_param"]
            if setting["disabled"]:
                disabled_days.add(setting["week_day"])
            else:
                disabled_days.remove(setting["week_day"])
        else:
            reply["schedule_list"] = {
                "global_disabled": True,
                "disabled_week_days": sorted(disabled_days),
                "schedule_mode": SCHEDULE_MODE_TIME_SLOT,
            }
        hass.async_create_task(mower.schedule.on_reply(json.dumps(reply)))
        return SimpleNamespace(rc=0)

    mower.mqtt_client.publish.side_effect = publish
    await tuesday.async_turn_off()
    assert tuesday.is_on is False
    assert monday.is_on is False
    assert mower.schedule.enabled is False
    mower._last_control_time = -100
    await tuesday.async_turn_on()
    assert tuesday.is_on is True
    assert monday.is_on is False
    assert disabled_days == {WEEK_DAYS["monday"]}
    assert [command["cmd_type"] for command in commands] == [
        SCHEDULE_SET_DISABLED_WEEK_DAYS,
        SCHEDULE_GET,
        SCHEDULE_SET_DISABLED_WEEK_DAYS,
        SCHEDULE_GET,
    ]
    assert commands[0]["set_disabled_week_days_param"] == {
        "week_day": WEEK_DAYS["tuesday"],
        "disabled": True,
    }
    assert commands[2]["set_disabled_week_days_param"] == {
        "week_day": WEEK_DAYS["tuesday"],
        "disabled": False,
    }


async def test_invalid_weekday_snapshot_cannot_enable_day_switches(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """设备上报非法枚举时不猜测七日状态，也不下发非法星期。"""
    monday = TerraMowWeekdayScheduleSwitch(mower.basic_data, hass, "monday")
    await mower.schedule.on_reply(
        json.dumps(
            {
                "seq": 1,
                "schedule_list": {
                    "disabled_week_days": ["WEEK_DAY_INVALID"],
                    "schedule_mode": SCHEDULE_MODE_TIME_SLOT,
                },
            }
        )
    )
    assert mower.schedule.enabled is True
    assert not monday.available
    assert monday.is_on is None
    with pytest.raises(HomeAssistantError, match="has not been read"):
        await monday.async_turn_off()
    with pytest.raises(ServiceValidationError, match="Invalid schedule weekday"):
        await mower.schedule.async_set_weekday_enabled("holiday", False)
    mower.mqtt_client.publish.assert_not_called()


async def test_external_change_triggers_own_get(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """其它客户端只有 SET 回复时，HA 也主动 GET 更新单日状态。"""
    mower.schedule.version = 5
    monday = TerraMowWeekdayScheduleSwitch(mower.basic_data, hass, "monday")
    await mower.schedule.on_reply(
        json.dumps(
            {
                "seq": 1,
                "schedule_list": {
                    "disabled_week_days": [],
                    "schedule_mode": SCHEDULE_MODE_TIME_SLOT,
                },
            }
        )
    )
    assert monday.is_on is True

    def publish(topic: str, payload: str) -> SimpleNamespace:
        assert topic == "data_point/122/app"
        command = json.loads(payload)
        assert command["cmd_type"] == SCHEDULE_GET
        hass.async_create_task(
            mower.schedule.on_reply(
                json.dumps(
                    {
                        "seq": command["seq"],
                        "schedule_list": {
                            "disabled_week_days": [WEEK_DAYS["monday"]],
                            "schedule_mode": SCHEDULE_MODE_TIME_SLOT,
                        },
                    }
                )
            )
        )
        return SimpleNamespace(rc=0)

    mower.mqtt_client.publish.side_effect = publish
    await mower.schedule.on_reply(
        json.dumps(
            {
                "cmd_type": SCHEDULE_SET_DISABLED_WEEK_DAYS,
                "seq": 900,
                "code": 0,
            }
        )
    )
    await hass.async_block_till_done()
    mower.mqtt_client.publish.assert_called_once()
    assert monday.is_on is False


def test_all_schedule_switch_translations() -> None:
    """每个受支持的翻译文件都有修剪计划开关的名称。"""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "terramow"
    for path in [root / "strings.json", *(root / "translations").glob("*.json")]:
        translation = json.loads(path.read_text(encoding="utf-8"))
        names = translation["entity"]["switch"]
        assert names["schedule"]["name"]
        assert all(names[f"schedule_{day}"]["name"] for day in WEEK_DAYS)
