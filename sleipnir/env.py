"""Environment for the worker and the client, from the repository.

Precedence, highest first: the process environment, `--env-file`, the
repository's `.envrc` through `direnv export` (only if direnv is installed
and has allowed the file), the repository's `.env`, then this machine's
`~/.sleipnir/env` (written by `sleip setup`). Files never override a
variable the process already has, and the machine-wide file comes last so
a checkout can point somewhere else without being reconfigured.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

SLEIPNIR_HOME = Path(os.environ.get("SLEIPNIR_HOME", str(Path.home() / ".sleipnir")))
USER_ENV = SLEIPNIR_HOME / "env"


def parse_env_file(text: str) -> dict[str, str]:
    """KEY=VALUE lines; `export` prefixes, quotes, and # comments allowed."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key[0].isdigit() or not all(c.isalnum() or c == "_" for c in key):
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            try:
                parts = shlex.split(value)
                value = parts[0] if parts else ""
            except ValueError:
                value = value.strip("'\"")
        else:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def direnv_export(root: Path) -> dict[str, str | None]:
    """What direnv would export in root, or {} if direnv is absent, the
    .envrc is not allowed, or nothing changes. None means unset."""
    if not (root / ".envrc").is_file() or shutil.which("direnv") is None:
        return {}
    try:
        proc = subprocess.run(
            ["direnv", "export", "json"], cwd=root, capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def load_env(root: Path, env_file: Path | None = None) -> dict[str, str]:
    """Apply the repository's environment to os.environ for variables the
    process does not already have. Returns {variable: source}."""
    applied: dict[str, str] = {}
    layers: list[tuple[str, dict[str, str | None]]] = []

    if env_file is not None:
        layers.append((str(env_file), parse_env_file(env_file.read_text())))
    layers.append((".envrc (direnv)", direnv_export(root)))
    dotenv = root / ".env"
    if dotenv.is_file():
        layers.append((".env", parse_env_file(dotenv.read_text())))
    if USER_ENV.is_file():
        try:
            layers.append((f"{USER_ENV} (sleip setup)", parse_env_file(USER_ENV.read_text())))
        except OSError:
            pass

    for source, values in layers:
        for key, value in values.items():
            if key in applied or key in os.environ or key.startswith("DIRENV_"):
                continue
            if value is None:
                continue
            os.environ[key] = value
            applied[key] = source
    return applied


def env_hint(root: Path) -> str | None:
    """A note for doctor when an .envrc exists but direnv cannot serve it."""
    if not (root / ".envrc").is_file():
        return None
    if shutil.which("direnv") is None:
        return ".envrc present but direnv is not installed; only .env is read"
    return None
