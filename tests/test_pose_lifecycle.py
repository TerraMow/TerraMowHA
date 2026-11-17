"""姿态更新与实体卸载的生命周期回归测试。"""

import json
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.lawn_mower import POSE_TOPIC, TerraMowLawnMowerEntity
from custom_components.terramow.sensor import TerraMowPoseSensor


async def test_pose_sensor_stops_receiving_updates_after_removal(
    hass: HomeAssistant,
) -> None:
    """实体移除后，后续设备姿态不能继续写入已卸载的实体。"""
    mower = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.77", ""), hass)
    sensor = TerraMowPoseSensor(mower.basic_data, hass)
    sensor.entity_id = "sensor.test_pose_lifecycle"
    sensor.async_write_ha_state = MagicMock()
    await sensor.async_added_to_hass()

    message = MagicMock(
        topic=POSE_TOPIC,
        payload=json.dumps({"x": 12, "y": 34, "yaw": 1.2}).encode(),
    )
    mower.on_mqtt_message(None, None, message)
    await hass.async_block_till_done()
    assert sensor.native_value == 1.2
    sensor.async_write_ha_state.assert_called_once()

    queued_callback = mower.pose_callbacks[0]
    await sensor.async_remove(force_remove=True)
    assert mower.pose_callbacks == []
    sensor.hass = None
    await queued_callback({"x": 13, "y": 35, "yaw": 1.3})
    mower.on_mqtt_message(None, None, message)
    await hass.async_block_till_done()
    sensor.async_write_ha_state.assert_called_once()


async def test_pose_callback_ignores_entity_without_hass(hass: HomeAssistant) -> None:
    """尚未注册或已经卸载的实体不应因姿态消息写入状态。"""
    mower = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.78", ""), hass)
    sensor = TerraMowPoseSensor(mower.basic_data, hass)
    assert mower.pose_callbacks == []
    sensor.hass = None

    await sensor._on_pose({"x": 1, "y": 2, "yaw": 0.5})
