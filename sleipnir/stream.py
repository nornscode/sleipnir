"""The agent channel: live events for any number of agents on one socket.

Phoenix wire format, v2: `[join_ref, ref, topic, event, payload]`. Joined
topics are re-joined after a reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets

logger = logging.getLogger("sleipnir.stream")

EventHandler = Callable[[int, str, dict], Awaitable[None] | None]


class AgentStream:
    def __init__(self, url: str, api_key: str, on_event: EventHandler):
        base = url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
        self._url = f"{base}/socket/websocket?token={api_key}&vsn=2.0.0"
        self._on_event = on_event
        self._topics: set[int] = set()
        self._ws = None
        self._ref = 0
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def join(self, agent_id: int) -> None:
        """Subscribe to an agent's events; a no-op if already joined."""
        if agent_id in self._topics:
            return
        self._topics.add(agent_id)
        if self._ws is not None:
            await self._send_join(agent_id)

    def _next_ref(self) -> str:
        self._ref += 1
        return str(self._ref)

    async def _send_join(self, agent_id: int) -> None:
        msg = [str(agent_id), self._next_ref(), f"agent:{agent_id}", "phx_join", {}]
        await self._ws.send(json.dumps(msg))

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                async with websockets.connect(self._url) as ws:
                    self._ws = ws
                    for agent_id in list(self._topics):
                        await self._send_join(agent_id)
                    heartbeat = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            await self._dispatch(raw)
                    finally:
                        heartbeat.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"agent stream disconnected: {e}")
            finally:
                self._ws = None
            if not self._stopped.is_set():
                await asyncio.sleep(2)

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(30)
            await ws.send(json.dumps([None, self._next_ref(), "phoenix", "heartbeat", {}]))

    async def _dispatch(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, list) or len(msg) < 5:
            return
        _join_ref, _ref, topic, event, payload = msg
        if event in ("phx_reply", "phx_close", "phx_error", "heartbeat") or not str(topic).startswith("agent:"):
            if event == "phx_reply" and isinstance(payload, dict) and payload.get("status") == "error":
                logger.warning(f"channel {topic}: {payload}")
            return
        try:
            agent_id = int(str(topic).split(":", 1)[1])
        except ValueError:
            return
        result = self._on_event(agent_id, event, payload if isinstance(payload, dict) else {})
        if asyncio.iscoroutine(result):
            await result
