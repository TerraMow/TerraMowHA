from __future__ import annotations
import logging

from homeassistant.components.button import ButtonEntity
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
    """Set up the TerraMow button entities."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        ResetBladeTimerButton(basic_data, hass),
        ResetBaseStationTimerButton(basic_data, hass),
    ]

    async_add_entities(entities)


class TerraMowResetButtonBase(ButtonEntity):
    """Base class for TerraMow reset buttons."""

    _attr_has_entity_name = True
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
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None


class ResetBladeTimerButton(TerraMowResetButtonBase):
    """Button to reset the mowing blade disk usage time."""

    _attr_translation_key = "reset_blade_timer"
    _attr_icon = "mdi:saw-blade"

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.host}.reset_blade_timer"

    async def async_press(self) -> None:
        """Reset the blade timer by sending 0 to dp_126."""
        _LOGGER.info("Resetting blade timer")
        self.basic_data.lawn_mower.publish_data_point(126, {"int_value": 0})


class ResetBaseStationTimerButton(TerraMowResetButtonBase):
    """Button to reset the base station usage time."""

    _attr_translation_key = "reset_base_station_timer"
    _attr_icon = "mdi:home-lightning-bolt"

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.host}.reset_base_station_timer"

    async def async_press(self) -> None:
        """Reset the base station timer by sending 0 to dp_125."""
        _LOGGER.info("Resetting base station timer")
        self.basic_data.lawn_mower.publish_data_point(125, {"int_value": 0})
