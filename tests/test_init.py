"""Tests for TerraMow config entry lifecycle."""

import logging
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import async_setup_entry, async_unload_entry
from custom_components.terramow.const import DOMAIN


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
