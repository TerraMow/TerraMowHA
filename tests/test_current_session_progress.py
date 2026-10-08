"""当前作业进度传感器的计算、即时更新与监听生命周期测试。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import CONF_HOST, CONF_PASSWORD, PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity
from custom_components.terramow.sensor import (
    CurrentSessionProgressSensor,
    async_setup_entry,
)


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """构造仅在内存中接收 dp_113 的割草机实体。"""
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.68", ""), hass)
    entity.schedule_update_ha_state = MagicMock()
    return entity


async def test_sensor_platform_adds_progress_entity(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """平台创建具备固定身份、单位和统计类型的诊断实体。"""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    progress_sensors = [
        entity
        for entity in add_entities.call_args.args[0]
        if isinstance(entity, CurrentSessionProgressSensor)
    ]
    assert len(progress_sensors) == 1
    sensor = progress_sensors[0]
    assert sensor.unique_id == (
        f"lawn_mower.terramow@{mower.host}.current_session_progress"
    )
    assert sensor.translation_key == "current_session_progress"
    assert sensor.native_unit_of_measurement == PERCENTAGE
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC


@pytest.mark.parametrize(
    ("work_data", "expected"),
    [
        ({}, None),
        ({"clean_area": 25}, None),
        ({"total_area": 0, "clean_area": 25}, None),
        ({"total_area": -1, "clean_area": 25}, None),
        ({"total_area": 100}, 0.0),
        ({"total_area": 200, "clean_area": 99}, 49.5),
        ({"total_area": 3, "clean_area": 2}, 66.7),
        ({"total_area": 100, "clean_area": 120}, 100.0),
    ],
)
async def test_progress_calculation(
    hass: HomeAssistant,
    mower: TerraMowLawnMowerEntity,
    work_data: dict,
    expected: float | None,
) -> None:
    """总面积无效时保持未知，其余结果保留一位小数且不超过 100%。"""
    sensor = CurrentSessionProgressSensor(mower.basic_data, hass)

    await mower.on_current_work_data(json.dumps(work_data))

    assert sensor.native_value == expected


async def test_updates_stop_after_entity_removal(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """有效上报立即刷新；无效上报与实体移除不会触发旧监听。"""
    mower.register_all_callbacks()
    sensor = CurrentSessionProgressSensor(mower.basic_data, hass)
    sensor.entity_id = "sensor.test_current_session_progress"
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    sensor.async_write_ha_state = write
    await sensor.async_added_to_hass()
    assert len(mower.callbacks[113]) == 1

    # 走 MQTT 消息分发路径，确认缓存处理先于实体刷新。
    mower.on_mqtt_message(
        None,
        None,
        SimpleNamespace(
            topic="data_point/113/robot",
            payload=b'{"total_area": 200, "clean_area": 50}',
            retain=False,
        ),
    )
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert sensor.native_value == 25.0
    assert writes == 1

    await mower.on_current_work_data("[]")
    await mower.on_current_work_data("not json")
    assert sensor.native_value == 25.0
    assert writes == 1

    await sensor.async_remove(force_remove=True)
    await mower.on_current_work_data('{"total_area": 200, "clean_area": 100}')
    assert sensor.native_value == 50.0
    assert writes == 1
    assert len(mower.callbacks[113]) == 1


async def test_sensor_can_load_before_mower(hass: HomeAssistant) -> None:
    """并发装载时先创建的传感器仍能收到后续作业上报。"""
    basic_data = TerraMowBasicData("192.0.2.69", "")
    sensor = CurrentSessionProgressSensor(basic_data, hass)
    sensor.entity_id = "sensor.test_current_session_progress_early"
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    sensor.async_write_ha_state = write
    await sensor.async_added_to_hass()
    assert not sensor.available
    assert sensor.native_value is None

    mower = TerraMowLawnMowerEntity(basic_data, hass)
    await mower.on_current_work_data('{"total_area": 400, "clean_area": 100}')
    assert sensor.available
    assert sensor.native_value == 25.0
    assert writes == 1
    await sensor.async_remove(force_remove=True)


@pytest.mark.parametrize(
    "file_name",
    [
        "strings.json",
        "translations/en.json",
        "translations/de.json",
        "translations/zh-Hans.json",
        "translations/zh-CN.json",
    ],
)
def test_progress_translation_exists(file_name: str) -> None:
    """所有已维护的语言文件都包含新诊断实体的名称。"""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "terramow"
    data = json.loads((root / file_name).read_text(encoding="utf-8"))
    assert data["entity"]["sensor"]["current_session_progress"]["name"]
