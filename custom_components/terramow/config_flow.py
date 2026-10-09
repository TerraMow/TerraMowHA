"""Config flow for the TerraMow integration."""

from __future__ import annotations

import logging
import threading
from typing import Any
from uuid import uuid4

import paho.mqtt.client as mqtt_client
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow as BaseConfigFlow

# 移除 ConfigFlowResult 导入
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_IDENTITY_KEY, DOMAIN, MQTT_PORT, MQTT_USERNAME

_LOGGER = logging.getLogger(__name__)
MQTT_CONNECT_TIMEOUT = 5

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """验证用户输入并测试MQTT连接."""

    def mqtt_connect() -> None:
        """等待 broker 的 CONNACK，区分认证失败和网络失败。"""
        client = mqtt_client.Client()
        client.username_pw_set(MQTT_USERNAME, data[CONF_PASSWORD])
        connected = threading.Event()
        connack: list[int] = []
        loop_started = False

        def on_connect(
            _client: Any,
            _userdata: Any,
            _flags: Any,
            return_code: Any,
            *_args: Any,
        ) -> None:
            """记录 MQTT 3.x broker 返回码，并唤醒等待线程。"""
            connack.append(int(return_code))
            connected.set()

        client.on_connect = on_connect
        try:
            connect_result = client.connect(data[CONF_HOST], MQTT_PORT, 5)
            if int(connect_result) != 0:
                raise CannotConnect

            # connect() 只建立 socket；必须运行网络循环才能收到 CONNACK。
            client.loop_start()
            loop_started = True
            if not connected.wait(MQTT_CONNECT_TIMEOUT):
                raise CannotConnect

            return_code = connack[0] if connack else -1
            if return_code in (4, 5):
                raise InvalidAuth
            if return_code != 0:
                raise CannotConnect
        except (CannotConnect, InvalidAuth):
            raise
        except Exception as err:
            _LOGGER.error("MQTT connection failed: %s", type(err).__name__)
            raise CannotConnect from err
        finally:
            if loop_started:
                try:
                    client.disconnect()
                finally:
                    client.loop_stop()

    try:
        # 在 executor 中运行同步 MQTT 连接测试，避免阻塞 HA 事件循环。
        await hass.async_add_executor_job(mqtt_connect)
    except (CannotConnect, InvalidAuth):
        raise
    except Exception as err:
        _LOGGER.exception("Unexpected MQTT validation error: %s", type(err).__name__)
        raise CannotConnect from err

    return {"title": f"TerraMow ({data[CONF_HOST]})"}


class ConfigFlow(BaseConfigFlow, domain=DOMAIN):
    """Handle a config flow for TerraMow."""

    VERSION = 1

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
                # 旧地址可能仍是另一配置项的实体身份；新设备不能复用该身份。
                reserved_ids = {
                    entry.data.get(
                        CONF_IDENTITY_KEY, entry.unique_id or entry.data[CONF_HOST]
                    )
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                }
                identity_key = host
                while identity_key in reserved_ids:
                    identity_key = f"{host}_{uuid4().hex}"
                return self.async_create_entry(
                    title=info["title"],
                    data={**user_input, CONF_IDENTITY_KEY: identity_key},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """验证新地址与凭据，并保留现有实体的注册表身份。"""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown")

        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            # 同一地址只能由一个配置项连接，避免重复实体和控制入口。
            if any(
                other.entry_id != entry.entry_id
                and (other.data.get(CONF_HOST) == host or other.unique_id == host)
                for other in self.hass.config_entries.async_entries(DOMAIN)
            ):
                errors["base"] = "already_configured"
            else:
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
                    # 配置项按当前地址去重；实体身份另存，避免重载后生成新实体。
                    identity_key = entry.data.get(
                        CONF_IDENTITY_KEY, entry.unique_id or entry.data[CONF_HOST]
                    )
                    self.hass.config_entries.async_update_entry(
                        entry,
                        title=info["title"],
                        unique_id=host,
                        data={
                            **entry.data,
                            **user_input,
                            CONF_IDENTITY_KEY: identity_key,
                        },
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, entry.data
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
