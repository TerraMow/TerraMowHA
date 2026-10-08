"""Tests for TerraMow config entry lifecycle."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import async_setup_entry, async_unload_entry
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.number import (
    MainDirectionAutoRotateIntervalNumber,
    MainDirectionSingleAngleNumber,
    MultipleDirectionAngle1Number,
    MultipleDirectionAngle2Number,
)
from custom_components.terramow.select import MainDirectionModeSelect


async def test_setup_and_unload_entry(hass, caplog) -> None:
    """The config entry stores runtime data and unloads cleanly."""
    caplog.set_level(logging.DEBUG, logger="custom_components.terramow")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.0.2.20", CONF_PASSWORD: "secret"},
        unique_id="192.0.2.20",
    )
    entry.add_to_hass(hass)

    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        new=AsyncMock(),
    ) as forward:
        assert await async_setup_entry(hass, entry)

    forward.assert_awaited_once()
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    assert runtime_data.host == "192.0.2.20"
    assert runtime_data.password == "secret"
    assert "secret" not in caplog.text

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ):
        assert await async_unload_entry(hass, entry)

    assert DOMAIN not in hass.data


async def test_mode_listeners_are_removed_with_entities(hass) -> None:
    """Direction mode listeners must not survive an entity unload."""
    basic_data = MagicMock(host="192.0.2.21")
    entities = [
        MainDirectionModeSelect(basic_data, hass),
        MainDirectionSingleAngleNumber(basic_data, hass),
        MainDirectionAutoRotateIntervalNumber(basic_data, hass),
        MultipleDirectionAngle1Number(basic_data, hass),
        MultipleDirectionAngle2Number(basic_data, hass),
    ]

    listeners = hass.bus.async_listeners()
    assert listeners["terramow_device_mode_confirmed"] == 1
    assert listeners["terramow_main_direction_mode_changed"] == 4

    for entity in entities:
        entity._call_on_remove_callbacks()

    listeners = hass.bus.async_listeners()
    assert listeners.get("terramow_device_mode_confirmed", 0) == 0
    assert listeners.get("terramow_main_direction_mode_changed", 0) == 0
