from __future__ import annotations
import logging
from typing import Any

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.switch import SwitchEntity
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
    """Set up TerraMow switch entities."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        ThoroughCornerCuttingSwitch(basic_data, hass),
    ]

    async_add_entities(entities)


class ThoroughCornerCuttingSwitch(SwitchEntity):
    """Switch for enabling thorough corner cutting in mow_param.

    Note: enable_thorough_corner_cutting is reported under
    map_info["mow_param"], but the documented data point for global
    operation parameter writes is dp_155. Until a dedicated DP for the
    mow_param flags is documented, we publish the toggle to dp_155 with
    the matching sub-dict — adjust if firmware exposes a different DP.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:vector-polyline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "thorough_corner_cutting"

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
        return DeviceInfo(
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
        )

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.host}.thorough_corner_cutting"

    def _get_mow_param(self) -> dict[str, Any] | None:
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            return None
        map_info = self.basic_data.lawn_mower.map_info
        if not map_info:
            return None
        mow_param = map_info.get('mow_param')
        if not isinstance(mow_param, dict):
            return None
        return mow_param

    @property
    def is_on(self) -> bool | None:
        mow_param = self._get_mow_param()
        if mow_param is None:
            return None
        value = mow_param.get('enable_thorough_corner_cutting')
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._publish(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._publish(False)

    async def _publish(self, enabled: bool) -> None:
        if not hasattr(self.basic_data, 'lawn_mower') or not self.basic_data.lawn_mower:
            _LOGGER.error("Lawn mower not available")
            return

        command = {'enable_thorough_corner_cutting': enabled}
        _LOGGER.info("Setting thorough corner cutting to %s", enabled)
        self.basic_data.lawn_mower.publish_data_point(155, command)
