"""One gard per repository, so runs from this checkout only ever reach the
worker running in it. The claim token is kept outside the repo, in
~/.sleipnir/gards.json, keyed by server and root. NORNS_GARD and
NORNS_GARD_CLAIM_TOKEN in the environment win over the file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sleipnir.api import NornsApi

STORE = Path(os.environ.get("SLEIPNIR_HOME", str(Path.home() / ".sleipnir"))) / "gards.json"


def _load() -> dict:
    try:
        return json.loads(STORE.read_text())
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2))
    try:
        STORE.chmod(0o600)
    except OSError:
        pass


def stored(url: str, root: Path) -> dict | None:
    return _load().get(f"{url.rstrip('/')}|{root}")


def root_of(url: str, gard_id: int) -> Path | None:
    """Where this space lives on this machine, if it lives here at all.

    The store already knows: it is keyed by server and checkout. This is
    what lets a client start a worker for a space it can see but is not
    running — and say nothing about one that belongs to another machine.
    """
    prefix = f"{url.rstrip('/')}|"
    for key, value in _load().items():
        if key.startswith(prefix) and str(value.get("id")) == str(gard_id):
            root = Path(key[len(prefix):])
            return root if root.is_dir() else None
    return None


def forget(gard_id: int) -> None:
    """Drop a destroyed gard from the store, whatever checkout it was for,
    so the next `sleip` there creates a new one instead of claiming a
    gard that no longer exists."""
    data = _load()
    for key in [k for k, v in data.items() if str(v.get("id")) == str(gard_id)]:
        data.pop(key)
    _save(data)


async def ensure_gard(api: NornsApi, root: Path) -> dict:
    """The gard for this repository on this server: from the environment,
    the store, or freshly created and stored."""
    env_id, env_token = os.environ.get("NORNS_GARD"), os.environ.get("NORNS_GARD_CLAIM_TOKEN")
    if env_id and env_token:
        return {"id": int(env_id), "claim_token": env_token, "name": None, "source": "env"}

    key = f"{api.url}|{root}"
    data = _load()
    if key in data:
        return {**data[key], "source": "store"}

    gard = await api.create_gard(root.name)
    entry = {"id": int(gard["id"]), "claim_token": gard["claim_token"], "name": gard.get("name") or root.name}
    data[key] = entry
    _save(data)
    return {**entry, "source": "created"}
