"""当前作业进度传感器：与 TerraMow App 进度环一致的取值、四路即时刷新和监听生命周期。"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import CONF_HOST, CONF_PASSWORD, PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity
from custom_components.terramow.sensor import (
    CurrentSessionProgressSensor,
    async_setup_entry,
)

CLEANING = "MAP_AREA_TYPE_CLEANING"
SELECT_REGION = "MAP_AREA_TYPE_SELECT_REGION_CLEANING"
BUILD_MAP = "MAP_AREA_TYPE_BUILD_MAP"
BUILD_MAP_AND_CLEANING = "MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING"
NO_AREA = "MAP_AREA_TYPE_NONE"
DRAW_REGION = "MAP_AREA_TYPE_DRAW_REGION_CLEANING"
EDGE_TRIM = "MAP_AREA_TYPE_EDGE_TRIM_CLEANING"

MAP_COMPLETE = {
    "is_map_detected": True,
    "map_id": 1,
    "map_state": "MAP_STATE_COMPLETE",
    "is_able_to_run_build_map": False,
}
GLOBAL_MODE = {
    "move_mode": "MOVE_MODE_MOW",
    "map_mode": "MAP_MODE_BASE_STATION",
    "mow_mode": "MOW_MODE_GLOBAL",
}


def work(area_type: str, total: int, clean: int, done: bool = False) -> dict:
    """按设备 dp_113 的字段构造作业数据（面积单位 0.1 平方米）。"""
    return {
        "type": area_type,
        "total_area": total,
        "clean_area": clean,
        "is_completed": done,
        "work_duration": 600,
    }


async def feed(
    mower: TerraMowLawnMowerEntity,
    *,
    work_data: dict | None = None,
    map_status: dict | None = MAP_COMPLETE,
    work_mode: dict | None = GLOBAL_MODE,
    mission: str | None = None,
    sub_mission: str = "SUB_MISSION_IDLE",
) -> None:
    """按设备上报灌入四路数据；传 None 表示该路尚未上报。"""
    mower.mqtt_connected = True
    if map_status is not None:
        await mower.on_map_status(json.dumps(map_status))
    if work_mode is not None:
        await mower.on_work_mode(json.dumps(work_mode))
    if work_data is not None:
        await mower.on_current_work_data(json.dumps(work_data))
    if mission is not None:
        await mower.on_mission_status(
            json.dumps(
                {
                    "mission": mission,
                    "sub_mission": sub_mission,
                    "state": "MISSION_STATE_RUNNING",
                }
            )
        )


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    """构造仅在内存中接收设备上报的割草机实体。"""
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.68", ""), hass)
    entity.schedule_update_ha_state = MagicMock()
    return entity


@pytest.fixture
def sensor(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> CurrentSessionProgressSensor:
    """尚未加入 HA 的传感器，仅用于检查计算结果。"""
    return CurrentSessionProgressSensor(mower.basic_data, hass)


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
    entity = progress_sensors[0]
    assert entity.unique_id == (
        f"lawn_mower.terramow@{mower.host}.current_session_progress"
    )
    assert entity.translation_key == "current_session_progress"
    assert entity.native_unit_of_measurement == PERCENTAGE
    assert entity.state_class == SensorStateClass.MEASUREMENT
    assert entity.entity_category == EntityCategory.DIAGNOSTIC
    assert not entity.should_poll


@pytest.mark.parametrize(
    ("work_data", "expected"),
    [
        # 进行中：按面积比，未完成时最高 98%。
        (work(CLEANING, 3000, 0), 0.0),
        (work(CLEANING, 3000, 1500), 50.0),
        (work(CLEANING, 3000, 2900), 96.7),
        (work(CLEANING, 3000, 2999), 98.0),
        (work(CLEANING, 3000, 3100), 98.0),
        (work(SELECT_REGION, 1200, 600), 50.0),
        # 模拟器自然样本：新作业刚开始，以及作业进行中。
        (work(CLEANING, 2457, 24), 1.0),
        (work(CLEANING, 2450, 246), 10.0),
        # 设备报告已完成才是 100%，即使面积没有达到总面积。
        (work(SELECT_REGION, 2451, 2027, True), 100.0),
        (work(CLEANING, 3000, 3000, True), 100.0),
        (work(CLEANING, 0, 0, True), 100.0),
        # 总面积缺失或为 0：App 以 0 计，不报错。
        (work(CLEANING, 0, 100), 0.0),
        ({"type": CLEANING, "clean_area": 100}, 0.0),
        ({"type": CLEANING, "total_area": None, "clean_area": None}, 0.0),
        # 地图已建完时，建图类面积不代表割草进度。
        (work(BUILD_MAP, 500, 0), 0.0),
        (work(BUILD_MAP_AND_CLEANING, 400, 100), 0.0),
        (work(BUILD_MAP_AND_CLEANING, 400, 400, True), 0.0),
    ],
)
async def test_progress_follows_app_rules(
    mower: TerraMowLawnMowerEntity,
    sensor: CurrentSessionProgressSensor,
    work_data: dict,
    expected: float,
) -> None:
    """全局割草、地图已建完时，取值与 App 进度环一致。"""
    await feed(mower, work_data=work_data)

    assert sensor.available
    assert sensor.native_value == expected


async def test_build_types_use_ratio_without_valid_map_id(
    mower: TerraMowLawnMowerEntity, sensor: CurrentSessionProgressSensor
) -> None:
    """App 仅在地图编号有效时才把建图类面积记为 0；无效编号退回面积比。"""
    await feed(
        mower,
        work_data=work(BUILD_MAP_AND_CLEANING, 400, 100),
        map_status={**MAP_COMPLETE, "map_id": -1},
    )

    assert sensor.native_value == 25.0


async def test_waiting_for_daylight_is_zero(
    mower: TerraMowLawnMowerEntity, sensor: CurrentSessionProgressSensor
) -> None:
    """等待日照时 App 进度环归零，优先于面积比和完成标志。"""
    await feed(
        mower,
        work_data=work(CLEANING, 3000, 1500, True),
        mission="MISSION_GLOBAL_CLEAN",
        sub_mission="SUB_MISSION_WAIT_FOR_DAYLIGHT",
    )

    assert sensor.native_value == 0.0


@pytest.mark.parametrize(
    ("map_status", "work_mode", "mission"),
    [
        # 地图未检测、未建完，或仍可建图：App 不显示进度环。
        ({**MAP_COMPLETE, "is_map_detected": False}, GLOBAL_MODE, None),
        ({**MAP_COMPLETE, "map_state": "MAP_STATE_INCOMPLETE"}, GLOBAL_MODE, None),
        ({**MAP_COMPLETE, "map_state": "MAP_STATE_EMPTY"}, GLOBAL_MODE, None),
        ({**MAP_COMPLETE, "is_able_to_run_build_map": True}, GLOBAL_MODE, None),
        ({}, GLOBAL_MODE, None),
        # Spot 模式、划区、沿边，以及未来固件新增的割草模式。
        (MAP_COMPLETE, {**GLOBAL_MODE, "map_mode": "MAP_MODE_SPOT"}, None),
        (MAP_COMPLETE, {**GLOBAL_MODE, "mow_mode": "MOW_MODE_DRAW_REGION"}, None),
        (MAP_COMPLETE, {**GLOBAL_MODE, "mow_mode": "MOW_MODE_EDGE_TRIM"}, None),
        (MAP_COMPLETE, {**GLOBAL_MODE, "mow_mode": "MOW_MODE_FUTURE_MODE"}, None),
        # 边建图边作业任务。
        (MAP_COMPLETE, GLOBAL_MODE, "MISSION_BUILD_MAP_AND_CLEAN"),
    ],
)
async def test_progress_hidden_when_app_hides_ring(
    mower: TerraMowLawnMowerEntity,
    sensor: CurrentSessionProgressSensor,
    map_status: dict,
    work_mode: dict,
    mission: str | None,
) -> None:
    """App 不显示进度环的场景，传感器为未知，且不沿用面积比。"""
    await feed(
        mower,
        work_data=work(CLEANING, 3000, 1500),
        map_status=map_status,
        work_mode=work_mode,
        mission=mission,
    )

    assert sensor.native_value is None


@pytest.mark.parametrize("is_completed", [False, True])
@pytest.mark.parametrize("area_type", [NO_AREA, DRAW_REGION, EDGE_TRIM])
@pytest.mark.parametrize(
    "work_mode",
    [
        None,  # 尚未收到 dp_154
        {},
        GLOBAL_MODE,  # 上一次作业遗留的快照，新作业的 dp_113 还没到
        {**GLOBAL_MODE, "mow_mode": "MOW_MODE_SELECT_REGION"},
    ],
)
async def test_area_types_without_valid_total_are_unknown(
    mower: TerraMowLawnMowerEntity,
    sensor: CurrentSessionProgressSensor,
    work_mode: dict | None,
    area_type: str,
    is_completed: bool,
) -> None:
    """协议规定这些类型的总面积无效；无论工作模式是否已知，都不据此算出比例。"""
    await feed(
        mower,
        work_data=work(area_type, 900, 450, is_completed),
        work_mode=work_mode,
    )

    assert sensor.available
    assert sensor.native_value is None


async def test_invalid_area_type_does_not_block_the_next_session(
    mower: TerraMowLawnMowerEntity, sensor: CurrentSessionProgressSensor
) -> None:
    """划区快照先于 dp_154 到达时为未知；新的全局作业数据到达后恢复显示。"""
    await feed(mower, work_data=work(DRAW_REGION, 900, 450), work_mode=None)
    assert sensor.native_value is None

    await mower.on_work_mode(
        json.dumps({**GLOBAL_MODE, "mow_mode": "MOW_MODE_DRAW_REGION"})
    )
    assert sensor.native_value is None

    # 模式已切回全局，但设备还没发布新作业的 dp_113，旧的划区快照不能算出比例。
    await mower.on_work_mode(json.dumps(GLOBAL_MODE))
    assert sensor.native_value is None

    await mower.on_current_work_data(json.dumps(work(CLEANING, 2457, 24)))
    assert sensor.native_value == 1.0


@pytest.mark.parametrize(
    "work_mode",
    [
        None,
        {},
        {"move_mode": "MOVE_MODE_MOW", "map_mode": "MAP_MODE_BASE_STATION"},
        {**GLOBAL_MODE, "mow_mode": "MOW_MODE_SELECT_REGION"},
        # 地图已建完且不可建图时，App 不看 move_mode。
        {**GLOBAL_MODE, "move_mode": "MOVE_MODE_MAPPING"},
    ],
)
async def test_work_mode_defaults_do_not_hide_progress(
    mower: TerraMowLawnMowerEntity,
    sensor: CurrentSessionProgressSensor,
    work_mode: dict | None,
) -> None:
    """未收到 dp_154 或旧固件缺少 mow_mode 时按默认的全局割草处理。"""
    await feed(mower, work_data=work(CLEANING, 3000, 1500), work_mode=work_mode)

    assert sensor.native_value == 50.0


async def test_unknown_until_work_data_arrives(
    mower: TerraMowLawnMowerEntity, sensor: CurrentSessionProgressSensor
) -> None:
    """尚未收到任何作业数据时为未知，而不是 0%。"""
    await feed(mower)

    assert sensor.available
    assert sensor.native_value is None


async def test_completed_snapshot_lasts_until_new_work_data(
    mower: TerraMowLawnMowerEntity, sensor: CurrentSessionProgressSensor
) -> None:
    """设备在新作业的 dp_113 到达前仍保留上次完成快照，传感器与 App 一致。"""
    await feed(
        mower,
        work_data=work(SELECT_REGION, 2451, 2027, True),
        mission="MISSION_IDLE",
    )
    assert sensor.native_value == 100.0

    # 新的作业已被设备受理，但新的 dp_113 还没有发布。
    await feed(mower, mission="MISSION_GLOBAL_CLEAN", sub_mission="SUB_MISSION_IDLE")
    assert sensor.native_value == 100.0

    await mower.on_current_work_data(json.dumps(work(CLEANING, 2457, 24)))
    assert sensor.native_value == 1.0


def test_signal_names_match_mower(
    mower: TerraMowLawnMowerEntity, sensor: CurrentSessionProgressSensor
) -> None:
    """传感器按主机标识拼出的信号名必须与割草机发送的完全一致。"""
    subscribed = {f"terramow_{mower.host}_{name}" for name in sensor._SIGNALS}

    assert subscribed == {
        mower.current_work_data_signal,
        mower.map_status_signal,
        mower.mission_signal,
        mower.work_mode_signal,
    }


async def test_each_report_refreshes_and_removal_unsubscribes(
    hass: HomeAssistant,
    mower: TerraMowLawnMowerEntity,
    sensor: CurrentSessionProgressSensor,
) -> None:
    """四路有效上报各自立即刷新一次；无效上报不刷新；实体移除后不再监听。"""
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    sensor.entity_id = "sensor.test_current_session_progress"
    sensor.async_write_ha_state = write
    mower.register_all_callbacks()
    await sensor.async_added_to_hass()
    mower.mqtt_connected = True

    await mower.on_map_status(json.dumps(MAP_COMPLETE))
    assert writes == 1
    await mower.on_work_mode(json.dumps(GLOBAL_MODE))
    assert writes == 2
    await mower.on_current_work_data(json.dumps(work(CLEANING, 200, 50)))
    assert writes == 3
    assert sensor.native_value == 25.0

    await mower.on_mission_status(
        json.dumps(
            {
                "mission": "MISSION_GLOBAL_CLEAN",
                "sub_mission": "SUB_MISSION_WAIT_FOR_DAYLIGHT",
                "state": "MISSION_STATE_RUNNING",
            }
        )
    )
    assert writes == 4
    assert sensor.native_value == 0.0

    # 工作模式变化立即让进度隐藏，再恢复。
    await mower.on_work_mode(
        json.dumps({**GLOBAL_MODE, "mow_mode": "MOW_MODE_EDGE_TRIM"})
    )
    assert writes == 5
    assert sensor.native_value is None
    await mower.on_work_mode(json.dumps(GLOBAL_MODE))
    assert writes == 6
    assert sensor.native_value == 0.0

    # 列表和损坏的 JSON 不替换缓存，也不触发刷新。
    for handler in (
        mower.on_current_work_data,
        mower.on_map_status,
        mower.on_work_mode,
    ):
        await handler("[]")
        await handler("not json")
    assert writes == 6

    await sensor.async_remove(force_remove=True)
    await mower.on_current_work_data(json.dumps(work(CLEANING, 200, 100)))
    await mower.on_map_status(json.dumps(MAP_COMPLETE))
    await mower.on_work_mode(json.dumps(GLOBAL_MODE))
    await mower.on_mission_status(
        json.dumps({"mission": "MISSION_IDLE", "state": "MISSION_STATE_IDLE"})
    )
    assert writes == 6
    # 割草机自己的回调保持各一个，不随传感器增减。
    assert [len(mower.callbacks[dp]) for dp in (107, 113, 117, 154)] == [1, 1, 1, 1]


async def test_mqtt_message_path_updates_sensor(
    hass: HomeAssistant,
    mower: TerraMowLawnMowerEntity,
    sensor: CurrentSessionProgressSensor,
) -> None:
    """走真实的 MQTT 消息分发路径，缓存先于刷新，并且 dp_154 已被订阅处理。"""
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    sensor.entity_id = "sensor.test_current_session_progress_mqtt"
    sensor.async_write_ha_state = write
    mower.register_all_callbacks()
    await sensor.async_added_to_hass()
    mower.mqtt_connected = True

    def deliver(dp_id: int, payload: dict) -> None:
        msg = MagicMock(
            topic=f"data_point/{dp_id}/robot",
            payload=json.dumps(payload).encode(),
            retain=True,
        )
        mower.on_mqtt_message(None, None, msg)

    deliver(117, MAP_COMPLETE)
    deliver(113, work(SELECT_REGION, 2451, 2027, True))
    deliver(154, {**GLOBAL_MODE, "mow_mode": "MOW_MODE_SELECT_REGION"})
    await asyncio.sleep(0)
    await hass.async_block_till_done()

    assert writes == 3
    assert sensor.native_value == 100.0
    await sensor.async_remove(force_remove=True)


async def test_work_mode_payloads(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """有效对象写入缓存并发信号；列表和损坏的 JSON 被忽略。"""
    signals = 0

    @callback
    def count() -> None:
        nonlocal signals
        signals += 1

    unsubscribe = async_dispatcher_connect(hass, mower.work_mode_signal, count)
    assert mower.work_mode == {}

    await mower.on_work_mode(json.dumps(GLOBAL_MODE))
    assert mower.work_mode == GLOBAL_MODE
    assert signals == 1

    await mower.on_work_mode("[]")
    await mower.on_work_mode("not json")
    assert mower.work_mode == GLOBAL_MODE
    assert signals == 1
    unsubscribe()


async def test_sensor_can_load_before_mower(hass: HomeAssistant) -> None:
    """并发装载时先创建的传感器仍能收到割草机建立后的上报。"""
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
    mower.schedule_update_ha_state = MagicMock()
    await feed(mower, work_data=work(CLEANING, 400, 100))
    assert sensor.available
    assert sensor.native_value == 25.0
    assert writes == 3
    await sensor.async_remove(force_remove=True)


async def test_connection_changes_availability_and_wait_for_fresh_map(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    """断线即不可用；重连后先等新的地图状态，再恢复显示，不沿用断线前的结论。"""
    sensor = CurrentSessionProgressSensor(mower.basic_data, hass)
    sensor.entity_id = "sensor.test_current_session_progress_connection"
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    sensor.async_write_ha_state = write
    await sensor.async_added_to_hass()
    assert not sensor.available

    async def settle() -> None:
        # HA 2025.3 的 add_job 先排入任务，再在下一轮执行回调。
        await asyncio.sleep(0)
        await hass.async_block_till_done()

    client = MagicMock()

    def connect() -> None:
        with (
            patch.object(mower, "_request_compatibility_info"),
            patch.object(mower, "update_activity_from_state"),
        ):
            mower.on_mqtt_connect(client, None, None, 0)

    connect()
    await settle()
    assert sensor.available
    assert sensor.native_value is None
    assert writes == 1

    await mower.on_map_status(json.dumps(MAP_COMPLETE))
    await mower.on_work_mode(json.dumps(GLOBAL_MODE))
    await mower.on_current_work_data(json.dumps(work(CLEANING, 200, 100)))
    assert sensor.native_value == 50.0
    assert writes == 4

    mower.on_mqtt_disconnect(client, None, 1)
    await settle()
    assert not sensor.available
    assert sensor.native_value is None
    assert writes == 5

    # 重连：已可用，但地图状态要等设备重新上报（retained 快照）才恢复。
    connect()
    await settle()
    assert sensor.available
    assert sensor.native_value is None
    assert writes == 6

    await mower.on_map_status(json.dumps(MAP_COMPLETE))
    assert sensor.native_value == 50.0
    assert writes == 7
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
