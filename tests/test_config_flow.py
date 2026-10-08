"""Tests for the TerraMow config flow."""

from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType

from custom_components.terramow.const import DOMAIN


async def test_user_flow_creates_entry(hass) -> None:
    """A reachable mower creates a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    client = MagicMock()

    def connect(*_args) -> int:
        client.on_connect(client, None, {}, 0)
        return 0

    client.connect.side_effect = connect
    with patch(
        "custom_components.terramow.config_flow.mqtt_client.Client",
        return_value=client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.10", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TerraMow (192.0.2.10)"
    assert result["data"] == {
        CONF_HOST: "192.0.2.10",
        CONF_PASSWORD: "secret",
    }
    client.connect.assert_called_once_with("192.0.2.10", 1883, 5)
    client.loop_start.assert_called_once_with()
    client.loop_stop.assert_called_once_with()
    client.disconnect.assert_called_once_with()


async def test_user_flow_reports_connection_error(hass) -> None:
    """An unreachable mower leaves the form open with an error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    client = MagicMock()
    client.connect.side_effect = OSError("unreachable")
    with patch(
        "custom_components.terramow.config_flow.mqtt_client.Client",
        return_value=client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.11", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_reports_invalid_auth(hass) -> None:
    """A broker CONNACK authentication refusal is shown as invalid_auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    client = MagicMock()

    def connect(*_args) -> int:
        client.on_connect(client, None, {}, 5)
        return 0

    client.connect.side_effect = connect
    with patch(
        "custom_components.terramow.config_flow.mqtt_client.Client",
        return_value=client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.12", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    client.disconnect.assert_called_once_with()
    client.loop_stop.assert_called_once_with()
