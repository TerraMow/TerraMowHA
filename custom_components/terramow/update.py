from __future__ import annotations

import logging

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TerraMowBasicData, DOMAIN
from .const import COMPATIBILITY_INFO_DP

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TerraMow update entities."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        TerraMowFirmwareUpdate(basic_data, hass),
    ]

    async_add_entities(entities)


class TerraMowFirmwareUpdate(UpdateEntity):
    """Update entity exposing the TerraMow firmware version."""

    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the firmware update entity."""
        super().__init__()
        self.basic_data = basic_data
        self.host = self.basic_data.host
        self.hass = hass
        _LOGGER.info("TerraMowFirmwareUpdate entity created")

    async def async_added_to_hass(self) -> None:
        # UpdateEntity.state is a cached_property; without an explicit
        # async_write_ha_state() the cached "unknown" sticks even after
        # firmware_version_info populates. Push a refresh on every dp_127
        # message so the cache is invalidated as soon as data arrives.
        await super().async_added_to_hass()
        if self.basic_data.lawn_mower:
            self.basic_data.lawn_mower.register_callback(
                COMPATIBILITY_INFO_DP, self._handle_compat_info
            )

    async def _handle_compat_info(self, _payload: str) -> None:
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={('TerraMowLawnMower', self.basic_data.host)},
            name='TerraMow',
            manufacturer='TerraMow',
            model=self.basic_data.lawn_mower.device_model
            if self.basic_data.lawn_mower
            else None,
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this entity."""
        return f"lawn_mower.terramow@{self.host}.firmware"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.basic_data.lawn_mower is not None

    def _format_version(self) -> str | None:
        """Build a version string from the firmware compatibility info."""
        if not self.basic_data.lawn_mower:
            return None

        info = self.basic_data.lawn_mower.firmware_version_info
        if not info:
            return None

        overall = info.get("overall")
        if overall is None:
            return None

        ha_version = info.get("module", {}).get("home_assistant")
        if ha_version is not None:
            return f"{overall}.{ha_version}"
        return str(overall)

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed firmware version."""
        return self._format_version()

    @property
    def latest_version(self) -> str | None:
        """Return the latest available firmware version.

        Updates are managed via the TerraMow app, so report the installed
        version to indicate that no update is available from Home Assistant.
        """
        return self._format_version()
