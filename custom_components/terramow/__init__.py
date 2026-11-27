"""The TerraMow integration."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PASSWORD,
    ENTITY_MATCH_ALL,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_IDENTITY_KEY,
    CURRENT_HA_VERSION,
    DOMAIN,
    MIN_REQUIRED_OVERALL_VERSION,
    CompatibilityStatus,
)
from .schedule_history import history_store

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LAWN_MOWER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.CAMERA,
    Platform.SWITCH,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.BUTTON,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_START_SELECT_REGION = "start_select_region"
ATTR_REGION_IDS = "region_ids"
_ZONE_ID_TEXT = re.compile(r"[0-9]+", re.ASCII)


def zone_id(value: Any) -> int:
    """Validate one zone ID: a non-negative integer, or a string of one.

    Booleans and floating-point numbers are rejected instead of being
    truncated, so ``true`` or ``1.9`` can never select zone 1.
    """
    if isinstance(value, bool):
        raise vol.Invalid("zone IDs must be whole numbers, not booleans")
    if isinstance(value, int):
        if value < 0:
            raise vol.Invalid("zone IDs must not be negative")
        return value
    if isinstance(value, str) and _ZONE_ID_TEXT.fullmatch(value.strip()):
        return int(value)
    raise vol.Invalid(f"invalid zone ID: {value!r}")


START_SELECT_REGION_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_REGION_IDS): vol.All(
            cv.ensure_list, vol.Length(min=1), [zone_id]
        )
    }
)


def _targeted_entity_ids(hass: HomeAssistant, call: ServiceCall) -> set[str]:
    """Entity IDs a service call targets, with devices and areas expanded.

    Home Assistant moved target resolution to ``helpers.target``; the
    ``helpers.service`` version is deprecated there but is all that older
    cores such as 2025.3 provide.
    """
    try:
        from homeassistant.helpers.target import (
            TargetSelection,
            async_extract_referenced_entity_ids,
        )
    except ImportError:
        from homeassistant.helpers.service import (
            async_extract_referenced_entity_ids as legacy_extract,
        )

        legacy = legacy_extract(hass, call)
        return legacy.referenced | legacy.indirectly_referenced
    selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
    return selected.referenced | selected.indirectly_referenced


@dataclass
class TerraMowBasicData:
    host: str
    password: str
    lawn_mower: Any = None
    compatibility_status: str = CompatibilityStatus.COMPATIBLE
    firmware_version: dict | None = None
    compatibility_reason: str = (
        ""  # Store the specific reason for compatibility check failure
    )
    identity_key: str | None = None

    @property
    def stable_id(self) -> str:
        """返回不会随连接地址变化的实体和设备身份。"""
        return self.identity_key or self.host

    def check_version_compatibility(self, compatibility_info: dict) -> str:
        """Check version compatibility and return status."""
        try:
            overall_version = compatibility_info.get("overall", 0)
            module_info = compatibility_info.get("module", {})
            ha_version = module_info.get("home_assistant", 0)

            _LOGGER.info(
                "Version compatibility check: firmware overall=%d, firmware HA version=%d, plugin HA version=%d",
                overall_version,
                ha_version,
                CURRENT_HA_VERSION,
            )

            # Check if firmware meets minimum requirements
            if overall_version < MIN_REQUIRED_OVERALL_VERSION:
                _LOGGER.warning(
                    "Firmware version too low: overall=%d < minimum required=%d",
                    overall_version,
                    MIN_REQUIRED_OVERALL_VERSION,
                )
                self.compatibility_reason = f"overall_version_low:{overall_version}"
                return CompatibilityStatus.UPGRADE_REQUIRED

            # Check HA version compatibility
            if ha_version < CURRENT_HA_VERSION:
                _LOGGER.warning(
                    "Firmware HA version is lower: %d < %d, some functions may not be available",
                    ha_version,
                    CURRENT_HA_VERSION,
                )
                self.compatibility_reason = f"ha_version_low:{ha_version}"
                return CompatibilityStatus.UPGRADE_REQUIRED
            elif ha_version > CURRENT_HA_VERSION:
                _LOGGER.warning(
                    "Firmware HA version is higher: %d > %d, recommend upgrading plugin",
                    ha_version,
                    CURRENT_HA_VERSION,
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
                firmware_version = self.compatibility_reason.split(":")[1]
                return f"Firmware HA module version is higher (firmware: {firmware_version}, plugin: {CURRENT_HA_VERSION}), recommend upgrading plugin"
            else:
                return "Firmware HA version is higher than plugin version, recommend upgrading plugin or using corresponding firmware version"
        else:
            return "Version incompatible, cannot work properly"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services once, independent of entries."""

    async def async_start_select_region(call: ServiceCall) -> None:
        """Start mowing the given zones on each targeted mower."""
        match_all = call.data.get(ATTR_ENTITY_ID) == ENTITY_MATCH_ALL
        targets = set() if match_all else _targeted_entity_ids(hass, call)
        mowers = [
            basic_data.lawn_mower
            for basic_data in hass.data.get(DOMAIN, {}).values()
            if basic_data.lawn_mower is not None
            and (match_all or basic_data.lawn_mower.entity_id in targets)
        ]
        if not mowers:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="mower_not_found"
            )
        for mower in mowers:
            await mower.async_start_select_region(call.data[ATTR_REGION_IDS])

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_SELECT_REGION,
        async_start_select_region,
        schema=START_SELECT_REGION_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    password = entry.data[CONF_PASSWORD]
    identity_key = entry.data.get(CONF_IDENTITY_KEY, entry.unique_id or host)

    # Automatic migration of the device identifier
    device_registry = dr.async_get(hass)
    old_identifier = ("TerraMowLanwMower", identity_key)
    new_identifier = ("TerraMowLawnMower", identity_key)

    # Search for the device with the old identifier
    old_device_entry = device_registry.async_get_device({old_identifier})

    if old_device_entry:
        _LOGGER.info(
            "Migrating device identifier from '%s' to '%s'",
            "TerraMowLanwMower",
            "TerraMowLawnMower",  # Corrected typo in identifier
        )
        # Check if a device with the new identifier already exists to avoid conflicts
        new_device_entry = device_registry.async_get_device({new_identifier})
        if new_device_entry:
            _LOGGER.warning(
                "Cannot migrate device, a device with the new identifier already exists. Please remove the old device manually."
            )
        else:
            device_registry.async_update_device(
                old_device_entry.id, new_identifiers={new_identifier}
            )
    # End of Automatic migration

    _LOGGER.info("Setting up TerraMow with host %s", host)

    basic_data = TerraMowBasicData(
        host=host, password=password, identity_key=identity_key
    )

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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove local appointment dates when the integration is deleted."""
    stable_id = entry.data.get(
        CONF_IDENTITY_KEY, entry.unique_id or entry.data[CONF_HOST]
    )
    await history_store(hass, stable_id).async_remove()
