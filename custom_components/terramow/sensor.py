from __future__ import annotations
import logging
import json

from homeassistant.components.sensor import SensorDeviceClass
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
    EntityCategory
)
from homeassistant.core import HomeAssistant

from enum import StrEnum
from . import TerraMowConfigEntry, TerraMowBasicData, DOMAIN

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

    _attr_icon = "mdi:battery"

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
        self.basic_data.lawn_mower.register_callback(8, self.set_capacity)
        self.basic_data.lawn_mower.register_callback(108, self.set_battery_attributes)

        _LOGGER.info("BatterySensor entity created")

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
        return f"lawn_mower.terramow@{self.host}.battery"

    @property
    def name(self):
        return "TerraMow battery"

    def set_battery_attributes(self, payload :str) -> None:
        """Handle battery status attributes updates."""
        try:
            data = json.loads(payload)
            self._attr_extra_state_attributes = {
                'state':  data.get('state', ''),
                'temperature':  data.get('tempreture', '').replace('TEMPRETURE', 'TEMPERATURE'),
                'charger_connected':  data.get('charger_connected', ''),
                'is_switch_on':  data.get('is_switch_on', '')
            }
            _LOGGER.info(f"Received battery loading status: {data}")

        except json.JSONDecodeError:
            _LOGGER.error(f"Invalid JSON payload: {payload}")
            return

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

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TerraMowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    battery_sensor = BatterySensor(basic_data, hass)

    async_add_entities([battery_sensor])