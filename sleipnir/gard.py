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
