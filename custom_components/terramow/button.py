from __future__ import annotations
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
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
    """Set up TerraMow button entities."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([EdgeTrimButton(basic_data)])


class EdgeTrimButton(ButtonEntity):
    """Button that starts the TerraMow in edge-trim mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "edge_trim"
    _attr_icon = "mdi:vector-square"

    def __init__(self, basic_data: TerraMowBasicData) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model,
        )

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.host}.edge_trim"

    async def async_press(self) -> None:
        """Trigger edge-trim mowing."""
        self.basic_data.lawn_mower.start_edge_trim()
