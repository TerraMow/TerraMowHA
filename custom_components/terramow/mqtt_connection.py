"""Ownership of one aiomqtt connection: opening, operations and cleanup.

Everything that relies on aiomqtt and paho-mqtt internals lives in this
module. manifest.json pins aiomqtt to the version these code paths are
tested with; review this module before raising that pin.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiomqtt
from homeassistant.util.async_ import create_eager_task

_LOGGER = logging.getLogger(__name__)

# aiomqtt's per-operation timeout: CONNACK, SUBACK and publish completion.
MQTT_OPERATION_TIMEOUT = 5.0
# Opening a connection: paho's TCP connect (5 s by default, in an executor
# thread) plus waiting for CONNACK (MQTT_OPERATION_TIMEOUT), with headroom.
MQTT_CONNECT_TIMEOUT = 12.0
# Closing: draining operations, a graceful DISCONNECT, or waiting out a
# connect attempt that is still in progress.
MQTT_CLOSE_TIMEOUT = 12.0
# Topics per SUBSCRIBE packet when subscribing at session start.
MQTT_SUBSCRIBE_BATCH_SIZE = 50
# SUBACK return codes at or above this value mean the subscription failed.
_SUBACK_FAILURE = 0x80


class MqttSubscribeError(aiomqtt.MqttError):
    """The broker refused one or more subscriptions."""


def _reason_value(code: Any) -> int:
    """SUBACK result as an int (paho 2.x reports ReasonCode objects)."""
    return int(getattr(code, "value", code))


class MqttConnection:
    """Owns a single connection attempt, from opening until it is closed.

    Opening, failures, cancellation, timeouts and unload all end in the same
    close path. Closing is shielded, so a cancellation cannot stop it halfway,
    and every step has a time budget.
    """

    def __init__(
        self,
        *,
        hostname: str,
        port: int,
        username: str,
        password: str,
        keepalive: int = 60,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = aiomqtt.Client(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            keepalive=keepalive,
            timeout=MQTT_OPERATION_TIMEOUT,
            logger=logger,
        )
        self._enter_task: asyncio.Task[Any] | None = None
        self._open = False
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._operations: set[asyncio.Task[None]] = set()

    @property
    def client(self) -> aiomqtt.Client:
        """The aiomqtt client of this connection."""
        return self._client

    @property
    def accepting(self) -> bool:
        """Whether new operations may still start on this connection."""
        return self._open and not self._closing

    async def async_open(self) -> aiomqtt.Client:
        """Connect and wait for CONNACK, or clean up and raise.

        The connect runs in its own task. Cancelling or timing out the caller
        leaves that task running instead of interrupting it, so the close path
        can wait for an executor-thread TCP connect that may still finish, and
        then close whatever socket it opened.
        """
        loop = asyncio.get_running_loop()
        self._enter_task = loop.create_task(self._client.__aenter__())
        try:
            async with asyncio.timeout(MQTT_CONNECT_TIMEOUT):
                await asyncio.shield(self._enter_task)
        except BaseException:
            await self.async_close()
            raise
        self._open = True
        return self._client

    async def async_subscribe(self, topics: list[str]) -> None:
        """Subscribe in bounded batches, awaiting and checking each SUBACK."""
        for start in range(0, len(topics), MQTT_SUBSCRIBE_BATCH_SIZE):
            batch = topics[start : start + MQTT_SUBSCRIBE_BATCH_SIZE]
            codes = await self._client.subscribe([(topic, 0) for topic in batch])
            refused = [
                topic
                for topic, code in zip(batch, codes, strict=False)
                if _reason_value(code) >= _SUBACK_FAILURE
            ]
            if len(codes) != len(batch) or refused:
                raise MqttSubscribeError(
                    f"Broker refused subscriptions: {', '.join(refused) or batch}"
                )

    def start_operation(
        self,
        operation: Callable[[aiomqtt.Client], Awaitable[Any]],
        topic: str,
    ) -> bool:
        """Run a publish or subscribe on this connection and track it.

        Must be called on the event loop. Returns False when the connection
        no longer accepts operations.
        """
        if not self.accepting:
            return False

        async def run() -> None:
            try:
                await operation(self._client)
            except aiomqtt.MqttError as err:
                _LOGGER.error("MQTT operation on %s failed: %s", topic, err)

        # Eager start hands the packet to paho right away, so operations
        # submitted in order are also sent in order.
        task = create_eager_task(run())
        if not task.done():
            self._operations.add(task)
            task.add_done_callback(self._operations.discard)
        return True

    async def async_close(self) -> None:
        """Close the connection; safe to call repeatedly and from any path."""
        self._closing = True
        if self._close_task is None:
            self._close_task = asyncio.get_running_loop().create_task(self._close())
        # Shielded: cancelling the caller does not interrupt the cleanup.
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        try:
            async with asyncio.timeout(MQTT_CLOSE_TIMEOUT):
                await self._drain_operations()
                enter = self._enter_task
                if not self._open and enter is not None:
                    if not enter.done() and self._tcp_connected():
                        # Only CONNACK is outstanding: the executor connect
                        # has finished, so the attempt can be cancelled.
                        enter.cancel()
                    # A TCP connect still running in the executor thread is
                    # waited out instead: cancelling cannot stop that thread,
                    # which could then open the socket after cleanup.
                    # asyncio.wait neither raises the attempt's error nor its
                    # cancellation, only a cancellation of this close itself.
                    await asyncio.wait({enter})
                    self._open = not enter.cancelled() and enter.exception() is None
                if self._open:
                    # Graceful DISCONNECT; waits for the broker to drop us.
                    await self._client.__aexit__(None, None, None)
        except Exception as err:  # cleanup continues below
            _LOGGER.debug("MQTT connection did not close cleanly: %s", err)
        finally:
            self._open = False
            self._force_close()
            misc = self._client._misc_task  # pinned aiomqtt version
            if misc is not None:
                # Let the cancelled maintenance task finish before returning.
                await asyncio.wait({misc}, timeout=1)

    def _tcp_connected(self) -> bool:
        """Whether paho already holds a socket for this attempt."""
        return self._client._client.socket() is not None

    async def _drain_operations(self) -> None:
        operations = list(self._operations)
        for task in operations:
            task.cancel()
        if operations:
            await asyncio.gather(*operations, return_exceptions=True)

    def _force_close(self) -> None:
        """Release whatever the attempt still holds: task, socket, misc loop."""
        enter = self._enter_task
        if enter is not None and not enter.done():
            _LOGGER.warning("MQTT connect did not finish within the close budget")
            enter.cancel()
        paho = self._client._client  # pinned aiomqtt version
        # paho's socket close also runs aiomqtt's close callback, which removes
        # the loop reader/writer and cancels aiomqtt's maintenance task.
        with contextlib.suppress(Exception):
            paho._sock_close()
        misc = self._client._misc_task
        if misc is not None and not misc.done():
            misc.cancel()
