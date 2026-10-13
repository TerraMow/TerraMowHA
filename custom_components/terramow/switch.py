"""TerraMow 修剪计划开关实体。"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, TerraMowBasicData
from .schedule import WEEK_DAYS


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """为设备添加全局修剪计划开关。"""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [TerraMowScheduleSwitch(basic_data, hass)]
        + [TerraMowWeekdayScheduleSwitch(basic_data, hass, day) for day in WEEK_DAYS]
    )


class TerraMowScheduleSwitch(SwitchEntity):
    """开表示启用全部计划，关表示暂停全部计划，状态取自设备回复。"""

    _attr_has_entity_name = True
    _attr_translation_key = "schedule"
    _attr_icon = "mdi:calendar-clock"
    _attr_should_poll = False

    def __init__(self, basic_data: TerraMowBasicData, hass: HomeAssistant) -> None:
        self.basic_data = basic_data
        self.hass = hass

    async def async_added_to_hass(self) -> None:
        """监听连接、能力和计划回复，移除实体时同步撤销监听。"""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"terramow_{self.basic_data.host}_schedule",
                self.async_write_ha_state,
            )
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)}
        )

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.schedule"

    @property
    def available(self) -> bool:
        mower = self.basic_data.lawn_mower
        return mower is not None and mower.schedule.available

    @property
    def is_on(self) -> bool | None:
        mower = self.basic_data.lawn_mower
        return mower.schedule.enabled if mower is not None else None

    async def async_turn_on(self, **kwargs: object) -> None:
        """启用全部计划，等待设备确认并回读实际开关值。"""
        await self.basic_data.lawn_mower.schedule.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """暂停全部计划，等待设备确认并回读实际开关值。"""
        await self.basic_data.lawn_mower.schedule.async_set_enabled(False)


class TerraMowWeekdayScheduleSwitch(TerraMowScheduleSwitch):
    """单日开表示允许当天的时间段预约，关表示禁止当天预约。"""

    _attr_icon = "mdi:calendar-week"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, basic_data: TerraMowBasicData, hass: HomeAssistant, day: str
    ) -> None:
        super().__init__(basic_data, hass)
        self.day = day
        self._attr_translation_key = f"schedule_{day}"

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.schedule_{self.day}"

    @property
    def available(self) -> bool:
        mower = self.basic_data.lawn_mower
        return mower is not None and mower.schedule.weekday_available

    @property
    def is_on(self) -> bool | None:
        mower = self.basic_data.lawn_mower
        return mower.schedule.weekday_enabled(self.day) if mower is not None else None

    async def async_turn_on(self, **kwargs: object) -> None:
        """解除该日禁用，设备确认并回读后才更新状态。"""
        await self.basic_data.lawn_mower.schedule.async_set_weekday_enabled(
            self.day, True
        )

    async def async_turn_off(self, **kwargs: object) -> None:
        """仅禁用该日，不改动总开关或其它星期设置。"""
        await self.basic_data.lawn_mower.schedule.async_set_weekday_enabled(
            self.day, False
        )
