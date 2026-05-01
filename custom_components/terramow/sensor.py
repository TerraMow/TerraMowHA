from __future__ import annotations
import logging
import json

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
    SensorEntityDescription
)

from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTime,
    UnitOfArea,
    UnitOfLength
)
from homeassistant.core import HomeAssistant

from enum import StrEnum
from typing import Any
from homeassistant.config_entries import ConfigEntry
from . import TerraMowBasicData, DOMAIN
from .const import (
    BLADE_MAINTENANCE_CYCLE_MINUTES,
    BASE_STATION_MAINTENANCE_CYCLE_MINUTES,
    MOW_SPEED_TYPES,
)
from .lawn_mower import Mission, SubMission, MissionState

_LOGGER = logging.getLogger(__name__)

class BatteryStateEnum(StrEnum):
    """Battery state type."""
    BATTERY_STATE_CHARGED = "BATTERY_STATE_CHARGED"
    BATTERY_STATE_CHARGING = "BATTERY_STATE_CHARGING"
    BATTERY_STATE_DISCHARGING = "BATTERY_STATE_DISCHARGING"

batteryStateDescription = SensorEntityDescription(
    name="TerraMow battery",
    key="terramow_battery_state_sensor",
    device_class=SensorDeviceClass.ENUM,
    options= [state.value for state in BatteryStateEnum]
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
        'state': 'unknown',
        'temperature': 'unknown',
        'charger_connected': 'unknown',
        'is_switch_on': 'unknown'
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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.battery"


    def set_capacity(self, payload :str) -> None:
        """Handle battery capacity status updates."""
        try:
            data = json.loads(payload)
            self._attr_native_value = data.get('int_value', self._attr_native_value)
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
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return {}

        battery_status = self.basic_data.lawn_mower.battery_status
        if not battery_status:
            return {}

        return {
            'state': battery_status.get('state', 'unknown'),
            'temperature': battery_status.get('tempreture', 'unknown').replace('TEMPRETURE', 'TEMPERATURE'),
            'charger_connected': battery_status.get('charger_connected', 'unknown'),
            'is_switch_on': battery_status.get('is_switch_on', 'unknown')
        }


class BatteryStateSensor(SensorEntity):
    """Battery state sensor - uses dp_108 data."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-charging"
    _attr_translation_key = "battery_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "BATTERY_STATE_DISCHARGE",
        "BATTERY_STATE_CHARGING",
        "BATTERY_STATE_CHARGED",
    ]
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
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.battery_state"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        battery_status = self.basic_data.lawn_mower.battery_status
        if not battery_status:
            return None

        state = battery_status.get('state')
        if state in self._attr_options:
            return state
        return None


class BatteryTemperatureStateSensor(SensorEntity):
    """Battery temperature state sensor - uses dp_108 data."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer"
    _attr_translation_key = "battery_temperature_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "BATTERY_TEMPRETURE_NORMAL",
        "BATTERY_TEMPRETURE_OVERHEAT",
        "BATTERY_TEMPRETURE_UNDERHEAT",
    ]
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
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.battery_temperature_state"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        battery_status = self.basic_data.lawn_mower.battery_status
        if not battery_status:
            return None

        # Firmware reports the field as 'tempreture' (typo preserved).
        value = battery_status.get('tempreture')
        if value in self._attr_options:
            return value
        return None


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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.total_mowing_time"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        statistics_data = self.basic_data.lawn_mower.statistics_data
        if not statistics_data:
            return None

        return statistics_data.get('duration')


class TotalMowingJobsSensor(SensorEntity):
    """Total mowing jobs sensor - uses dp_124 data"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = None
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "total_mowing_jobs"

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
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.total_mowing_jobs"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        statistics_data = self.basic_data.lawn_mower.statistics_data
        if not statistics_data:
            return None

        return statistics_data.get('clean_times')


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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.current_session_area"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        current_work_data = self.basic_data.lawn_mower.current_work_data
        if not current_work_data:
            return None

        # clean_area单位为0.1平方米，转换为平方米
        clean_area = current_work_data.get('clean_area', 0)
        return round(clean_area / 10, 1) if clean_area else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return {}

        current_work_data = self.basic_data.lawn_mower.current_work_data
        if not current_work_data:
            return {}

        attrs = {}
        work_type = current_work_data.get('type', '')
        if work_type:
            attrs['work_type'] = work_type

        total_area = current_work_data.get('total_area', 0)
        if total_area:
            attrs['total_area'] = round(total_area / 10, 1)

        is_completed = current_work_data.get('is_completed')
        if is_completed is not None:
            attrs['is_completed'] = is_completed

        return attrs


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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.current_session_time"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        current_work_data = self.basic_data.lawn_mower.current_work_data
        if not current_work_data:
            return None

        return current_work_data.get('work_duration')


class CurrentJobTypeSensor(SensorEntity):
    """Current job type sensor - uses dp_113 data"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:format-list-bulleted-type"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "MAP_AREA_TYPE_NONE",
        "MAP_AREA_TYPE_BUILD_MAP",
        "MAP_AREA_TYPE_CLEANING",
        "MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING",
        "MAP_AREA_TYPE_SELECT_REGION_CLEANING",
        "MAP_AREA_TYPE_DRAW_REGION_CLEANING",
        "MAP_AREA_TYPE_EDGE_TRIM_CLEANING",
    ]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "current_job_type"

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
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.current_job_type"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        current_work_data = self.basic_data.lawn_mower.current_work_data
        if not current_work_data:
            return None

        job_type = current_work_data.get('type')
        if job_type in self._attr_options:
            return job_type
        return None


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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.remaining_blade_time"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        blade_time = self.basic_data.lawn_mower.blade_time
        if not blade_time:
            return None

        used_time = blade_time.get('int_value', 0)
        # 刀盘推荐清洁周期为240小时,即14400分钟
        remaining_time = BLADE_MAINTENANCE_CYCLE_MINUTES - used_time
        return max(0, remaining_time)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return {}

        blade_time = self.basic_data.lawn_mower.blade_time
        if not blade_time:
            return {}

        used_time = blade_time.get('int_value', 0)
        return {
            'used_time': used_time,
            'recommended_cycle': BLADE_MAINTENANCE_CYCLE_MINUTES,
            'recommended_cycle_hours': BLADE_MAINTENANCE_CYCLE_MINUTES // 60,
            'needs_maintenance': used_time >= BLADE_MAINTENANCE_CYCLE_MINUTES
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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.remaining_base_station_time"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        base_station_time = self.basic_data.lawn_mower.base_station_time
        if not base_station_time:
            return None

        used_time = base_station_time.get('int_value', 0)
        # 基站推荐清洁周期为30天，即43200分钟
        remaining_time = BASE_STATION_MAINTENANCE_CYCLE_MINUTES - used_time
        return max(0, remaining_time)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return {}

        base_station_time = self.basic_data.lawn_mower.base_station_time
        if not base_station_time:
            return {}

        used_time = base_station_time.get('int_value', 0)
        return {
            'used_time': used_time,
            'recommended_cycle': BASE_STATION_MAINTENANCE_CYCLE_MINUTES,  # 30 days in minutes
            'recommended_cycle_days': BASE_STATION_MAINTENANCE_CYCLE_MINUTES // (60 * 24),
            'needs_maintenance': used_time >= BASE_STATION_MAINTENANCE_CYCLE_MINUTES
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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.mow_height"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None

        mow_height = global_params.get('mow_height', {})
        return mow_height.get('value')


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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.mow_speed"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None

        mow_speed = global_params.get('mow_speed', {})
        speed_type = mow_speed.get('speed_type')
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
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return {}

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return {}

        attrs = {}

        # 割草间距
        mow_spacing = global_params.get('mow_spacing', {})
        if 'value' in mow_spacing:
            attrs['mow_spacing'] = mow_spacing['value']

        # 沿边割草距离
        edge_cutting_distance = global_params.get('edge_cutting_distance', {})
        if 'value' in edge_cutting_distance:
            attrs['edge_cutting_distance'] = edge_cutting_distance['value']

        # 刀盘转速
        blade_disk_speed = global_params.get('blade_disk_speed', {})
        if 'speed_type' in blade_disk_speed:
            attrs['blade_disk_speed'] = blade_disk_speed['speed_type']

        if self._unknown_speed_type:
            attrs['unknown_mow_speed_type'] = self._unknown_speed_type

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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.next_scheduled_start"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        schedule_data = self.basic_data.lawn_mower.schedule_data
        if not schedule_data:
            return None

        # 检查是否存在预约
        if not schedule_data.get('exist', False):
            return None

        start_time = schedule_data.get('start_time', {})
        if not start_time or 'hour' not in start_time or 'minute' not in start_time:
            return None

        # 返回格式化的时间字符串
        hour = start_time['hour']
        minute = start_time['minute']
        return f"{hour:02d}:{minute:02d}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return {}

        schedule_data = self.basic_data.lawn_mower.schedule_data
        if not schedule_data:
            return {}

        attrs = {}

        if schedule_data.get('exist', False):
            attrs['has_schedule'] = True
            attrs['item_id'] = schedule_data.get('item_id')
            attrs['shift_id'] = schedule_data.get('shift_id')

            # 结束时间
            end_time = schedule_data.get('end_time', {})
            if end_time and 'hour' in end_time and 'minute' in end_time:
                attrs['end_time'] = f"{end_time['hour']:02d}:{end_time['minute']:02d}"
        else:
            attrs['has_schedule'] = False

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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"version_compatibility.terramow@{self.basic_data.host}"

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
            attributes["firmware_overall_version"] = firmware_info.get("overall", "unknown")
            module_info = firmware_info.get("module", {})
            attributes["firmware_ha_version"] = module_info.get("home_assistant", "unknown")
            attributes["firmware_map_version"] = module_info.get("map", "unknown")
            attributes["firmware_control_version"] = module_info.get("control", "unknown")

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

        if hasattr(basic_data, 'lawn_mower') and basic_data.lawn_mower:
            basic_data.lawn_mower.register_pose_callback(self._on_pose)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.pose"

    async def _on_pose(self, pose: dict[str, Any]) -> None:
        """处理姿态更新"""
        self._pose = pose
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the sensor value (yaw)."""
        if not self._pose:
            return None
        yaw = self._pose.get('yaw')
        return float(yaw) if yaw is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        if not self._pose:
            return {}
        return {
            'x': self._pose.get('x'),
            'y': self._pose.get('y'),
            'yaw': self._pose.get('yaw'),
            'timestamp_ms': self._pose.get('timestamp_ms'),
            'frame': self._pose.get('frame'),
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
        TerraMowMapStatusSensor,
        TerraMowMapAreaSensor,
        TerraMowCleanModeSensor,
    )

    # 创建传感器实体列表
    entities = [
        # 基本传感器
        BatterySensor(basic_data, hass),
        BatteryStateSensor(basic_data, hass),
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
        TotalMowingJobsSensor(basic_data, hass),
        CurrentSessionAreaSensor(basic_data, hass),
        CurrentSessionTimeSensor(basic_data, hass),
CurrentJobTypeSensor(basic_data, hass),

        # 维护提醒传感器
        RemainingBladeTimeSensor(basic_data, hass),
        RemainingBaseStationTimeSensor(basic_data, hass),

        # 计划任务传感器
        NextScheduledStartSensor(basic_data, hass),

        # 版本兼容性传感器
        VersionCompatibilitySensor(basic_data, hass),

        # 主方向状态传感器
        MainDirectionStatusSensor(basic_data, hass),

        # 电源模式传感器 (dp_107)
        PowerModeSensor(basic_data, hass),

        # 任务状态相关 (dp_107)
        BackToStationReasonSensor(basic_data, hass),
        TerraMowMissionSensor(basic_data, hass),
        TerraMowSubMissionSensor(basic_data, hass),
        TerraMowMissionStateSensor(basic_data, hass),
    ]

    async_add_entities(entities)


class PowerModeSensor(SensorEntity):
    """Power mode sensor - uses dp_107 data."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "POWER_MODE_RUNNING",
        "POWER_MODE_STANDBY",
        "POWER_MODE_HIBERNATE",
    ]
    _attr_translation_key = "power_mode"
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
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.power_mode"

    @property
    def native_value(self) -> str | None:
        """Return the current power mode."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        power_mode = self.basic_data.lawn_mower.power_mode
        if power_mode in self._attr_options:
            return power_mode
        return None

    @property
    def available(self):
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None


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
            identifiers={('TerraMowLawnMower', self.basic_data.host)}, # Corrected typo in identifier
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.main_direction_status"

    @property
    def native_value(self) -> str | None:
        """Return the sensor value."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return "unavailable"

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return "no_config"

        main_direction_config = global_params.get('main_direction_angle_config', {})
        mode = main_direction_config.get('mode', 'MAIN_DIRECTION_MODE_SINGLE')

        # 返回当前模式作为传感器值
        return mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {}

        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return attrs

        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return attrs

        main_direction_config = global_params.get('main_direction_angle_config', {})

        # 基本模式信息
        mode = main_direction_config.get('mode', 'MAIN_DIRECTION_MODE_SINGLE')
        attrs['mode'] = mode

        # 当前角度（如果有）
        current_angle = main_direction_config.get('current_angle')
        if current_angle is not None:
            attrs['current_angle'] = current_angle
            attrs['current_angle_degrees'] = f"{current_angle}°"

        # 根据模式添加特定配置信息
        if mode == 'MAIN_DIRECTION_MODE_SINGLE':
            single_config = main_direction_config.get('single_mode_config', {})
            configured_angle = single_config.get('angle', 0)
            attrs['configured_angle'] = configured_angle
            attrs['configured_angle_degrees'] = f"{configured_angle}°"
            attrs['mode_description'] = "Single main direction"

        elif mode == 'MAIN_DIRECTION_MODE_MULTIPLE':
            multiple_config = main_direction_config.get('multiple_mode_config', {})
            configured_angles = multiple_config.get('angles', [])
            attrs['configured_angles'] = configured_angles
            attrs['configured_angles_degrees'] = [f"{angle}°" for angle in configured_angles]
            attrs['angles_count'] = len(configured_angles)
            attrs['mode_description'] = "Multiple main directions"

        elif mode == 'MAIN_DIRECTION_MODE_AUTO_ROTATE':
            auto_config = main_direction_config.get('auto_rotate_mode_config', {})
            interval = auto_config.get('angle_interval', 15)
            attrs['rotation_interval'] = interval
            attrs['rotation_interval_degrees'] = f"{interval}°"
            attrs['mode_description'] = "Auto rotate main direction"

        # 添加模式可读名称
        mode_names = {
            'MAIN_DIRECTION_MODE_SINGLE': 'Single Direction',
            'MAIN_DIRECTION_MODE_MULTIPLE': 'Multiple Directions',
            'MAIN_DIRECTION_MODE_AUTO_ROTATE': 'Auto Rotate'
        }
        attrs['mode_friendly_name'] = mode_names.get(mode, mode)

        return attrs


BACK_TO_STATION_REASON_OPTIONS = [
    "BACK_TO_STATION_REASON_NONE",
    "BACK_TO_STATION_REASON_LOW_BATTERY",
    "BACK_TO_STATION_REASON_RAINING",
    "BACK_TO_STATION_REASON_MOW_MOTOR_OVERHEAT",
    "BACK_TO_STATION_REASON_WHEEL_OVERHEAT",
    "BACK_TO_STATION_REASON_NIGHT_TIME",
]


class BackToStationReasonSensor(SensorEntity):
    """Enum sensor exposing the dp_107 back_to_station_reason field."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-import-outline"
    _attr_translation_key = "back_to_station_reason"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = BACK_TO_STATION_REASON_OPTIONS.copy()

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
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.back_to_station_reason"

    @property
    def native_value(self) -> str | None:
        """Return the raw back_to_station_reason enum string."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None
        reason = self.basic_data.lawn_mower.back_to_station_reason
        if reason in self._attr_options:
            return reason
        return None

    @property
    def available(self):
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None


class _MissionEnumSensorBase(SensorEntity):
    """Shared base for the dp_107 mission/sub_mission/state enum sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM

    _enum_attr: str = ""
    _unique_suffix: str = ""

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.basic_data.lawn_mower:
            self.basic_data.lawn_mower.register_callback(107, self._handle_dp_107)

    async def _handle_dp_107(self, _payload: str) -> None:
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model,
        )

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.host}.{self._unique_suffix}"

    @property
    def available(self) -> bool:
        return self.basic_data.lawn_mower is not None

    @property
    def native_value(self) -> str | None:
        if not self.basic_data.lawn_mower:
            return None
        member = getattr(self.basic_data.lawn_mower, self._enum_attr, None)
        if member is None:
            return None
        value = member.value if hasattr(member, "value") else str(member)
        return value if value in self._attr_options else None


class TerraMowMissionSensor(_MissionEnumSensorBase):
    """Current top-level mission (dp_107)."""

    _attr_icon = "mdi:robot-mower-outline"
    _attr_translation_key = "mission"
    _attr_options = [member.value for member in Mission]
    _enum_attr = "mission"
    _unique_suffix = "mission"


class TerraMowSubMissionSensor(_MissionEnumSensorBase):
    """Current sub-mission (dp_107) — surfaces transient states like waiting for rain."""

    _attr_icon = "mdi:list-status"
    _attr_translation_key = "sub_mission"
    _attr_options = [member.value for member in SubMission]
    _enum_attr = "sub_mission"
    _unique_suffix = "sub_mission"


class TerraMowMissionStateSensor(_MissionEnumSensorBase):
    """Mission lifecycle state (dp_107): idle / running / paused / abort / complete."""

    _attr_icon = "mdi:state-machine"
    _attr_translation_key = "mission_state"
    _attr_options = [member.value for member in MissionState]
    _enum_attr = "mission_state"
    _unique_suffix = "mission_state"
