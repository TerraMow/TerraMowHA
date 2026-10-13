"""读取并控制割草机的全局修剪计划开关。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send

if TYPE_CHECKING:
    from .lawn_mower import TerraMowLawnMowerEntity

_LOGGER = logging.getLogger(__name__)

SCHEDULE_DP = 122
SCHEDULE_GET = "SCHEDULE_CMD_TYPE_GET"
SCHEDULE_SET_GLOBAL_DISABLED = "SCHEDULE_CMD_TYPE_SET_GLOBAL_DISABLED"
SCHEDULE_SET_DISABLED_WEEK_DAYS = "SCHEDULE_CMD_TYPE_SET_DISABLED_WEEK_DAYS"
SCHEDULE_MODE_TIME_SLOT = "SCHEDULE_MODE_TIME_SLOT"
SCHEDULE_REPLY_TIMEOUT = 5.0
WEEK_DAYS = {
    "monday": "WEEK_DAY_MONDAY",
    "tuesday": "WEEK_DAY_TUESDAY",
    "wednesday": "WEEK_DAY_WEDNESDAY",
    "thursday": "WEEK_DAY_THURSDAY",
    "friday": "WEEK_DAY_FRIDAY",
    "saturday": "WEEK_DAY_SATURDAY",
    "sunday": "WEEK_DAY_SUNDAY",
}


class TerraMowSchedule:
    """持有本次连接的计划状态，并串行匹配读取和设置回复。"""

    def __init__(self, mower: TerraMowLawnMowerEntity) -> None:
        self.mower = mower
        self.signal = f"terramow_{mower.host}_schedule"
        self.enabled: bool | None = None
        self.disabled_week_days: frozenset[str] | None = None
        self.schedule_mode: str | None = None
        self.version: int | None = None
        self._lock = asyncio.Lock()
        self._pending: tuple[int, str, asyncio.Future[dict[str, Any]]] | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._refresh_pending = False

    @property
    def available(self) -> bool:
        """仅在设备在线且明确支持全局计划开关时提供控制。"""
        return (
            self.mower.mqtt_connected and self.version is not None and self.version >= 2
        )

    @property
    def weekday_available(self) -> bool:
        """频率预约不应用按星期禁用的配置，因此不开放单日控制。"""
        return (
            self.available
            and self.disabled_week_days is not None
            and self.schedule_mode == SCHEDULE_MODE_TIME_SLOT
        )

    def weekday_enabled(self, day: str) -> bool | None:
        """返回该日是否允许预约；未知快照不能解释为全部启用。"""
        days = self.disabled_week_days
        return WEEK_DAYS[day] not in days if days is not None else None

    @callback
    def reset_connection(self) -> None:
        """断线或新连接后清除旧状态，终止上一连接尚未完成的请求。"""
        self.enabled = None
        self.disabled_week_days = None
        self.schedule_mode = None
        self.version = None
        # 让等待中的任务收到断线异常并自行结束，避免取消后留下未读取的 Future 异常。
        self._refresh_pending = False
        self._refresh_task = None
        if self._pending is not None:
            future = self._pending[2]
            if not future.done():
                future.set_exception(HomeAssistantError("TerraMow disconnected"))
        async_dispatcher_send(self.mower.hass, self.signal)

    def update_version(self, compatibility_info: dict[str, Any]) -> None:
        """从兼容性报告识别能力；支持时主动读取设备的当前设置。"""
        module = compatibility_info.get("module")
        raw = module.get("schedule") if isinstance(module, dict) else None
        if type(raw) is int:
            self.version = raw
        elif isinstance(raw, str) and raw.isdecimal():
            self.version = int(raw)
        else:
            self.version = None
        async_dispatcher_send(self.mower.hass, self.signal)
        self.request_refresh()

    def request_refresh(self) -> None:
        """合并密集变更；读取进行时的新变更至少再触发一次读取。"""
        if not self.available:
            return
        self._refresh_pending = True
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = self.mower.hass.async_create_task(
                self._drain_refresh()
            )

    async def _drain_refresh(self) -> None:
        """后台刷新不阻塞其它平台，失败时保持未知或上次已确认的状态。"""
        while self._refresh_pending and self.available:
            self._refresh_pending = False
            try:
                await self.async_refresh()
            except (HomeAssistantError, ServiceValidationError) as err:
                _LOGGER.debug("Unable to read TerraMow schedule: %s", err)

    def _update_from_list(self, schedule_list: Any) -> bool:
        if not isinstance(schedule_list, dict):
            return False
        disabled = schedule_list.get("global_disabled", False)
        if type(disabled) is not bool:
            return False
        # protobuf JSON 可省略默认 false；只有完整的成功 GET 回复才更新开关。
        new_enabled = not disabled
        raw_days = schedule_list.get("disabled_week_days", [])
        if isinstance(raw_days, list) and all(
            isinstance(day, str) and day in WEEK_DAYS.values() for day in raw_days
        ):
            new_days: frozenset[str] | None = frozenset(raw_days)
        else:
            new_days = None
        mode = schedule_list.get("schedule_mode", SCHEDULE_MODE_TIME_SLOT)
        new_mode = (
            mode
            if mode in (SCHEDULE_MODE_TIME_SLOT, "SCHEDULE_MODE_FREQUENCY")
            else None
        )
        if (
            self.enabled is not new_enabled
            or self.disabled_week_days != new_days
            or self.schedule_mode != new_mode
        ):
            self.enabled = new_enabled
            self.disabled_week_days = new_days
            self.schedule_mode = new_mode
            async_dispatcher_send(self.mower.hass, self.signal)
        return True

    async def on_reply(self, payload: str, retained: bool = False) -> None:
        """仅接受当前连接的有效回复；GET 回复也可同步其他客户端的修改。"""
        if retained or not self.available:
            return
        try:
            reply = json.loads(payload)
        except (TypeError, ValueError):
            return
        if not isinstance(reply, dict):
            return
        seq = reply.get("seq")
        # GET 为枚举零值，protobuf JSON 可能不输出该字段。
        cmd_type = reply.get("cmd_type", SCHEDULE_GET)
        code = reply.get("code", 0)
        if (
            type(seq) is not int
            or type(code) is not int
            or not isinstance(cmd_type, str)
        ):
            return
        if code == 0 and cmd_type == SCHEDULE_GET:
            self._update_from_list(reply.get("schedule_list"))
        pending = self._pending
        matched = (
            pending is not None
            and (seq, cmd_type) == pending[:2]
            and not pending[2].done()
        )
        if matched:
            pending[2].set_result(reply)
        elif code == 0 and cmd_type != SCHEDULE_GET:
            # 其它客户端的 SET 回复不含新状态；主动回读，避免 HA 一直显示旧开关。
            self.request_refresh()

    async def _send(
        self, cmd_type: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        client = self.mower.mqtt_client
        if not self.available or client is None or not client.is_connected():
            raise HomeAssistantError("TerraMow schedule is unavailable")
        # 预约协议使用 int32 序号；通用命令计数器可产生 uint32 高半区的值。
        seq = self.mower.get_cmd_seq() & 0x7FFFFFFF
        if seq == 0:
            seq = self.mower.get_cmd_seq() & 0x7FFFFFFF
        command = {"cmd_type": cmd_type, "seq": seq, **(params or {})}
        future: asyncio.Future[dict[str, Any]] = self.mower.hass.loop.create_future()
        self._pending = (seq, cmd_type, future)
        try:
            info = self.mower.publish_data_point(SCHEDULE_DP, command)
            if info is None or info.rc != 0:
                raise HomeAssistantError("TerraMow schedule request could not be sent")
            try:
                reply = await asyncio.wait_for(future, SCHEDULE_REPLY_TIMEOUT)
            except TimeoutError as err:
                raise HomeAssistantError(
                    "TerraMow did not confirm the schedule request"
                ) from err
            if reply.get("code", 0) != 0:
                raise HomeAssistantError(
                    f"TerraMow rejected the schedule request (code={reply['code']})"
                )
            return reply
        finally:
            self._pending = None
            if not future.done():
                future.cancel()

    async def async_refresh(self) -> None:
        """读取完整计划列表中的总开关，供启动和重新连接后恢复状态。"""
        async with self._lock:
            reply = await self._send(SCHEDULE_GET)
            if not self._update_from_list(reply.get("schedule_list")):
                raise HomeAssistantError("TerraMow did not report the schedule switch")

    async def async_set_enabled(self, enabled: bool) -> None:
        """等待设置成功，再重新读取，避免把发送成功误当成状态生效。"""
        if self.version is None or self.version < 2:
            raise ServiceValidationError(
                "Schedule switch requires schedule version 2 or later"
            )
        if not self.mower.mqtt_connected:
            raise HomeAssistantError("TerraMow is not connected to MQTT")
        async with self._lock:
            if not self.mower._can_accept_command():
                raise ServiceValidationError(
                    "TerraMow control requests must be at least one second apart"
                )
            # 设置可能成功但回复丢失，发送前就撤销旧状态的可信度。
            self.enabled = None
            async_dispatcher_send(self.mower.hass, self.signal)
            await self._send(
                SCHEDULE_SET_GLOBAL_DISABLED,
                {"set_global_disabled_param": {"global_disabled": not enabled}},
            )
            reply = await self._send(SCHEDULE_GET)
            if not self._update_from_list(reply.get("schedule_list")):
                raise HomeAssistantError("TerraMow did not report the schedule switch")
            if self.enabled is not enabled:
                raise HomeAssistantError(
                    "TerraMow reported a different schedule switch state"
                )

    async def async_set_weekday_enabled(self, day: str, enabled: bool) -> None:
        """修改单日禁用集合，并以 GET 回报确认对应星期的实际状态。"""
        if day not in WEEK_DAYS:
            raise ServiceValidationError("Invalid schedule weekday")
        if not self.available:
            raise HomeAssistantError("TerraMow schedule is unavailable")
        if self.schedule_mode != SCHEDULE_MODE_TIME_SLOT:
            raise ServiceValidationError(
                "Weekday switches require time-slot schedule mode"
            )
        if self.disabled_week_days is None:
            raise HomeAssistantError("TerraMow weekday schedule has not been read")
        async with self._lock:
            if not self.mower._can_accept_command():
                raise ServiceValidationError(
                    "TerraMow control requests must be at least one second apart"
                )
            # 命令超时也可能已生效；清空旧集合，直到 GET 再次确认。
            self.disabled_week_days = None
            async_dispatcher_send(self.mower.hass, self.signal)
            await self._send(
                SCHEDULE_SET_DISABLED_WEEK_DAYS,
                {
                    "set_disabled_week_days_param": {
                        "week_day": WEEK_DAYS[day],
                        "disabled": not enabled,
                    }
                },
            )
            reply = await self._send(SCHEDULE_GET)
            if not self._update_from_list(reply.get("schedule_list")):
                raise HomeAssistantError("TerraMow did not report the weekday schedule")
            if (
                self.disabled_week_days is None
                or self.weekday_enabled(day) is not enabled
            ):
                raise HomeAssistantError(
                    "TerraMow reported a different weekday schedule state"
                )
