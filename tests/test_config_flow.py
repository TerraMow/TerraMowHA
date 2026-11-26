"""Tests for the TerraMow config flow."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiomqtt
import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData, async_setup_entry
from custom_components.terramow.binary_sensor import TerraMowChargingSensor
from custom_components.terramow.config_flow import CannotConnect, InvalidAuth
from custom_components.terramow.const import CONF_IDENTITY_KEY, DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity
from custom_components.terramow.map_sensor import TerraMowMapStatusSensor
from custom_components.terramow.number import MowingHeightNumber
from custom_components.terramow.select import MowSpeedSelect
from custom_components.terramow.sensor import (
    BatterySensor,
    CurrentSessionProgressSensor,
)


class _FakeConnection:
    """Stands in for aiomqtt.Client in the connection test."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.kwargs: dict = {}
        self.exited = False

    def __call__(self, **kwargs) -> "_FakeConnection":
        self.kwargs = kwargs
        return self

    async def __aenter__(self) -> "_FakeConnection":
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *_exc) -> None:
        self.exited = True

    # The created entry is set up right away and its mower connects through
    # the same fake: accept subscriptions and publishes, deliver no messages.
    async def subscribe(self, *_args, **_kwargs) -> None:
        return None

    async def publish(self, *_args, **_kwargs) -> None:
        return None

    @property
    def messages(self):
        async def never():
            await asyncio.Event().wait()
            yield  # pragma: no cover

        return never()


def _patch_connection(connection: _FakeConnection):
    return patch("custom_components.terramow.config_flow.aiomqtt.Client", connection)


async def test_user_flow_creates_entry(hass) -> None:
    """A reachable mower creates a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    connection = _FakeConnection()
    with _patch_connection(connection):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.10", CONF_PASSWORD: "secret"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TerraMow (192.0.2.10)"
    assert result["data"] == {
        CONF_HOST: "192.0.2.10",
        CONF_PASSWORD: "secret",
        CONF_IDENTITY_KEY: "192.0.2.10",
    }
    assert connection.kwargs["hostname"] == "192.0.2.10"
    assert connection.kwargs["port"] == 1883
    assert connection.kwargs["username"] == "terramow"
    assert connection.kwargs["password"] == "secret"
    assert connection.exited


@pytest.mark.parametrize(
    "error",
    [
        OSError("unreachable"),
        TimeoutError(),
        aiomqtt.MqttError("no route"),
        aiomqtt.MqttCodeError(3, "server unavailable"),
        RuntimeError("unexpected"),
    ],
)
async def test_user_flow_reports_connection_error(hass, error) -> None:
    """An unreachable mower leaves the form open with an error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    with _patch_connection(_FakeConnection(error)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.11", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize("code", [4, 5, 134, 135])
async def test_user_flow_reports_invalid_auth(hass, code) -> None:
    """A broker CONNACK authentication refusal is shown as invalid_auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    with _patch_connection(_FakeConnection(aiomqtt.MqttCodeError(code, "refused"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.12", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_auth_refusal_as_reason_code_object(hass) -> None:
    """paho 2.x may wrap the CONNACK code in an object with a value."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    error = aiomqtt.MqttCodeError(0, "refused")
    error.rc = SimpleNamespace(value=135)

    with _patch_connection(_FakeConnection(error)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.13", CONF_PASSWORD: "wrong"},
        )

    assert result["errors"] == {"base": "invalid_auth"}


async def _start_reconfigure(hass, entry: MockConfigEntry) -> dict:
    """为指定配置项打开 Home Assistant 的重新配置表单。"""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return result


async def test_reconfigure_preserves_entity_and_device_identity(hass) -> None:
    """地址变化后沿用已有实体和设备，连接则改用新地址。"""
    old_host = "192.0.2.20"
    new_host = "192.0.2.21"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: old_host, CONF_PASSWORD: "old-secret"},
        unique_id=old_host,
    )
    entry.add_to_hass(hass)
    entities = er.async_get(hass)
    old_battery = entities.async_get_or_create(
        "sensor", DOMAIN, f"lawn_mower.terramow@{old_host}.battery", config_entry=entry
    )
    devices = dr.async_get(hass)
    old_device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("TerraMowLawnMower", old_host)},
    )

    result = await _start_reconfigure(hass, entry)
    with (
        patch(
            "custom_components.terramow.config_flow.validate_input",
            new=AsyncMock(return_value={"title": f"TerraMow ({new_host})"}),
        ),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: new_host, CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    reload.assert_awaited_once_with(entry.entry_id)
    assert entry.unique_id == new_host
    assert entry.data == {
        CONF_HOST: new_host,
        CONF_PASSWORD: "new-secret",
        CONF_IDENTITY_KEY: old_host,
    }
    assert (
        hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, old_host) is None
    )

    with patch.object(
        hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
    ):
        assert await async_setup_entry(hass, entry)
    basic_data = hass.data[DOMAIN][entry.entry_id]
    assert isinstance(basic_data, TerraMowBasicData)
    assert basic_data.host == new_host
    assert basic_data.password == "new-secret"
    assert basic_data.stable_id == old_host

    mower = TerraMowLawnMowerEntity(basic_data, hass)
    platform_entities = [
        mower,
        BatterySensor(basic_data, hass),
        CurrentSessionProgressSensor(basic_data, hass),
        TerraMowMapStatusSensor(basic_data, hass),
        TerraMowChargingSensor(basic_data, hass),
        MowingHeightNumber(basic_data, hass),
        MowSpeedSelect(basic_data, hass),
    ]
    for entity in platform_entities:
        assert f"@{old_host}" in entity.unique_id
        assert entity.device_info["identifiers"] == {("TerraMowLawnMower", old_host)}
    assert mower.host == new_host
    assert devices.async_get_device({("TerraMowLawnMower", old_host)}) == old_device
    assert devices.async_get_device({("TerraMowLawnMower", new_host)}) is None
    assert (
        entities.async_get_or_create(
            "sensor", DOMAIN, platform_entities[1].unique_id, config_entry=entry
        ).entity_id
        == old_battery.entity_id
    )

    # 旧地址分配给另一台设备时，不得占用原设备沿用的实体身份。
    new_flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with (
        patch(
            "custom_components.terramow.config_flow.validate_input",
            new=AsyncMock(return_value={"title": f"TerraMow ({old_host})"}),
        ),
        patch.object(hass.config_entries, "async_setup", new=AsyncMock()),
    ):
        new_result = await hass.config_entries.flow.async_configure(
            new_flow["flow_id"], {CONF_HOST: old_host, CONF_PASSWORD: "other-secret"}
        )
    assert new_result["type"] is FlowResultType.CREATE_ENTRY
    assert new_result["data"][CONF_IDENTITY_KEY] != old_host
    other_data = TerraMowBasicData(
        host=old_host,
        password="other-secret",
        identity_key=new_result["data"][CONF_IDENTITY_KEY],
    )
    TerraMowLawnMowerEntity(other_data, hass)
    assert BatterySensor(other_data, hass).unique_id != platform_entities[1].unique_id


async def test_reconfigure_rejects_configured_host(hass) -> None:
    """目标地址已配置时保留原配置，且不再发起连接。"""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.0.2.30", CONF_PASSWORD: "secret"},
        unique_id="192.0.2.30",
    )
    other = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.0.2.31", CONF_PASSWORD: "secret"},
        unique_id="192.0.2.31",
    )
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    result = await _start_reconfigure(hass, entry)
    with patch("custom_components.terramow.config_flow.validate_input") as validate:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.31", CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}
    validate.assert_not_called()
    assert entry.data[CONF_HOST] == "192.0.2.30"
    assert entry.unique_id == "192.0.2.30"


async def test_reconfigure_again_keeps_first_entity_identity(hass) -> None:
    """第二次修改连接地址时仍沿用首次配置的实体身份。"""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.0.2.51",
            CONF_PASSWORD: "secret",
            CONF_IDENTITY_KEY: "192.0.2.50",
        },
        unique_id="192.0.2.51",
    )
    entry.add_to_hass(hass)
    result = await _start_reconfigure(hass, entry)
    with (
        patch(
            "custom_components.terramow.config_flow.validate_input",
            new=AsyncMock(return_value={"title": "TerraMow (192.0.2.52)"}),
        ),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.52", CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert entry.unique_id == "192.0.2.52"
    assert entry.data[CONF_IDENTITY_KEY] == "192.0.2.50"


@pytest.mark.parametrize(
    ("failure", "error"),
    [(CannotConnect, "cannot_connect"), (InvalidAuth, "invalid_auth")],
)
async def test_reconfigure_validation_failure_keeps_entry(hass, failure, error) -> None:
    """连接或认证失败时不改动现有连接信息。"""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.0.2.40", CONF_PASSWORD: "secret"},
        unique_id="192.0.2.40",
    )
    entry.add_to_hass(hass)
    result = await _start_reconfigure(hass, entry)
    with (
        patch(
            "custom_components.terramow.config_flow.validate_input",
            new=AsyncMock(side_effect=failure),
        ),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.0.2.41", CONF_PASSWORD: "new-secret"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    reload.assert_not_awaited()
    assert entry.data == {CONF_HOST: "192.0.2.40", CONF_PASSWORD: "secret"}
    assert entry.unique_id == "192.0.2.40"
