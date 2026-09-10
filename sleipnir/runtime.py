"""Process-wide harness state: the workspace and the permission set.

Tool handlers receive only their arguments from the SDK, so the root and
the allow list live here, set once by `configure` before the worker
connects (and per test).
"""

from __future__ import annotations

import os
from pathlib import Path

from sleipnir.permissions import Permissions
from sleipnir.workspace import Workspace

ALLOW_FILE = Path(".sleipnir") / "allow"

_workspace: Workspace | None = None
_permissions: Permissions | None = None


def configure(root: str | os.PathLike, allow_file: Path | None = None) -> None:
    global _workspace, _permissions
    _workspace = Workspace(root)
    _permissions = Permissions(allow_file if allow_file is not None else _workspace.root / ALLOW_FILE)


def workspace() -> Workspace:
    if _workspace is None:
        raise RuntimeError("sleipnir.runtime.configure() has not been called")
    return _workspace


def permissions() -> Permissions:
    if _permissions is None:
        raise RuntimeError("sleipnir.runtime.configure() has not been called")
    return _permissions
