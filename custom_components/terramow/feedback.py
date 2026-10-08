"""将设备命令回复、历史事件和当前故障分别交给 HA。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .lawn_mower import TerraMowLawnMowerEntity

_LOGGER = logging.getLogger(__name__)
COMMAND_REPLY_TIMEOUT = 5.0
EVENT_DESCRIPTIONS = {
    66: "Selected region mowing completed",
    95: "Returning outside operating time",
    114: "Resume cancelled near sunset",
    115: "Returning because it is dark",
    116: "Cannot work because it is dark",
    135: "Outside operating time",
}
FAULT_DESCRIPTIONS = {903: "TerraMow is stuck"}


@dataclass
class PendingCommand:
    """由 HA 事件循环持有一次请求；时间用于排除旧事件作为拒绝原因。"""

    future: asyncio.Future[dict[str, Any]]
    sent_at: float
    sent_utc: datetime


class TerraMowFeedback:
    """管理一个设备的回复匹配与诊断状态，所有更新都在 HA 事件循环执行。"""

    def __init__(self, mower: TerraMowLawnMowerEntity) -> None:
        self.mower = mower
        self.signal = f"terramow_{mower.host}_feedback"
        self.latest_event: dict[str, Any] | None = None
        # None 表示尚未收到故障信息；空字典表示设备已明确报告没有故障。
        self.active_errors: dict[int, dict[str, Any]] | None = None
        self._pending: dict[tuple[int, int], PendingCommand] = {}
        self._last_live_event: tuple[float, int] | None = None
        self._history_time: datetime | None = None
        self._command_lock = asyncio.Lock()

    def register_callbacks(self) -> None:
        """在 MQTT 线程启动前注册，确保 retained 状态不会先于处理入口到达。"""
        for dp_id in (103, 104, 105, 106):
            self.mower.register_callback(dp_id, partial(self.on_reply, dp_id=dp_id))
        for dp_id in (114, 123):
            self.mower.register_callback(dp_id, partial(self.on_event, dp_id=dp_id))
        self.mower.register_callback(115, self.on_error)
        self.mower.register_callback(116, self.on_error_list)

    async def async_send_command(self, dp_id: int, command: dict) -> None:
        """发送控制并等待同 DP、同序号的回复；拒绝、掉线和超时都向调用方报错。"""
        # 不同时等待多条控制，避免把旁路事件误关联到另一个未完成请求。
        if self._command_lock.locked():
            raise ServiceValidationError(
                "TerraMow is still confirming the previous command"
            )
        async with self._command_lock:
            await self._send_and_wait(dp_id, command)

    async def _send_and_wait(self, dp_id: int, command: dict) -> None:
        """在控制锁内创建等待者、发送命令并释放等待资源。"""
        if not self.mower._can_accept_command():
            raise ServiceValidationError(
                "TerraMow control requests must be at least one second apart"
            )
        client = self.mower.mqtt_client
        if client is None or not client.is_connected():
            raise HomeAssistantError("TerraMow is not connected to MQTT")

        command = {**command, "seq": self.mower.get_cmd_seq()}
        key = (dp_id, command["seq"])
        pending = PendingCommand(
            self.mower.hass.loop.create_future(), time.monotonic(), dt_util.utcnow()
        )
        # 先登记再发布，避免非常快的设备回复找不到等待者。
        self._pending[key] = pending
        try:
            info = self.mower.publish_data_point(dp_id, command)
            # 发布入口仍可能因连接被清理而返回空值，不能将其当作已发送。
            if info is None:
                raise HomeAssistantError("TerraMow MQTT client is not initialized")
            if info.rc != 0:
                raise HomeAssistantError(f"TerraMow MQTT publish failed (rc={info.rc})")
            try:
                reply = await asyncio.wait_for(pending.future, COMMAND_REPLY_TIMEOUT)
            except TimeoutError as err:
                # 超时不能证明成功或失败，也不能重发可能已经被执行的启动命令。
                raise HomeAssistantError(
                    "TerraMow command was sent, but the robot did not confirm its result"
                ) from err
            if reply.get("ret", 0) != 0:
                reason = ""
                event = self._last_live_event
                if event is not None and event[0] >= pending.sent_at:
                    code = event[1]
                    reason = f"; event={code}: {EVENT_DESCRIPTIONS.get(code, 'Unknown event')}"
                raise HomeAssistantError(
                    f"TerraMow rejected command {dp_id} (ret={reply['ret']}{reason})"
                )
        finally:
            self._pending.pop(key, None)
            if not pending.future.done():
                pending.future.cancel()

    @staticmethod
    def _decode(payload: str) -> dict[str, Any] | None:
        """只接受对象类型 JSON，不在错误日志中复制设备原始数据。"""
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            _LOGGER.warning("Invalid TerraMow feedback JSON")
            return None
        return data if isinstance(data, dict) else None

    async def on_reply(self, payload: str, *, dp_id: int) -> None:
        """晚到、重复或其他请求的回复不能完成当前请求。"""
        data = self._decode(payload)
        if (
            data is None
            or type(data.get("seq")) is not int
            or type(data.get("ret", 0)) is not int
        ):
            return
        # protobuf JSON 可能省略默认值 ret=0，不能把这种成功回复判成超时。
        pending = self._pending.get((dp_id, data["seq"]))
        if pending is not None and not pending.future.done():
            _LOGGER.info(
                "TerraMow command reply: dp=%d seq=%d ret=%d",
                dp_id,
                data["seq"],
                data.get("ret", 0),
            )
            pending.future.set_result(data)

    @staticmethod
    def _event_time(value: object) -> datetime | None:
        """设备事件时间须含时区，避免混用本地时间或畸形时间导致比较失败。"""
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        return parsed if parsed is not None and parsed.tzinfo is not None else None

    async def on_event(
        self, payload: str, retained: bool = False, *, dp_id: int
    ) -> None:
        """历史基线与实时通知独立保存，防止历史重放覆盖当前拒绝原因。"""
        data = self._decode(payload)
        if data is None:
            return
        old = self.latest_event
        event_time: datetime | None = None
        event: dict[str, Any]
        if dp_id == 114:
            code = data.get("int_value")
            if type(code) is not int or (retained and old is not None):
                return
            event = {
                "code": code,
                "time": None if retained else dt_util.utcnow().isoformat(),
                "source": 114,
            }
        else:
            items = data.get("event_list", [])
            if not isinstance(items, list):
                return
            # 保留已校验的时间，排序和后续比较都复用它，避免再次解析得到空值。
            events: list[tuple[datetime, dict[str, Any]]] = []
            for item in items:
                if not isinstance(item, dict) or type(item.get("code")) is not int:
                    continue
                parsed_time = self._event_time(item.get("time"))
                if parsed_time is not None:
                    events.append((parsed_time, item))
            if not events:
                return
            event_time, latest = max(events, key=lambda entry: entry[0])
            event = {**latest, "source": 123}
            if self._history_time is not None and event_time <= self._history_time:
                return
            self._history_time = event_time
            # 114 的时间是本机接收时间；允许短暂传输延迟后由 123 补齐设备时间。
            if old is not None and old["source"] == 114:
                live_time = self._event_time(old.get("time"))
                if live_time is not None:
                    tolerance = timedelta(
                        seconds=2 if old["code"] == event["code"] else 0
                    )
                    if event_time < live_time - tolerance:
                        return
        event["description"] = EVENT_DESCRIPTIONS.get(event["code"], "Unknown event")
        if not retained:
            if dp_id == 114 or (
                event_time is not None
                and any(event_time >= p.sent_utc for p in self._pending.values())
            ):
                # 历史队列的接收时间不代表其中事件刚刚发生。
                self._last_live_event = (time.monotonic(), event["code"])
        if event != old:
            self.latest_event = event
            self._notify()

    async def on_error(self, payload: str, retained: bool = False) -> None:
        """处理实时故障；忽略 retained 单条旧故障，以 116 快照恢复当前状态。"""
        data = self._decode(payload)
        if (
            retained
            or data is None
            or type(data.get("int_value")) is not int
            or data["int_value"] <= 0
        ):
            return
        code = data["int_value"]
        if self.active_errors is None:
            self.active_errors = {}
        self.active_errors[code] = {
            "code": code,
            "time": dt_util.utcnow().isoformat(),
            "description": FAULT_DESCRIPTIONS.get(code, "Unknown fault"),
        }
        self._notify()

    async def on_error_list(self, payload: str) -> None:
        """当前故障集合是权威快照；清空时解除故障，不从事件历史反推故障。"""
        data = self._decode(payload)
        if data is None:
            return
        items = data.get("error_list", [])
        if not isinstance(items, list) or any(
            not isinstance(e, dict) or type(e.get("code")) is not int or e["code"] <= 0
            for e in items
        ):
            return
        self.active_errors = {
            e["code"]: {
                "code": e["code"],
                "time": e.get("time"),
                "description": FAULT_DESCRIPTIONS.get(e["code"], "Unknown fault"),
            }
            for e in items
        }
        self._notify()

    def _notify(self) -> None:
        """让割草机状态与诊断传感器在同一轮设备反馈后更新。"""
        self.mower.update_activity_from_state()
        async_dispatcher_send(self.mower.hass, self.signal)

    @callback
    def disconnected(self) -> None:
        """掉线或卸载时及时结束等待，不把旧连接的回复留给重连后的请求。"""
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_exception(
                    HomeAssistantError(
                        "TerraMow disconnected before confirming the command"
                    )
                )
