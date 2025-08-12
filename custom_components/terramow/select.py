from __future__ import annotations
import logging
from typing import Any

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from . import TerraMowBasicData, DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TerraMow select entities."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    
    # 创建选择实体
    entities = [
        TerraMowRegionSelect(basic_data, hass),
        MowSpeedSelect(basic_data, hass),
        BladeSpeedSelect(basic_data, hass),
        MainDirectionModeSelect(basic_data, hass),
    ]
    
    async_add_entities(entities)

class TerraMowRegionSelect(SelectEntity):
    """地图区域选择器"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker-multiple"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "region_select"
    
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
        self._current_option: str | None = None
        self._options = ["no_regions_available"]
        
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
    
    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.region_select"
    
    
    @property
    def options(self) -> list[str]:
        """Return a set of selectable options."""
        return self._options
    
    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        return self._current_option
    
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._options:
            _LOGGER.warning("Invalid region option selected: %s", option)
            return
        
        if option == "no_regions_available" or option == "all_regions":
            # 这些是特殊选项，不执行具体的区域切换操作
            self._current_option = option
            self.async_write_ha_state()
            return
        
        # 解析区域ID
        try:
            # 格式: "区域名称 (ID: 123)"
            if " (ID: " in option:
                region_id_str = option.split(" (ID: ")[1].rstrip(")")
                region_id = int(region_id_str)
                
                # 发送选区作业命令
                await self._start_region_clean(region_id)
                self._current_option = option
                self.async_write_ha_state()
            else:
                _LOGGER.warning("Unable to parse region ID from option: %s", option)
                
        except (ValueError, IndexError) as e:
            _LOGGER.error("Error parsing region option %s: %s", option, e)
    
    async def _start_region_clean(self, region_id: int):
        """发送选区清洁命令"""
        _LOGGER.info("Starting region clean for region ID: %d", region_id)
        
        # 获取lawn_mower实体以发送命令
        if hasattr(self.basic_data, 'lawn_mower') and self.basic_data.lawn_mower:
            command = {
                'seq': self.basic_data.lawn_mower.get_cmd_seq(),
                'mode': 'START_MODE_SELECT_REGION_CLEAN',
                'select_region_clean': {
                    'region_ids': [region_id]
                }
            }
            self.basic_data.lawn_mower.publish_data_point(103, command)
            _LOGGER.info("Region clean command sent: region_id=%d", region_id)
        else:
            _LOGGER.error("Cannot send region clean command: lawn_mower not available")
    
    async def _on_map_info(self, map_info: dict[str, Any]) -> None:
        """处理地图信息更新"""
        self._map_info = map_info
        self._update_options()
        self.async_write_ha_state()
    
    def _update_options(self) -> None:
        """根据地图信息更新可选区域列表"""
        if not self._map_info:
            self._options = ["no_regions_available"]
            self._current_option = "no_regions_available"
            return
        
        regions = self._map_info.get('regions', [])
        if not regions:
            self._options = ["no_regions_available"]
            self._current_option = "no_regions_available"
            return
        
        # 构建区域选项列表 - 只添加子区域
        options = ["all_regions"]  # 添加全部区域选项
        
        for region in regions:
            # 只处理子区域
            sub_regions = region.get('sub_regions', [])
            for sub_region in sub_regions:
                sub_region_id = sub_region.get('id')
                sub_region_name = sub_region.get('name', f'Sub-region {sub_region_id}')
                
                if sub_region_name and sub_region_name.strip():
                    sub_option = f"{sub_region_name} (ID: {sub_region_id})"
                else:
                    sub_option = f"Sub-region {sub_region_id} (ID: {sub_region_id})"
                options.append(sub_option)
        
        self._options = options
        
        # 设置当前选项
        if not self._current_option or self._current_option not in self._options:
            self._current_option = "all_regions"
        
        _LOGGER.info("Updated region options: %d sub-regions available", len(self._options) - 1)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not self._map_info:
            return {}
        
        regions = self._map_info.get('regions', [])
        
        # 统计所有子区域
        all_sub_regions = []
        for region in regions:
            sub_regions = region.get('sub_regions', [])
            for sub_region in sub_regions:
                sub_region_info = {
                    'id': sub_region.get('id'),
                    'name': sub_region.get('name', ''),
                    'parent_region_id': region.get('id'),
                    'parent_region_name': region.get('name', '')
                }
                all_sub_regions.append(sub_region_info)
        
        attrs = {
            'map_id': self._map_info.get('id'),
            'sub_regions_count': len(all_sub_regions),
            'available_sub_regions': all_sub_regions
        }
        
        # 显示当前清洁信息
        clean_info = self._map_info.get('clean_info', {})
        if clean_info.get('mode') == 'MAP_CLEAN_INFO_MODE_SELECT_REGION':
            select_region = clean_info.get('select_region', {})
            selected_region_ids = select_region.get('region_id', [])
            attrs['currently_selected_regions'] = selected_region_ids
        
        return attrs


class MowSpeedSelect(SelectEntity):
    """割草行走速度选择器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:speedometer"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "mow_speed_setting"
    
    # 割草速度选项
    _attr_options = [
        "MOW_SPEED_TYPE_LOW",
        "MOW_SPEED_TYPE_MEDIUM", 
        "MOW_SPEED_TYPE_ADAPTIVE_HIGH"
    ]
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass
        self._current_option = "MOW_SPEED_TYPE_MEDIUM"  # 默认中速
    
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
        return f"lawn_mower.terramow@{self.host}.mow_speed_setting"
    
    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return self._current_option
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return self._current_option
        
        mow_speed = global_params.get('mow_speed', {})
        speed_type = mow_speed.get('speed_type')
        
        if speed_type and speed_type in self._attr_options:
            self._current_option = speed_type
            
        return self._current_option
    
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._attr_options:
            _LOGGER.error("Invalid mow speed option: %s", option)
            return
            
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 发送设置命令到dp_155
        command = {
            'mow_speed': {
                'speed_type': option
            }
        }
        
        _LOGGER.info("Setting mow speed to %s", option)
        self.basic_data.lawn_mower.publish_data_point(155, command)
        self._current_option = option
        self.async_write_ha_state()
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            'available_speeds': {
                'MOW_SPEED_TYPE_LOW': 'Low Speed',
                'MOW_SPEED_TYPE_MEDIUM': 'Medium Speed (Default)',
                'MOW_SPEED_TYPE_ADAPTIVE_HIGH': 'Adaptive High Speed'
            }
        }


class BladeSpeedSelect(SelectEntity):
    """刀盘转速选择器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:fan"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "blade_speed"
    
    # 刀盘转速选项
    _attr_options = [
        "BLADE_DISK_SPEED_TYPE_LOW",
        "BLADE_DISK_SPEED_TYPE_MEDIUM", 
        "BLADE_DISK_SPEED_TYPE_HIGH"
    ]
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass
        self._current_option = "BLADE_DISK_SPEED_TYPE_MEDIUM"  # 默认高速
    
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
        return f"lawn_mower.terramow@{self.host}.blade_speed"
    
    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return self._current_option
            
        global_params = self.basic_data.lawn_mower.global_params
        if not global_params:
            return self._current_option
        
        blade_disk_speed = global_params.get('blade_disk_speed', {})
        speed_type = blade_disk_speed.get('speed_type')
        
        if speed_type and speed_type in self._attr_options:
            self._current_option = speed_type
            
        return self._current_option
    
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._attr_options:
            _LOGGER.error("Invalid blade speed option: %s", option)
            return
            
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 发送设置命令到dp_155
        command = {
            'blade_disk_speed': {
                'speed_type': option
            }
        }
        
        _LOGGER.info("Setting blade speed to %s", option)
        self.basic_data.lawn_mower.publish_data_point(155, command)
        self._current_option = option
        self.async_write_ha_state()
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            'available_speeds': {
                'BLADE_DISK_SPEED_TYPE_LOW': 'Low Speed',
                'BLADE_DISK_SPEED_TYPE_MEDIUM': 'Medium Speed', 
                'BLADE_DISK_SPEED_TYPE_HIGH': 'High Speed (Default)'
            }
        }


class MainDirectionModeSelect(SelectEntity):
    """主方向模式选择器 - 使用dp_155数据"""
    
    _attr_has_entity_name = True
    _attr_icon = "mdi:compass"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "main_direction_mode"
    
    # 主方向模式选项
    _attr_options = [
        "MAIN_DIRECTION_MODE_SINGLE",
        "MAIN_DIRECTION_MODE_MULTIPLE", 
        "MAIN_DIRECTION_MODE_AUTO_ROTATE"
    ]
    
    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass
        self._current_option = "MAIN_DIRECTION_MODE_SINGLE"  # 默认单主方向
        self._pending_mode: str | None = None  # 缓存待生效的模式
        
        # 注册设备确认事件监听器
        self._register_device_confirmation_listener()
    
    def _register_device_confirmation_listener(self) -> None:
        """注册设备确认事件监听器"""
        async def on_device_confirmed(event):
            if event.data.get("device_host") == self.host:
                confirmed_mode = event.data.get("confirmed_mode")
                if confirmed_mode:
                    self.on_device_mode_confirmed(confirmed_mode)
        
        self.hass.bus.async_listen(f"{DOMAIN}_device_mode_confirmed", on_device_confirmed)
    
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
        return f"lawn_mower.terramow@{self.host}.main_direction_mode"
    
    def get_effective_mode(self) -> str:
        """获取当前生效的模式（包括待处理模式）"""
        # 如果有待处理的模式，优先返回待处理模式
        if self._pending_mode:
            return self._pending_mode
            
        # 否则尝试从设备获取实际模式
        if hasattr(self.basic_data, 'lawn_mower') and self.basic_data.lawn_mower:
            global_params = self.basic_data.lawn_mower.global_params
            if global_params:
                main_direction_config = global_params.get('main_direction_angle_config', {})
                device_mode = main_direction_config.get('mode')
                if device_mode and device_mode in self._attr_options:
                    return device_mode
        
        return self._current_option
    
    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        mode = self.get_effective_mode()
        self._current_option = mode
        return mode
    
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._attr_options:
            _LOGGER.error("Invalid main direction mode option: %s", option)
            return
            
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return
        
        # 保存旧模式，用于事件通知
        old_mode = self._current_option
        
        # 立即设置待处理状态，提供即时反馈
        self._pending_mode = option
        self._current_option = option
        
        # 立即更新当前实体状态
        self.async_write_ha_state()
        
        # 通知相关角度控制器立即更新可用状态（传递旧模式和新模式）
        self._notify_angle_controllers_mode_change(old_mode, option)
        
        # 获取当前的全局参数以保留其他配置
        global_params = self.basic_data.lawn_mower.global_params or {}
        current_main_direction = global_params.get('main_direction_angle_config', {})
        
        # 构建主方向配置
        main_direction_config: dict[str, Any] = {
            'mode': option
        }
        
        # 根据模式添加对应的配置结构
        if option == "MAIN_DIRECTION_MODE_SINGLE":
            # 保留现有的单主方向配置，如果没有则使用默认值0度
            current_single_config: dict[str, Any] = current_main_direction.get('single_mode_config', {})
            main_direction_config['single_mode_config'] = {
                'angle': current_single_config.get('angle', 0)
            }
        elif option == "MAIN_DIRECTION_MODE_MULTIPLE":
            # 保留现有的多主方向配置，如果没有则使用默认角度列表
            current_multiple_config: dict[str, Any] = current_main_direction.get('multiple_mode_config', {})
            main_direction_config['multiple_mode_config'] = {
                'angles': current_multiple_config.get('angles', [0, 90])
            }
        elif option == "MAIN_DIRECTION_MODE_AUTO_ROTATE":
            # 保留现有的自动旋转配置，如果没有则使用默认间隔15度
            current_auto_config: dict[str, Any] = current_main_direction.get('auto_rotate_mode_config', {})
            main_direction_config['auto_rotate_mode_config'] = {
                'angle_interval': current_auto_config.get('angle_interval', 15)
            }
        
        # 发送设置命令到dp_155
        command = {
            'main_direction_angle_config': main_direction_config
        }
        
        _LOGGER.info("Setting main direction mode from %s to %s", old_mode, option)
        self.basic_data.lawn_mower.publish_data_point(155, command)
        
        # 设置超时清理待处理状态（防止设备响应失败导致状态卡死）
        self.hass.async_create_task(self._clear_pending_mode_after_timeout())
    
    def _notify_angle_controllers_mode_change(self, old_mode: str, new_mode: str) -> None:
        """通知相关角度控制器模式已改变"""
        # 触发Home Assistant事件，角度控制器可以监听此事件
        self.hass.bus.fire(f"{DOMAIN}_main_direction_mode_changed", {
            "device_host": self.host,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "source": "mode_select"
        })
        
        # 延迟触发所有相关实体的状态更新
        async def delayed_update():
            await self.hass.async_add_executor_job(self._force_update_related_entities)
        
        self.hass.async_create_task(delayed_update())
    
    def _force_update_related_entities(self) -> None:
        """强制更新相关角度控制实体的状态"""
        try:
            # 简化的实体更新方案：直接通过entity_id推断来更新
            related_entity_patterns = [
                "main_direction_single_angle",
                "main_direction_auto_rotate_interval", 
                "multiple_direction_angle1",
                "multiple_direction_angle2"
            ]
            
            entities_to_update = []
            host_suffix = self.host.replace('.', '_')
            
            for pattern in related_entity_patterns:
                # 构造预期的entity_id
                entity_id = f"number.terramow_{host_suffix}_{pattern}"
                # 检查实体是否存在
                if self.hass.states.get(entity_id):
                    entities_to_update.append(entity_id)
            
            # 触发这些实体的状态更新
            for entity_id in entities_to_update:
                try:
                    # 使用异步方式调度更新
                    self.hass.async_create_task(
                        self.hass.helpers.entity_component.async_update_entity(entity_id)
                    )
                except Exception as update_error:
                    _LOGGER.debug("Could not update entity %s: %s", entity_id, update_error)
                        
            _LOGGER.debug("Triggered state update for angle control entities: %s", entities_to_update)
        except Exception as e:
            _LOGGER.warning("Failed to force update related entities: %s", e)
    
    async def _clear_pending_mode_after_timeout(self) -> None:
        """超时后清理待处理状态"""
        import asyncio
        await asyncio.sleep(10)  # 10秒超时
        if self._pending_mode:
            _LOGGER.info("Clearing pending mode %s after timeout", self._pending_mode)
            self._pending_mode = None
            self.async_write_ha_state()
    
    def on_device_mode_confirmed(self, confirmed_mode: str) -> None:
        """设备确认模式更改后的回调"""
        if self._pending_mode == confirmed_mode:
            _LOGGER.debug("Device confirmed mode change to %s, clearing pending state", confirmed_mode)
            self._pending_mode = None
            self.async_write_ha_state()
        elif self._pending_mode:
            _LOGGER.warning("Device confirmed mode %s but pending mode was %s", 
                          confirmed_mode, self._pending_mode)
            self._pending_mode = None
            self._current_option = confirmed_mode
            self.async_write_ha_state()
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs: dict[str, Any] = {
            'available_modes': {
                'MAIN_DIRECTION_MODE_SINGLE': 'Single Direction',
                'MAIN_DIRECTION_MODE_MULTIPLE': 'Multiple Directions',
                'MAIN_DIRECTION_MODE_AUTO_ROTATE': 'Auto Rotate Direction'
            }
        }
        
        # 添加状态信息
        if self._pending_mode:
            attrs['status'] = 'changing_mode'
            attrs['pending_mode'] = self._pending_mode
        else:
            attrs['status'] = 'active'
        
        # 添加当前配置的详细信息
        if hasattr(self.basic_data, 'lawn_mower') and self.basic_data.lawn_mower:
            global_params = self.basic_data.lawn_mower.global_params
            if global_params:
                main_direction_config = global_params.get('main_direction_angle_config', {})
                current_angle = main_direction_config.get('current_angle')
                if current_angle is not None:
                    attrs['current_angle'] = current_angle
                
                mode = main_direction_config.get('mode')
                if mode == 'MAIN_DIRECTION_MODE_SINGLE':
                    single_config = main_direction_config.get('single_mode_config', {})
                    attrs['single_angle'] = single_config.get('angle', 0)
                elif mode == 'MAIN_DIRECTION_MODE_MULTIPLE':
                    multiple_config = main_direction_config.get('multiple_mode_config', {})
                    attrs['multiple_angles'] = multiple_config.get('angles', [])
                elif mode == 'MAIN_DIRECTION_MODE_AUTO_ROTATE':
                    auto_config = main_direction_config.get('auto_rotate_mode_config', {})
                    attrs['auto_rotate_interval'] = auto_config.get('angle_interval', 15)
        
        return attrs