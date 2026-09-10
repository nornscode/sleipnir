"""Async client for the Norns REST API, the slice the session client needs."""

from __future__ import annotations

from typing import Any

import httpx


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class NornsApi:
    def __init__(self, url: str, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.url + "/api/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        resp = await self._client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                message = resp.json().get("error", resp.text)
            except ValueError:
                message = resp.text
            raise ApiError(resp.status_code, str(message))
        if not resp.content:
            return None
        body = resp.json()
        # Collection and record responses wrap their payload in `data`; action
        # responses (accepted, run_id, ...) are returned whole.
        if isinstance(body, dict) and set(body) <= {"data"}:
            return body["data"]
        return body

    async def sessions(self, limit: int = 100) -> list[dict]:
        return await self._request("GET", "/sessions", params={"limit": limit})

    async def session(self, session_id: int) -> dict:
        return await self._request("GET", f"/sessions/{session_id}")

    async def agents(self) -> list[dict]:
        return await self._request("GET", "/agents")

    async def send_message(
        self, agent_id: int, content: str, *, conversation_key: str | None = None, gard_id: int | None = None
    ) -> int:
        body: dict[str, Any] = {"content": content}
        if conversation_key:
            body["conversation_key"] = conversation_key
        if gard_id:
            body["gard_id"] = gard_id
        data = await self._request("POST", f"/agents/{agent_id}/messages", json=body)
        return int(data["run_id"])

    async def reply(self, run_id: int, answer: str) -> None:
        await self._request("POST", f"/runs/{run_id}/reply", json={"answer": answer})

    async def fork(self, run_id: int, step: int, message: str | None = None) -> dict:
        body: dict[str, Any] = {"step": step}
        if message:
            body["message"] = message
        return await self._request("POST", f"/runs/{run_id}/fork", json=body)

    async def run(self, run_id: int) -> dict:
        return await self._request("GET", f"/runs/{run_id}")

    async def run_events(self, run_id: int) -> list[dict]:
        return await self._request("GET", f"/runs/{run_id}/events")

    async def gards(self) -> list[dict]:
        return await self._request("GET", "/gards")

    async def create_gard(self, name: str) -> dict:
        return await self._request("POST", "/gards", json={"name": name})
