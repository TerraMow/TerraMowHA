"""Blade and base-station counter resets, confirmed by the mower's report."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.button import (
    TerraMowResetBaseStationButton,
    TerraMowResetBladeButton,
    async_setup_entry,
)
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.95", ""), hass)
    entity.schedule_update_ha_state = MagicMock()
    entity.mqtt_connected = True
    entity.mqtt_client = MagicMock()
    entity.mqtt_client.is_connected.return_value = True
    entity.register_all_callbacks()
    # By default the mower answers a reset by reporting the counter as zero.
    entity.report_after_reset = 0

    def publish(topic: str, payload: str) -> SimpleNamespace:
        dp_id = int(topic.split("/")[1])
        handler = {125: entity.on_base_station_time, 126: entity.on_blade_time}
        if entity.report_after_reset is not None:
            hass.async_create_task(
                handler[dp_id](json.dumps({"int_value": entity.report_after_reset}))
            )
        return SimpleNamespace(rc=0)

    entity.mqtt_client.publish.side_effect = publish
    return entity


def _sent(mower: TerraMowLawnMowerEntity) -> list[tuple[str, dict]]:
    return [
        (call.args[0], json.loads(call.args[1]))
        for call in mower.mqtt_client.publish.call_args_list
    ]


@pytest.fixture
def short_timeout():
    with patch("custom_components.terramow.feedback.COMMAND_REPLY_TIMEOUT", 0.01):
        yield


async def test_buttons_are_registered(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    blade, station = add_entities.call_args.args[0]
    stable_id = mower.basic_data.stable_id
    assert isinstance(blade, TerraMowResetBladeButton)
    assert blade.unique_id == f"lawn_mower.terramow@{stable_id}.reset_blade_time"
    assert blade.translation_key == "reset_blade_time"
    assert isinstance(station, TerraMowResetBaseStationButton)
    assert station.unique_id == (
        f"lawn_mower.terramow@{stable_id}.reset_base_station_time"
    )
    assert station.translation_key == "reset_base_station_time"
    assert blade.entity_category is EntityCategory.CONFIG
    assert blade.device_info["identifiers"] == {("TerraMowLawnMower", stable_id)}


@pytest.mark.parametrize(
    ("button_class", "dp_id", "attribute"),
    [
        (TerraMowResetBladeButton, 126, "_blade_time"),
        (TerraMowResetBaseStationButton, 125, "_base_station_time"),
    ],
)
async def test_press_resets_and_waits_for_the_zero_report(
    hass: HomeAssistant,
    mower: TerraMowLawnMowerEntity,
    button_class,
    dp_id: int,
    attribute: str,
) -> None:
    button = button_class(mower.basic_data, hass)

    await button.async_press()

    assert _sent(mower) == [(f"data_point/{dp_id}/app", {"int_value": 0})]
    assert getattr(mower, attribute) == {"int_value": 0}
    assert mower._counter_reset_waiters == {}


async def test_reset_is_callable_from_code(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    await mower.async_reset_counter(126)
    assert _sent(mower) == [("data_point/126/app", {"int_value": 0})]


@pytest.mark.parametrize("report", [None, 120])
async def test_reset_without_a_zero_report_fails(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, short_timeout, report
) -> None:
    # No report at all, or the counter still reporting usage.
    mower.report_after_reset = report

    with pytest.raises(HomeAssistantError) as err:
        await mower.async_reset_blade_time()

    assert err.value.translation_key == "reset_not_confirmed"
    assert mower._counter_reset_waiters == {}


async def test_reset_while_disconnected_fails_without_sending(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    mower.mqtt_client.is_connected.return_value = False

    with pytest.raises(HomeAssistantError) as err:
        await mower.async_reset_base_station_time()

    assert err.value.translation_key == "not_connected"
    mower.mqtt_client.publish.assert_not_called()


async def test_reset_without_a_client_fails(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    mower.mqtt_client = None

    with pytest.raises(HomeAssistantError) as err:
        await mower.async_reset_blade_time()

    assert err.value.translation_key == "not_connected"


async def test_a_failed_publish_fails(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    mower.mqtt_client.publish.side_effect = None
    mower.mqtt_client.publish.return_value = SimpleNamespace(rc=4)

    with pytest.raises(HomeAssistantError) as err:
        await mower.async_reset_blade_time()

    assert err.value.translation_key == "not_connected"
    assert mower._counter_reset_waiters == {}


async def test_reports_without_a_pending_reset_are_stored_only(
    mower: TerraMowLawnMowerEntity,
) -> None:
    await mower.on_blade_time('{"int_value": 0}')
    await mower.on_base_station_time('{"int_value": 30}')
    await mower.on_blade_time("not json")

    assert mower._blade_time == {"int_value": 0}
    assert mower._base_station_time == {"int_value": 30}


async def test_availability_follows_the_connection(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    button = TerraMowResetBladeButton(mower.basic_data, hass)
    button.entity_id = "button.terramow_reset_blade_time"
    button.async_write_ha_state = callback(MagicMock())
    await button.async_added_to_hass()
    assert button.available

    mower.mqtt_connected = False
    async_dispatcher_send(hass, f"terramow_{mower.host}_map_status")
    await hass.async_block_till_done()

    assert not button.available
    button.async_write_ha_state.assert_called()

    mower.basic_data.lawn_mower = None
    assert not button.available
