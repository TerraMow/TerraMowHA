import threading
import asyncio
import paho.mqtt.client as mqtt_client
import logging
import time
import re
import gzip
import json
import random
from typing import Callable, Any
from homeassistant.components.lawn_mower import LawnMowerEntity
from homeassistant.components.lawn_mower.const import LawnMowerActivity, LawnMowerEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import TerraMowBasicData
from homeassistant.config_entries import ConfigEntry
from .const import (
    MQTT_PORT,
    MQTT_USERNAME,
    DOMAIN,
    COMPATIBILITY_INFO_DP,
    CompatibilityStatus,
    MODEL_NAME_TOPIC,
    MAP_INFO_TOPIC,
    MAP_META_TOPIC,
    PATH_META_TOPIC,
    PATH_HISTORY_META_TOPIC,
    POSE_TOPIC,
)

_LOGGER = logging.getLogger(__name__)

# 定义正则表达式模式
TOPIC_PATTERN = re.compile(r"^data_point/(\d+)/robot$")

from enum import Enum

class Mission(Enum):
    MISSION_IDLE = "MISSION_IDLE"
    MISSION_RECHARGE = "MISSION_RECHARGE"
    MISSION_GLOBAL_CLEAN = "MISSION_GLOBAL_CLEAN"
    MISSION_BUILD_MAP = "MISSION_BUILD_MAP"
    MISSION_BUILD_MAP_AND_CLEAN = "MISSION_BUILD_MAP_AND_CLEAN"
    MISSION_TEMPORARY_CLEAN = "MISSION_TEMPORARY_CLEAN"
    MISSION_BACK_TO_STARTING_POINT = "MISSION_BACK_TO_STARTING_POINT"
    MISSION_REMOTE_CONTROL_CLEAN = "MISSION_REMOTE_CONTROL_CLEAN"
    MISSION_SCHEDULE_GLOBAL_CLEAN = "MISSION_SCHEDULE_GLOBAL_CLEAN"
    MISSION_SCHEDULE_BUILD_MAP_AND_CLEAN = "MISSION_SCHEDULE_BUILD_MAP_AND_CLEAN"
    MISSION_SELECT_REGION_CLEAN = "MISSION_SELECT_REGION_CLEAN"
    MISSION_CREATE_CUSTOM_PASSAGE = "MISSION_CREATE_CUSTOM_PASSAGE"
    MISSION_BACKUP_MAP = "MISSION_BACKUP_MAP"
    MISSION_RELOCATE_BASE_STATION = "MISSION_RELOCATE_BASE_STATION"
    MISSION_USER_AUTO_CALIBRATION = "MISSION_USER_AUTO_CALIBRATION"
    MISSION_RESTORE_BACKUP_MAP = "MISSION_RESTORE_BACKUP_MAP"
    MISSION_SCHEDULE_SELECT_REGION_CLEAN = "MISSION_SCHEDULE_SELECT_REGION_CLEAN"
    MISSION_DRAW_REGION_CLEAN = "MISSION_DRAW_REGION_CLEAN"
    MISSION_EDGE_TRIM_CLEAN = "MISSION_EDGE_TRIM_CLEAN"
    MISSION_UPDATE_BACKUP_MAP = "MISSION_UPDATE_BACKUP_MAP"

class SubMission(Enum):
    SUB_MISSION_IDLE = "SUB_MISSION_IDLE"
    SUB_MISSION_RELOCATION = "SUB_MISSION_RELOCATION"
    SUB_MISSION_RETURN_TO_BASE = "SUB_MISSION_RETURN_TO_BASE"
    SUB_MISSION_OUT_OF_STATION = "SUB_MISSION_OUT_OF_STATION"
    SUB_MISSION_REMOTE_CONTROL = "SUB_MISSION_REMOTE_CONTROL"
    SUB_MISSION_SAVING_MAP = "SUB_MISSION_SAVING_MAP"
    SUB_MISSION_SETTING_BLADE_HEIGHT = "SUB_MISSION_SETTING_BLADE_HEIGHT"
    SUB_MISSION_CHARGING = "SUB_MISSION_CHARGING"
    SUB_MISSION_REMOTE_CONTROL_CLEAN = "SUB_MISSION_REMOTE_CONTROL_CLEAN"
    SUB_MISSION_DEFOGGING = "SUB_MISSION_DEFOGGING"
    SUB_MISSION_WAIT_FOR_DAYLIGHT = "SUB_MISSION_WAIT_FOR_DAYLIGHT"
    SUB_MISSION_COOLING_DOWN_MOTOR = "SUB_MISSION_COOLING_DOWN_MOTOR"
    SUB_MISSION_WAIT_FOR_RAIN_TO_STOP = "SUB_MISSION_WAIT_FOR_RAIN_TO_STOP"
    SUB_MISSION_FLEXIBLE_STATION_WAIT = "SUB_MISSION_FLEXIBLE_STATION_WAIT"

class MissionState(Enum):
    MISSION_STATE_IDLE = "MISSION_STATE_IDLE"
    MISSION_STATE_RUNNING = "MISSION_STATE_RUNNING"
    MISSION_STATE_PAUSE = "MISSION_STATE_PAUSE"
    MISSION_STATE_ABORT = "MISSION_STATE_ABORT"
    MISSION_STATE_COMPLETE = "MISSION_STATE_COMPLETE"

class PowerMode(Enum):
    POWER_MODE_RUNNING = "POWER_MODE_RUNNING"
    POWER_MODE_STANDBY = "POWER_MODE_STANDBY"
    POWER_MODE_HIBERNATE = "POWER_MODE_HIBERNATE"

class BackToStationReason(Enum):
    BACK_TO_STATION_REASON_NONE = "BACK_TO_STATION_REASON_NONE"
    BACK_TO_STATION_REASON_LOW_BATTERY = "BACK_TO_STATION_REASON_LOW_BATTERY"
    BACK_TO_STATION_REASON_RAINING = "BACK_TO_STATION_REASON_RAINING"
    BACK_TO_STATION_REASON_MOW_MOTOR_OVERHEAT = "BACK_TO_STATION_REASON_MOW_MOTOR_OVERHEAT"
    BACK_TO_STATION_REASON_WHEEL_OVERHEAT = "BACK_TO_STATION_REASON_WHEEL_OVERHEAT"
    BACK_TO_STATION_REASON_NIGHT_TIME = "BACK_TO_STATION_REASON_NIGHT_TIME"

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TerraMow entity."""
    # 从 hass.data 获取数据而不是 config_entry.runtime_data
    basic_data = hass.data[DOMAIN][config_entry.entry_id]

    # 创建实体
    entity = TerraMowLawnMowerEntity(basic_data, hass)

    # 添加实体
    async_add_entities([entity])

    # 启动 MQTT 客户端
    entity.start_mqtt_client()

class TerraMowLawnMowerEntity(LawnMowerEntity):
    _attr_has_entity_name = True
    # 使用默认图标
    _attr_icon = "mdi:robot-mower"
    _attr_translation_key = "lawn_mower"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        """Initialize a lawn mower."""
        super().__init__()
        self.basic_data = basic_data
        self.host = self.basic_data.host
        self.password = self.basic_data.password
        self.hass = hass
        self._activity = LawnMowerActivity.DOCKED  # 默认状态
        self.mqtt_client = None
        self._stop_event = threading.Event()  # 用于停止重连循环
        self.callbacks: dict[int, list[Callable]] = {}  # 存储 dp_id 和对应的回调函数列表
        self.map_callbacks: list[Callable] = []  # 存储地图信息回调函数
        self.pose_callbacks: list[Callable] = []  # 存储姿态回调函数
        self.path_callbacks: list[Callable] = []  # 存储路径数据回调函数
        self.history_path_callbacks: list[Callable] = []  # 存储历史路径数据回调函数
        self._map_info: dict[str, Any] = {}  # 存储当前地图信息
        self._map_meta: dict[str, Any] = {}  # 存储地图元信息
        self._path_meta: dict[str, Any] = {}  # 存储路径元信息
        self._history_path_meta: dict[str, Any] = {}  # 存储历史路径元信息
        self._map_data: dict[str, Any] = {}  # 存储HTTP拉取的地图数据
        self._path_data: dict[str, Any] = {}  # 存储HTTP拉取的路径数据
        self._history_path_data: dict[str, Any] = {}  # 存储HTTP拉取的历史路径数据
        self._pose: dict[str, Any] = {}  # 存储实时姿态
        self._pending_map_meta: dict[str, Any] | None = None
        self._pending_path_meta: dict[str, Any] | None = None
        self._pending_history_path_meta: dict[str, Any] | None = None
        self._map_retry_meta: dict[str, Any] | None = None
        self._path_retry_meta: dict[str, Any] | None = None
        self._history_path_retry_meta: dict[str, Any] | None = None
        self._map_retry_count = 0
        self._path_retry_count = 0
        self._history_path_retry_count = 0
        self._map_retry_task: asyncio.Task | None = None
        self._path_retry_task: asyncio.Task | None = None
        self._history_path_retry_task: asyncio.Task | None = None
        self._map_no_seq_last_fetch = 0.0
        self._path_no_seq_last_fetch = 0.0
        self._history_path_no_seq_last_fetch = 0.0
        self._no_seq_min_interval = 5.0
        self._map_seq = -1
        self._path_seq = -1
        self._history_path_seq = -1
        self._map_etag: str | None = None
        self._path_etag: str | None = None
        self._history_path_etag: str | None = None
        self._fetching_map = False
        self._fetching_path = False
        self._fetching_history_path = False
        self._global_params: dict[str, Any] = {}  # 存储dp_155全局作业参数
        self._map_status: dict[str, Any] = {}  # 存储dp_117地图状态
        self._current_work_data: dict[str, Any] = {}  # 存储dp_113当前作业数据
        self._statistics_data: dict[str, Any] = {}  # 存储dp_124作业统计数据
        self._base_station_time: dict[str, Any] = {}  # 存储dp_125基站使用时间
        self._blade_time: dict[str, Any] = {}  # 存储dp_126刀盘使用时间
        self._schedule_data: dict[str, Any] = {}  # 存储dp_138即将到来的预约
        self._battery_status: dict[str, Any] = {} # Store dp_108 battery status
        self._task_status: dict[str, Any] = {}  # Store dp_107 task status raw payload
        self._device_model: str = "TerraMow S1200"  # 默认型号名称，保持向后兼容
        self.basic_data.lawn_mower = self

        # 机器人状态
        self.mission = Mission.MISSION_IDLE
        self.sub_mission = SubMission.SUB_MISSION_IDLE
        self.mission_state = MissionState.MISSION_STATE_IDLE
        self._is_robot_navi_located: bool | None = None
        self._is_upgrading: bool | None = None
        self._power_mode: str | None = None

        self.cmd_seq = random.randint(0, 0xFFFFFFFF)  # 生成随机的指令序号

        self._last_control_time = time.monotonic()
        self._control_interval = 1.0 # 控制间隔时间

        self._has_returning = hasattr(LawnMowerActivity, 'RETURNING')
        if not self._has_returning:
            _LOGGER.info("LawnMowerActivity.RETURNING not available in this HA version")

        _LOGGER.info("TerraMowLawnMowerEntity created with host %s", self.host)
        _LOGGER.debug("Initialization params: host=%s, password=%s", self.host, self.password)
        _LOGGER.debug("Initial state: activity=%s, mission=%s, sub_mission=%s",
                     self._activity, self.mission, self.sub_mission)


    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.device_model
        )

    @property
    def device_model(self) -> str:
        """返回设备型号"""
        return self._device_model

    @device_model.setter
    def device_model(self, model_name: str) -> None:
        """更新设备型号"""
        self._device_model = model_name
    def _can_accept_command(self):
        """Check if control commands can be accepted"""
        now = time.monotonic()
        if now - self._last_control_time < self._control_interval:
            _LOGGER.info("Request too quick, skip it")
            return False
        self._last_control_time = now
        return True

    def _get_mow_missions(self):
        """Get the list of mowing missions"""
        return [
            Mission.MISSION_GLOBAL_CLEAN,
            Mission.MISSION_BUILD_MAP,
            Mission.MISSION_BUILD_MAP_AND_CLEAN,
            Mission.MISSION_TEMPORARY_CLEAN,
            Mission.MISSION_SELECT_REGION_CLEAN,
            Mission.MISSION_DRAW_REGION_CLEAN,
            Mission.MISSION_EDGE_TRIM_CLEAN,
            Mission.MISSION_SCHEDULE_GLOBAL_CLEAN,
            Mission.MISSION_SCHEDULE_BUILD_MAP_AND_CLEAN,
            Mission.MISSION_SCHEDULE_SELECT_REGION_CLEAN
        ]

    def _get_recharge_missions(self):
        """Get the list of recharging missions"""
        return [
            Mission.MISSION_RECHARGE,
            Mission.MISSION_BACK_TO_STARTING_POINT
        ]

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}"


    @property
    def activity(self) -> LawnMowerActivity:
        """Return the current activity of the lawn mower."""
        return self._activity

    @activity.setter
    def activity(self, value: LawnMowerActivity):
        """Set the current activity of the lawn mower."""
        old_activity = self._activity
        self._activity = value
        _LOGGER.info("Activity changed from %s to %s", old_activity, value)
        _LOGGER.debug("State change details: mission=%s, sub_mission=%s, mission_state=%s, has_error=%s",
                     self.mission, self.sub_mission, self.mission_state, self.has_error)
        self.schedule_update_ha_state()

    @property
    def supported_features(self) -> LawnMowerEntityFeature:
        """Flag lawn mower features that are supported."""
        return LawnMowerEntityFeature.START_MOWING | LawnMowerEntityFeature.PAUSE | LawnMowerEntityFeature.DOCK

    def start_mqtt_client(self):
        """Start the MQTT client in a separate thread."""
        _LOGGER.info("Starting MQTT client, connecting to %s:%d", self.host, MQTT_PORT)
        _LOGGER.debug("MQTT connection params: username=%s, password=%s", MQTT_USERNAME, self.password)

        self.mqtt_client = mqtt_client.Client()
        self.mqtt_client.username_pw_set(MQTT_USERNAME, self.password)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message

        # Start MQTT loop thread
        _LOGGER.debug("Starting MQTT thread")
        self.mqtt_thread = threading.Thread(target=self.mqtt_loop)
        self.mqtt_thread.daemon = True
        self.mqtt_thread.start()

        self.register_all_callbacks()
        _LOGGER.debug("MQTT client startup completed")

    def register_all_callbacks(self):
        """Register all callbacks for data points."""
        self.register_callback(107, self.on_mission_status)
        self.register_callback(155, self.on_global_params)
        self.register_callback(117, self.on_map_status)
        self.register_callback(113, self.on_current_work_data)
        self.register_callback(124, self.on_statistics_data)
        self.register_callback(125, self.on_base_station_time)
        self.register_callback(126, self.on_blade_time)
        self.register_callback(138, self.on_schedule_data)
        self.register_callback(108, self.on_battery_status)
        self.register_callback(COMPATIBILITY_INFO_DP, self.on_compatibility_info)

    def update_activity_from_state(self):
        """Update activity based on current mission state."""
        last_activity = self.activity

        if self.has_error:
            self.activity = LawnMowerActivity.ERROR
        elif self.mission_state == MissionState.MISSION_STATE_RUNNING:
            if self.mission in self._get_mow_missions():
                if self.sub_mission == SubMission.SUB_MISSION_FLEXIBLE_STATION_WAIT:
                    # 基站中等待，等效于暂停
                    self.activity = LawnMowerActivity.PAUSED
                elif self.sub_mission == SubMission.SUB_MISSION_SAVING_MAP:
                    # 正在保存地图，等效于结束
                    self.activity = LawnMowerActivity.DOCKED
                else:
                    self.activity = LawnMowerActivity.MOWING
            elif self.mission in self._get_recharge_missions():
                if self._has_returning:
                    self.activity = LawnMowerActivity.RETURNING
                else:
                    # 旧版本的HA没有RETURNING状态，使用DOCKED替代
                    self.activity = LawnMowerActivity.DOCKED
            else:
                self.activity = LawnMowerActivity.DOCKED
        elif self.mission_state == MissionState.MISSION_STATE_PAUSE:
            self.activity = LawnMowerActivity.PAUSED
        else:
            self.activity = LawnMowerActivity.DOCKED

        if last_activity != self.activity:
            self.schedule_update_ha_state()

    async def on_global_params(self, payload: str):
        """Handle global parameter updates (dp_155)."""
        _LOGGER.debug("Raw global params payload: %s", payload)
        try:
            data = json.loads(payload)
            old_params = self._global_params
            self._global_params = data
            _LOGGER.info("Global parameters updated: %s", data)

            # 检查主方向模式是否有变化，通知模式选择器
            self._notify_mode_selector_if_changed(old_params, data)

        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload for dp_155: %s", payload)

    def _notify_mode_selector_if_changed(self, old_params: dict, new_params: dict) -> None:
        """如果主方向模式有变化，通知模式选择器"""
        try:
            old_mode = old_params.get('main_direction_angle_config', {}).get('mode') if old_params else None
            new_mode = new_params.get('main_direction_angle_config', {}).get('mode')

            if new_mode and old_mode != new_mode:
                _LOGGER.debug("Main direction mode changed from %s to %s, notifying mode selector", old_mode, new_mode)

                # 通过Home Assistant事件通知模式选择器
                self.hass.bus.fire(f"{DOMAIN}_device_mode_confirmed", {
                    "device_host": self.host,
                    "confirmed_mode": new_mode,
                    "old_mode": old_mode,
                    "source": "device_feedback"
                })

        except Exception as e:
            _LOGGER.warning("Error notifying mode selector: %s", e)

    async def on_map_status(self, payload: str):
        """Handle map status updates (dp_117)."""
        _LOGGER.debug("Raw map status payload: %s", payload)
        try:
            data = json.loads(payload)
            self._map_status = data
            _LOGGER.info("Map status updated: %s", data)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload for dp_117: %s", payload)

    async def on_current_work_data(self, payload: str):
        """Handle current work data updates (dp_113)."""
        _LOGGER.debug("Raw current work data payload: %s", payload)
        try:
            data = json.loads(payload)
            self._current_work_data = data
            _LOGGER.info("Current work data updated: %s", data)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload for dp_113: %s", payload)

    async def on_statistics_data(self, payload: str):
        """Handle statistics data updates (dp_124)."""
        _LOGGER.debug("Raw statistics data payload: %s", payload)
        try:
            data = json.loads(payload)
            self._statistics_data = data
            _LOGGER.info("Statistics data updated: %s", data)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload for dp_124: %s", payload)

    async def on_base_station_time(self, payload: str):
        """Handle base station time updates (dp_125)."""
        _LOGGER.debug("Raw base station time payload: %s", payload)
        try:
            data = json.loads(payload)
            self._base_station_time = data
            _LOGGER.info("Base station time updated: %s", data)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload for dp_125: %s", payload)

    async def on_blade_time(self, payload: str):
        """Handle blade time updates (dp_126)."""
        _LOGGER.debug("Raw blade time payload: %s", payload)
        try:
            data = json.loads(payload)
            self._blade_time = data
            _LOGGER.info("Blade time updated: %s", data)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload for dp_126: %s", payload)

    async def on_schedule_data(self, payload: str):
        """Handle schedule data updates (dp_138)."""
        _LOGGER.debug("Raw schedule data payload: %s", payload)
        try:
            data = json.loads(payload)
            self._schedule_data = data
            _LOGGER.info("Schedule data updated: %s", data)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload for dp_138: %s", payload)

    async def on_battery_status(self, payload: str):
        """Handle battery status updates (dp_108)."""
        _LOGGER.debug("Raw battery status payload: %s", payload)
        try:
            data = json.loads(payload)
            self._battery_status = data
            _LOGGER.info("Battery status updated: %s", data)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload for dp_108: %s", payload)

    async def on_mission_status(self, payload: str):
        """Handle mission status updates."""
        _LOGGER.debug("Raw mission status payload: %s", payload)
        try:
            data = json.loads(payload)
            _LOGGER.info("Received mission status: %s", data)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON payload: %s", payload)
            return

        # Preserve the raw payload so that downstream entities can read fields
        # like has_error / back_to_station_reason without enum conversion.
        self._task_status = dict(data)

        # Define a mapping from field names to enum classes
        enum_mapping = {
            "mission": Mission,
            "sub_mission": SubMission,
            "state": MissionState,
            "power_mode": PowerMode,
            "back_to_station_reason": BackToStationReason
        }

        # Capture raw fields before enum conversion mutates the dict
        if "is_robot_navi_located" in data:
            self._is_robot_navi_located = data.get("is_robot_navi_located")
        if "is_upgrading" in data:
            self._is_upgrading = data.get("is_upgrading")
        if "power_mode" in data:
            self._power_mode = data.get("power_mode")

        # Convert enum strings to enum members
        for key, enum_class in enum_mapping.items():
            if key in data:
                old_value = data[key]
                try:
                    data[key] = enum_class(data[key])
                    _LOGGER.debug("Converted %s: %s -> %s", key, old_value, data[key])
                except (ValueError, KeyError) as e:
                    _LOGGER.error("Invalid value for %s: %s (error: %s)", key, data[key], e)
                    data[key] = None

        # Store old values for logging
        old_mission = self.mission
        old_sub_mission = self.sub_mission
        old_mission_state = self.mission_state

        self.mission = data.get("mission", self.mission)
        self.sub_mission = data.get("sub_mission", self.sub_mission)
        self.mission_state = data.get("state", self.mission_state)

        _LOGGER.debug("Mission state updated: mission=%s->%s, sub_mission=%s->%s, state=%s->%s, has_error=%s, back_to_station_reason=%s",
                     old_mission, self.mission, old_sub_mission, self.sub_mission,
                     old_mission_state, self.mission_state, self.has_error, self.back_to_station_reason)

        self.update_activity_from_state()

    async def on_compatibility_info(self, payload: str):
        """Handle compatibility info updates (dp_112)."""
        _LOGGER.debug("Raw compatibility info payload: %s", payload)
        try:
            data = json.loads(payload)
            _LOGGER.info("Received version compatibility info: %s", data)

            # 进行版本兼容性检查
            compatibility_status = self.basic_data.check_version_compatibility(data)
            self.basic_data.compatibility_status = compatibility_status
            self.basic_data.firmware_version = data

            # 记录兼容性检查结果
            message = self.basic_data.get_compatibility_message()
            if compatibility_status == CompatibilityStatus.COMPATIBLE:
                _LOGGER.info("Version compatibility check: %s", message)
            else:
                _LOGGER.warning("Version compatibility check: %s", message)

            # 如果版本不兼容，可以考虑禁用某些功能或显示警告
            if compatibility_status == CompatibilityStatus.INCOMPATIBLE:
                _LOGGER.error("Version completely incompatible, recommend checking firmware and plugin versions")

        except json.JSONDecodeError:
            _LOGGER.error("Failed to parse compatibility info JSON: %s", payload)
        except Exception as e:
            _LOGGER.error("Error processing version compatibility info: %s", e)

    def mqtt_loop(self):
        """MQTT main loop with auto-reconnect."""
        while not self._stop_event.is_set():
            try:
                if self.mqtt_client and not self.mqtt_client.is_connected():
                    _LOGGER.info("Attempting to connect to MQTT Broker %s", self.host)
                    self.mqtt_client.connect(self.host, MQTT_PORT, 60)
                    _LOGGER.info("Connected to MQTT Broker")
                if self.mqtt_client:
                    self.mqtt_client.loop_forever()
            except Exception as e:
                _LOGGER.error(f"MQTT connection error: {e}")
                # 设置错误状态
                self.activity = LawnMowerActivity.ERROR
                self.schedule_update_ha_state()
                time.sleep(5)  # 等待 5 秒后重试

    def on_mqtt_connect(self, client, _userdata, _flags, rc):  # type: ignore[misc]
        """Callback when connected to MQTT Broker."""
        if rc == 0:
            _LOGGER.info("MQTT connected")
            # 订阅主题
            for dp_id in range(201):
                topic = f"data_point/{dp_id}/robot"
                client.subscribe(topic)
            # 订阅地图信息主题（旧固件兼容）
            client.subscribe(MAP_INFO_TOPIC)
            _LOGGER.info("Subscribed to %s topic", MAP_INFO_TOPIC)

            # 订阅地图/路径元数据与姿态
            client.subscribe(MAP_META_TOPIC)
            client.subscribe(PATH_META_TOPIC)
            client.subscribe(PATH_HISTORY_META_TOPIC)
            client.subscribe(POSE_TOPIC)
            _LOGGER.info(
                "Subscribed to %s/%s/%s/%s topic",
                MAP_META_TOPIC,
                PATH_META_TOPIC,
                PATH_HISTORY_META_TOPIC,
                POSE_TOPIC,
            )

            # 订阅设备型号主题
            client.subscribe(MODEL_NAME_TOPIC)
            _LOGGER.info("Subscribed to %s topic", MODEL_NAME_TOPIC)

            # 主动请求版本兼容性信息
            self._request_compatibility_info()

            self.update_activity_from_state()
        else:
            _LOGGER.error(f"MQTT connection failed with code {rc}")
            # 设置错误状态
            self.activity = LawnMowerActivity.ERROR
            self.schedule_update_ha_state()

    def on_mqtt_disconnect(self, _client, _userdata, rc):  # type: ignore[misc]
        """Callback when disconnected from MQTT Broker."""
        if rc != 0:
            _LOGGER.warning(f"Unexpected MQTT disconnection: {rc}")
            # 断开连接后自动重连
            # 设置错误状态
            self.activity = LawnMowerActivity.ERROR
            self.schedule_update_ha_state()

    def on_mqtt_message(self, _client, _userdata, msg):  # type: ignore[misc]
        """Callback when a message is received."""
        topic = msg.topic
        payload = msg.payload.decode()

        if topic != POSE_TOPIC:
            _LOGGER.debug("Received MQTT message: topic=%s, payload=%s", topic, payload)

        # 处理地图元信息
        if topic == MAP_META_TOPIC:
            try:
                meta = json.loads(payload)
                self._map_meta = meta
                self.hass.add_job(self._async_handle_map_meta, meta)
            except json.JSONDecodeError:
                _LOGGER.error("Failed to parse map meta JSON: %s", payload[:200])
            except Exception as e:
                _LOGGER.error("Error handling map meta: %s", e)
            return

        # 处理路径元信息
        if topic == PATH_META_TOPIC:
            try:
                meta = json.loads(payload)
                self._path_meta = meta
                self.hass.add_job(self._async_handle_path_meta, meta)
            except json.JSONDecodeError:
                _LOGGER.error("Failed to parse path meta JSON: %s", payload[:200])
            except Exception as e:
                _LOGGER.error("Error handling path meta: %s", e)
            return

        # 处理历史路径元信息
        if topic == PATH_HISTORY_META_TOPIC:
            try:
                meta = json.loads(payload)
                self._history_path_meta = meta
                self.hass.add_job(self._async_handle_history_path_meta, meta)
            except json.JSONDecodeError:
                _LOGGER.error("Failed to parse history path meta JSON: %s", payload[:200])
            except Exception as e:
                _LOGGER.error("Error handling history path meta: %s", e)
            return

        # 处理实时姿态
        if topic == POSE_TOPIC:
            try:
                pose = json.loads(payload)
                self._pose = pose
                for callback in self.pose_callbacks:
                    self.hass.add_job(callback, pose)
            except json.JSONDecodeError:
                _LOGGER.error("Failed to parse pose JSON: %s", payload[:200])
            except Exception as e:
                _LOGGER.error("Error handling pose: %s", e)
            return

        # 处理地图信息主题
        if topic == MAP_INFO_TOPIC:
            _LOGGER.info("Received map info message, size: %d bytes", len(payload))
            self._handle_map_info(payload)
            return

        # 处理设备型号主题
        if topic == MODEL_NAME_TOPIC:
            _LOGGER.info("Received device model message: %s", payload)
            self._handle_model_name(payload)
            return

        # 使用正则表达式解析 data_point topic
        match = TOPIC_PATTERN.fullmatch(topic)
        if not match:
            _LOGGER.warning("Invalid topic format: %s", topic)
            return

        try:
            dp_id = int(match.group(1))
            _LOGGER.debug("Parsed dp_id: %d from topic: %s", dp_id, topic)
        except ValueError:
            _LOGGER.warning("Invalid dp_id in topic: %s", topic)
            return

        # 调用对应的回调函数
        callbacks = self.callbacks.get(dp_id)
        if callbacks:
            _LOGGER.debug("Calling %d callbacks for dp_id %d", len(callbacks), dp_id)
            for callback in callbacks:
                self.hass.add_job(callback, payload)
        else:
            _LOGGER.debug("No callback registered for dp_id: %d", dp_id)

    def register_callback(self, dp_id: int, callback: Callable):
        """Register a callback function for a specific dp_id."""
        if not callable(callback):
            raise ValueError("Callback must be a callable function.")
        if dp_id not in self.callbacks:
            self.callbacks[dp_id] = []
        self.callbacks[dp_id].append(callback)
        _LOGGER.info(f"Callback registered for dp_id: {dp_id}")

    def register_map_callback(self, callback: Callable):
        """Register a callback function for map info updates."""
        if not callable(callback):
            raise ValueError("Callback must be a callable function.")
        self.map_callbacks.append(callback)
        _LOGGER.info("Map callback registered")
        # 如果已有地图数据，立即触发回调
        if self._map_info:
            self.hass.add_job(callback, self._map_info)

    def register_pose_callback(self, callback: Callable):
        """Register a callback function for pose updates."""
        if not callable(callback):
            raise ValueError("Callback must be a callable function.")
        self.pose_callbacks.append(callback)
        _LOGGER.info("Pose callback registered")
        if self._pose:
            self.hass.add_job(callback, self._pose)

    def register_path_callback(self, callback: Callable):
        """Register a callback function for path data updates."""
        if not callable(callback):
            raise ValueError("Callback must be a callable function.")
        self.path_callbacks.append(callback)
        _LOGGER.info("Path callback registered")
        if self._path_data:
            self.hass.add_job(callback, self._path_data)

    def register_history_path_callback(self, callback: Callable):
        """Register a callback function for history path data updates."""
        if not callable(callback):
            raise ValueError("Callback must be a callable function.")
        self.history_path_callbacks.append(callback)
        _LOGGER.info("History path callback registered")
        if self._history_path_data:
            self.hass.add_job(callback, self._history_path_data)

    def _update_map_info(self, map_info: dict[str, Any]) -> None:
        """Update map info and notify callbacks."""
        self._map_info = map_info
        _LOGGER.info("Map info updated: id=%s, name=%s, state=%s",
                     map_info.get('id'), map_info.get('name'), map_info.get('map_state'))
        for callback in self.map_callbacks:
            self.hass.add_job(callback, map_info)

    def _get_map_field(self, data: dict[str, Any], *keys: str) -> Any | None:
        """从可能的字段名中取值"""
        for key in keys:
            if key in data:
                return data.get(key)
        return None

    def _build_map_info_from_map_data(self, map_data: dict[str, Any]) -> dict[str, Any] | None:
        """根据 HTTP map 数据构建/补全 map_info"""
        if not isinstance(map_data, dict):
            return None
        base = dict(self._map_info) if self._map_info else {}
        current_id = base.get("id")
        new_id = self._get_map_field(map_data, "id", "map_id", "mapId")
        if new_id is not None and new_id != current_id:
            base = {}
        mapped = {
            "id": new_id,
            "name": self._get_map_field(map_data, "name", "map_name", "mapName"),
            "map_state": self._get_map_field(map_data, "map_state", "mapState", "state"),
            "regions": map_data.get("regions"),
            "clean_info": self._get_map_field(map_data, "clean_info", "cleanInfo"),
            "total_area": self._get_map_field(map_data, "total_area", "totalArea"),
            "sub_regions": self._get_map_field(map_data, "sub_regions", "subRegions"),
        }
        for key, value in mapped.items():
            if value is not None:
                base[key] = value
        if not base:
            return None
        if "map_state" not in base:
            base["map_state"] = "unknown"
        return base

    def _get_meta_seq(self, meta: dict[str, Any], label: str, warn: bool = True) -> int:
        """解析 meta 中的 seq"""
        try:
            return int(meta.get("seq", -1))
        except (ValueError, TypeError):
            if warn:
                _LOGGER.warning("Invalid %s meta seq: %s", label, meta.get("seq"))
            return -1

    def _should_replace_pending(self, pending_meta: dict[str, Any] | None, seq: int, label: str) -> bool:
        """是否用新的 meta 替换缓存的 pending meta"""
        if pending_meta is None:
            return True
        pending_seq = self._get_meta_seq(pending_meta, label, warn=False)
        if seq == -1:
            return pending_seq == -1
        if pending_seq == -1:
            return True
        return seq > pending_seq

    def _get_retry_delay(self, count: int) -> float:
        """获取重试延迟（秒）"""
        delays = [2.0, 5.0, 10.0, 30.0]
        if count < len(delays):
            return delays[count]
        return delays[-1]

    def _reset_map_retry(self) -> None:
        """清理地图拉取重试状态"""
        self._map_retry_meta = None
        self._map_retry_count = 0
        if self._map_retry_task and not self._map_retry_task.done():
            self._map_retry_task.cancel()
        self._map_retry_task = None

    def _reset_path_retry(self) -> None:
        """清理路径拉取重试状态"""
        self._path_retry_meta = None
        self._path_retry_count = 0
        if self._path_retry_task and not self._path_retry_task.done():
            self._path_retry_task.cancel()
        self._path_retry_task = None

    def _reset_history_path_retry(self) -> None:
        """清理历史路径拉取重试状态"""
        self._history_path_retry_meta = None
        self._history_path_retry_count = 0
        if self._history_path_retry_task and not self._history_path_retry_task.done():
            self._history_path_retry_task.cancel()
        self._history_path_retry_task = None

    def _reset_pending_meta(self) -> None:
        """清理 pending meta"""
        self._pending_map_meta = None
        self._pending_path_meta = None
        self._pending_history_path_meta = None

    def _schedule_map_retry(self, meta: dict[str, Any]) -> None:
        """安排地图拉取重试"""
        self._map_retry_meta = meta
        if self._map_retry_task and not self._map_retry_task.done():
            return
        delay = self._get_retry_delay(self._map_retry_count)
        self._map_retry_count += 1
        self._map_retry_task = self.hass.async_create_task(self._async_retry_map(delay))

    def _schedule_path_retry(self, meta: dict[str, Any]) -> None:
        """安排路径拉取重试"""
        self._path_retry_meta = meta
        if self._path_retry_task and not self._path_retry_task.done():
            return
        delay = self._get_retry_delay(self._path_retry_count)
        self._path_retry_count += 1
        self._path_retry_task = self.hass.async_create_task(self._async_retry_path(delay))

    def _schedule_history_path_retry(self, meta: dict[str, Any]) -> None:
        """安排历史路径拉取重试"""
        self._history_path_retry_meta = meta
        if self._history_path_retry_task and not self._history_path_retry_task.done():
            return
        delay = self._get_retry_delay(self._history_path_retry_count)
        self._history_path_retry_count += 1
        self._history_path_retry_task = self.hass.async_create_task(
            self._async_retry_history_path(delay)
        )

    async def _async_retry_map(self, delay: float) -> None:
        """延迟重试地图拉取"""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._map_retry_task = None
        meta = self._map_retry_meta
        if meta:
            await self._async_handle_map_meta(meta)

    async def _async_retry_path(self, delay: float) -> None:
        """延迟重试路径拉取"""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._path_retry_task = None
        meta = self._path_retry_meta
        if meta:
            await self._async_handle_path_meta(meta)

    async def _async_retry_history_path(self, delay: float) -> None:
        """延迟重试历史路径拉取"""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._history_path_retry_task = None
        meta = self._history_path_retry_meta
        if meta:
            await self._async_handle_history_path_meta(meta)

    def _handle_map_info(self, payload: str):
        """Handle map info message."""
        try:
            map_info = json.loads(payload)
            self._update_map_info(map_info)

        except json.JSONDecodeError:
            _LOGGER.error("Failed to parse map info JSON: %s", payload[:200])
        except Exception as e:
            _LOGGER.error("Error handling map info: %s", e)

    async def _async_handle_map_meta(self, meta: dict[str, Any]) -> None:
        """Handle map meta message and fetch map data via HTTP."""
        seq = self._get_meta_seq(meta, "map")

        if seq != -1 and seq <= self._map_seq:
            return
        if seq != -1 and seq > self._map_seq:
            self._reset_map_retry()
        if seq == -1:
            now = time.monotonic()
            if (now - self._map_no_seq_last_fetch) < self._no_seq_min_interval:
                return
        if self._fetching_map:
            if self._should_replace_pending(self._pending_map_meta, seq, "map"):
                self._pending_map_meta = meta
            return

        self._fetching_map = True
        try:
            data, etag, ok, _not_modified = await self._async_fetch_json(meta, self._map_etag)
            if ok:
                if seq != -1:
                    self._map_seq = seq
                else:
                    self._map_no_seq_last_fetch = time.monotonic()
                self._reset_map_retry()
            if etag:
                self._map_etag = etag
            if data is not None:
                self._map_data = data
                map_info = self._build_map_info_from_map_data(data)
                if map_info is not None:
                    self._update_map_info(map_info)
            if not ok:
                self._schedule_map_retry(meta)
        except Exception as e:
            _LOGGER.error("Failed to fetch map data: %s", e)
            self._schedule_map_retry(meta)
        finally:
            self._fetching_map = False
            pending_meta = self._pending_map_meta
            self._pending_map_meta = None
            if pending_meta:
                pending_seq = self._get_meta_seq(pending_meta, "map", warn=False)
                if pending_seq == -1 or pending_seq > self._map_seq:
                    self.hass.async_create_task(self._async_handle_map_meta(pending_meta))

    async def _async_handle_path_meta(self, meta: dict[str, Any]) -> None:
        """Handle path meta message and fetch path data via HTTP."""
        seq = self._get_meta_seq(meta, "path")

        # When a new mowing session starts, the device republishes path meta
        # with seq counted from 0 again. Without this reset, the new meta is
        # discarded by the seq <= _path_seq guard and the path stays hidden
        # until the integration is reloaded. Treat a backward seq as a reset.
        if seq != -1 and self._path_seq != -1 and seq < self._path_seq:
            _LOGGER.info(
                "Path seq went backward (%d -> %d); treating as new session",
                self._path_seq, seq,
            )
            self._path_seq = -1
            self._path_etag = None
        if seq != -1 and seq <= self._path_seq:
            return
        if seq != -1 and seq > self._path_seq:
            self._reset_path_retry()
        if seq == -1:
            now = time.monotonic()
            if (now - self._path_no_seq_last_fetch) < self._no_seq_min_interval:
                return
        if self._fetching_path:
            if self._should_replace_pending(self._pending_path_meta, seq, "path"):
                self._pending_path_meta = meta
            return

        self._fetching_path = True
        try:
            data, etag, ok, _not_modified = await self._async_fetch_json(meta, self._path_etag)
            if ok:
                if seq != -1:
                    self._path_seq = seq
                else:
                    self._path_no_seq_last_fetch = time.monotonic()
                self._reset_path_retry()
            if etag:
                self._path_etag = etag
            if data is not None:
                self._path_data = data
                for callback in self.path_callbacks:
                    self.hass.async_create_task(callback(data))
            if not ok:
                self._schedule_path_retry(meta)
        except Exception as e:
            _LOGGER.error("Failed to fetch path data: %s", e)
            self._schedule_path_retry(meta)
        finally:
            self._fetching_path = False
            pending_meta = self._pending_path_meta
            self._pending_path_meta = None
            if pending_meta:
                pending_seq = self._get_meta_seq(pending_meta, "path", warn=False)
                if pending_seq == -1 or pending_seq > self._path_seq:
                    self.hass.async_create_task(self._async_handle_path_meta(pending_meta))

    async def _async_handle_history_path_meta(self, meta: dict[str, Any]) -> None:
        """Handle history path meta message and fetch history path data via HTTP."""
        seq = self._get_meta_seq(meta, "history path")

        # Same session-reset handling as _async_handle_path_meta: a new mowing
        # session republishes meta with a seq starting from 0, which would
        # otherwise be dropped by the seq guard.
        if seq != -1 and self._history_path_seq != -1 and seq < self._history_path_seq:
            _LOGGER.info(
                "History path seq went backward (%d -> %d); treating as new session",
                self._history_path_seq, seq,
            )
            self._history_path_seq = -1
            self._history_path_etag = None
        if seq != -1 and seq <= self._history_path_seq:
            return
        if seq != -1 and seq > self._history_path_seq:
            self._reset_history_path_retry()
        if seq == -1:
            now = time.monotonic()
            if (now - self._history_path_no_seq_last_fetch) < self._no_seq_min_interval:
                return
        if self._fetching_history_path:
            if self._should_replace_pending(self._pending_history_path_meta, seq, "history path"):
                self._pending_history_path_meta = meta
            return

        self._fetching_history_path = True
        try:
            data, etag, ok, _not_modified = await self._async_fetch_json(meta, self._history_path_etag)
            if ok:
                if seq != -1:
                    self._history_path_seq = seq
                else:
                    self._history_path_no_seq_last_fetch = time.monotonic()
                self._reset_history_path_retry()
            if etag:
                self._history_path_etag = etag
            if data is not None:
                self._history_path_data = data
                for callback in self.history_path_callbacks:
                    self.hass.async_create_task(callback(data))
            if not ok:
                self._schedule_history_path_retry(meta)
        except Exception as e:
            _LOGGER.error("Failed to fetch history path data: %s", e)
            self._schedule_history_path_retry(meta)
        finally:
            self._fetching_history_path = False
            pending_meta = self._pending_history_path_meta
            self._pending_history_path_meta = None
            if pending_meta:
                pending_seq = self._get_meta_seq(pending_meta, "history path", warn=False)
                if pending_seq == -1 or pending_seq > self._history_path_seq:
                    self.hass.async_create_task(self._async_handle_history_path_meta(pending_meta))

    async def _async_fetch_json(
        self,
        meta: dict[str, Any],
        etag: str | None,
    ) -> tuple[dict[str, Any] | None, str | None, bool, bool]:
        """Fetch JSON data via HTTP using meta info."""
        http_port = meta.get("http_port")
        http_path = meta.get("http_path")
        token = meta.get("token")
        if not http_port or not http_path or not token:
            _LOGGER.warning("Incomplete meta for HTTP fetch: %s", meta)
            return None, etag, False, False

        url = f"http://{self.host}:{http_port}{http_path}"
        headers = {"Authorization": f"Bearer {token}"}
        if etag:
            headers["If-None-Match"] = etag

        session = async_get_clientsession(self.hass)
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 304:
                return None, etag, True, True
            if resp.status >= 400:
                _LOGGER.error("HTTP fetch failed: %s status=%d", url, resp.status)
                return None, etag, False, False
            new_etag = resp.headers.get("ETag") or etag
            raw = await resp.read()
            # 手动处理 gzip 压缩：协议要求 Content-Encoding: gzip
            if raw[:2] == b'\x1f\x8b':
                raw = await self.hass.async_add_executor_job(gzip.decompress, raw)
            text = raw.decode("utf-8")
            data = json.loads(text)
            return data, new_etag, True, False

    async def _async_update_device_model(self, model_name: str):
        """异步更新设备注册表中的模型信息."""
        try:
            device_registry = dr.async_get(self.hass)
            device_identifier = ('TerraMowLawnMower', self.basic_data.host)

            # 查找设备并更新模型信息
            device_entry = device_registry.async_get_device({device_identifier})
            if device_entry:
                device_registry.async_update_device(
                    device_entry.id,
                    model=model_name
                )
                _LOGGER.info("Device registry updated with new model: %s", model_name)
            else:
                _LOGGER.warning("Device not found in registry for update")
        except Exception as e:
            _LOGGER.error("Error updating device registry: %s", e)

    def _handle_model_name(self, payload: str):
        """Handle device model name message."""
        try:
            # payload 直接是型号名称字符串
            model_name = payload.strip()
            if model_name:
                old_model = self.device_model
                self.device_model = model_name
                _LOGGER.info("Device model updated: %s -> %s", old_model, model_name)

                # 使用 hass.add_job 调度异步设备注册表更新操作到主事件循环
                self.hass.add_job(self._async_update_device_model, model_name)

                # 触发实体状态更新
                self.schedule_update_ha_state()
            else:
                _LOGGER.warning("Received empty model name, keeping default")
        except Exception as e:
            _LOGGER.error("Error handling model name: %s", e)

    @property
    def map_info(self) -> dict:
        """Get current map info."""
        return self._map_info

    @property
    def map_data(self) -> dict:
        """Get HTTP-fetched map data."""
        return self._map_data

    @property
    def path_data(self) -> dict:
        """Get HTTP-fetched path data."""
        return self._path_data

    @property
    def history_path_data(self) -> dict:
        """Get HTTP-fetched history path data."""
        return self._history_path_data

    @property
    def pose(self) -> dict:
        """Get current pose data."""
        return self._pose

    @property
    def global_params(self) -> dict:
        """Get current global parameters from dp_155."""
        return self._global_params

    @property
    def map_status(self) -> dict:
        """Get current map status from dp_117."""
        return self._map_status

    @property
    def current_work_data(self) -> dict:
        """Get current work data from dp_113."""
        return self._current_work_data

    @property
    def statistics_data(self) -> dict:
        """Get statistics data from dp_124."""
        return self._statistics_data

    @property
    def base_station_time(self) -> dict:
        """Get base station time from dp_125."""
        return self._base_station_time

    @property
    def blade_time(self) -> dict:
        """Get blade time from dp_126."""
        return self._blade_time

    @property
    def schedule_data(self) -> dict:
        """Get schedule data from dp_138."""
        return self._schedule_data

    @property
    def battery_status(self) -> dict:
        """Get current battery status from dp_108."""
        return self._battery_status

    @property
    def is_robot_navi_located(self) -> bool | None:
        """Get whether the robot is navigation-located (from dp_107)."""
        return self._is_robot_navi_located

    @property
    def is_upgrading(self) -> bool | None:
        """Get whether the robot is upgrading firmware (from dp_107)."""
        return self._is_upgrading

    @property
    def power_mode(self) -> str | None:
        """Get current power mode from dp_107."""
        return self._power_mode

    @property
    def task_status(self) -> dict:
        """Get current task status raw payload from dp_107."""
        return self._task_status

    @property
    def has_error(self) -> bool:
        """Return whether the robot currently reports a fault (dp_107)."""
        return bool(self._task_status.get("has_error", False))

    @property
    def back_to_station_reason(self) -> str | None:
        """Return the raw back_to_station_reason enum string from dp_107."""
        return self._task_status.get("back_to_station_reason")

    @property
    def compatibility_status(self) -> str:
        """Return current compatibility status."""
        return self.basic_data.compatibility_status

    @property
    def compatibility_message(self) -> str:
        """Return current compatibility message."""
        return self.basic_data.get_compatibility_message()

    @property
    def firmware_version_info(self) -> dict:
        """Return firmware version information."""
        return self.basic_data.firmware_version or {}

    def publish_data_point(self, dp_id: int, data: dict):
        """Publish data to a specific data point."""
        topic = f"data_point/{dp_id}/app"
        _LOGGER.info(f"Publishing data to topic {topic}: {data}")
        payload = json.dumps(data)
        if self.mqtt_client:
            self.mqtt_client.publish(topic, payload)
        else:
            _LOGGER.error("MQTT client is not initialized")

    def get_cmd_seq(self):
        """Generate a new command sequence number."""
        self.cmd_seq += 1
        return self.cmd_seq

    def start_mowing(self):
        """Start mowing implementation for lawn_mower entity."""
        if not self._can_accept_command():
            logging.warning("Request too quick, skip start mowing command")
            return

        if self.mission in self._get_mow_missions():
            if self.sub_mission == SubMission.SUB_MISSION_FLEXIBLE_STATION_WAIT:
                _LOGGER.info("SubMissionWaitInStation resume mow")
                self._resume_mow()
            else:
                if self.mission_state == MissionState.MISSION_STATE_RUNNING:
                    _LOGGER.info("Now is mowing, can not start mow again")
                elif self.mission_state == MissionState.MISSION_STATE_PAUSE:
                    _LOGGER.info("Mission paused, resume mow")
                    self._resume_mow()
        else:
            _LOGGER.info("START CLEAN : Sending start command")
            self._start_normal_mow()

    def pause(self):
        """Pause mowing implementation for lawn_mower entity."""
        if not self._can_accept_command():
            logging.warning("Request too quick, skip pause command")
            return

        if self.mission in self._get_mow_missions():
            if self.sub_mission == SubMission.SUB_MISSION_FLEXIBLE_STATION_WAIT:
                _LOGGER.info("SubMissionWaitInStation, now is not ok to pause mow")
            else:
                if self.mission_state == MissionState.MISSION_STATE_RUNNING:
                    _LOGGER.info("PAUSE CLEAN : Sending pause command")
                    self._send_pause_command()
                elif self.mission_state == MissionState.MISSION_STATE_PAUSE:
                    _LOGGER.info("Now is paused, can not pause mow again")
        else:
            if self.mission_state == MissionState.MISSION_STATE_RUNNING:
                _LOGGER.info("PAUSE CLEAN : Sending pause command")
                self._send_pause_command()
            elif self.mission_state == MissionState.MISSION_STATE_PAUSE:
                _LOGGER.info("Now is paused, can not pause mow again")

    def dock(self):
        """Docking implementation for lawn_mower entity."""
        if not self._can_accept_command():
            logging.warning("Request too quick, skip dock command")
            return

        if self.mission in self._get_recharge_missions():
            if self.mission_state == MissionState.MISSION_STATE_RUNNING:
                _LOGGER.info("Now is not ok to start recharge")
            elif self.mission_state == MissionState.MISSION_STATE_PAUSE:
                _LOGGER.info("ResumeRecharge : Resuming recharge")
                self._resume_recharge()
        else:
            _LOGGER.info("StartRecharge : Sending recharge command")
            self._start_normal_recharge()

    def _start_normal_mow(self):
        """Start normal mowing"""
        command = {
            'seq': self.get_cmd_seq(),
            'mode': 'START_MODE_GLOBAL_CLEAN',
            'global_clean': {'restart': False}
        }
        self.publish_data_point(103, command)

    def start_select_region_clean(self, region_ids: list[int]):
        """Start mowing for the specified sub-region IDs."""
        if not region_ids:
            _LOGGER.warning("start_select_region_clean called with empty region_ids")
            return
        if not self._can_accept_command():
            _LOGGER.warning("Request too quick, skip start_select_region_clean command")
            return
        command = {
            'seq': self.get_cmd_seq(),
            'mode': 'START_MODE_SELECT_REGION_CLEAN',
            'select_region': {'region_id': list(region_ids)}
        }
        _LOGGER.info("START SELECT REGION CLEAN: regions=%s", region_ids)
        self.publish_data_point(103, command)

    def _start_edge_trim(self):
        """Start edge-trim mowing"""
        command = {
            'seq': self.get_cmd_seq(),
            'mode': 'START_MODE_EDGE_TRIM_CLEAN'
        }
        self.publish_data_point(103, command)

    def start_edge_trim(self):
        """Public wrapper to start edge-trim mowing."""
        if not self._can_accept_command():
            logging.warning("Request too quick, skip start edge trim command")
            return

        _LOGGER.info("START EDGE TRIM : Sending edge trim command")
        self._start_edge_trim()

    def _resume_mow(self):
        """Resume mowing"""
        command = {'seq': self.get_cmd_seq()}
        self.publish_data_point(106, command)

    def _send_pause_command(self):
        """Send pause command"""
        command = {'seq': self.get_cmd_seq()}
        self.publish_data_point(105, command)

    def _start_normal_recharge(self):
        """Start normal recharging"""
        command = {
            'seq': self.get_cmd_seq(),
            'mode': 'START_MODE_RETURN'
        }
        self.publish_data_point(103, command)

    def _resume_recharge(self):
        """Resume recharging"""
        # 继续回充等效于继续割草
        return self._resume_mow();

    async def async_will_remove_from_hass(self):
        """Clean up resources when the entity is removed."""
        _LOGGER.info("Stopping MQTT client")
        self._stop_event.set()
        self._reset_map_retry()
        self._reset_path_retry()
        self._reset_history_path_retry()
        self._reset_pending_meta()
        if self.mqtt_client:
            self.mqtt_client.disconnect()

    def _request_compatibility_info(self):
        """Request version compatibility information."""
        try:
            _LOGGER.info("Requesting version compatibility information")
            # 发送空的请求来获取兼容性信息
            request_data = {"seq": self.get_cmd_seq()}
            self.publish_data_point(COMPATIBILITY_INFO_DP, request_data)
        except Exception as e:
            _LOGGER.error("Failed to request version compatibility information: %s", e)
