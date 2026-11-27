"""MQTT connection lifecycle against an in-process MQTT 3.1.1 broker.

The broker runs on 127.0.0.1 and can hold back CONNACK and SUBACK, so the
waiting phases of a connection are exercised with the real aiomqtt client
and real sockets: cancellation while awaiting CONNACK, unload while awaiting
SUBACK, connect timeouts, repeated reloads and late worker-thread calls.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import aiomqtt
import pytest
import pytest_socket
from homeassistant.components.lawn_mower.const import LawnMowerActivity
from homeassistant.core import HomeAssistant

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow import mqtt_connection as mqtt_connection_module
from custom_components.terramow.lawn_mower import (
    MQTT_ERR_NO_CONN,
    MQTT_ERR_SUCCESS,
    MqttClient,
    MqttMessage,
    TerraMowLawnMowerEntity,
)
from custom_components.terramow.mqtt_connection import (
    MQTT_SUBSCRIBE_BATCH_SIZE,
    MqttConnection,
    MqttSubscribeError,
)

# --------------------------------------------------------------------------
# A minimal MQTT 3.1.1 broker
# --------------------------------------------------------------------------


def _remaining_length(length: int) -> bytes:
    out = bytearray()
    while True:
        byte, length = length % 128, length // 128
        out.append(byte | (0x80 if length else 0))
        if not length:
            return bytes(out)


class BrokerConnection:
    """One client connection as the broker sees it."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        self.subscribed: list[str] = []
        self.subscribe_packets = 0
        self.published: list[tuple[str, bytes]] = []
        self.disconnect_received = False
        self.closed = asyncio.Event()

    def send(self, topic: str, payload: bytes, retain: bool = False) -> None:
        """Deliver a QoS 0 PUBLISH to the client."""
        name = topic.encode()
        body = len(name).to_bytes(2, "big") + name + payload
        header = 0x30 | (0x01 if retain else 0)
        self.writer.write(bytes([header]) + _remaining_length(len(body)) + body)


class FakeBroker:
    """Accepts MQTT clients; CONNACK and SUBACK can be held back or refused."""

    def __init__(self) -> None:
        self.connack_gate: asyncio.Event | None = None
        self.suback_gate: asyncio.Event | None = None
        self.refuse_topics: set[str] = set()
        self.connections: list[BrokerConnection] = []
        self.timeline: list[tuple[str, str]] = []
        self.port = 0
        self._server: asyncio.Server | None = None
        self._held_replies: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        # Release held-back replies so no handler blocks the shutdown.
        for task in self._held_replies:
            task.cancel()
        await asyncio.gather(*self._held_replies, return_exceptions=True)
        for connection in self.connections:
            connection.writer.close()
        if self._server is not None:
            self._server.close()
            async with asyncio.timeout(5):
                await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        connection = BrokerConnection(writer)
        self.connections.append(connection)
        try:
            while True:
                header = (await reader.readexactly(1))[0]
                length, multiplier = 0, 1
                while True:
                    byte = (await reader.readexactly(1))[0]
                    length += (byte & 0x7F) * multiplier
                    multiplier *= 128
                    if not byte & 0x80:
                        break
                body = await reader.readexactly(length)
                self._packet(connection, header, body)
                await writer.drain()
                if connection.disconnect_received:
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            connection.closed.set()
            writer.close()

    def _reply(
        self,
        connection: BrokerConnection,
        gate: asyncio.Event | None,
        data: bytes,
        event: tuple[str, str] | None = None,
    ) -> None:
        """Send a reply now, or once its gate opens.

        Held-back replies wait in their own task, so the connection keeps
        being read and a client closing it is noticed while a reply is held.
        """

        def send() -> None:
            if not connection.closed.is_set():
                connection.writer.write(data)
                if event is not None:
                    self.timeline.append(event)

        if gate is None or gate.is_set():
            send()
            return

        async def held() -> None:
            await gate.wait()
            send()

        task = asyncio.get_running_loop().create_task(held())
        self._held_replies.add(task)
        task.add_done_callback(self._held_replies.discard)

    def _packet(self, connection: BrokerConnection, header: int, body: bytes) -> None:
        packet_type = header >> 4
        writer = connection.writer
        if packet_type == 1:  # CONNECT
            self._reply(connection, self.connack_gate, bytes([0x20, 0x02, 0x00, 0x00]))
        elif packet_type == 8:  # SUBSCRIBE
            packet_id, index, topics = body[:2], 2, []
            while index < len(body):
                size = int.from_bytes(body[index : index + 2], "big")
                topics.append(body[index + 2 : index + 2 + size].decode())
                index += 3 + size
            connection.subscribed.extend(topics)
            connection.subscribe_packets += 1
            codes = bytes(0x80 if t in self.refuse_topics else 0 for t in topics)
            body_out = packet_id + codes
            self._reply(
                connection,
                self.suback_gate,
                bytes([0x90]) + _remaining_length(len(body_out)) + body_out,
                ("suback", ""),
            )
        elif packet_type == 3:  # PUBLISH
            qos = (header >> 1) & 0x03
            size = int.from_bytes(body[:2], "big")
            topic = body[2 : 2 + size].decode()
            rest = body[2 + size :]
            if qos:
                writer.write(b"\x40\x02" + rest[:2])
                rest = rest[2:]
            connection.published.append((topic, rest))
            self.timeline.append(("publish", topic))
        elif packet_type == 12:  # PINGREQ
            writer.write(b"\xd0\x00")
        elif packet_type == 14:  # DISCONNECT
            connection.disconnect_received = True


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------


@pytest.fixture
def local_sockets():
    """Allow TCP to 127.0.0.1 only, for the in-process broker."""
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(["127.0.0.1"])
    yield
    pytest_socket.disable_socket(allow_unix_socket=True)


@pytest.fixture
async def broker(local_sockets) -> FakeBroker:
    fake = FakeBroker()
    await fake.start()
    with (
        patch("custom_components.terramow.lawn_mower.MQTT_PORT", fake.port),
        # Fast reconnects and short aiomqtt timeouts keep the tests quick.
        patch("custom_components.terramow.lawn_mower.MQTT_RECONNECT_BASE_DELAY", 0.05),
        patch.object(mqtt_connection_module, "MQTT_OPERATION_TIMEOUT", 1.0),
    ):
        yield fake
    await fake.stop()


def _mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    entity = TerraMowLawnMowerEntity(TerraMowBasicData("127.0.0.1", "secret"), hass)
    entity.schedule_update_ha_state = MagicMock()
    return entity


@pytest.fixture
def mower(hass: HomeAssistant) -> TerraMowLawnMowerEntity:
    return _mower(hass)


async def _until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def _stop(mower: TerraMowLawnMowerEntity, budget: float = 5.0) -> None:
    async with asyncio.timeout(budget):
        await mower.async_will_remove_from_hass()


# --------------------------------------------------------------------------
# Connection lifecycle with the real aiomqtt client
# --------------------------------------------------------------------------


async def test_startup_subscribes_in_acknowledged_batches(
    hass: HomeAssistant,
    broker: FakeBroker,
    mower: TerraMowLawnMowerEntity,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    mower.start_mqtt_client()
    await _until(lambda: mower.mqtt_connected)
    await _until(lambda: ("publish", "data_point/122/app") in broker.timeline)

    (connection,) = broker.connections
    topics = mower.subscription_topics()
    # The existing topic set, in order, in a few bounded SUBSCRIBE packets.
    assert connection.subscribed == topics
    assert connection.subscribe_packets == -(-len(topics) // MQTT_SUBSCRIBE_BATCH_SIZE)
    # The session is ready, and requests data, only after the last SUBACK.
    last_suback = max(
        i for i, event in enumerate(broker.timeline) if event[0] == "suback"
    )
    first_publish = min(
        i for i, event in enumerate(broker.timeline) if event[0] == "publish"
    )
    assert last_suback < first_publish
    assert "pending" not in caplog.text

    await _stop(mower)
    assert connection.disconnect_received
    await _until(connection.closed.is_set)
    assert not mower.mqtt_connected


async def test_messages_reach_registered_callbacks(
    hass: HomeAssistant, broker: FakeBroker, mower: TerraMowLawnMowerEntity
) -> None:
    received: list[tuple] = []

    async def on_dp(payload: str, *args) -> None:
        received.append((payload, *args))

    mower.register_callback(42, on_dp)
    mower.register_callback(114, on_dp)
    mower.start_mqtt_client()
    await _until(lambda: mower.mqtt_connected)

    (connection,) = broker.connections
    connection.send("data_point/42/robot", b'{"a": 1}')
    connection.send("data_point/114/robot", b'{"b": 2}', retain=True)
    await _until(lambda: len(received) == 2)
    assert received == [('{"a": 1}',), ('{"b": 2}', True)]

    await _stop(mower)


async def test_cancel_while_awaiting_connack_releases_the_connection(
    hass: HomeAssistant, broker: FakeBroker, mower: TerraMowLawnMowerEntity
) -> None:
    broker.connack_gate = asyncio.Event()  # never set: CONNACK stays pending
    mower.start_mqtt_client()
    await _until(lambda: len(broker.connections) == 1)
    task = mower._mqtt_task

    await _stop(mower, budget=3.0)

    assert task is not None and task.done()
    await _until(broker.connections[0].closed.is_set, timeout=2.0)
    assert not mower.mqtt_connected


async def test_connect_timeout_closes_the_attempt_and_retries(
    hass: HomeAssistant, broker: FakeBroker, mower: TerraMowLawnMowerEntity
) -> None:
    broker.connack_gate = asyncio.Event()
    mower.start_mqtt_client()
    # aiomqtt gives up waiting for CONNACK; the attempt is closed and retried.
    await _until(lambda: len(broker.connections) >= 2)
    await _until(broker.connections[0].closed.is_set, timeout=2.0)
    assert mower.activity == LawnMowerActivity.ERROR

    broker.connack_gate.set()
    await _until(lambda: mower.mqtt_connected)
    await _stop(mower)
    for connection in broker.connections:
        await _until(connection.closed.is_set, timeout=2.0)


async def test_open_budget_bounds_a_stalled_connect(
    hass: HomeAssistant, broker: FakeBroker
) -> None:
    broker.connack_gate = asyncio.Event()
    connection = MqttConnection(
        hostname="127.0.0.1", port=broker.port, username="u", password="p"
    )
    with (
        patch.object(mqtt_connection_module, "MQTT_CONNECT_TIMEOUT", 0.2),
        pytest.raises(TimeoutError),
    ):
        await connection.async_open()

    await _until(broker.connections[0].closed.is_set, timeout=2.0)
    assert not connection.accepting


async def test_unload_while_awaiting_suback(
    hass: HomeAssistant, broker: FakeBroker, mower: TerraMowLawnMowerEntity
) -> None:
    broker.suback_gate = asyncio.Event()  # never set: SUBACK stays pending
    mower.start_mqtt_client()
    await _until(lambda: broker.connections and broker.connections[0].subscribed)

    await _stop(mower, budget=3.0)

    await _until(broker.connections[0].closed.is_set, timeout=2.0)
    assert not mower.mqtt_connected
    assert not mower.mqtt_client.is_connected()


async def test_refused_subscription_fails_the_session(
    hass: HomeAssistant, broker: FakeBroker, mower: TerraMowLawnMowerEntity
) -> None:
    broker.refuse_topics = {"data_point/122/robot"}
    mower.start_mqtt_client()
    await _until(lambda: len(broker.connections) >= 2)

    await _until(broker.connections[0].closed.is_set, timeout=2.0)
    assert not mower.mqtt_connected
    assert mower.activity == LawnMowerActivity.ERROR
    # Nothing was requested on a session that never became ready.
    assert not broker.connections[0].published
    await _stop(mower)


async def test_lost_connection_reconnects(
    hass: HomeAssistant, broker: FakeBroker, mower: TerraMowLawnMowerEntity
) -> None:
    mower.start_mqtt_client()
    await _until(lambda: mower.mqtt_connected)

    broker.connections[0].writer.close()  # the broker drops the client
    await _until(lambda: len(broker.connections) == 2 and mower.mqtt_connected)

    await _stop(mower)


async def test_repeated_reloads_leave_no_connection_behind(
    hass: HomeAssistant, broker: FakeBroker
) -> None:
    for _ in range(5):
        mower = _mower(hass)
        mower.start_mqtt_client()
        await _until(lambda mower=mower: mower.mqtt_connected)
        await _stop(mower)

    assert len(broker.connections) == 5
    for connection in broker.connections:
        await _until(connection.closed.is_set, timeout=2.0)
        assert connection.disconnect_received


async def test_pending_operations_are_cancelled_on_close(
    hass: HomeAssistant, broker: FakeBroker, mower: TerraMowLawnMowerEntity
) -> None:
    mower.start_mqtt_client()
    await _until(lambda: mower.mqtt_connected)
    connection = mower.mqtt_client.connection
    assert connection is not None

    broker.suback_gate = asyncio.Event()  # the next SUBACK never arrives
    assert mower.mqtt_client.subscribe("extra/topic").rc == MQTT_ERR_SUCCESS
    await _until(lambda: "extra/topic" in broker.connections[0].subscribed)
    assert connection._operations

    await _stop(mower)

    assert not connection._operations
    assert mower.mqtt_client.publish("t", "{}").rc == MQTT_ERR_NO_CONN


async def test_worker_thread_submissions(
    hass: HomeAssistant, broker: FakeBroker, mower: TerraMowLawnMowerEntity
) -> None:
    mower.start_mqtt_client()
    await _until(lambda: mower.mqtt_connected)
    facade = mower.mqtt_client

    result = await hass.async_add_executor_job(facade.publish, "from/thread", "{}")
    assert result.rc == MQTT_ERR_SUCCESS
    await _until(lambda: ("publish", "from/thread") in broker.timeline)

    # A submission that reaches the event loop after its connection retired
    # is dropped instead of running on that connection.
    retired = facade.connection
    assert retired is not None
    operation = MagicMock()
    facade.attach(None)
    facade._start_from_thread(retired, operation, "late/topic")
    facade.attach(retired)
    await _stop(mower)
    facade._start_from_thread(retired, operation, "late/topic")
    operation.assert_not_called()
    assert ("publish", "late/topic") not in broker.timeline


# --------------------------------------------------------------------------
# Units without a broker
# --------------------------------------------------------------------------


def _message(topic: str, payload, retain: bool = False) -> SimpleNamespace:
    return SimpleNamespace(topic=aiomqtt.Topic(topic), payload=payload, retain=retain)


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


async def test_failed_operation_is_logged(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    connection = MqttConnection(
        hostname="192.0.2.1", port=1883, username="u", password="p"
    )
    connection._open = True

    async def fail(_client) -> None:
        raise aiomqtt.MqttError("gone")

    assert connection.start_operation(fail, "data_point/103/app")
    await hass.async_block_till_done()
    assert "MQTT operation on data_point/103/app failed" in caplog.text


async def test_subscribe_checks_reason_code_objects() -> None:
    connection = MqttConnection(
        hostname="192.0.2.1", port=1883, username="u", password="p"
    )

    async def subscribe(topics):
        return [SimpleNamespace(value=0), SimpleNamespace(value=0x87)][: len(topics)]

    connection._client.subscribe = subscribe
    with pytest.raises(MqttSubscribeError, match="b"):
        await connection.async_subscribe(["a", "b"])
