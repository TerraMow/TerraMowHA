from __future__ import annotations
import logging
import json

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TerraMowBasicData, DOMAIN

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
        _LOGGER.info("TerraMowChargingSensor entity created") # Callback is no longer needed here

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
        return f"lawn_mower.terramow@{self.host}.charging_state"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        battery_status = self.basic_data.lawn_mower.battery_status
        charger_connected = battery_status.get('charger_connected')

        return bool(charger_connected) if charger_connected is not None else None

    @property
    def available(self):
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None


class _MapStatusBinarySensorBase(BinarySensorEntity):
    """Shared base for dp_117 map_status flag binary sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _map_status_field: str = ""
    _unique_suffix: str = ""

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = self.basic_data.host
        self.hass = hass

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.basic_data.lawn_mower:
            self.basic_data.lawn_mower.register_callback(117, self._handle_dp_117)

    async def _handle_dp_117(self, _payload: str) -> None:
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
    def is_on(self) -> bool | None:
        if not self.basic_data.lawn_mower:
            return None
        map_status = self.basic_data.lawn_mower.map_status
        if not map_status:
            return None
        value = map_status.get(self._map_status_field)
        return bool(value) if value is not None else None


class TerraMowMapDetectedBinarySensor(_MapStatusBinarySensorBase):
    """True when the device reports an active/detected map."""

    _attr_translation_key = "map_detected"
    _attr_icon = "mdi:map-check"
    _map_status_field = "is_map_detected"
    _unique_suffix = "map_detected"


class TerraMowMapBuildableBinarySensor(_MapStatusBinarySensorBase):
    """True when the device is in a state where a build-map command would be accepted."""

    _attr_translation_key = "map_buildable"
    _attr_icon = "mdi:map-plus"
    _map_status_field = "is_able_to_run_build_map"
    _unique_suffix = "map_buildable"


class TerraMowMapBackingUpBinarySensor(_MapStatusBinarySensorBase):
    """True while a map backup is in progress."""

    _attr_translation_key = "map_backing_up"
    _attr_icon = "mdi:cloud-upload-outline"
    _map_status_field = "is_backing_up_map"
    _unique_suffix = "map_backing_up"