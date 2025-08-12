from __future__ import annotations
import logging
import json
from typing import Any

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
    NumberDeviceClass
)

from homeassistant.const import (
    EntityCategory,
    UnitOfLength
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from . import TerraMowBasicData, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TerraMow number entities."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    
    # 创建数值控制实体
    entities = [
        MowingHeightNumber(basic_data, hass),
        EdgeCuttingDistanceNumber(basic_data, hass),
        MowingSpacingNumber(basic_data, hass),
        MainDirectionSingleAngleNumber(basic_data, hass),
        MainDirectionAutoRotateIntervalNumber(basic_data, hass),
        MultipleDirectionAngle1Number(basic_data, hass),
        MultipleDirectionAngle2Number(basic_data, hass),
    ]
    
    async_add_entities(entities)


class TerraMowNumberBase(NumberEntity):
    """TerraMow数值控制基类"""
    
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


class MowingHeightNumber(TerraMowNumberBase):
    """割草高度设置控制器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:arrow-up-down"
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_device_class = NumberDeviceClass.DISTANCE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "mowing_height"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 20
    _attr_native_max_value = 70
    _attr_native_step = 1
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.mowing_height"
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None
            
        mow_height = global_params.get('mow_height', {})
        value = mow_height.get('value')
        return float(value) if value is not None else None
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the mowing height."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 发送设置命令到dp_155
        command = {
            'mow_height': {
                'value': int(value)
            }
        }
        
        _LOGGER.info("Setting mowing height to %d mm", int(value))
        self.basic_data.lawn_mower.publish_data_point(155, command)


class EdgeCuttingDistanceNumber(TerraMowNumberBase):
    """边缘割草距离设置控制器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:border-outside"
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_device_class = NumberDeviceClass.DISTANCE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "edge_cutting_distance"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 50
    _attr_native_step = 1
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.edge_cutting_distance"
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None
            
        edge_cutting_distance = global_params.get('edge_cutting_distance', {})
        value = edge_cutting_distance.get('value')
        return float(value) if value is not None else None
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the edge cutting distance."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 发送设置命令到dp_155
        command = {
            'edge_cutting_distance': {
                'value': int(value)
            }
        }
        
        _LOGGER.info("Setting edge cutting distance to %d mm", int(value))
        self.basic_data.lawn_mower.publish_data_point(155, command)


class MowingSpacingNumber(TerraMowNumberBase):
    """割草间距设置控制器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:ruler"
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_device_class = NumberDeviceClass.DISTANCE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "mowing_spacing"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 80  # 8cm 最小值
    _attr_native_max_value = 140  # 14cm 最大值
    _attr_native_step = 10  # 1cm 步进
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.mowing_spacing"
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None
            
        mow_spacing = global_params.get('mow_spacing', {})
        value = mow_spacing.get('value')
        return float(value) if value is not None else None
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            'valid_range': '80-140mm (8-14cm)',
            'warning': 'Changing this value will reset mowing progress',
            'warning_zh': '修改此值将重置作业进度'
        }
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the mowing spacing."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 验证输入范围
        int_value = int(value)
        if int_value < 80 or int_value > 140:
            _LOGGER.error("Invalid mowing spacing value: %d mm. Valid range: 80-140mm", int_value)
            return
        
        # 发送设置命令到dp_155
        command = {
            'mow_spacing': {
                'value': int_value
            }
        }
        
        _LOGGER.info("Setting mowing spacing to %d mm (will reset mowing progress)", int_value)
        self.basic_data.lawn_mower.publish_data_point(155, command)


class MainDirectionSingleAngleNumber(TerraMowNumberBase):
    """单主方向角度设置控制器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:compass-outline"
    _attr_native_unit_of_measurement = "°"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "main_direction_single_angle"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 359
    _attr_native_step = 1
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
        # 注册模式切换事件监听器
        self._register_mode_change_listener()
    
    def _register_mode_change_listener(self) -> None:
        """注册模式切换事件监听器"""
        async def on_mode_changed(event):
            if event.data.get("device_host") == self.host:
                # 从事件中获取新模式，并缓存
                new_mode = event.data.get("new_mode")
                if new_mode:
                    self._cached_mode = new_mode
                # 立即更新实体状态
                self.async_write_ha_state()
        
        self.hass.bus.async_listen(f"{DOMAIN}_main_direction_mode_changed", on_mode_changed)
        self._cached_mode = None  # 初始化缓存的模式
    
    def _get_current_mode_from_selector(self) -> str | None:
        """尝试从模式选择器获取当前模式"""
        # 优先使用事件缓存的模式
        if hasattr(self, '_cached_mode') and self._cached_mode:
            mode = self._cached_mode
            # 清除缓存，下次使用实际状态
            self._cached_mode = None
            return mode
            
        try:
            # 查找同设备的模式选择器实体
            mode_selector_entity_id = f"select.terramow_{self.host.replace('.', '_')}_main_direction_mode"
            mode_selector_state = self.hass.states.get(mode_selector_entity_id)
            if mode_selector_state and mode_selector_state.state != "unavailable":
                return mode_selector_state.state
        except Exception:
            pass
        return None
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.main_direction_single_angle"
    
    @property
    def available(self) -> bool:
        """Return True if entity is available (only in single mode)."""
        # 首先尝试从模式选择器获取即时状态
        current_mode = self._get_current_mode_from_selector()
        if current_mode:
            return current_mode == 'MAIN_DIRECTION_MODE_SINGLE'
        
        # 备用方案：从设备数据获取
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return False
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return False
        
        main_direction_config = global_params.get('main_direction_angle_config', {})
        mode = main_direction_config.get('mode', 'MAIN_DIRECTION_MODE_SINGLE')
        return mode == 'MAIN_DIRECTION_MODE_SINGLE'
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not self.available:
            return None
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None
            
        main_direction_config = global_params.get('main_direction_angle_config', {})
        single_config = main_direction_config.get('single_mode_config', {})
        angle = single_config.get('angle')
        return float(angle) if angle is not None else None
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the single main direction angle."""
        if not self.available:
            _LOGGER.error("Single angle control not available in current mode")
            return
            
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 确保角度值在0-359范围内
        angle_value = int(value) % 360
        
        # 发送设置命令到dp_155
        command = {
            'main_direction_angle_config': {
                'mode': 'MAIN_DIRECTION_MODE_SINGLE',
                'single_mode_config': {
                    'angle': angle_value
                }
            }
        }
        
        _LOGGER.info("Setting single main direction angle to %d degrees", angle_value)
        self.basic_data.lawn_mower.publish_data_point(155, command)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            'valid_range': '0-359 degrees',
            'description': 'Angle for single main direction mode',
            'description_zh': '单主方向模式的角度设置'
        }
        
        # 添加当前角度信息
        if hasattr(self.basic_data, 'lawn_mower') and self.basic_data.lawn_mower:
            global_params = self.basic_data.lawn_mower.global_params
            if global_params:
                main_direction_config = global_params.get('main_direction_angle_config', {})
                current_angle = main_direction_config.get('current_angle')
                if current_angle is not None:
                    attrs['current_robot_angle'] = current_angle
        
        return attrs


class MainDirectionAutoRotateIntervalNumber(TerraMowNumberBase):
    """自动旋转主方向间隔设置控制器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:rotate-right"
    _attr_native_unit_of_measurement = "°"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "main_direction_auto_rotate_interval"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 180
    _attr_native_step = 1
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
        # 注册模式切换事件监听器
        self._register_mode_change_listener()
    
    def _register_mode_change_listener(self) -> None:
        """注册模式切换事件监听器"""
        async def on_mode_changed(event):
            if event.data.get("device_host") == self.host:
                # 从事件中获取新模式，并缓存
                new_mode = event.data.get("new_mode")
                if new_mode:
                    self._cached_mode = new_mode
                # 立即更新实体状态
                self.async_write_ha_state()
        
        self.hass.bus.async_listen(f"{DOMAIN}_main_direction_mode_changed", on_mode_changed)
        self._cached_mode = None  # 初始化缓存的模式
    
    def _get_current_mode_from_selector(self) -> str | None:
        """尝试从模式选择器获取当前模式"""
        # 优先使用事件缓存的模式
        if hasattr(self, '_cached_mode') and self._cached_mode:
            mode = self._cached_mode
            # 清除缓存，下次使用实际状态
            self._cached_mode = None
            return mode
            
        try:
            # 查找同设备的模式选择器实体
            mode_selector_entity_id = f"select.terramow_{self.host.replace('.', '_')}_main_direction_mode"
            mode_selector_state = self.hass.states.get(mode_selector_entity_id)
            if mode_selector_state and mode_selector_state.state != "unavailable":
                return mode_selector_state.state
        except Exception:
            pass
        return None
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.main_direction_auto_rotate_interval"
    
    @property
    def available(self) -> bool:
        """Return True if entity is available (only in auto rotate mode)."""
        # 首先尝试从模式选择器获取即时状态
        current_mode = self._get_current_mode_from_selector()
        if current_mode:
            return current_mode == 'MAIN_DIRECTION_MODE_AUTO_ROTATE'
        
        # 备用方案：从设备数据获取
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return False
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return False
        
        main_direction_config = global_params.get('main_direction_angle_config', {})
        mode = main_direction_config.get('mode', 'MAIN_DIRECTION_MODE_SINGLE')
        return mode == 'MAIN_DIRECTION_MODE_AUTO_ROTATE'
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not self.available:
            return None
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None
            
        main_direction_config = global_params.get('main_direction_angle_config', {})
        auto_config = main_direction_config.get('auto_rotate_mode_config', {})
        interval = auto_config.get('angle_interval')
        return float(interval) if interval is not None else None
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the auto rotate interval."""
        if not self.available:
            _LOGGER.error("Auto rotate interval control not available in current mode")
            return
            
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        interval_value = int(value)
        
        # 发送设置命令到dp_155
        command = {
            'main_direction_angle_config': {
                'mode': 'MAIN_DIRECTION_MODE_AUTO_ROTATE',
                'auto_rotate_mode_config': {
                    'angle_interval': interval_value
                }
            }
        }
        
        _LOGGER.info("Setting auto rotate interval to %d degrees", interval_value)
        self.basic_data.lawn_mower.publish_data_point(155, command)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            'valid_range': '1-180 degrees',
            'description': 'Angle interval for auto rotate mode',
            'description_zh': '自动旋转模式的角度间隔设置'
        }
        
        # 添加当前角度信息
        if hasattr(self.basic_data, 'lawn_mower') and self.basic_data.lawn_mower:
            global_params = self.basic_data.lawn_mower.global_params
            if global_params:
                main_direction_config = global_params.get('main_direction_angle_config', {})
                current_angle = main_direction_config.get('current_angle')
                if current_angle is not None:
                    attrs['current_robot_angle'] = current_angle
        
        return attrs


class MultipleDirectionAngle1Number(TerraMowNumberBase):
    """多主方向第一角度设置控制器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:compass-outline"
    _attr_native_unit_of_measurement = "°"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "multiple_direction_angle1"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 359
    _attr_native_step = 1
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
        # 注册模式切换事件监听器
        self._register_mode_change_listener()
    
    def _register_mode_change_listener(self) -> None:
        """注册模式切换事件监听器"""
        async def on_mode_changed(event):
            if event.data.get("device_host") == self.host:
                # 从事件中获取新模式，并缓存
                new_mode = event.data.get("new_mode")
                if new_mode:
                    self._cached_mode = new_mode
                # 立即更新实体状态
                self.async_write_ha_state()
        
        self.hass.bus.async_listen(f"{DOMAIN}_main_direction_mode_changed", on_mode_changed)
        self._cached_mode = None  # 初始化缓存的模式
    
    def _get_current_mode_from_selector(self) -> str | None:
        """尝试从模式选择器获取当前模式"""
        # 优先使用事件缓存的模式
        if hasattr(self, '_cached_mode') and self._cached_mode:
            mode = self._cached_mode
            # 清除缓存，下次使用实际状态
            self._cached_mode = None
            return mode
            
        try:
            # 查找同设备的模式选择器实体
            mode_selector_entity_id = f"select.terramow_{self.host.replace('.', '_')}_main_direction_mode"
            mode_selector_state = self.hass.states.get(mode_selector_entity_id)
            if mode_selector_state and mode_selector_state.state != "unavailable":
                return mode_selector_state.state
        except Exception:
            pass
        return None
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.multiple_direction_angle1"
    
    @property
    def available(self) -> bool:
        """Return True if entity is available (only in multiple mode)."""
        # 首先尝试从模式选择器获取即时状态
        current_mode = self._get_current_mode_from_selector()
        if current_mode:
            return current_mode == 'MAIN_DIRECTION_MODE_MULTIPLE'
        
        # 备用方案：从设备数据获取
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return False
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return False
        
        main_direction_config = global_params.get('main_direction_angle_config', {})
        mode = main_direction_config.get('mode', 'MAIN_DIRECTION_MODE_SINGLE')
        return mode == 'MAIN_DIRECTION_MODE_MULTIPLE'
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not self.available:
            return None
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None
            
        main_direction_config = global_params.get('main_direction_angle_config', {})
        multiple_config = main_direction_config.get('multiple_mode_config', {})
        angles = multiple_config.get('angles', [0, 90])
        
        # 返回第一个角度，如果数组为空则返回0
        return float(angles[0]) if len(angles) > 0 else 0.0
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the first multiple direction angle."""
        if not self.available:
            _LOGGER.error("Multiple direction angle1 control not available in current mode")
            return
            
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 确保角度值在0-359范围内
        angle1_value = int(value) % 360
        
        # 获取当前的第二个角度
        global_params = self.basic_data.lawn_mower.global_params or {}
        main_direction_config = global_params.get('main_direction_angle_config', {})
        multiple_config = main_direction_config.get('multiple_mode_config', {})
        current_angles = multiple_config.get('angles', [0, 90])
        
        # 获取第二个角度，如果不存在则使用默认值90
        angle2_value = current_angles[1] if len(current_angles) > 1 else 90
        
        # 检查两个角度是否相同
        if angle1_value == angle2_value:
            _LOGGER.warning("Angle1 (%d°) is same as Angle2 (%d°), this may not be effective", 
                          angle1_value, angle2_value)
        
        # 发送设置命令到dp_155
        command = {
            'main_direction_angle_config': {
                'mode': 'MAIN_DIRECTION_MODE_MULTIPLE',
                'multiple_mode_config': {
                    'angles': [angle1_value, angle2_value]
                }
            }
        }
        
        _LOGGER.info("Setting multiple direction angles to [%d°, %d°]", angle1_value, angle2_value)
        self.basic_data.lawn_mower.publish_data_point(155, command)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            'valid_range': '0-359 degrees',
            'description': 'First angle for multiple main direction mode',
            'description_zh': '多主方向模式的第一个角度'
        }
        
        # 添加当前角度信息和第二角度信息
        if hasattr(self.basic_data, 'lawn_mower') and self.basic_data.lawn_mower:
            global_params = self.basic_data.lawn_mower.global_params
            if global_params:
                main_direction_config = global_params.get('main_direction_angle_config', {})
                current_angle = main_direction_config.get('current_angle')
                if current_angle is not None:
                    attrs['current_robot_angle'] = current_angle
                
                # 显示配对的第二个角度
                multiple_config = main_direction_config.get('multiple_mode_config', {})
                angles = multiple_config.get('angles', [])
                if len(angles) > 1:
                    attrs['paired_angle2'] = angles[1]
                    attrs['angle_difference'] = abs(angles[1] - angles[0])
        
        return attrs


class MultipleDirectionAngle2Number(TerraMowNumberBase):
    """多主方向第二角度设置控制器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:compass"
    _attr_native_unit_of_measurement = "°"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "multiple_direction_angle2"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 359
    _attr_native_step = 1
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(basic_data, hass)
        # 注册模式切换事件监听器
        self._register_mode_change_listener()
    
    def _register_mode_change_listener(self) -> None:
        """注册模式切换事件监听器"""
        async def on_mode_changed(event):
            if event.data.get("device_host") == self.host:
                # 从事件中获取新模式，并缓存
                new_mode = event.data.get("new_mode")
                if new_mode:
                    self._cached_mode = new_mode
                # 立即更新实体状态
                self.async_write_ha_state()
        
        self.hass.bus.async_listen(f"{DOMAIN}_main_direction_mode_changed", on_mode_changed)
        self._cached_mode = None  # 初始化缓存的模式
    
    def _get_current_mode_from_selector(self) -> str | None:
        """尝试从模式选择器获取当前模式"""
        # 优先使用事件缓存的模式
        if hasattr(self, '_cached_mode') and self._cached_mode:
            mode = self._cached_mode
            # 清除缓存，下次使用实际状态
            self._cached_mode = None
            return mode
            
        try:
            # 查找同设备的模式选择器实体
            mode_selector_entity_id = f"select.terramow_{self.host.replace('.', '_')}_main_direction_mode"
            mode_selector_state = self.hass.states.get(mode_selector_entity_id)
            if mode_selector_state and mode_selector_state.state != "unavailable":
                return mode_selector_state.state
        except Exception:
            pass
        return None
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.multiple_direction_angle2"
    
    @property
    def available(self) -> bool:
        """Return True if entity is available (only in multiple mode)."""
        # 首先尝试从模式选择器获取即时状态
        current_mode = self._get_current_mode_from_selector()
        if current_mode:
            return current_mode == 'MAIN_DIRECTION_MODE_MULTIPLE'
        
        # 备用方案：从设备数据获取
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return False
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return False
        
        main_direction_config = global_params.get('main_direction_angle_config', {})
        mode = main_direction_config.get('mode', 'MAIN_DIRECTION_MODE_SINGLE')
        return mode == 'MAIN_DIRECTION_MODE_MULTIPLE'
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not self.available:
            return None
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return None
            
        main_direction_config = global_params.get('main_direction_angle_config', {})
        multiple_config = main_direction_config.get('multiple_mode_config', {})
        angles = multiple_config.get('angles', [0, 90])
        
        # 返回第二个角度，如果数组长度不足则返回90
        return float(angles[1]) if len(angles) > 1 else 90.0
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the second multiple direction angle."""
        if not self.available:
            _LOGGER.error("Multiple direction angle2 control not available in current mode")
            return
            
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 确保角度值在0-359范围内
        angle2_value = int(value) % 360
        
        # 获取当前的第一个角度
        global_params = self.basic_data.lawn_mower.global_params or {}
        main_direction_config = global_params.get('main_direction_angle_config', {})
        multiple_config = main_direction_config.get('multiple_mode_config', {})
        current_angles = multiple_config.get('angles', [0, 90])
        
        # 获取第一个角度，如果不存在则使用默认值0
        angle1_value = current_angles[0] if len(current_angles) > 0 else 0
        
        # 检查两个角度是否相同
        if angle1_value == angle2_value:
            _LOGGER.warning("Angle2 (%d°) is same as Angle1 (%d°), this may not be effective", 
                          angle2_value, angle1_value)
        
        # 发送设置命令到dp_155
        command = {
            'main_direction_angle_config': {
                'mode': 'MAIN_DIRECTION_MODE_MULTIPLE',
                'multiple_mode_config': {
                    'angles': [angle1_value, angle2_value]
                }
            }
        }
        
        _LOGGER.info("Setting multiple direction angles to [%d°, %d°]", angle1_value, angle2_value)
        self.basic_data.lawn_mower.publish_data_point(155, command)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            'valid_range': '0-359 degrees',
            'description': 'Second angle for multiple main direction mode',
            'description_zh': '多主方向模式的第二个角度'
        }
        
        # 添加当前角度信息和第一角度信息
        if hasattr(self.basic_data, 'lawn_mower') and self.basic_data.lawn_mower:
            global_params = self.basic_data.lawn_mower.global_params
            if global_params:
                main_direction_config = global_params.get('main_direction_angle_config', {})
                current_angle = main_direction_config.get('current_angle')
                if current_angle is not None:
                    attrs['current_robot_angle'] = current_angle
                
                # 显示配对的第一个角度
                multiple_config = main_direction_config.get('multiple_mode_config', {})
                angles = multiple_config.get('angles', [])
                if len(angles) > 0:
                    attrs['paired_angle1'] = angles[0]
                    if len(angles) > 1:
                        attrs['angle_difference'] = abs(angles[1] - angles[0])
        
        return attrs