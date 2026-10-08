"""地图二元传感器的状态、连接可用性和监听生命周期测试。"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.binary_sensor import (
    TerraMowMapBackingUpBinarySensor,
    TerraMowMapBuildableBinarySensor,
    TerraMowMapDetectedBinarySensor,
    async_setup_entry,
)
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity

_MAP_SENSOR_TYPES = (
    TerraMowMapDetectedBinarySensor,
    TerraMowMapBuildableBinarySensor,
    TerraMowMapBackingUpBinarySensor,
)


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """构造不连接真实 MQTT 的割草机实体。"""
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.66", ""), hass)
    entity.schedule_update_ha_state = MagicMock()
    return entity


async def test_platform_adds_map_binary_sensors(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """三项地图标志各有稳定且互不冲突的实体标识。"""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    entities = add_entities.call_args.args[0]
    map_sensors = [
        entity for entity in entities if isinstance(entity, _MAP_SENSOR_TYPES)
    ]
    assert [type(entity) for entity in map_sensors] == list(_MAP_SENSOR_TYPES)
    assert len({entity.unique_id for entity in map_sensors}) == 3


async def test_sensor_can_load_before_mower(hass: HomeAssistant) -> None:
    """平台并发装载时，先创建的传感器仍能收到后续地图上报。"""
    basic_data = TerraMowBasicData("192.0.2.67", "")
    sensor = TerraMowMapDetectedBinarySensor(basic_data, hass)
    sensor.entity_id = "binary_sensor.test_map_detected_early"
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    sensor.async_write_ha_state = write
    await sensor.async_added_to_hass()
    assert not sensor.available
    assert sensor.is_on is None
    assert sensor.device_info["identifiers"] == {("TerraMowLawnMower", basic_data.host)}

    mower = TerraMowLawnMowerEntity(basic_data, hass)
    mower.mqtt_connected = True
    await mower.on_map_status('{"is_map_detected": true}')
    assert sensor.available
    assert sensor.is_on is True
    assert writes == 1
    await sensor.async_remove(force_remove=True)


async def test_map_flags_update_and_removed_sensor_unsubscribes(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """只在有效上报后推送状态，移除单个实体不会留下旧监听。"""
    sensors = [sensor(mower.basic_data, hass) for sensor in _MAP_SENSOR_TYPES]
    writes = [0, 0, 0]

    def make_write(index: int):
        @callback
        def write() -> None:
            writes[index] += 1

        return write

    mower.mqtt_connected = True
    for index, sensor in enumerate(sensors):
        sensor.entity_id = f"binary_sensor.test_{sensor._unique_suffix}"
        sensor.async_write_ha_state = make_write(index)
        await sensor.async_added_to_hass()

    assert all(sensor.available for sensor in sensors)
    await mower.on_map_status(
        json.dumps(
            {
                "is_map_detected": True,
                "is_able_to_run_build_map": False,
                "is_backing_up_map": True,
            }
        )
    )
    assert [sensor.is_on for sensor in sensors] == [True, False, True]
    assert writes == [1, 1, 1]

    await sensors[1].async_remove(force_remove=True)
    await mower.on_map_status(
        json.dumps(
            {
                "is_map_detected": False,
                "is_able_to_run_build_map": True,
                "is_backing_up_map": False,
            }
        )
    )
    assert [sensor.is_on for sensor in sensors] == [False, True, False]
    assert writes == [2, 1, 2]

    # 列表和损坏的 JSON 不应替换上一轮地图缓存或触发状态推送。
    await mower.on_map_status("[]")
    await mower.on_map_status("not json")
    assert writes == [2, 1, 2]
    assert [sensor.is_on for sensor in sensors] == [False, True, False]

    await sensors[0].async_remove(force_remove=True)
    await sensors[2].async_remove(force_remove=True)


async def test_connection_changes_map_sensor_availability(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """连接与断开都及时刷新可用性，不把缓存值当作在线状态。"""
    sensor = TerraMowMapDetectedBinarySensor(mower.basic_data, hass)
    sensor.entity_id = "binary_sensor.test_map_detected"
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    sensor.async_write_ha_state = write
    await sensor.async_added_to_hass()
    assert not sensor.available

    client = MagicMock()
    with (
        patch.object(mower, "_request_compatibility_info"),
        patch.object(mower, "update_activity_from_state"),
    ):
        mower.on_mqtt_connect(client, None, None, 0)
    await hass.async_block_till_done()
    assert sensor.available
    assert writes == 1

    await mower.on_map_status('{"is_map_detected": true}')
    assert sensor.is_on is True
    assert writes == 2

    mower.on_mqtt_disconnect(client, None, 1)
    await hass.async_block_till_done()
    assert not sensor.available
    assert sensor.is_on is None
    assert writes == 3

    with (
        patch.object(mower, "_request_compatibility_info"),
        patch.object(mower, "update_activity_from_state"),
    ):
        mower.on_mqtt_connect(client, None, None, 0)
    await hass.async_block_till_done()
    assert sensor.available
    assert sensor.is_on is None
    assert writes == 4

    await mower.on_map_status('{"is_map_detected": false}')
    assert sensor.is_on is False
    assert writes == 5
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
def test_map_binary_sensor_translation_keys(
    file_name: str, hass: HomeAssistant
) -> None:
    """所有已维护的语言文件都能命名三个新实体。"""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "terramow"
    data = json.loads((root / file_name).read_text(encoding="utf-8"))
    names = data["entity"]["binary_sensor"]
    for sensor_type in _MAP_SENSOR_TYPES:
        sensor = sensor_type(TerraMowBasicData("192.0.2.66", ""), hass)
        assert names[sensor.translation_key]["name"]
