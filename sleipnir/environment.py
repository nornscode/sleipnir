"""Load the selected checkout's approved direnv environment at startup."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess


def load(root: Path) -> None:
    executable = shutil.which("direnv")
    if executable is None:
        if any((p / ".envrc").is_file() for p in (root, *root.parents)):
            raise ValueError("found .envrc but direnv is not installed; install direnv and run direnv allow in the checkout")
        return

    try:
        result = subprocess.run(
            [executable, "export", "json"], cwd=root,
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("could not load direnv environment (failed to start or timed out)") from None
    # Do not print shell output: .envrc scripts may include secrets.
    if result.returncode:
        raise ValueError("direnv could not load the environment; check .envrc and run direnv allow in the checkout")
    try:
        changes = json.loads(result.stdout) if result.stdout.strip() else {}
        if not isinstance(changes, dict) or any(
            not k or "=" in k or "\0" in k
            or (v is not None and (not isinstance(v, str) or "\0" in v))
            for k, v in changes.items()
        ):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("direnv returned an invalid environment") from None
    for key, value in changes.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
