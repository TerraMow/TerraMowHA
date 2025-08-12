from __future__ import annotations
from typing import Any

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)

from homeassistant.const import (
    EntityCategory,
    UnitOfArea
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from . import TerraMowBasicData, DOMAIN
# 移除硬编码的映射，使用翻译系统

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TerraMow map sensors."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    
    # 创建地图传感器实体
    entities = [
        TerraMowMapStatusSensor(basic_data, hass),
        TerraMowMapAreaSensor(basic_data, hass),
        TerraMowCleanModeSensor(basic_data, hass),
    ]
    
    async_add_entities(entities)

class TerraMowMapSensorBase(SensorEntity):
    """地图传感器基类"""
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass
        self._map_info: dict[str, Any] = {}
        
        # 注册地图信息回调
        if hasattr(basic_data, 'lawn_mower') and basic_data.lawn_mower:
            basic_data.lawn_mower.register_map_callback(self._on_map_info)
    
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
    
    async def _on_map_info(self, map_info: dict[str, Any]) -> None:
        """处理地图信息更新"""
        self._map_info = map_info
        self.async_write_ha_state()

class TerraMowMapStatusSensor(SensorEntity):
    """地图状态传感器 - 使用dp_117数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:map"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "map_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["MAP_STATE_EMPTY", "MAP_STATE_INCOMPLETE", "MAP_STATE_COMPLETE"]
    
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
                ('TerraMowLanwMower', self.basic_data.host)
            },
            name='TerraMow',
            manufacturer='TerraMow',
            model='TerraMow S1200'
        )
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.map_status"
    
    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None
            
        map_status = self.basic_data.lawn_mower.map_status
        if not map_status:
            return None
            
        return map_status.get('map_state')
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return {}
            
        map_status = self.basic_data.lawn_mower.map_status
        if not map_status:
            return {}
        
        return {
            'is_map_detected': map_status.get('is_map_detected', False),
            'map_id': map_status.get('map_id'),
            'map_number': map_status.get('map_number', 0),
            'is_backing_up_map': map_status.get('is_backing_up_map', False),
            'backup_map_id': map_status.get('backup_map_id'),
            'main_direction_angle': map_status.get('main_direction_angle'),
            'is_spot_mode_map': map_status.get('is_spot_mode_map', False),
            'spot_mode_map_number': map_status.get('spot_mode_map_number', 0),
            'is_able_to_run_build_map': map_status.get('is_able_to_run_build_map', False),
        }

class TerraMowMapAreaSensor(TerraMowMapSensorBase):
    """地图面积传感器"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:texture-box"
    _attr_native_unit_of_measurement = UnitOfArea.SQUARE_METERS
    _attr_device_class = None  # 没有标准的面积设备类
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "map_area"
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.map_area"
    
    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not self._map_info:
            return None
        
        # total_area单位为0.1平方米，转换为平方米
        total_area = self._map_info.get('total_area', 0)
        return round(total_area / 10, 1) if total_area else None


class TerraMowCleanModeSensor(TerraMowMapSensorBase):
    """清洁模式传感器"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:broom"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "clean_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["MAP_CLEAN_INFO_MODE_GLOBAL", "MAP_CLEAN_INFO_MODE_SELECT_REGION", "MAP_CLEAN_INFO_MODE_DRAW_REGION", "MAP_CLEAN_INFO_MODE_MOVE_TO_TARGET_POINT"]
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.clean_mode"
    
    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not self._map_info:
            return None
        
        clean_info = self._map_info.get('clean_info', {})
        mode = clean_info.get('mode', '')
        
        return mode if mode else None
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not self._map_info:
            return {}
        
        clean_info = self._map_info.get('clean_info', {})
        attrs = {}
        
        # 根据不同的作业模式显示详细信息
        if 'select_region' in clean_info:
            region_ids = clean_info['select_region'].get('region_id', [])
            attrs['selected_regions'] = region_ids
            attrs['selected_regions_count'] = len(region_ids)
        
        return attrs

