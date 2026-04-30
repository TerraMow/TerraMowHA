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
        PowerSwitchSensor(basic_data, hass),
        TerraMowProblemSensor(basic_data, hass),
        TerraMowRainSensor(basic_data, hass),
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


class PowerSwitchSensor(BinarySensorEntity):
    """Binary sensor for the TerraMow power switch state."""

    _attr_has_entity_name = True
    _attr_translation_key = "power_switch"
    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the power switch sensor."""
        super().__init__()
        self.basic_data = basic_data
        self.host = self.basic_data.host
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
        return f"lawn_mower.terramow@{self.host}.power_switch"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None

        battery_status = self.basic_data.lawn_mower.battery_status
        is_switch_on = battery_status.get('is_switch_on')

        return bool(is_switch_on) if is_switch_on is not None else None

    @property
    def available(self):
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None


class TerraMowProblemSensor(BinarySensorEntity):
    """Binary sensor exposing the dp_107 has_error flag as a problem."""

    _attr_has_entity_name = True
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = self.basic_data.host
        self.hass = hass
        _LOGGER.info("TerraMowProblemSensor entity created")

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
        return f"lawn_mower.terramow@{self.host}.problem"

    @property
    def is_on(self) -> bool | None:
        """Return true if the robot reports an error."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None
        return bool(self.basic_data.lawn_mower.has_error)

    @property
    def available(self):
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None


class TerraMowRainSensor(BinarySensorEntity):
    """Binary sensor that signals when the robot returns due to rain."""

    _attr_has_entity_name = True
    _attr_translation_key = "rain_detected"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = self.basic_data.host
        self.hass = hass
        _LOGGER.info("TerraMowRainSensor entity created")

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
        return f"lawn_mower.terramow@{self.host}.rain_detected"

    @property
    def is_on(self) -> bool | None:
        """Return true if the back-to-station reason is raining."""
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None
        return self.basic_data.lawn_mower.back_to_station_reason == "BACK_TO_STATION_REASON_RAINING"

    @property
    def available(self):
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None
