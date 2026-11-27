"""TerraMow mower event entity: one event per mower state transition."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, TerraMowBasicData
from .lawn_mower import MissionState, SubMission, TerraMowLawnMowerEntity

EVENT_MOWING_STARTED = "mowing_started"
EVENT_PAUSED = "paused"
EVENT_RETURNING = "returning"
EVENT_DOCKED = "docked"
EVENT_MOWING_COMPLETED = "mowing_completed"
EVENT_ERROR = "error"

EVENT_TYPES = [
    EVENT_MOWING_STARTED,
    EVENT_PAUSED,
    EVENT_RETURNING,
    EVENT_DOCKED,
    EVENT_MOWING_COMPLETED,
    EVENT_ERROR,
]

# Phase reached -> event fired when the mower enters it.
_PHASE_EVENTS = {
    "mowing": EVENT_MOWING_STARTED,
    "paused": EVENT_PAUSED,
    "returning": EVENT_RETURNING,
    "docked": EVENT_DOCKED,
    "error": EVENT_ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the mower event entity."""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([TerraMowMowerEvent(basic_data, hass)])


def mower_phase(mower: TerraMowLawnMowerEntity) -> str:
    """Return the mower's phase from its mission status (dp_107) and faults.

    Mirrors the activity mapping in ``update_activity_from_state``, except that
    a lost MQTT connection is not a phase: only a device fault (``has_error``
    or an active fault from feedback) counts as ``error``.
    """
    if mower.has_error or mower.feedback.active_errors:
        return "error"
    if mower.mission_state == MissionState.MISSION_STATE_RUNNING:
        if mower.mission in mower._get_mow_missions():
            if mower.sub_mission == SubMission.SUB_MISSION_FLEXIBLE_STATION_WAIT:
                return "paused"
            if mower.sub_mission == SubMission.SUB_MISSION_SAVING_MAP:
                return "docked"
            return "mowing"
        if mower.mission in mower._get_recharge_missions():
            return "returning"
        return "docked"
    if mower.mission_state == MissionState.MISSION_STATE_PAUSE:
        return "paused"
    return "docked"


class TerraMowMowerEvent(EventEntity):
    """Fires once per mower state transition, never for replayed state.

    The baseline is taken from the first complete picture of each connection:
    the mission status (dp_107) and the fault snapshot (dp_116). Until both
    have arrived nothing fires, so the retained reports delivered after a
    restart or reconnect only set the baseline instead of replaying events.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "mower_event"
    _attr_event_types = EVENT_TYPES
    _attr_should_poll = False

    def __init__(self, basic_data: TerraMowBasicData, hass: HomeAssistant) -> None:
        self.basic_data = basic_data
        self.hass = hass
        self._phase: str | None = None
        self._completed = False
        self._mission_seen = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.stable_id)}
        )

    @property
    def unique_id(self) -> str:
        return f"lawn_mower.terramow@{self.basic_data.stable_id}.mower_event"

    async def async_added_to_hass(self) -> None:
        """Follow dp_107 reports and fault changes until the entity is removed."""
        await super().async_added_to_hass()
        host = self.basic_data.host
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"terramow_{host}_mission", self._async_mission_updated
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"terramow_{host}_feedback", self._async_feedback_updated
            )
        )

    @callback
    def _async_mission_updated(self) -> None:
        self._mission_seen = True
        self._async_evaluate()

    @callback
    def _async_feedback_updated(self) -> None:
        self._async_evaluate()

    @callback
    def _async_evaluate(self) -> None:
        mower = self.basic_data.lawn_mower
        if mower is None or not mower.mqtt_connected:
            # Disconnected: the next connection sets a fresh baseline.
            self._phase = None
            self._mission_seen = False
            return
        if not self._mission_seen or mower.feedback.snapshot_error_codes is None:
            return

        phase = mower_phase(mower)
        completed = (
            mower.mission_state == MissionState.MISSION_STATE_COMPLETE
            and mower.mission in mower._get_mow_missions()
        )
        if self._phase is None:
            self._phase = phase
            self._completed = completed
            return

        event_type: str | None = None
        if completed and not self._completed:
            event_type = EVENT_MOWING_COMPLETED
        elif phase != self._phase:
            event_type = _PHASE_EVENTS[phase]
        self._phase = phase
        self._completed = completed
        if event_type is not None:
            self._trigger_event(event_type, self._event_attributes(mower))
            self.async_write_ha_state()

    @staticmethod
    def _event_attributes(mower: TerraMowLawnMowerEntity) -> dict[str, Any]:
        """The mission fields and active faults behind the event."""
        reason = mower.back_to_station_reason
        return {
            "mission": mower.mission.value if mower.mission else None,
            "sub_mission": mower.sub_mission.value if mower.sub_mission else None,
            "state": mower.mission_state.value if mower.mission_state else None,
            "back_to_station_reason": reason.value if reason else None,
            "active_faults": sorted((mower.feedback.active_errors or {}).keys()),
        }
