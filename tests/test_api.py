import json

import httpx
import pytest

from sleipnir.api import ApiError, NornsApi


def make_api(handler):
    return NornsApi("http://norns.test", "nrn_x", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_requests_and_unwrapping():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization"), request.content))
        if request.url.path == "/api/v1/sessions":
            return httpx.Response(200, json={"data": [{"id": 1}]})
        if request.url.path == "/api/v1/agents/5/messages":
            return httpx.Response(202, json={"status": "accepted", "run_id": 9})
        if request.url.path == "/api/v1/runs/9/fork":
            return httpx.Response(201, json={"status": "accepted", "run_id": 10, "agent_id": 5, "data": {}})
        if request.url.path == "/api/v1/runs/9/reply":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"error": "not found"})

    api = make_api(handler)
    assert await api.sessions(limit=5) == [{"id": 1}]
    assert await api.send_message(5, "hi", conversation_key="k", gard_id=3) == 9
    assert (await api.fork(9, 2, "again"))["run_id"] == 10
    await api.reply(9, "yes")
    with pytest.raises(ApiError) as exc:
        await api.session(404)
    assert exc.value.status == 404 and exc.value.message == "not found"
    await api.close()

    assert seen[0][2] == "Bearer nrn_x"
    assert json.loads(seen[1][3]) == {"content": "hi", "conversation_key": "k", "gard_id": 3}
    assert json.loads(seen[2][3]) == {"step": 2, "message": "again"}
