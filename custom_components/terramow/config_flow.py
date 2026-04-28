"""Config flow for the TerraMow integration."""

from __future__ import annotations

import logging
from typing import Any

import paho.mqtt.client as mqtt_client
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow as BaseConfigFlow
# 移除 ConfigFlowResult 导入
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
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

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """验证用户输入并测试MQTT连接."""
    try:
        def mqtt_connect() -> bool:
            client = mqtt_client.Client()
            client.username_pw_set(MQTT_USERNAME, data[CONF_PASSWORD])
            try:
                client.connect(data[CONF_HOST], MQTT_PORT, 5)
                client.disconnect()
                return True
            except Exception as err:
                _LOGGER.error("Connection failed: %s", err)
                return False

        # 在executor中运行同步MQTT连接测试
        is_valid = await hass.async_add_executor_job(mqtt_connect)

        if not is_valid:
            raise InvalidAuth

        return {"title": f"TerraMow ({data[CONF_HOST]})"}

    except Exception as err:
        _LOGGER.exception("Unexpected error: %s", err)
        raise CannotConnect from err

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


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
