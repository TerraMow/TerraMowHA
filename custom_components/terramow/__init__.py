"""The TerraMow integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    Platform,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LAWN_MOWER, Platform.SENSOR]

@dataclass
class TerraMowBasicData:
    host: str
    password: str

# 使用 TypeVar 而不是泛型配置条目
TerraMowConfigEntry = TypeVar("TerraMowConfigEntry", bound=ConfigEntry)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    password = entry.data[CONF_PASSWORD]

    _LOGGER.info("Setting up TerraMow with host %s", host)

    basic_data = TerraMowBasicData(host=host, password=password)

    # 使用 hass.data 代替 entry.runtime_data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = basic_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # 如果卸载成功，清除数据
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok
