import threading
import paho.mqtt.client as mqtt_client
import logging
import time
import re
import json
import random
from homeassistant.components.lawn_mower import LawnMowerEntity
from homeassistant.components.lawn_mower.const import LawnMowerActivity, LawnMowerEntityFeature
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from . import TerraMowConfigEntry, TerraMowBasicData
from .const import MQTT_PORT, MQTT_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

# 定义正则表达式模式
TOPIC_PATTERN = re.compile(r"^data_point/(\d+)/robot$")

from enum import Enum, IntEnum

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
    config_entry: TerraMowConfigEntry,
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
    @property
    def name(self):
        """Name of the entity."""
        return "TerraMow Unknown model"

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
        self.callbacks = {}  # 存储 dp_id 和对应的回调函数
        self.basic_data.lawn_mower = self

        # 机器人状态
        self.mission = Mission.MISSION_IDLE
        self.sub_mission = SubMission.SUB_MISSION_IDLE
        self.mission_state = MissionState.MISSION_STATE_IDLE
        self.has_error = False

        self.cmd_seq = random.randint(0, 0xFFFFFFFF)  # 生成随机的指令序号

        self._last_control_time = time.monotonic()
        self._control_interval = 1.0 # 控制间隔时间

        self._has_returning = hasattr(LawnMowerActivity, 'RETURNING')
        if not self._has_returning:
            _LOGGER.info("LawnMowerActivity.RETURNING not available in this HA version")

        _LOGGER.info("TerraMowLawnMowerEntity created with host %s", self.host)


    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ('TerraMowLanwMower', self.basic_data.host)
            },
            name='TerraMow',
            manufacturer='TerraMow',
            model='TerraMow S1200'
        )

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
    def name(self):
        """Name of the entity."""
        return "TerraMow S1200"

    @property
    def activity(self) -> LawnMowerActivity:
        """Return the current activity of the lawn mower."""
        return self._activity

    @activity.setter
    def activity(self, value: LawnMowerActivity):
        """Set the current activity of the lawn mower."""
        self._activity = value
        _LOGGER.info("Activity changed to %s", value)
        self.schedule_update_ha_state()

    @property
    def supported_features(self) -> LawnMowerEntityFeature:
        """Flag lawn mower features that are supported."""
        return LawnMowerEntityFeature.START_MOWING | LawnMowerEntityFeature.PAUSE | LawnMowerEntityFeature.DOCK

    def start_mqtt_client(self):
        """Start the MQTT client in a separate thread."""
        self.mqtt_client = mqtt_client.Client()
        self.mqtt_client.username_pw_set(MQTT_USERNAME, self.password)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message

        # 启动 MQTT 循环线程
        self.mqtt_thread = threading.Thread(target=self.mqtt_loop)
        self.mqtt_thread.daemon = True
        self.mqtt_thread.start()

        self.register_all_callbacks()

    def register_all_callbacks(self):
        """Register all callbacks for data points."""
        self.register_callback(107, self.on_mission_status)

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

    async def on_mission_status(self, payload: str):
        """Handle mission status updates."""
        try:
            data = json.loads(payload)
            _LOGGER.info(f"Received mission status: {data}")
        except json.JSONDecodeError:
            _LOGGER.error(f"Invalid JSON payload: {payload}")
            return

        # Define a mapping from field names to enum classes
        enum_mapping = {
            "mission": Mission,
            "sub_mission": SubMission,
            "state": MissionState,
            "power_mode": PowerMode,
            "back_to_station_reason": BackToStationReason
        }

        # Convert enum strings to enum members
        for key, enum_class in enum_mapping.items():
            if key in data:
                try:
                    data[key] = enum_class(data[key])
                except KeyError:
                    _LOGGER.error(f"Invalid value for {key}: {data[key]}")
                    data[key] = None

        self.mission = data.get("mission", self.mission)
        self.sub_mission = data.get("sub_mission", self.sub_mission)
        self.mission_state = data.get("state", self.mission_state)
        self.has_error = data.get("has_error", self.has_error)

        self.update_activity_from_state()

    def mqtt_loop(self):
        """MQTT main loop with auto-reconnect."""
        while not self._stop_event.is_set():
            try:
                if not self.mqtt_client.is_connected():
                    _LOGGER.info("Attempting to connect to MQTT Broker %s", self.host)
                    self.mqtt_client.connect(self.host, MQTT_PORT, 60)
                    _LOGGER.info("Connected to MQTT Broker")
                self.mqtt_client.loop_forever()
            except Exception as e:
                _LOGGER.error(f"MQTT connection error: {e}")
                # 设置错误状态
                self.activity = LawnMowerActivity.ERROR
                self.schedule_update_ha_state()
                time.sleep(5)  # 等待 5 秒后重试

    def on_mqtt_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT Broker."""
        if rc == 0:
            _LOGGER.info("MQTT connected")
            # 订阅主题
            for dp_id in range(201):
                topic = f"data_point/{dp_id}/robot"
                client.subscribe(topic)
            self.update_activity_from_state()
        else:
            _LOGGER.error(f"MQTT connection failed with code {rc}")
            # 设置错误状态
            self.activity = LawnMowerActivity.ERROR
            self.schedule_update_ha_state()

    def on_mqtt_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT Broker."""
        if rc != 0:
            _LOGGER.warning(f"Unexpected MQTT disconnection: {rc}")
            # 断开连接后自动重连
            # 设置错误状态
            self.activity = LawnMowerActivity.ERROR
            self.schedule_update_ha_state()

    def on_mqtt_message(self, client, userdata, msg):
        """Callback when a message is received."""
        topic = msg.topic
        payload = msg.payload.decode()

        _LOGGER.debug(f"Received MQTT message: {topic} {payload}")

        # 使用正则表达式解析 topic
        match = TOPIC_PATTERN.fullmatch(topic)
        if not match:
            _LOGGER.warning(f"Invalid topic format: {topic}")
            return

        try:
            dp_id = int(match.group(1))
        except ValueError:
            _LOGGER.warning(f"Invalid dp_id in topic: {topic}")
            return

        # 调用对应的回调函数
        callback = self.callbacks.get(dp_id)
        if callback:
            self.hass.add_job(callback, payload)
        else:
            _LOGGER.debug(f"No callback registered for dp_id: {dp_id}")

    def register_callback(self, dp_id: int, callback: callable):
        """Register a callback function for a specific dp_id."""
        if not callable(callback):
            raise ValueError("Callback must be a callable function.")
        self.callbacks[dp_id] = callback
        _LOGGER.info(f"Callback registered for dp_id: {dp_id}")

    def publish_data_point(self, dp_id: int, data: dict):
        """Publish data to a specific data point."""
        topic = f"data_point/{dp_id}/app"
        _LOGGER.info(f"Publishing data to topic {topic}: {data}")
        payload = json.dumps(data)
        self.mqtt_client.publish(topic, payload)

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
        if self.mqtt_client:
            self.mqtt_client.disconnect()
