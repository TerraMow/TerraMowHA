from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfArea,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, TerraMowBasicData
from .const import (
    BASE_STATION_MAINTENANCE_CYCLE_MINUTES,
    BLADE_MAINTENANCE_CYCLE_MINUTES,
    MOW_SPEED_TYPES,
)
from .lawn_mower import Mission, MissionState, SubMission, TerraMowLawnMowerEntity

_LOGGER = logging.getLogger(__name__)


class TerraMowFeedbackSensor(SensorEntity):
    """展示设备的最近事件或当前故障；由设备反馈触发更新，无需轮询。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, basic_data: TerraMowBasicData, kind: str) -> None:
        """kind 选择事件或故障；状态由割草机实体保存，本传感器只负责展示。"""
        self.basic_data = basic_data
        self.kind = kind
        self._attr_translation_key = kind
        self._attr_unique_id = f"lawn_mower.terramow@{basic_data.stable_id}.{kind}"
        self._attr_icon = (
            "mdi:message-alert" if kind == "last_event" else "mdi:alert-circle"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)}
        )

    async def async_added_to_hass(self) -> None:
        """订阅反馈，并在实体卸载时自动撤销监听。"""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self.basic_data.lawn_mower.feedback.signal,
                self.async_write_ha_state,
            )
        )

    @property
    def native_value(self) -> int | None:
        feedback = self.basic_data.lawn_mower.feedback
        if self.kind == "last_event":
            return feedback.latest_event["code"] if feedback.latest_event else None
        if feedback.active_errors is None:
            return None
        return min(feedback.active_errors, default=0)

    @property
    def extra_state_attributes(self) -> dict:
        feedback = self.basic_data.lawn_mower.feedback
        if self.kind == "last_event":
            return dict(feedback.latest_event or {})
        return {"active_faults": list((feedback.active_errors or {}).values())}


class BatteryStateEnum(StrEnum):
    """Battery state type."""

    BATTERY_STATE_CHARGED = "BATTERY_STATE_CHARGED"
    BATTERY_STATE_CHARGING = "BATTERY_STATE_CHARGING"
    BATTERY_STATE_DISCHARGING = "BATTERY_STATE_DISCHARGING"


batteryStateDescription = SensorEntityDescription(
    name="TerraMow battery",
    key="terramow_battery_state_sensor",
    device_class=SensorDeviceClass.ENUM,
    options=[state.value for state in BatteryStateEnum],
)


class BatterySensor(SensorEntity):
    """Representation of the battery sensor."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery"
    _attr_translation_key = "battery"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_extra_state_attributes = {
        "state": "unknown",
        "temperature": "unknown",
        "charger_connected": "unknown",
        "is_switch_on": "unknown",
    }

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = self.basic_data.host
        self.hass = hass
        self._attr_native_value: int | None = None  # 初始化电池电量值
        self.basic_data.lawn_mower.register_callback(8, self.set_capacity)
        # self.basic_data.lawn_mower.register_callback(108, self.set_battery_attributes) # This is now handled by the lawn_mower entity

        _LOGGER.info("BatterySensor entity created")

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.battery"

    def set_capacity(self, payload: str) -> None:
        """Handle battery capacity status updates."""
        try:
            data = json.loads(payload)
            self._attr_native_value = data.get("int_value", self._attr_native_value)
            _LOGGER.info(f"Received battery capacity status: {data}")

        except json.JSONDecodeError:
            _LOGGER.error(f"Invalid JSON payload: {payload}")
            return

    @property
    def native_value(self) -> int | None:
        """Return value of sensor."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return {}

        battery_status = self.basic_data.lawn_mower.battery_status
        if not battery_status:
            return {}

        return {
            "state": battery_status.get("state", "unknown"),
            "temperature": battery_status.get("tempreture", "unknown").replace(
                "TEMPRETURE", "TEMPERATURE"
            ),
            "charger_connected": battery_status.get("charger_connected", "unknown"),
            "is_switch_on": battery_status.get("is_switch_on", "unknown"),
        }


_BATTERY_TEMPERATURE_STATES = {
    "BATTERY_TEMPRETURE_NORMAL": "normal",
    "BATTERY_TEMPRETURE_OVERHEAT": "overheat",
    "BATTERY_TEMPRETURE_UNDERHEAT": "underheat",
    "BATTERY_TEMPERATURE_NORMAL": "normal",
    "BATTERY_TEMPERATURE_OVERHEAT": "overheat",
    "BATTERY_TEMPERATURE_UNDERHEAT": "underheat",
}


class BatteryTemperatureStateSensor(SensorEntity):
    """将设备上报的电池温度等级展示为独立诊断实体。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:thermometer"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["normal", "overheat", "underheat"]
    _attr_translation_key = "battery_temperature_state"

    def __init__(self, basic_data: TerraMowBasicData, hass: HomeAssistant) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.hass = hass
        self._attr_unique_id = (
            f"lawn_mower.terramow@{basic_data.stable_id}.battery_temperature_state"
        )

    async def async_added_to_hass(self) -> None:
        """监听电池报告和连接变化，移除实体时同时撤销监听。"""
        await super().async_added_to_hass()
        for name in ("battery_status", "map_status"):
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"terramow_{self.basic_data.host}_{name}",
                    self.async_write_ha_state,
                )
            )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)}
        )

    @property
    def available(self) -> bool:
        mower = self.basic_data.lawn_mower
        return mower is not None and mower.mqtt_connected

    @property
    def native_value(self) -> str | None:
        mower = self.basic_data.lawn_mower
        if mower is None or not mower.battery_status_fresh:
            return None
        raw = mower.battery_status.get("tempreture")
        if not isinstance(raw, str):
            return None
        return _BATTERY_TEMPERATURE_STATES.get(raw)


class TotalMowingTimeSensor(SensorEntity):
    """Total mowing time sensor - uses dp_124 data"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "total_mowing_time"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.total_mowing_time"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        statistics_data = self.basic_data.lawn_mower.statistics_data
        if not statistics_data:
            return None

        return statistics_data.get("duration")


class CurrentSessionAreaSensor(SensorEntity):
    """Current session mowing area sensor - uses dp_113 data"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:vector-square"
    _attr_native_unit_of_measurement = UnitOfArea.SQUARE_METERS
    _attr_device_class = None
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "current_session_area"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.current_session_area"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        current_work_data = self.basic_data.lawn_mower.current_work_data
        if not current_work_data:
            return None

        # clean_area单位为0.1平方米，转换为平方米
        clean_area = current_work_data.get("clean_area", 0)
        return round(clean_area / 10, 1) if clean_area else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return {}

        current_work_data = self.basic_data.lawn_mower.current_work_data
        if not current_work_data:
            return {}

        attrs = {}
        work_type = current_work_data.get("type", "")
        if work_type:
            attrs["work_type"] = work_type

        total_area = current_work_data.get("total_area", 0)
        if total_area:
            attrs["total_area"] = round(total_area / 10, 1)

        is_completed = current_work_data.get("is_completed")
        if is_completed is not None:
            attrs["is_completed"] = is_completed

        return attrs


# 以下条件决定当前作业的面积数据是否可用于展示割草进度。
_BUILD_AREA_TYPES = frozenset(
    {"MAP_AREA_TYPE_BUILD_MAP", "MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING"}
)
# 协议规定这些类型没有可用于计算进度的总面积（NONE 表示从未作业）。
# 工作模式可能晚于作业数据到达，因此先按 dp_113 的类型排除。
_NO_PROGRESS_AREA_TYPES = frozenset(
    {
        "MAP_AREA_TYPE_NONE",
        "MAP_AREA_TYPE_DRAW_REGION_CLEANING",
        "MAP_AREA_TYPE_EDGE_TRIM_CLEANING",
    }
)
_PROGRESS_MOW_MODES = frozenset({"MOW_MODE_GLOBAL", "MOW_MODE_SELECT_REGION"})
_INVALID_MAP_ID = -1
_UNFINISHED_PROGRESS_CAP = 98.0


class CurrentSessionProgressSensor(SensorEntity):
    """根据设备上报展示当前割草作业进度。

    进度只在“基站地图已建完、全局或选区割草”时显示，作业完成前最多 98%，
    设备报告已完成才是 100%。输入来自 dp_113 作业面积、dp_117 地图状态、
    dp_107 任务状态和 dp_154 工作模式，任何一路更新都会立即刷新。
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:progress-check"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "current_session_progress"

    # 割草机实体按同样的名称发送信号；用主机标识拼接，兼容平台装载顺序。
    # map_status 信号同时承担 MQTT 连接与断线通知，用来刷新可用性。
    _SIGNALS = ("current_work_data", "map_status", "mission", "work_mode")

    def __init__(self, basic_data: TerraMowBasicData, hass: HomeAssistant) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.hass = hass
        self._attr_unique_id = (
            f"lawn_mower.terramow@{basic_data.stable_id}.current_session_progress"
        )

    async def async_added_to_hass(self) -> None:
        """订阅四路上报，实体移除时自动撤销监听。"""
        await super().async_added_to_hass()
        for name in self._SIGNALS:
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"terramow_{self.basic_data.host}_{name}",
                    self.async_write_ha_state,
                )
            )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)}
        )

    @property
    def available(self) -> bool:
        mower = self.basic_data.lawn_mower
        return mower is not None and mower.mqtt_connected

    @property
    def native_value(self) -> float | None:
        mower = self.basic_data.lawn_mower
        work = mower.current_work_data if mower is not None else None
        if not work or work.get("type") in _NO_PROGRESS_AREA_TYPES:
            return None
        if not self._progress_is_applicable(mower):
            return None

        if mower.sub_mission is SubMission.SUB_MISSION_WAIT_FOR_DAYLIGHT:
            return 0.0
        # 地图已建完时，建图类面积不代表割草进度。
        if (
            work.get("type") in _BUILD_AREA_TYPES
            and mower.map_status.get("map_id", 0) != _INVALID_MAP_ID
        ):
            return 0.0
        if work.get("is_completed") is True:
            return 100.0

        total_area = work.get("total_area") or 0
        if total_area <= 0:
            return 0.0
        progress = 100.0 * (work.get("clean_area") or 0) / total_area
        return round(min(progress, _UNFINISHED_PROGRESS_CAP), 1)

    @staticmethod
    def _progress_is_applicable(mower: TerraMowLawnMowerEntity | None) -> bool:
        """判断当前地图与任务模式是否适合展示割草进度。

        未收到 dp_154 或载荷缺字段时，按默认的基站地图和全局割草处理，
        避免旧固件缺少工作模式数据时一直显示未知。
        """
        if mower is None:
            return False
        map_status = mower.map_status
        mode = mower.work_mode
        if mode.get("map_mode") == "MAP_MODE_SPOT":
            return False
        map_complete = (
            map_status.get("is_map_detected") is True
            and map_status.get("map_state") == "MAP_STATE_COMPLETE"
        )
        if not map_complete or map_status.get("is_able_to_run_build_map") is True:
            return False
        if mower.mission is Mission.MISSION_BUILD_MAP_AND_CLEAN:
            return False
        return mode.get("mow_mode", "MOW_MODE_GLOBAL") in _PROGRESS_MOW_MODES


class CurrentSessionTimeSensor(SensorEntity):
    """Current session mowing time sensor - uses dp_113 data"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "current_session_time"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.current_session_time"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        current_work_data = self.basic_data.lawn_mower.current_work_data
        if not current_work_data:
            return None

        return current_work_data.get("work_duration")


class RemainingBladeTimeSensor(SensorEntity):
    """Remaining blade usage time sensor - uses dp_126 data"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:saw-blade"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "remaining_blade_time"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.remaining_blade_time"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        blade_time = self.basic_data.lawn_mower.blade_time
        if not blade_time:
            return None

        used_time = blade_time.get("int_value", 0)
        # 刀盘推荐清洁周期为240小时,即14400分钟
        remaining_time = BLADE_MAINTENANCE_CYCLE_MINUTES - used_time
        return max(0, remaining_time)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return {}

        blade_time = self.basic_data.lawn_mower.blade_time
        if not blade_time:
            return {}

        used_time = blade_time.get("int_value", 0)
        return {
            "used_time": used_time,
            "recommended_cycle": BLADE_MAINTENANCE_CYCLE_MINUTES,
            "recommended_cycle_hours": BLADE_MAINTENANCE_CYCLE_MINUTES // 60,
            "needs_maintenance": used_time >= BLADE_MAINTENANCE_CYCLE_MINUTES,
        }


class RemainingBaseStationTimeSensor(SensorEntity):
    """Remaining base station cleaning time sensor - uses dp_125 data"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-clock"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "remaining_base_station_time"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.remaining_base_station_time"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        base_station_time = self.basic_data.lawn_mower.base_station_time
        if not base_station_time:
            return None

        used_time = base_station_time.get("int_value", 0)
        # 基站推荐清洁周期为30天，即43200分钟
        remaining_time = BASE_STATION_MAINTENANCE_CYCLE_MINUTES - used_time
        return max(0, remaining_time)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return {}

        base_station_time = self.basic_data.lawn_mower.base_station_time
        if not base_station_time:
            return {}

        used_time = base_station_time.get("int_value", 0)
        return {
            "used_time": used_time,
            "recommended_cycle": BASE_STATION_MAINTENANCE_CYCLE_MINUTES,  # 30 days in minutes
            "recommended_cycle_days": BASE_STATION_MAINTENANCE_CYCLE_MINUTES
            // (60 * 24),
            "needs_maintenance": used_time >= BASE_STATION_MAINTENANCE_CYCLE_MINUTES,
        }


class TerraMowMowHeightSensor(SensorEntity):
    """割草高度传感器 - 使用dp_155数据"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:arrow-up-down"
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "mow_height"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.mow_height"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None

        mow_height = global_params.get("mow_height", {})
        return mow_height.get("value")


class TerraMowMowSpeedSensor(SensorEntity):
    """割草速度传感器 - 使用dp_155数据"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:speedometer"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "mow_speed"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = MOW_SPEED_TYPES.copy()

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass
        self._unknown_speed_type: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.mow_speed"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None

        mow_speed = global_params.get("mow_speed", {})
        speed_type = mow_speed.get("speed_type")
        if not speed_type:
            self._unknown_speed_type = None
            return None

        if speed_type in self._attr_options:
            self._unknown_speed_type = None
            return speed_type

        if speed_type != self._unknown_speed_type:
            _LOGGER.warning(
                "Unknown mow speed type from device: %s. Expose raw value in attributes.",
                speed_type,
            )
            self._unknown_speed_type = speed_type

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return {}

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return {}

        attrs = {}

        # 割草间距
        mow_spacing = global_params.get("mow_spacing", {})
        if "value" in mow_spacing:
            attrs["mow_spacing"] = mow_spacing["value"]

        # 沿边割草距离
        edge_cutting_distance = global_params.get("edge_cutting_distance", {})
        if "value" in edge_cutting_distance:
            attrs["edge_cutting_distance"] = edge_cutting_distance["value"]

        # 刀盘转速
        blade_disk_speed = global_params.get("blade_disk_speed", {})
        if "speed_type" in blade_disk_speed:
            attrs["blade_disk_speed"] = blade_disk_speed["speed_type"]

        if self._unknown_speed_type:
            attrs["unknown_mow_speed_type"] = self._unknown_speed_type

        return attrs


class NextScheduledStartSensor(SensorEntity):
    """Next scheduled start sensor - uses dp_138 data"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "next_scheduled_start"
    _attr_device_class = None  # 使用字符串显示时间

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.next_scheduled_start"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        schedule_data = self.basic_data.lawn_mower.schedule_data
        if not schedule_data:
            return None

        # 检查是否存在预约
        if not schedule_data.get("exist", False):
            return None

        start_time = schedule_data.get("start_time", {})
        if not start_time or "hour" not in start_time or "minute" not in start_time:
            return None

        # 返回格式化的时间字符串
        hour = start_time["hour"]
        minute = start_time["minute"]
        return f"{hour:02d}:{minute:02d}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return {}

        schedule_data = self.basic_data.lawn_mower.schedule_data
        if not schedule_data:
            return {}

        attrs = {}

        if schedule_data.get("exist", False):
            attrs["has_schedule"] = True
            attrs["item_id"] = schedule_data.get("item_id")
            attrs["shift_id"] = schedule_data.get("shift_id")

            # 结束时间
            end_time = schedule_data.get("end_time", {})
            if end_time and "hour" in end_time and "minute" in end_time:
                attrs["end_time"] = f"{end_time['hour']:02d}:{end_time['minute']:02d}"
        else:
            attrs["has_schedule"] = False

        return attrs


class VersionCompatibilitySensor(SensorEntity):
    """版本兼容性状态传感器."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:update"
    _attr_translation_key = "version_compatibility"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the sensor."""
        self.basic_data = basic_data
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"version_compatibility.terramow@{self.basic_data.stable_id}"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.basic_data.compatibility_status

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attributes = {}

        # 获取兼容性消息
        attributes["message"] = self.basic_data.get_compatibility_message()

        # 添加详细的版本信息
        firmware_info = self.basic_data.firmware_version
        if firmware_info:
            attributes["firmware_overall_version"] = firmware_info.get(
                "overall", "unknown"
            )
            module_info = firmware_info.get("module", {})
            attributes["firmware_ha_version"] = module_info.get(
                "home_assistant", "unknown"
            )
            attributes["firmware_map_version"] = module_info.get("map", "unknown")
            attributes["firmware_control_version"] = module_info.get(
                "control", "unknown"
            )

        from .const import CURRENT_HA_VERSION, MIN_REQUIRED_OVERALL_VERSION

        attributes["plugin_ha_version"] = CURRENT_HA_VERSION
        attributes["min_required_overall_version"] = MIN_REQUIRED_OVERALL_VERSION

        return attributes


class TerraMowPoseSensor(SensorEntity):
    """实时姿态传感器（2Hz）"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:crosshairs-gps"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "pose"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass
        self._pose: dict[str, Any] = {}

        if hasattr(basic_data, "lawn_mower") and basic_data.lawn_mower:
            basic_data.lawn_mower.register_pose_callback(self._on_pose)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)},
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.pose"

    async def _on_pose(self, pose: dict[str, Any]) -> None:
        """处理姿态更新"""
        self._pose = pose
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the sensor value (yaw)."""
        if not self._pose:
            return None
        yaw = self._pose.get("yaw")
        return float(yaw) if yaw is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        if not self._pose:
            return {}
        return {
            "x": self._pose.get("x"),
            "y": self._pose.get("y"),
            "yaw": self._pose.get("yaw"),
            "timestamp_ms": self._pose.get("timestamp_ms"),
            "frame": self._pose.get("frame"),
        }

    @property
    def available(self):
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    basic_data = hass.data[DOMAIN][config_entry.entry_id]

    # 导入地图相关传感器类
    from .map_sensor import (
        TerraMowCleanModeSensor,
        TerraMowMapAreaSensor,
        TerraMowMapStatusSensor,
    )

    # 创建传感器实体列表
    entities = [
        TerraMowFeedbackSensor(basic_data, "last_event"),
        TerraMowFeedbackSensor(basic_data, "active_fault"),
        # 基本传感器
        BatterySensor(basic_data, hass),
        BatteryTemperatureStateSensor(basic_data, hass),
        TerraMowPoseSensor(basic_data, hass),
        # 地图相关传感器
        TerraMowMapStatusSensor(basic_data, hass),
        TerraMowMapAreaSensor(basic_data, hass),
        TerraMowCleanModeSensor(basic_data, hass),
        # 全局参数显示传感器 (dp_155)
        TerraMowMowHeightSensor(basic_data, hass),
        TerraMowMowSpeedSensor(basic_data, hass),
        # 统计和会话传感器
        TotalMowingTimeSensor(basic_data, hass),
        CurrentSessionAreaSensor(basic_data, hass),
        CurrentSessionProgressSensor(basic_data, hass),
        CurrentSessionTimeSensor(basic_data, hass),
        # 维护提醒传感器
        RemainingBladeTimeSensor(basic_data, hass),
        RemainingBaseStationTimeSensor(basic_data, hass),
        # 计划任务传感器
        NextScheduledStartSensor(basic_data, hass),
        # 版本兼容性传感器
        VersionCompatibilitySensor(basic_data, hass),
        # 主方向状态传感器
        MainDirectionStatusSensor(basic_data, hass),
        # dp_107 中的任务、子任务和任务阶段
        TerraMowMissionSensor(basic_data, hass),
        TerraMowSubMissionSensor(basic_data, hass),
        TerraMowMissionStateSensor(basic_data, hass),
    ]

    async_add_entities(entities)


class MainDirectionStatusSensor(SensorEntity):
    """主方向状态传感器 - 显示当前主方向配置和角度"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:compass"
    _attr_translation_key = "main_direction_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.stable_id)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.main_direction_status"

    @property
    def native_value(self) -> str | None:
        """Return the sensor value."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return "unavailable"

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return "no_config"

        main_direction_config = global_params.get("main_direction_angle_config", {})
        mode = main_direction_config.get("mode", "MAIN_DIRECTION_MODE_SINGLE")

        # 返回当前模式作为传感器值
        return mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {}

        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return attrs

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return attrs

        main_direction_config = global_params.get("main_direction_angle_config", {})

        # 基本模式信息
        mode = main_direction_config.get("mode", "MAIN_DIRECTION_MODE_SINGLE")
        attrs["mode"] = mode

        # 当前角度（如果有）
        current_angle = main_direction_config.get("current_angle")
        if current_angle is not None:
            attrs["current_angle"] = current_angle
            attrs["current_angle_degrees"] = f"{current_angle}°"

        # 根据模式添加特定配置信息
        if mode == "MAIN_DIRECTION_MODE_SINGLE":
            single_config = main_direction_config.get("single_mode_config", {})
            configured_angle = single_config.get("angle", 0)
            attrs["configured_angle"] = configured_angle
            attrs["configured_angle_degrees"] = f"{configured_angle}°"
            attrs["mode_description"] = "Single main direction"

        elif mode == "MAIN_DIRECTION_MODE_MULTIPLE":
            multiple_config = main_direction_config.get("multiple_mode_config", {})
            configured_angles = multiple_config.get("angles", [])
            attrs["configured_angles"] = configured_angles
            attrs["configured_angles_degrees"] = [
                f"{angle}°" for angle in configured_angles
            ]
            attrs["angles_count"] = len(configured_angles)
            attrs["mode_description"] = "Multiple main directions"

        elif mode == "MAIN_DIRECTION_MODE_AUTO_ROTATE":
            auto_config = main_direction_config.get("auto_rotate_mode_config", {})
            interval = auto_config.get("angle_interval", 15)
            attrs["rotation_interval"] = interval
            attrs["rotation_interval_degrees"] = f"{interval}°"
            attrs["mode_description"] = "Auto rotate main direction"

        # 添加模式可读名称
        mode_names = {
            "MAIN_DIRECTION_MODE_SINGLE": "Single Direction",
            "MAIN_DIRECTION_MODE_MULTIPLE": "Multiple Directions",
            "MAIN_DIRECTION_MODE_AUTO_ROTATE": "Auto Rotate",
        }
        attrs["mode_friendly_name"] = mode_names.get(mode, mode)

        return attrs


class _MissionEnumSensorBase(SensorEntity):
    """把割草机已解析的 dp_107 枚举状态展示为只读诊断传感器。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM

    _enum_attr: str = ""
    _unique_suffix: str = ""

    def __init__(self, basic_data: TerraMowBasicData, hass: HomeAssistant) -> None:
        """共享割草机状态；实体只负责展示，不拥有设备连接。"""
        super().__init__()
        self.basic_data = basic_data
        self.hass = hass
        self._attr_unique_id = (
            f"lawn_mower.terramow@{basic_data.stable_id}.{self._unique_suffix}"
        )

    async def async_added_to_hass(self) -> None:
        """订阅解析后的状态，并在实体移除时撤销监听。"""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self.basic_data.lawn_mower.mission_signal,
                self.async_write_ha_state,
            )
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)}
        )

    @property
    def available(self) -> bool:
        return self.basic_data.lawn_mower is not None

    @property
    def native_value(self) -> str | None:
        value = self._protocol_value()
        if value is None:
            return None
        state = value.lower()
        return state if state in self.options else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """保留设备原始枚举，状态本身使用可被 HA 翻译的小写键。"""
        value = self._protocol_value()
        return {"protocol_value": value} if value is not None else {}

    def _protocol_value(self) -> str | None:
        """读取已解析的枚举，不把未知值伪装成有效状态。"""
        mower = self.basic_data.lawn_mower
        if mower is None:
            return None
        member = getattr(mower, self._enum_attr, None)
        value = getattr(member, "value", member)
        if not isinstance(value, str) or value.lower() not in self.options:
            return None
        return value


class TerraMowMissionSensor(_MissionEnumSensorBase):
    """展示当前顶层任务。"""

    _attr_icon = "mdi:robot-mower-outline"
    _attr_translation_key = "mission"
    _attr_options = [member.value.lower() for member in Mission]
    _enum_attr = "mission"
    _unique_suffix = "mission"


class TerraMowSubMissionSensor(_MissionEnumSensorBase):
    """展示等待雨停、降温等当前子任务。"""

    _attr_icon = "mdi:list-status"
    _attr_translation_key = "sub_mission"
    _attr_options = [member.value.lower() for member in SubMission]
    _enum_attr = "sub_mission"
    _unique_suffix = "sub_mission"


class TerraMowMissionStateSensor(_MissionEnumSensorBase):
    """展示任务运行、暂停或完成等阶段。"""

    _attr_icon = "mdi:state-machine"
    _attr_translation_key = "mission_state"
    _attr_options = [member.value.lower() for member in MissionState]
    _enum_attr = "mission_state"
    _unique_suffix = "mission_state"
