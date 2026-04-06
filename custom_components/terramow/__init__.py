"""The TerraMow integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN, 
    CURRENT_HA_VERSION, 
    MIN_REQUIRED_OVERALL_VERSION,
    CompatibilityStatus
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LAWN_MOWER, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT, Platform.NUMBER, Platform.CAMERA]

@dataclass
class TerraMowBasicData:
    host: str
    password: str
    lawn_mower: Any = None
    compatibility_status: str = CompatibilityStatus.COMPATIBLE
    firmware_version: Optional[dict] = None
    compatibility_reason: str = ""  # Store the specific reason for compatibility check failure
    
    def check_version_compatibility(self, compatibility_info: dict) -> str:
        """Check version compatibility and return status."""
        try:
            overall_version = compatibility_info.get("overall", 0)
            module_info = compatibility_info.get("module", {})
            ha_version = module_info.get("home_assistant", 0)
            
            _LOGGER.info(
                "Version compatibility check: firmware overall=%d, firmware HA version=%d, plugin HA version=%d",
                overall_version, ha_version, CURRENT_HA_VERSION
            )
            
            # Check if firmware meets minimum requirements
            if overall_version < MIN_REQUIRED_OVERALL_VERSION:
                _LOGGER.warning(
                    "Firmware version too low: overall=%d < minimum required=%d",
                    overall_version, MIN_REQUIRED_OVERALL_VERSION
                )
                self.compatibility_reason = f"overall_version_low:{overall_version}"
                return CompatibilityStatus.UPGRADE_REQUIRED
            
            # Check HA version compatibility
            if ha_version < CURRENT_HA_VERSION:
                _LOGGER.warning(
                    "Firmware HA version is lower: %d < %d, some functions may not be available",
                    ha_version, CURRENT_HA_VERSION
                )
                self.compatibility_reason = f"ha_version_low:{ha_version}"
                return CompatibilityStatus.UPGRADE_REQUIRED
            elif ha_version > CURRENT_HA_VERSION:
                _LOGGER.warning(
                    "Firmware HA version is higher: %d > %d, recommend upgrading plugin",
                    ha_version, CURRENT_HA_VERSION
                )
                self.compatibility_reason = f"ha_version_high:{ha_version}"
                return CompatibilityStatus.DOWNGRADE_RECOMMENDED
            
            _LOGGER.info("Version compatibility check passed")
            self.compatibility_reason = ""  # Clear the reason for failure
            return CompatibilityStatus.COMPATIBLE
            
        except Exception as e:
            _LOGGER.error("Version compatibility check failed: %s", e)
            return CompatibilityStatus.INCOMPATIBLE
    
    def get_compatibility_message(self) -> str:
        """Get user-friendly compatibility status message."""
        if self.compatibility_status == CompatibilityStatus.COMPATIBLE:
            return "Version compatible, all functions working"
        elif self.compatibility_status == CompatibilityStatus.UPGRADE_REQUIRED:
            # Provide different prompts based on the specific reason
            if self.compatibility_reason.startswith("overall_version_low:"):
                return f"Firmware overall version too low, please upgrade firmware to version {MIN_REQUIRED_OVERALL_VERSION} or higher"
            elif self.compatibility_reason.startswith("ha_version_low:"):
                return f"Firmware HA module version too low (current: {self.compatibility_reason.split(':')[1]}, required: {CURRENT_HA_VERSION}), please upgrade firmware"
            else:
                return f"Firmware version too low, please upgrade firmware to overall version {MIN_REQUIRED_OVERALL_VERSION} or higher"
        elif self.compatibility_status == CompatibilityStatus.DOWNGRADE_RECOMMENDED:
            if self.compatibility_reason.startswith("ha_version_high:"):
                firmware_version = self.compatibility_reason.split(':')[1]
                return f"Firmware HA module version is higher (firmware: {firmware_version}, plugin: {CURRENT_HA_VERSION}), recommend upgrading plugin"
            else:
                return "Firmware HA version is higher than plugin version, recommend upgrading plugin or using corresponding firmware version"
        else:
            return "Version incompatible, cannot work properly"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    password = entry.data[CONF_PASSWORD]

    # Automatic migration of the device identifier
    device_registry = dr.async_get(hass)
    old_identifier = ('TerraMowLanwMower', host)
    new_identifier = ('TerraMowLawnMower', host)

    # Search for the device with the old identifier
    old_device_entry = device_registry.async_get_device({old_identifier})

    if old_device_entry:
        _LOGGER.info(
            "Migrating device identifier from '%s' to '%s'",
            "TerraMowLanwMower", "TerraMowLawnMower" # Corrected typo in identifier
        )
        # Check if a device with the new identifier already exists to avoid conflicts
        new_device_entry = device_registry.async_get_device({new_identifier})
        if new_device_entry:
            _LOGGER.warning("Cannot migrate device, a device with the new identifier already exists. Please remove the old device manually.")
        else:
            device_registry.async_update_device(
                old_device_entry.id, new_identifiers={new_identifier}
            )
    # End of Automatic migration

    _LOGGER.info("Setting up TerraMow with host %s", host)
    _LOGGER.debug("TerraMow entry data: %s", dict(entry.data))

    basic_data = TerraMowBasicData(host=host, password=password)

    # Use hass.data instead of entry.runtime_data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = basic_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # If unloading is successful, clear the data
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok
