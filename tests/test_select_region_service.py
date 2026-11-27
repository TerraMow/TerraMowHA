"""terramow.start_select_region: mow several zones in one confirmed command."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity

ENTITY_ID = "lawn_mower.terramow"
MAP_INFO = {
    "id": 1,
    "regions": [
        {"id": 100, "sub_regions": [{"id": 1, "name": "Front"}, {"id": 2}]},
        {"id": 200, "sub_regions": [{"id": 3, "name": "Back"}]},
    ],
}


@pytest.fixture
async def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    assert await async_setup_component(hass, DOMAIN, {})
    basic_data = TerraMowBasicData("192.0.2.90", "")
    entity = TerraMowLawnMowerEntity(basic_data, hass)
    entity.entity_id = ENTITY_ID
    entity.schedule_update_ha_state = MagicMock()
    entity.mqtt_client = MagicMock()
    entity.mqtt_client.is_connected.return_value = True
    entity._last_control_time = -100
    entity.register_all_callbacks()
    entity._map_info = dict(MAP_INFO)
    entity.reply_ret = 0

    def publish(topic: str, payload: str) -> SimpleNamespace:
        data = json.loads(payload)
        hass.async_create_task(
            entity.feedback.on_reply(
                json.dumps({"seq": data["seq"], "ret": entity.reply_ret}), dp_id=103
            )
        )
        return SimpleNamespace(rc=0)

    entity.mqtt_client.publish.side_effect = publish
    hass.data.setdefault(DOMAIN, {})["entry"] = basic_data
    return entity


async def _call(hass: HomeAssistant, region_ids, entity_id=ENTITY_ID, **target) -> None:
    data = {"region_ids": region_ids, **target}
    if entity_id is not None:
        data["entity_id"] = entity_id
    await hass.services.async_call(DOMAIN, "start_select_region", data, blocking=True)


def _register_mower(hass: HomeAssistant, area_id: str | None = None) -> str:
    """Register the mower entity on a device (optionally in an area)."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("TerraMowLawnMower", "192.0.2.90")},
    )
    if area_id is not None:
        dr.async_get(hass).async_update_device(device.id, area_id=area_id)
    registered = er.async_get(hass).async_get_or_create(
        "lawn_mower",
        DOMAIN,
        "lawn_mower.terramow@192.0.2.90",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="terramow",
    )
    assert registered.entity_id == ENTITY_ID
    return device.id


def _sent(mower: TerraMowLawnMowerEntity) -> list[tuple[str, dict]]:
    return [
        (call.args[0], json.loads(call.args[1]))
        for call in mower.mqtt_client.publish.call_args_list
    ]


async def test_service_starts_the_listed_zones(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    await _call(hass, [3, "1", 3])

    ((topic, command),) = _sent(mower)
    assert topic == "data_point/103/app"
    assert command["mode"] == "START_MODE_SELECT_REGION_CLEAN"
    # One request for all zones, duplicates dropped, order kept.
    assert command["select_region_clean"] == {"region_ids": [3, 1]}


async def test_service_accepts_a_single_id_and_all_mowers(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    await _call(hass, 2, entity_id="all")

    ((_, command),) = _sent(mower)
    assert command["select_region_clean"] == {"region_ids": [2]}


async def test_unknown_zone_ids_are_rejected_before_sending(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, [1, 9, 7])

    assert err.value.translation_key == "unknown_zones"
    assert err.value.translation_placeholders == {"zone_ids": "7, 9"}
    mower.mqtt_client.publish.assert_not_called()


async def test_a_map_without_zones_is_rejected(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    mower._map_info = {"id": 1, "regions": [{"id": 100}]}

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, [1])

    assert err.value.translation_key == "no_zones"
    mower.mqtt_client.publish.assert_not_called()


async def test_a_rejected_command_raises(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    mower.reply_ret = -3

    with pytest.raises(HomeAssistantError, match="ret=-3"):
        await _call(hass, [1, 2])


async def test_an_unknown_target_is_rejected(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, [1], entity_id="lawn_mower.other")

    assert err.value.translation_key == "mower_not_found"
    mower.mqtt_client.publish.assert_not_called()


async def test_device_target_resolves_to_the_mower(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    device_id = _register_mower(hass)

    await _call(hass, [1], entity_id=None, device_id=device_id)

    ((_, command),) = _sent(mower)
    assert command["select_region_clean"] == {"region_ids": [1]}


async def test_area_target_resolves_to_the_mower(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    area = ar.async_get(hass).async_create("Garden")
    _register_mower(hass, area_id=area.id)

    await _call(hass, [2], entity_id=None, area_id=area.id)

    ((_, command),) = _sent(mower)
    assert command["select_region_clean"] == {"region_ids": [2]}


async def test_a_device_without_a_mower_is_rejected(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    entry = MockConfigEntry(domain="other")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("other", "x")}
    )

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, [1], entity_id=None, device_id=device.id)

    assert err.value.translation_key == "mower_not_found"
    mower.mqtt_client.publish.assert_not_called()


async def test_integer_strings_are_accepted(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    await _call(hass, ["2", " 3 "])

    ((_, command),) = _sent(mower)
    assert command["select_region_clean"] == {"region_ids": [2, 3]}


@pytest.mark.parametrize(
    "region_ids",
    [
        [],
        ["front"],
        [-1],
        ["-1"],
        ["1.0"],
        [True],
        [False],
        [1.9],
        [-0.9],
        [0.0],
        None,
        [[1]],
        [1, 1.5],  # a mixed list with one invalid value sends nothing
    ],
)
async def test_invalid_ids_fail_validation(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, region_ids
) -> None:
    # Depending on the Home Assistant version the schema error surfaces as
    # vol.Invalid or wrapped in a ServiceValidationError.
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await _call(hass, region_ids)

    mower.mqtt_client.publish.assert_not_called()


async def test_zone_zero_is_valid_but_not_from_false_or_floats(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity
) -> None:
    mower._map_info = {"regions": [{"sub_regions": [{"id": 0}, {"id": 1}]}]}

    for invalid in ([False], [-0.9], [0.4]):
        with pytest.raises((vol.Invalid, ServiceValidationError)):
            await _call(hass, invalid)
    mower.mqtt_client.publish.assert_not_called()

    await _call(hass, [0])
    ((_, command),) = _sent(mower)
    assert command["select_region_clean"] == {"region_ids": [0]}


async def test_zone_ids_skip_malformed_map_entries(
    mower: TerraMowLawnMowerEntity,
) -> None:
    mower._map_info = {
        "regions": [
            "not a region",
            {"sub_regions": None},
            {"sub_regions": ["x", {"id": "4"}, {"id": 5}]},
        ]
    }
    assert mower.zone_ids == {5}

    mower._map_info = {}
    assert mower.zone_ids == set()
