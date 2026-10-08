"""任务诊断传感器的状态同步、监听生命周期和翻译契约。"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity
from custom_components.terramow.sensor import (
    TerraMowMissionSensor,
    TerraMowMissionStateSensor,
    TerraMowSubMissionSensor,
    async_setup_entry,
)


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """构造只在内存中处理 dp_107 的割草机，不连接 MQTT。"""
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.65", ""), hass)
    entity.schedule_update_ha_state = MagicMock()
    return entity


async def test_sensor_platform_adds_mission_entities(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """平台装载时创建三个可被实体注册表识别的诊断传感器。"""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    entities = add_entities.call_args.args[0]
    mission_entities = [
        entity for entity in entities if isinstance(entity, _MISSION_SENSOR_TYPES)
    ]
    assert [type(entity) for entity in mission_entities] == list(_MISSION_SENSOR_TYPES)
    assert len({entity.unique_id for entity in mission_entities}) == 3


_MISSION_SENSOR_TYPES = (
    TerraMowMissionSensor,
    TerraMowSubMissionSensor,
    TerraMowMissionStateSensor,
)


async def test_mission_sensors_update_and_unsubscribe(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """解析后的状态立即推送；实体移除后不再触发旧监听。"""
    sensors = [sensor(mower.basic_data, hass) for sensor in _MISSION_SENSOR_TYPES]
    writes = [0, 0, 0]

    def make_write(index: int):
        # 与真实实体一致，在 HA 事件循环内直接执行，避免测试替身进入线程池。
        @callback
        def write() -> None:
            writes[index] += 1

        return write

    for index, sensor in enumerate(sensors):
        sensor.entity_id = f"sensor.test_{sensor._unique_suffix}"
        sensor.async_write_ha_state = make_write(index)
        await sensor.async_added_to_hass()

    await mower.on_mission_status(
        json.dumps(
            {
                "mission": "MISSION_GLOBAL_CLEAN",
                "sub_mission": "SUB_MISSION_WAIT_FOR_RAIN_TO_STOP",
                "state": "MISSION_STATE_PAUSE",
            }
        )
    )
    assert [sensor.native_value for sensor in sensors] == [
        "mission_global_clean",
        "sub_mission_wait_for_rain_to_stop",
        "mission_state_pause",
    ]
    assert [sensor.extra_state_attributes["protocol_value"] for sensor in sensors] == [
        "MISSION_GLOBAL_CLEAN",
        "SUB_MISSION_WAIT_FOR_RAIN_TO_STOP",
        "MISSION_STATE_PAUSE",
    ]
    assert writes == [1, 1, 1]

    # 模拟用户单独禁用子任务实体，验证设备继续上报时不会更新旧实体。
    await sensors[1].async_remove(force_remove=True)
    await mower.on_mission_status(
        json.dumps(
            {
                "mission": "MISSION_RECHARGE",
                "sub_mission": "SUB_MISSION_RETURN_TO_BASE",
                "state": "MISSION_STATE_RUNNING",
            }
        )
    )
    assert [sensor.native_value for sensor in sensors] == [
        "mission_recharge",
        "sub_mission_return_to_base",
        "mission_state_running",
    ]
    assert writes == [2, 1, 2]

    await sensors[0].async_remove(force_remove=True)
    await sensors[2].async_remove(force_remove=True)


@pytest.mark.parametrize(
    "file_name",
    [
        "strings.json",
        "translations/en.json",
        "translations/de.json",
        "translations/zh-Hans.json",
    ],
)
def test_mission_translation_keys_match_options(
    file_name: str, hass: HomeAssistant
) -> None:
    """显示状态与翻译键一一对应，原始枚举另存于属性。"""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "terramow"
    data = json.loads((root / file_name).read_text(encoding="utf-8"))
    basic_data = TerraMowBasicData("192.0.2.65", "")
    sensors = (sensor(basic_data, hass) for sensor in _MISSION_SENSOR_TYPES)
    for sensor in sensors:
        states = data["entity"]["sensor"][sensor.translation_key]["state"]
        assert set(states) == set(sensor.options)
