"""Per-repository harness config at .sleipnir/config, `key = value` lines.

Precedence for a setting: command-line flag, then environment
(SLEIPNIR_<KEY>), then this file, then the default.
"""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_FILE = Path(".sleipnir") / "config"

DEFAULTS = {
    "agent": "sleipnir",
    "model": "claude-sonnet-5",
    "max_steps": "200",
}
KEYS = tuple(DEFAULTS)


def config_path(root: Path) -> Path:
    return root / CONFIG_FILE


def load(root: Path) -> dict[str, str]:
    p = config_path(root)
    values: dict[str, str] = {}
    if p.is_file():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip()
    return values


def save(root: Path, values: dict[str, str]) -> None:
    p = config_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"{k} = {v}\n" for k, v in values.items()))


def set_value(root: Path, key: str, value: str) -> None:
    if key not in KEYS:
        raise KeyError(f"unknown setting {key!r}; settings are: {', '.join(KEYS)}")
    if key == "max_steps" and not value.isdigit():
        raise ValueError("max_steps must be a positive integer")
    values = load(root)
    values[key] = value
    save(root, values)


def unset_value(root: Path, key: str) -> None:
    values = load(root)
    values.pop(key, None)
    save(root, values)


def resolve(root: Path, overrides: dict[str, str | None] | None = None) -> dict[str, str]:
    """Effective settings after applying precedence."""
    file_values = load(root)
    out = {}
    for k in KEYS:
        flag = (overrides or {}).get(k)
        env = os.environ.get(f"SLEIPNIR_{k.upper()}")
        out[k] = flag or env or file_values.get(k) or DEFAULTS[k]
    return out


def source(root: Path, key: str, overrides: dict[str, str | None] | None = None) -> str:
    if (overrides or {}).get(key):
        return "flag"
    if os.environ.get(f"SLEIPNIR_{key.upper()}"):
        return "env"
    if key in load(root):
        return "file"
    return "default"
