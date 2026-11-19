"""读取并控制割草机的全局修剪计划开关。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send

if TYPE_CHECKING:
    from .lawn_mower import TerraMowLawnMowerEntity

from .schedule_history import CalendarMetadata, OneTimeScheduleHistory
from .schedule_model import GLOBAL_SCHEDULE_V2, GlobalTimeSlot

_LOGGER = logging.getLogger(__name__)

SCHEDULE_DP = 122
SCHEDULE_GET = "SCHEDULE_CMD_TYPE_GET"
SCHEDULE_ADD = "SCHEDULE_CMD_TYPE_ADD"
SCHEDULE_MODIFY = "SCHEDULE_CMD_TYPE_MODIFY"
SCHEDULE_DELETE = "SCHEDULE_CMD_TYPE_DELETE"
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
        self.items: dict[int, dict[str, Any]] | None = None
        self.history = OneTimeScheduleHistory(mower.hass, mower.basic_data.stable_id)
        self._editing = False
        self._lock = asyncio.Lock()
        self._pending: tuple[int, str, asyncio.Future[dict[str, Any]]] | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._refresh_pending = False

    @property
    def available(self) -> bool:
        """Allow DP122 requests while connected; the calendar needs a valid snapshot."""
        return self.mower.mqtt_connected

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
        self.items = None
        self.disabled_week_days = None
        self.schedule_mode = None
        # 让等待中的任务收到断线异常并自行结束，避免取消后留下未读取的 Future 异常。
        self._refresh_pending = False
        self._refresh_task = None
        if self._pending is not None:
            future = self._pending[2]
            if not future.done():
                future.set_exception(HomeAssistantError("TerraMow disconnected"))
        async_dispatcher_send(self.mower.hass, self.signal)

    @callback
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
        raw_items = schedule_list.get("items", [])
        new_items: dict[int, dict[str, Any]] | None = {}
        if not isinstance(raw_items, list):
            new_items = None
        else:
            for item in raw_items:
                if not isinstance(item, dict):
                    new_items = None
                    break
                item_id = item.get("id", 0)
                if (
                    type(item_id) is not int
                    or not 0 <= item_id <= 0x7FFFFFFF
                    or item_id in new_items
                ):
                    new_items = None
                    break
                try:
                    if item.get("schedule_type") == GLOBAL_SCHEDULE_V2:
                        GlobalTimeSlot.from_payload(item.get("global_schedule_v2"))
                except ValueError:
                    new_items = None
                    break
                new_items[item_id] = deepcopy(item)
        # A malformed list must not replace the last successfully read snapshot.
        if new_items is None:
            return False
        if new_mode == SCHEDULE_MODE_TIME_SLOT and new_days is not None:
            self.history.sync(new_items, new_enabled, new_days)
        if (
            self.items != new_items
            or self.enabled is not new_enabled
            or self.disabled_week_days != new_days
            or self.schedule_mode != new_mode
        ):
            self.items = new_items
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
            await self.history.async_load()
            if not self.available:
                return
        pending = self._pending
        matched = (
            pending is not None
            and (seq, cmd_type) == pending[:2]
            and not pending[2].done()
        )
        if (
            code == 0
            and cmd_type == SCHEDULE_GET
            and not self._editing
            and (pending is None or matched)
        ):
            self._update_from_list(reply.get("schedule_list"))
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
        await self.history.async_load()
        if not self.available or not client.is_connected():
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
                raise HomeAssistantError(
                    "TerraMow did not report a valid schedule list"
                )

    async def async_set_enabled(self, enabled: bool) -> None:
        """等待设置成功，再重新读取，避免把发送成功误当成状态生效。"""
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

    @property
    def calendar_available(self) -> bool:
        """Calendar data is usable only after a valid GET in time-slot mode."""
        return (
            self.available
            and self.items is not None
            and self.schedule_mode == SCHEDULE_MODE_TIME_SLOT
            and self.disabled_week_days is not None
        )

    async def _read_calendar(self) -> dict[int, dict[str, Any]]:
        reply = await self._send(SCHEDULE_GET)
        if (
            not self._update_from_list(reply.get("schedule_list"))
            or not self.calendar_available
        ):
            raise HomeAssistantError(
                "TerraMow did not report a valid time-slot schedule list"
            )
        return deepcopy(self.items)

    @staticmethod
    def _global_item(items: dict[int, dict[str, Any]], item_id: int) -> dict[str, Any]:
        item = items.get(item_id)
        if item is None or item.get("schedule_type") != GLOBAL_SCHEDULE_V2:
            raise ServiceValidationError(
                "Global schedule no longer exists; refresh the calendar"
            )
        return item

    async def async_edit_global(
        self,
        cmd_type: str,
        item_id: int | None = None,
        build_slot: Callable[[GlobalTimeSlot | None], GlobalTimeSlot] | None = None,
        build_metadata: Callable[[int, GlobalTimeSlot], CalendarMetadata] | None = None,
    ) -> int:
        """Serialize baseline GET, edit ACK and verification GET with the switches.

        ADD has no returned ID. Only one new ID with the expected content is
        accepted; ambiguous concurrent changes are reported as a failure.
        """
        if cmd_type not in (SCHEDULE_ADD, SCHEDULE_MODIFY, SCHEDULE_DELETE):
            raise ServiceValidationError("Invalid global schedule edit")
        async with self._lock:
            before = await self._read_calendar()
            original = None
            if cmd_type != SCHEDULE_ADD:
                original = self._global_item(before, item_id)
            expected = None
            params: dict[str, Any]
            if cmd_type == SCHEDULE_DELETE:
                params = {"delete_param": {"id": item_id}}
            else:
                current = (
                    GlobalTimeSlot.from_payload(original["global_schedule_v2"])
                    if original
                    else None
                )
                if build_slot is None:
                    raise ServiceValidationError("Missing global schedule content")
                expected = build_slot(current)
                if expected == current and build_metadata is not None:
                    # A fresh GET confirmed the device fields. Only HA-local
                    # text/display fields changed; do not re-arm a run-once item.
                    self._editing = True
                    try:
                        await self.history.async_set_metadata(
                            item_id, build_metadata(item_id, expected)
                        )
                        async_dispatcher_send(self.mower.hass, self.signal)
                    finally:
                        self._editing = False
                    return item_id
                # Preserve fields introduced by newer firmware when editing.
                payload = deepcopy(original["global_schedule_v2"]) if original else {}
                had_run_once = "run_once" in payload.get("basic_config", {})
                had_repeat = "repeat_until_end_time" in payload
                payload.setdefault("basic_config", {}).update(
                    expected.as_payload()["basic_config"]
                )
                payload["repeat_until_end_time"] = expected.repeat_until_end_time
                # Omit optional default fields unless already reported by the
                # device. Requested non-default values still require ACK/readback.
                if not expected.run_once and not had_run_once:
                    payload["basic_config"].pop("run_once", None)
                if not expected.repeat_until_end_time and not had_repeat:
                    payload.pop("repeat_until_end_time", None)
                edit = {
                    "schedule_type": GLOBAL_SCHEDULE_V2,
                    "global_schedule_v2": payload,
                }
                if original is not None:
                    edit["id"] = item_id
                params = {
                    "add_param" if cmd_type == SCHEDULE_ADD else "modify_param": edit
                }
            if not self.mower._can_accept_command():
                raise ServiceValidationError(
                    "TerraMow control requests must be at least one second apart"
                )
            self._editing = True
            try:
                await self._send(cmd_type, params)
                # Publish valid device state even when the edit's verification fails.
                after = await self._read_calendar()
                if cmd_type == SCHEDULE_DELETE:
                    if item_id in after:
                        raise HomeAssistantError(
                            "TerraMow readback still contains the deleted schedule"
                        )
                    await self.history.async_flush()
                    return item_id
                if cmd_type == SCHEDULE_MODIFY:
                    actual = after.get(item_id)
                    if (
                        actual is None
                        or actual.get("schedule_type") != GLOBAL_SCHEDULE_V2
                        or GlobalTimeSlot.from_payload(actual.get("global_schedule_v2"))
                        != expected
                    ):
                        raise HomeAssistantError(
                            "TerraMow readback differs from the requested schedule"
                        )
                    if build_metadata is not None:
                        await self.history.async_set_metadata(
                            item_id, build_metadata(item_id, expected)
                        )
                        async_dispatcher_send(self.mower.hass, self.signal)
                    return item_id
                new_ids = after.keys() - before.keys()
                if len(new_ids) != 1:
                    raise HomeAssistantError(
                        "TerraMow readback cannot unambiguously identify the new schedule"
                    )
                new_id = next(iter(new_ids))
                actual = after[new_id]
                if (
                    actual.get("schedule_type") != GLOBAL_SCHEDULE_V2
                    or GlobalTimeSlot.from_payload(actual.get("global_schedule_v2"))
                    != expected
                ):
                    raise HomeAssistantError(
                        "TerraMow readback differs from the requested schedule"
                    )
                if build_metadata is not None:
                    await self.history.async_set_metadata(
                        new_id, build_metadata(new_id, expected)
                    )
                    async_dispatcher_send(self.mower.hass, self.signal)
                return new_id
            finally:
                self._editing = False
