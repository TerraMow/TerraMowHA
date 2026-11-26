"""TerraMow maintenance counter reset buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, TerraMowBasicData


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the blade and base-station reset buttons."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            TerraMowResetBladeButton(basic_data, hass),
            TerraMowResetBaseStationButton(basic_data, hass),
        ]
    )


class TerraMowResetButton(ButtonEntity):
    """Reset a maintenance counter after service; the mower confirms it."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _key: str

    def __init__(self, basic_data: TerraMowBasicData, hass: HomeAssistant) -> None:
        self.basic_data = basic_data
        self.hass = hass
        self._attr_translation_key = self._key

    async def async_added_to_hass(self) -> None:
        """Follow connection changes, which the map status signal announces."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"terramow_{self.basic_data.host}_map_status",
                self.async_write_ha_state,
            )
        )

    @property
    def available(self) -> bool:
        mower = self.basic_data.lawn_mower
        return mower is not None and bool(mower.mqtt_connected)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)}
        )

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.{self._key}"


class TerraMowResetBladeButton(TerraMowResetButton):
    """Reset the blade usage counter (dp_126)."""

    _key = "reset_blade_time"
    _attr_icon = "mdi:saw-blade"

    async def async_press(self) -> None:
        await self.basic_data.lawn_mower.async_reset_blade_time()


class TerraMowResetBaseStationButton(TerraMowResetButton):
    """Reset the base-station usage counter (dp_125)."""

    _key = "reset_base_station_time"
    _attr_icon = "mdi:home-lightning-bolt"

    async def async_press(self) -> None:
        await self.basic_data.lawn_mower.async_reset_base_station_time()
