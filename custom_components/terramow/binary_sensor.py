from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, TerraMowBasicData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TerraMow binary sensor entities."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        TerraMowChargingSensor(basic_data, hass),
        TerraMowMapDetectedBinarySensor(basic_data, hass),
        TerraMowMapBuildableBinarySensor(basic_data, hass),
        TerraMowMapBackingUpBinarySensor(basic_data, hass),
    ]

    async_add_entities(entities)


class TerraMowChargingSensor(BinarySensorEntity):
    """Binary sensor for the TerraMow charging state."""

    _attr_has_entity_name = True
    _attr_translation_key = "charging_state"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the charging sensor."""
        super().__init__()
        self.basic_data = basic_data
        self.host = self.basic_data.host
        self.hass = hass
        self._attr_is_on: bool | None = None
        _LOGGER.info(
            "TerraMowChargingSensor entity created"
        )  # Callback is no longer needed here

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                ("TerraMowLawnMower", self.basic_data.host)
            },  # Corrected typo in identifier
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,  # Use dynamically updated model
        )

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.charging_state"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if not hasattr(self.basic_data, "lawn_mower") or not self.basic_data.lawn_mower:
            return None

        battery_status = self.basic_data.lawn_mower.battery_status
        charger_connected = battery_status.get("charger_connected")

        return bool(charger_connected) if charger_connected is not None else None

    @property
    def available(self):
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None


class _MapStatusBinarySensorBase(BinarySensorEntity):
    """展示 dp_117 的一个地图标志，并随设备连接与上报刷新。"""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _map_status_field: str = ""
    _unique_suffix: str = ""

    def __init__(self, basic_data: TerraMowBasicData, hass: HomeAssistant) -> None:
        """保存共享设备数据；MQTT 连接由割草机实体持有。"""
        super().__init__()
        self.basic_data = basic_data
        self.hass = hass
        self.host = basic_data.host

    async def async_added_to_hass(self) -> None:
        """订阅地图状态，并在实体移除时自动撤销监听。"""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"terramow_{self.host}_map_status",
                self.async_write_ha_state,
            )
        )

    @property
    def device_info(self) -> DeviceInfo:
        """使用割草机的设备标识，避免平台并发装载时依赖其创建顺序。"""
        return DeviceInfo(identifiers={("TerraMowLawnMower", self.host)})

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.host}.{self._unique_suffix}"

    @property
    def available(self) -> bool:
        mower = self.basic_data.lawn_mower
        return mower is not None and mower.mqtt_connected

    @property
    def is_on(self) -> bool | None:
        mower = self.basic_data.lawn_mower
        if mower is None:
            return None
        value = mower.map_status.get(self._map_status_field)
        return value if isinstance(value, bool) else None


class TerraMowMapDetectedBinarySensor(_MapStatusBinarySensorBase):
    """显示设备是否识别到地图。"""

    _attr_translation_key = "map_detected"
    _attr_icon = "mdi:map-check"
    _map_status_field = "is_map_detected"
    _unique_suffix = "map_detected"


class TerraMowMapBuildableBinarySensor(_MapStatusBinarySensorBase):
    """显示设备当前是否允许建图。"""

    _attr_translation_key = "map_buildable"
    _attr_icon = "mdi:map-plus"
    _map_status_field = "is_able_to_run_build_map"
    _unique_suffix = "map_buildable"


class TerraMowMapBackingUpBinarySensor(_MapStatusBinarySensorBase):
    """显示设备是否正在备份或恢复地图。"""

    _attr_translation_key = "map_backing_up"
    _attr_icon = "mdi:cloud-upload-outline"
    _map_status_field = "is_backing_up_map"
    _unique_suffix = "map_backing_up"
