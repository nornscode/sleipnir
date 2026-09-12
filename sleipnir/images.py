"""Handing the agent a picture.

The developer's instinct is to screenshot a bug and pass it over, which is
how they work with every other agent. Nothing in the harness allowed it:
the file tools are sandboxed to the repository, and a screenshot lives in
a temp folder. This is the other direction — the user attaching a file
they chose, not the agent reaching outside its workspace.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

# Big enough for a retina screenshot, small enough that the base64 of it
# does not dominate every later turn: the block stays in the conversation
# and is re-sent with each one.
MAX_BYTES = 3_500_000

SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class ImageError(Exception):
    """Why a file could not be attached, in words for the user."""


def expand(raw: str) -> Path:
    return Path(raw.strip().strip("\'\"")).expanduser()


def image_block(path: Path) -> dict:
    """An OpenAI-format image block: what LiteLLM wants and what the SDK
    already passes through untouched."""
    if not path.is_file():
        raise ImageError(f"{path} is not a file")
    if path.suffix.lower() not in SUFFIXES:
        raise ImageError(f"{path.suffix or 'that'} is not an image sleipnir can send")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ImageError(f"{path.name} is {size // 1024}KB; the limit is {MAX_BYTES // 1024}KB")

    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{data}"},
        # Not part of the wire format the model reads; it is what the
        # transcript shows instead of a megabyte of base64.
        "name": path.name,
    }


def message_with_image(text: str, path: Path) -> list[dict]:
    blocks: list[dict] = []
    if text.strip():
        blocks.append({"type": "text", "text": text.strip()})
    blocks.append(image_block(path))
    return blocks
