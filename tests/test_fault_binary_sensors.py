"""安全告警二元传感器的故障快照与连接生命周期测试。"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.binary_sensor import (
    DATA_COMPONENT,
    BinarySensorDeviceClass,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.binary_sensor import (
    TerraMowAntiTheftBoundaryAlarmBinarySensor,
    TerraMowLiftAlarmBinarySensor,
    async_setup_entry,
)
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity

_ALARM_TYPES = (
    TerraMowLiftAlarmBinarySensor,
    TerraMowAntiTheftBoundaryAlarmBinarySensor,
)


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """构造带稳定设备身份的实体，消息由测试直接交给反馈处理器。"""
    basic_data = TerraMowBasicData("192.0.2.34", "", identity_key="alarm-device")
    entity = TerraMowLawnMowerEntity(basic_data, hass)
    entity.schedule_update_ha_state = MagicMock()
    return entity


async def test_platform_adds_distinct_main_device_alarms(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """两项告警默认添加到设备主区域，重配地址时身份保持稳定。"""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    alarms = [
        entity
        for entity in add_entities.call_args.args[0]
        if isinstance(entity, _ALARM_TYPES)
    ]
    assert [type(entity) for entity in alarms] == list(_ALARM_TYPES)
    assert {entity.unique_id for entity in alarms} == {
        "lawn_mower.terramow@alarm-device.lift_alarm",
        "lawn_mower.terramow@alarm-device.anti_theft_boundary_alarm",
    }
    assert all(
        entity.device_class == BinarySensorDeviceClass.TAMPER for entity in alarms
    )
    assert all(entity.entity_category is None for entity in alarms)
    assert all(
        entity.device_info["identifiers"] == {("TerraMowLawnMower", "alarm-device")}
        for entity in alarms
    )


async def test_only_complete_fault_list_changes_alarm_state(
    mower: TerraMowLawnMowerEntity,
) -> None:
    """单条故障和历史事件不能替代当前故障集合。"""
    lift = TerraMowLiftAlarmBinarySensor(mower.basic_data, mower.hass)
    boundary = TerraMowAntiTheftBoundaryAlarmBinarySensor(mower.basic_data, mower.hass)
    mower.mqtt_connected = True
    assert (lift.is_on, boundary.is_on) == (None, None)

    await mower.feedback.on_error('{"int_value":201}')
    assert (lift.is_on, boundary.is_on) == (None, None)
    await mower.feedback.on_error_list("{}")
    assert (lift.is_on, boundary.is_on) == (False, False)

    await mower.feedback.on_error('{"int_value":1409}')
    await mower.feedback.on_event('{"int_value":201}', dp_id=114)
    assert (lift.is_on, boundary.is_on) == (False, False)

    await mower.feedback.on_error_list(
        '{"error_list":[{"code":201},{"code":1409},{"code":903}]}'
    )
    assert (lift.is_on, boundary.is_on) == (True, True)

    await mower.feedback.on_error_list('{"error_list":[{"code":202},{"code":903}]}')
    assert (lift.is_on, boundary.is_on) == (True, False)

    for invalid in (
        "not json",
        "[]",
        '{"unexpected":true}',
        '{"error_list":"bad"}',
        '{"error_list":[{"code":true}]}',
    ):
        await mower.feedback.on_error_list(invalid)
    assert (lift.is_on, boundary.is_on) == (True, False)

    await mower.feedback.on_error_list('{"error_list":[{"code":1409}]}')
    assert (lift.is_on, boundary.is_on) == (False, True)
    await mower.feedback.on_error_list('{"error_list":[]}')
    assert (lift.is_on, boundary.is_on) == (False, False)


async def test_lift_alarm_publishes_ha_state(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """HA 状态机只在完整故障集合变化时向自动化提供告警状态。"""
    await async_setup_component(hass, "binary_sensor", {})
    mower.mqtt_connected = True
    alarm = TerraMowLiftAlarmBinarySensor(mower.basic_data, hass)
    alarm.entity_id = "binary_sensor.test_lift_alarm"
    await hass.data[DATA_COMPONENT].async_add_entities([alarm])
    await hass.async_block_till_done()
    assert hass.states.get(alarm.entity_id).state == "unknown"

    await mower.feedback.on_error('{"int_value":201}')
    await hass.async_block_till_done()
    assert hass.states.get(alarm.entity_id).state == "unknown"

    await mower.feedback.on_error_list('{"error_list":[{"code":201}]}')
    await hass.async_block_till_done()
    assert hass.states.get(alarm.entity_id).state == "on"

    await mower.feedback.on_error_list("{}")
    await hass.async_block_till_done()
    assert hass.states.get(alarm.entity_id).state == "off"

    mower.on_mqtt_disconnect(MagicMock(), None, 1)
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert hass.states.get(alarm.entity_id).state == "unavailable"


async def test_alarm_waits_for_new_snapshot_after_reconnect(
    hass: HomeAssistant,
) -> None:
    """早装载与重连都等待当前快照，移除实体后不留下反馈监听。"""
    basic_data = TerraMowBasicData("192.0.2.35", "")
    alarm = TerraMowLiftAlarmBinarySensor(basic_data, hass)
    alarm.entity_id = "binary_sensor.test_lift_alarm"
    writes = 0

    @callback
    def record_write() -> None:
        nonlocal writes
        writes += 1

    alarm.async_write_ha_state = record_write
    await alarm.async_added_to_hass()
    assert not alarm.available
    assert alarm.is_on is None

    mower = TerraMowLawnMowerEntity(basic_data, hass)
    mower.schedule_update_ha_state = MagicMock()
    client = MagicMock()

    async def settle_dispatcher() -> None:
        await asyncio.sleep(0)
        await hass.async_block_till_done()

    with (
        patch.object(mower, "_request_compatibility_info"),
        patch.object(mower, "update_activity_from_state"),
    ):
        mower.on_mqtt_connect(client, None, None, 0)
    await settle_dispatcher()
    assert alarm.available
    assert alarm.is_on is None

    await mower.feedback.on_error_list('{"error_list":[{"code":201}]}')
    assert alarm.is_on is True

    mower.on_mqtt_disconnect(client, None, 1)
    await settle_dispatcher()
    assert not alarm.available
    assert alarm.is_on is None

    with (
        patch.object(mower, "_request_compatibility_info"),
        patch.object(mower, "update_activity_from_state"),
    ):
        mower.on_mqtt_connect(client, None, None, 0)
    await settle_dispatcher()
    assert alarm.available
    assert alarm.is_on is None
    await mower.feedback.on_error('{"int_value":201}')
    assert alarm.is_on is None

    await mower.feedback.on_error_list("{}")
    assert alarm.is_on is False
    assert writes >= 4

    await alarm.async_remove(force_remove=True)
    old_writes = writes
    await mower.feedback.on_error_list('{"error_list":[{"code":202}]}')
    assert writes == old_writes


@pytest.mark.parametrize(
    "file_name",
    (
        "strings.json",
        "translations/en.json",
        "translations/de.json",
        "translations/zh-Hans.json",
        "translations/zh-CN.json",
    ),
)
def test_alarm_names_are_translated(file_name: str) -> None:
    """维护的语言文件都包含两个安全告警名称。"""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "terramow"
    names = json.loads((root / file_name).read_text(encoding="utf-8"))["entity"][
        "binary_sensor"
    ]
    assert names["lift_alarm"]["name"]
    assert names["anti_theft_boundary_alarm"]["name"]
