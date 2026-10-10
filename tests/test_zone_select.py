"""分区选择器的沿边作业与设备确认测试。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity
from custom_components.terramow.select import TerraMowZoneSelect


@pytest.fixture
def selector(hass: HomeAssistant) -> TerraMowZoneSelect:
    """用内存 MQTT 构造选择器，不向设备发送实际控制。"""
    mower = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.28", ""), hass)
    mower.mqtt_client = MagicMock()
    mower.mqtt_client.is_connected.return_value = True
    mower.mqtt_client.publish.return_value = SimpleNamespace(rc=0)
    mower._last_control_time = -100
    zone_select = TerraMowZoneSelect(mower.basic_data, hass)
    zone_select.async_write_ha_state = MagicMock()
    return zone_select


async def test_edge_cutting_is_listed_with_zones(selector: TerraMowZoneSelect) -> None:
    """地图刷新后保留原分区选项，并增加沿边作业入口。"""
    assert selector.options == ["no_zones_available"]
    await selector._on_map_info(
        {"regions": [{"sub_regions": [{"id": 7, "name": "Front"}]}]}
    )
    assert selector.options == ["all_zones", "edge_cutting", "Front (ID: 7)"]
    assert selector.current_option == "all_zones"


async def test_edge_cutting_is_available_without_zones(
    selector: TerraMowZoneSelect,
) -> None:
    """地图没有可选分区时，仍能发起整图沿边作业。"""
    await selector._on_map_info({"id": 1, "regions": []})
    assert selector.options == ["no_zones_available", "edge_cutting"]
    assert selector.current_option == "no_zones_available"


@pytest.mark.parametrize("ret", [0, -3])
@pytest.mark.parametrize("firmware", [{"module": {"control": 8}}, []])
async def test_edge_cutting_waits_for_device_reply(
    selector: TerraMowZoneSelect, ret: int, firmware: Any
) -> None:
    """只有设备确认接受，才把沿边作业显示为当前选项。"""
    await selector._on_map_info({"regions": [{"sub_regions": []}]})
    selector.basic_data.firmware_version = firmware
    mower = selector.basic_data.lawn_mower
    task = asyncio.create_task(selector.async_select_option("edge_cutting"))
    await asyncio.sleep(0)

    topic, payload = mower.mqtt_client.publish.call_args.args
    command = json.loads(payload)
    assert topic == "data_point/103/app"
    assert command == {"mode": "START_MODE_EDGE_TRIM_CLEAN", "seq": command["seq"]}
    assert selector.current_option == "all_zones"

    await mower.feedback.on_reply(
        json.dumps({"seq": command["seq"], "ret": ret}), dp_id=103
    )
    if ret:
        with pytest.raises(HomeAssistantError, match="ret=-3"):
            await task
        assert selector.current_option == "all_zones"
    else:
        await task
        assert selector.current_option == "edge_cutting"


@pytest.mark.parametrize("version", [7, "7"])
async def test_old_control_version_does_not_send_edge_command(
    selector: TerraMowZoneSelect, version: int | str
) -> None:
    """明确不支持沿边启动的固件不应收到该控制命令。"""
    await selector._on_map_info({"id": 1, "regions": []})
    selector.basic_data.firmware_version = {"module": {"control": version}}
    with pytest.raises(HomeAssistantError, match="control version 8"):
        await selector.async_select_option("edge_cutting")
    assert selector.current_option == "no_zones_available"
    selector.basic_data.lawn_mower.mqtt_client.publish.assert_not_called()


async def test_no_zones_placeholder_does_not_start_job(
    selector: TerraMowZoneSelect,
) -> None:
    """未收到可用地图时，占位选项不能发送作业命令。"""
    await selector.async_select_option("no_zones_available")
    selector.basic_data.lawn_mower.mqtt_client.publish.assert_not_called()


@pytest.mark.parametrize("locale", ["en", "de", "zh-Hans"])
def test_edge_cutting_has_translation(locale: str) -> None:
    """新增选项在发布的语言文件中都有可读名称。"""
    path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "terramow"
        / "translations"
        / f"{locale}.json"
    )
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert data["entity"]["select"]["region_select"]["state"]["edge_cutting"]
