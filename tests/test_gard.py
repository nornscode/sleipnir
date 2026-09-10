import json

import httpx
import pytest

from sleipnir import gard
from sleipnir.api import NornsApi


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(gard, "STORE", tmp_path / "home" / "gards.json")
    monkeypatch.delenv("NORNS_GARD", raising=False)
    monkeypatch.delenv("NORNS_GARD_CLAIM_TOKEN", raising=False)
    return gard.STORE


@pytest.mark.asyncio
async def test_creates_once_then_reuses(store, tmp_path):
    created = []

    def handler(request):
        created.append(json.loads(request.content))
        return httpx.Response(201, json={"data": {"id": 42, "name": "repo", "claim_token": "tok"}})

    api = NornsApi("http://norns.test", "k", transport=httpx.MockTransport(handler))
    root = tmp_path / "repo"
    root.mkdir()
    first = await gard.ensure_gard(api, root)
    assert first == {"id": 42, "claim_token": "tok", "name": "repo", "source": "created"}
    assert created == [{"name": "repo"}]
    assert oct(store.stat().st_mode)[-3:] == "600"

    second = await gard.ensure_gard(api, root)
    assert second["source"] == "store" and second["id"] == 42
    assert len(created) == 1
    assert gard.stored("http://norns.test", root)["claim_token"] == "tok"


@pytest.mark.asyncio
async def test_environment_wins(store, tmp_path, monkeypatch):
    monkeypatch.setenv("NORNS_GARD", "7")
    monkeypatch.setenv("NORNS_GARD_CLAIM_TOKEN", "t")
    api = NornsApi("http://norns.test", "k", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert (await gard.ensure_gard(api, tmp_path))["id"] == 7
