"""Config flow for the TerraMow integration."""

from __future__ import annotations

import logging
import threading
from typing import Any

import paho.mqtt.client as mqtt_client
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow as BaseConfigFlow
# 移除 ConfigFlowResult 导入
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import MQTT_PORT, MQTT_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_USER_PASS_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """验证用户输入并测试MQTT连接.

    Raises InvalidAuth on authentication failure (broker rejects credentials)
    and CannotConnect for any other failure mode.
    """

    def mqtt_connect() -> tuple[bool, bool]:
        """Return (connected, auth_failed) by attempting an MQTT connection."""
        connected = False
        auth_failed = False
        event = threading.Event()

        def on_connect(client, userdata, flags, rc):
            nonlocal connected, auth_failed
            # rc 4 = bad username/password, rc 5 = not authorized
            if rc == 0:
                connected = True
            elif rc in (4, 5):
                auth_failed = True
            event.set()

        client = mqtt_client.Client()
        client.username_pw_set(MQTT_USERNAME, data[CONF_PASSWORD])
        client.on_connect = on_connect
        try:
            client.connect(data[CONF_HOST], MQTT_PORT, 5)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Connection failed: %s", err)
            return False, False

        client.loop_start()
        try:
            event.wait(timeout=5)
        finally:
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        return connected, auth_failed

    connected, auth_failed = await hass.async_add_executor_job(mqtt_connect)

    if auth_failed:
        raise InvalidAuth
    if not connected:
        raise CannotConnect

    return {"title": f"TerraMow ({data[CONF_HOST]})"}


class ConfigFlow(BaseConfigFlow, domain=DOMAIN):
    """Handle a config flow for TerraMow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_host: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):  # 移除返回值类型注解
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                host = user_input[CONF_HOST]
                _LOGGER.info('Setting up for host "%s"', host)
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors
        )

    async def async_step_zeroconf(self, discovery_info):
        """Handle a flow initialized by zeroconf discovery."""
        host = getattr(discovery_info, "host", None)
        if host is None and isinstance(discovery_info, dict):
            host = discovery_info.get("host")
        if not host:
            return self.async_abort(reason="cannot_connect")

        _LOGGER.info("Zeroconf discovered TerraMow at %s", host)

        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_host = host
        self.context["title_placeholders"] = {"host": host}

        return await self.async_step_user_pass()

    async def async_step_user_pass(
        self, user_input: dict[str, Any] | None = None
    ):
        """Ask the user for the password after zeroconf discovery."""
        errors: dict[str, str] = {}

        if self._discovered_host is None:
            return await self.async_step_user(user_input)

        if user_input is not None:
            data = {
                CONF_HOST: self._discovered_host,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                info = await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                _LOGGER.info(
                    'Setting up discovered host "%s"', self._discovered_host
                )
                return self.async_create_entry(
                    title=info["title"],
                    data=data,
                )

        return self.async_show_form(
            step_id="user_pass",
            data_schema=STEP_USER_PASS_DATA_SCHEMA,
            description_placeholders={"host": self._discovered_host},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Trigger the re-authentication flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle re-authentication confirmation."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(
            self.context.get("entry_id")
        )

        if user_input is not None and entry is not None:
            updated_data = {
                **entry.data,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await validate_input(self.hass, updated_data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data=updated_data
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OptionsFlowHandler":
        """Return the options flow handler for this entry."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for TerraMow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the TerraMow options (host/password)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, **user_input},
                )
                await self.hass.config_entries.async_reload(
                    self.config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=self.config_entry.data.get(CONF_HOST, ""),
                ): str,
                vol.Required(
                    CONF_PASSWORD,
                    default=self.config_entry.data.get(CONF_PASSWORD, ""),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
