"""Enum states must be lowercase so Home Assistant can translate them."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity
from custom_components.terramow.map_sensor import (
    TerraMowCleanModeSensor,
    TerraMowMapStatusSensor,
)
from custom_components.terramow.select import (
    BladeSpeedSelect,
    MainDirectionModeSelect,
    MowSpeedSelect,
)
from custom_components.terramow.sensor import (
    MainDirectionStatusSensor,
    TerraMowMowSpeedSensor,
)

EN = json.loads(
    (
        Path(__file__).parents[1] / "custom_components/terramow/translations/en.json"
    ).read_text()
)


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """Mower with in-memory MQTT and typical device parameters."""
    mower = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.28", ""), hass)
    mower.mqtt_client = MagicMock()
    mower.mqtt_client.is_connected.return_value = True
    mower.mqtt_client.publish.return_value = SimpleNamespace(rc=0)
    mower._global_params = {
        "mow_speed": {"speed_type": "MOW_SPEED_TYPE_LOW"},
        "blade_disk_speed": {"speed_type": "BLADE_DISK_SPEED_TYPE_MEDIUM"},
        "main_direction_angle_config": {"mode": "MAIN_DIRECTION_MODE_MULTIPLE"},
    }
    mower._map_status = {"map_state": "MAP_STATE_COMPLETE"}
    return mower


@pytest.mark.parametrize(
    ("cls", "platform", "expected"),
    [
        (MowSpeedSelect, "select", "mow_speed_type_low"),
        (BladeSpeedSelect, "select", "blade_disk_speed_type_medium"),
        (MainDirectionModeSelect, "select", "main_direction_mode_multiple"),
        (TerraMowMowSpeedSensor, "sensor", "mow_speed_type_low"),
        (MainDirectionStatusSensor, "sensor", "main_direction_mode_multiple"),
        (TerraMowMapStatusSensor, "sensor", "map_state_complete"),
    ],
)
def test_states_are_translatable(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, cls, platform, expected
) -> None:
    """Reported state and all options exist as translation keys."""
    entity = cls(mower.basic_data, hass)
    states = EN["entity"][platform][entity.translation_key]["state"]
    value = entity.current_option if platform == "select" else entity.native_value
    assert value == expected
    assert value in states
    for option in getattr(entity, "options", None) or []:
        assert option in states


def test_clean_mode_is_translatable(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """Clean mode sensor reports lowercase translation keys."""
    sensor = TerraMowCleanModeSensor(mower.basic_data, hass)
    sensor._map_info = {"clean_info": {"mode": "MAP_CLEAN_INFO_MODE_GLOBAL"}}
    states = EN["entity"]["sensor"]["clean_mode"]["state"]
    assert sensor.native_value == "map_clean_info_mode_global"
    assert set(sensor.options) <= set(states)


@pytest.mark.parametrize(
    ("cls", "option", "key", "device_value"),
    [
        (MowSpeedSelect, "mow_speed_type_medium", "mow_speed", "MOW_SPEED_TYPE_MEDIUM"),
        (
            BladeSpeedSelect,
            "blade_disk_speed_type_high",
            "blade_disk_speed",
            "BLADE_DISK_SPEED_TYPE_HIGH",
        ),
    ],
)
async def test_select_sends_device_value(
    hass: HomeAssistant,
    mower: TerraMowLawnMowerEntity,
    cls,
    option,
    key,
    device_value,
) -> None:
    """Lowercase HA option is sent to the device in its original form."""
    entity = cls(mower.basic_data, hass)
    entity.async_write_ha_state = MagicMock()
    mower.publish_data_point = MagicMock()
    await entity.async_select_option(option)
    mower.publish_data_point.assert_called_once_with(
        155, {key: {"speed_type": device_value}}
    )
