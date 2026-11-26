"""aiomqtt connection task: connect, dispatch, reconnect and clean shutdown."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import aiomqtt
import pytest
from homeassistant.components.lawn_mower.const import LawnMowerActivity
from homeassistant.core import HomeAssistant

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.lawn_mower import (
    MQTT_ERR_NO_CONN,
    MQTT_ERR_SUCCESS,
    MqttClient,
    MqttMessage,
    TerraMowLawnMowerEntity,
)

LOST = object()  # queued into FakeClient.messages to drop the connection


class FakeClient:
    """Stands in for aiomqtt.Client; one instance per connection attempt."""

    # Per attempt: an exception to raise on connect, or None to connect.
    connect_results: list[BaseException | None] = []
    instances: list["FakeClient"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.subscribed: list[str] = []
        self.published: list[tuple[str, str]] = []
        self.queue: asyncio.Queue = asyncio.Queue()
        self.exited = False
        FakeClient.instances.append(self)

    async def __aenter__(self) -> "FakeClient":
        result = (
            FakeClient.connect_results.pop(0) if FakeClient.connect_results else None
        )
        if result is not None:
            raise result
        return self

    async def __aexit__(self, *_exc) -> None:
        self.exited = True

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscribed.append(topic)

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        self.published.append((topic, payload))

    @property
    def messages(self):
        async def iterate():
            while True:
                item = await self.queue.get()
                if item is LOST:
                    raise aiomqtt.MqttError("Disconnected during message iteration")
                if item is None:
                    return
                yield item

        return iterate()


def _message(topic: str, payload: bytes, retain: bool = False) -> SimpleNamespace:
    return SimpleNamespace(topic=aiomqtt.Topic(topic), payload=payload, retain=retain)


@pytest.fixture
def fake_client():
    FakeClient.connect_results = []
    FakeClient.instances = []
    with patch(
        "custom_components.terramow.lawn_mower.aiomqtt.Client", FakeClient
    ) as client:
        yield client


@pytest.fixture
def no_backoff():
    """Make reconnect waits instant while recording the requested delays."""
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def sleep(delay: float) -> None:
        # The patch replaces asyncio.sleep everywhere; only record the
        # reconnect waits, not the zero-length yields of the test itself.
        if delay:
            delays.append(delay)
        await real_sleep(0)

    with patch("custom_components.terramow.lawn_mower.asyncio.sleep", sleep):
        yield delays


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.40", "secret"), hass)
    entity.schedule_update_ha_state = MagicMock()
    return entity


async def _settle(hass: HomeAssistant) -> None:
    for _ in range(5):
        await asyncio.sleep(0)
    await hass.async_block_till_done()


async def test_connect_subscribes_and_dispatches_messages(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, fake_client
) -> None:
    received: list[tuple] = []

    async def on_dp(payload: str, *args) -> None:
        received.append((payload, *args))

    mower.register_callback(42, on_dp)
    mower.register_callback(114, on_dp)
    mower.start_mqtt_client()
    await _settle(hass)

    client = FakeClient.instances[0]
    assert client.kwargs["hostname"] == "192.0.2.40"
    assert client.kwargs["username"] == "terramow"
    assert client.kwargs["password"] == "secret"
    assert mower.mqtt_connected
    assert mower.mqtt_client.is_connected()
    assert "data_point/122/robot" in client.subscribed
    assert "data_point/200/robot" in client.subscribed
    # The session is primed: compatibility info and the schedule are requested.
    published = [topic for topic, _ in client.published]
    assert "data_point/127/app" in published
    assert "data_point/122/app" in published

    client.queue.put_nowait(_message("data_point/42/robot", b'{"a": 1}'))
    client.queue.put_nowait(_message("data_point/114/robot", b'{"b": 2}', True))
    await _settle(hass)
    assert received == [('{"a": 1}',), ('{"b": 2}', True)]

    await mower.async_will_remove_from_hass()
    assert client.exited
    assert mower._mqtt_task is None
    assert not mower.mqtt_connected
    assert not mower.mqtt_client.is_connected()


async def test_connect_failures_back_off_then_recover(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, fake_client, no_backoff
) -> None:
    FakeClient.connect_results = [OSError("down"), OSError("down"), None]
    mower.start_mqtt_client()
    await _settle(hass)

    assert len(FakeClient.instances) == 3
    assert no_backoff[:2] == [5, 10]
    assert mower.mqtt_connected
    assert mower.activity == LawnMowerActivity.DOCKED

    await mower.async_will_remove_from_hass()


async def test_failure_sets_error_activity(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, fake_client
) -> None:
    # Real backoff: the task waits after the failed attempt until removal.
    FakeClient.connect_results = [aiomqtt.MqttError("refused")]
    mower.start_mqtt_client()
    await _settle(hass)

    assert mower.activity == LawnMowerActivity.ERROR
    assert not mower.mqtt_connected

    await mower.async_will_remove_from_hass()


async def test_lost_connection_reconnects(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, fake_client, no_backoff
) -> None:
    mower.start_mqtt_client()
    await _settle(hass)
    first = FakeClient.instances[0]

    first.queue.put_nowait(LOST)
    await _settle(hass)

    assert first.exited
    assert len(FakeClient.instances) == 2
    assert no_backoff == [5]
    assert mower.mqtt_connected
    assert mower.mqtt_client.is_connected()

    await mower.async_will_remove_from_hass()


async def test_broker_closing_the_session_reconnects(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, fake_client, no_backoff
) -> None:
    mower.start_mqtt_client()
    await _settle(hass)

    FakeClient.instances[0].queue.put_nowait(None)  # stream ends without error
    await _settle(hass)

    assert len(FakeClient.instances) == 2
    assert no_backoff == [5]
    assert mower.mqtt_connected

    await mower.async_will_remove_from_hass()


async def test_unload_while_reconnecting_stops_the_task(
    hass: HomeAssistant, mower: TerraMowLawnMowerEntity, fake_client
) -> None:
    FakeClient.connect_results = [OSError("down")]
    mower.start_mqtt_client()
    await asyncio.sleep(0)
    task = mower._mqtt_task

    await mower.async_will_remove_from_hass()

    assert task is not None and task.done()
    assert len(FakeClient.instances) == 1


def test_message_normalizes_aiomqtt_payloads() -> None:
    raw = MqttMessage.from_aiomqtt(_message("data_point/1/robot", bytearray(b"x")))
    assert (raw.topic, raw.payload, raw.retain) == ("data_point/1/robot", b"x", False)
    assert MqttMessage.from_aiomqtt(_message("t", None)).payload == b""
    assert MqttMessage.from_aiomqtt(_message("t", 7)).payload == b"7"


async def test_facade_without_connection_reports_no_conn(hass: HomeAssistant) -> None:
    facade = MqttClient(hass)
    assert not facade.is_connected()
    assert facade.publish("t", "{}").rc == MQTT_ERR_NO_CONN
    assert facade.subscribe("t").rc == MQTT_ERR_NO_CONN


async def test_facade_publishes_from_a_worker_thread(hass: HomeAssistant) -> None:
    client = FakeClient()
    facade = MqttClient(hass)
    facade.attach(client)

    result = await hass.async_add_executor_job(facade.publish, "t", '{"x": 1}')
    await _settle(hass)

    assert result.rc == MQTT_ERR_SUCCESS
    assert client.published == [("t", '{"x": 1}')]


async def test_facade_logs_a_failed_operation(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    client = MagicMock()

    async def fail(*_args, **_kwargs) -> None:
        raise aiomqtt.MqttError("gone")

    client.publish = fail
    facade = MqttClient(hass)
    facade.attach(client)

    assert facade.publish("data_point/103/app", json.dumps({})).rc == MQTT_ERR_SUCCESS
    await hass.async_block_till_done()

    assert "MQTT operation on data_point/103/app failed" in caplog.text
