"""Workspace root and path safety.

Every tool resolves paths against one root, the repository the harness
was started in. A path that resolves outside it (including through a
symlink) is refused.
"""

from __future__ import annotations

import os
from pathlib import Path

# Directories never worth showing a model or searching through.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".eggs",
    "dist",
    "build",
    "_build",
    "deps",
    ".elixir_ls",
    "target",
    ".sleipnir",
}


class ToolError(Exception):
    """A tool failure the model should read and act on."""


class Workspace:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        """Resolve a workspace-relative (or absolute) path, refusing escapes."""
        p = (self.root / path).resolve()
        if p != self.root and self.root not in p.parents:
            raise ToolError(f"{path} is outside the workspace root {self.root}")
        return p

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))

    def skipped(self, p: Path) -> bool:
        return any(part in SKIP_DIRS for part in p.relative_to(self.root).parts)

    def walk_files(self, start: Path):
        """Yield files under start, depth-first and sorted, skipping SKIP_DIRS."""
        if start.is_file():
            yield start
            return
        for dirpath, dirnames, filenames in os.walk(start):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                yield Path(dirpath) / name


def is_binary(p: Path, sniff: int = 8192) -> bool:
    try:
        with open(p, "rb") as f:
            return b"\0" in f.read(sniff)
    except OSError:
        return True
