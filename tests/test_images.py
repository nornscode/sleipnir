"""Attaching a picture to a turn."""

import base64

import pytest

from sleipnir import images

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_an_image_becomes_a_block_the_model_can_see(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(PNG)

    blocks = images.message_with_image("look at this", p)
    assert blocks[0] == {"type": "text", "text": "look at this"}
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # The name is for the transcript; the model reads the url.
    assert blocks[1]["name"] == "shot.png"


def test_a_picture_with_nothing_said_about_it_is_still_a_turn(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(PNG)
    assert [b["type"] for b in images.message_with_image("   ", p)] == ["image_url"]


def test_what_cannot_be_sent_says_why(tmp_path):
    with pytest.raises(images.ImageError, match="not a file"):
        images.message_with_image("", tmp_path / "nope.png")

    doc = tmp_path / "notes.txt"
    doc.write_text("hello")
    with pytest.raises(images.ImageError, match="not an image"):
        images.message_with_image("", doc)

    big = tmp_path / "huge.png"
    big.write_bytes(b"\x89PNG" + b"0" * images.MAX_BYTES)
    with pytest.raises(images.ImageError, match="the limit is"):
        images.message_with_image("", big)


def test_a_pasted_path_is_taken_as_typed(tmp_path):
    # Shells and screenshot tools quote paths with spaces; take them anyway.
    assert images.expand('  "/tmp/Screenshot 1.png"  ') == images.Path("/tmp/Screenshot 1.png")
    assert images.expand("~/x.png").is_absolute()
