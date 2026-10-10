"""电池温度状态实体的上报、可用性和翻译契约。"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity
from custom_components.terramow.sensor import (
    BatteryTemperatureStateSensor,
    async_setup_entry,
)


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """只处理内存中的电池报告，不连接设备。"""
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.68", ""), hass)
    entity.schedule_update_ha_state = MagicMock()
    return entity


async def test_temperature_entity_is_registered(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """温度等级拥有独立且稳定的诊断实体标识。"""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    sensors = [
        entity
        for entity in add_entities.call_args.args[0]
        if isinstance(entity, BatteryTemperatureStateSensor)
    ]
    assert len(sensors) == 1
    assert sensors[0].unique_id == (
        f"lawn_mower.terramow@{mower.basic_data.stable_id}.battery_temperature_state"
    )
    assert sensors[0].translation_key == "battery_temperature_state"


async def test_temperature_updates_and_listener_cleanup(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """有效报告即时刷新；损坏数据不覆盖状态，移除后停止回调。"""
    sensor = BatteryTemperatureStateSensor(mower.basic_data, hass)
    sensor.entity_id = "sensor.test_battery_temperature_state"
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    sensor.async_write_ha_state = write
    await sensor.async_added_to_hass()
    mower.mqtt_connected = True

    for raw, expected in (
        ("BATTERY_TEMPRETURE_NORMAL", "normal"),
        ("BATTERY_TEMPRETURE_OVERHEAT", "overheat"),
        ("BATTERY_TEMPRETURE_UNDERHEAT", "underheat"),
        ("BATTERY_TEMPERATURE_NORMAL", "normal"),
    ):
        await mower.on_battery_status(json.dumps({"tempreture": raw}))
        assert sensor.native_value == expected
    assert writes == 4

    await mower.on_battery_status("[]")
    await mower.on_battery_status("not json")
    assert writes == 4
    assert sensor.native_value == "normal"

    await mower.on_battery_status('{"tempreture": "UNRECOGNIZED"}')
    assert sensor.native_value is None
    await sensor.async_remove(force_remove=True)
    await mower.on_battery_status('{"tempreture": "BATTERY_TEMPRETURE_NORMAL"}')
    assert writes == 5


async def test_temperature_connection_requires_fresh_report(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """断线不可用，重连后等待新的电池上报才恢复已知等级。"""
    sensor = BatteryTemperatureStateSensor(mower.basic_data, hass)
    sensor.entity_id = "sensor.test_temperature_connection"
    sensor.async_write_ha_state = callback(MagicMock())
    await sensor.async_added_to_hass()
    mower.mqtt_connected = True
    await mower.on_battery_status('{"tempreture": "BATTERY_TEMPRETURE_NORMAL"}')
    assert sensor.available
    assert sensor.native_value == "normal"

    client = MagicMock()
    mower.on_mqtt_disconnect(client, None, 1)
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert not sensor.available
    assert sensor.native_value is None

    with (
        patch.object(mower, "_request_compatibility_info"),
        patch.object(mower, "update_activity_from_state"),
    ):
        mower.on_mqtt_connect(client, None, None, 0)
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert sensor.available
    assert sensor.native_value is None

    await mower.on_battery_status('{"tempreture": "BATTERY_TEMPRETURE_OVERHEAT"}')
    assert sensor.native_value == "overheat"
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
def test_temperature_translation_keys(file_name: str) -> None:
    """所有语言的状态键与实体输出一致。"""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "terramow"
    data = json.loads((root / file_name).read_text(encoding="utf-8"))
    states = data["entity"]["sensor"]["battery_temperature_state"]["state"]
    assert set(states) == {"normal", "overheat", "underheat"}
