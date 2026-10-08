"""Tests for the TerraMow lawn mower platform."""

import logging
from unittest.mock import MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import (
    TerraMowLawnMowerEntity,
    async_setup_entry,
)


async def test_lawn_mower_entity_is_created_without_real_network(hass, caplog) -> None:
    """Platform setup creates one entity and delegates MQTT startup."""
    caplog.set_level(logging.DEBUG, logger="custom_components.terramow")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.0.2.30", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = TerraMowBasicData(
        host="192.0.2.30",
        password="secret",
    )
    async_add_entities = MagicMock()

    with patch.object(TerraMowLawnMowerEntity, "start_mqtt_client") as start:
        await async_setup_entry(hass, entry, async_add_entities)

    entities = async_add_entities.call_args.args[0]
    assert len(entities) == 1
    assert isinstance(entities[0], TerraMowLawnMowerEntity)
    assert entities[0].host == "192.0.2.30"
    start.assert_called_once_with()

    with (
        patch("custom_components.terramow.lawn_mower.mqtt_client.Client") as client,
        patch("custom_components.terramow.lawn_mower.threading.Thread"),
    ):
        entities[0].start_mqtt_client()

    client.return_value.username_pw_set.assert_called_once_with("terramow", "secret")
    assert "secret" not in caplog.text
