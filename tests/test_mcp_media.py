"""Content and file helpers of the MCP tools (:mod:`arasaac_mcp.mcp.media`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from arasaac_mcp.mcp import media
from helpers import make_png


def _png() -> bytes:
    return media.png_bytes(Image.new("RGBA", (4, 4), "#336699"))


def test_text_block() -> None:
    block = media.text("hallo")
    assert block.type == "text"
    assert block.text == "hallo"


def test_png_bytes_are_a_png() -> None:
    assert _png().startswith(b"\x89PNG\r\n\x1a\n")


def test_image_from_bytes_and_path(tmp_path: Path) -> None:
    data = _png()
    from_bytes = media.image_from_bytes(data)
    path = tmp_path / "icon.png"
    path.write_bytes(data)
    from_path = media.image_from_path(path)

    assert hasattr(from_bytes, "data")
    assert hasattr(from_path, "data")


def test_save_png_disabled_returns_none() -> None:
    assert media.save_png(Image.new("RGBA", (2, 2)), None) is None


def test_save_png_names_files_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(media.time, "time", lambda: 1000.0)
    tokens = iter(["aaaa", "bbbb"])
    monkeypatch.setattr(media.secrets, "token_hex", lambda _n: next(tokens))

    first = media.save_png(Image.new("RGBA", (2, 2)), tmp_path)
    second = media.save_png(Image.new("RGBA", (2, 2)), tmp_path)

    assert first is not None and second is not None
    assert first.name == "sheet_1000000-aaaa.png"
    assert second.name == "sheet_1000000-bbbb.png"
    assert first.is_file() and second.is_file()


def test_save_icon_copies_into_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(media.time, "time", lambda: 2000.0)
    monkeypatch.setattr(media.secrets, "token_hex", lambda _n: "cafe")
    icon = make_png(tmp_path / "src" / "42_Auto.png")

    saved = media.save_icon(icon, tmp_path / "output")

    assert saved.name == "icon_2000000-cafe-42_Auto.png"
    assert saved.read_bytes() == icon.read_bytes()


def test_render_result_saved_is_text_only_with_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARASAAC_PUBLIC_BASE_URL", "http://sheets.test")
    saved = tmp_path / "sheet_1.png"
    saved.write_bytes(_png())

    result = media.render_result(["Rendered"], _png(), saved)

    types = [part.type for part in result.content]
    assert types == ["text"]
    assert "Rendered" in result.content[0].text
    assert "Image: http://sheets.test/sheet/sheet_1.png" in result.content[0].text
    assert result.structured_content is None


def test_render_result_unsaved_carries_image_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARASAAC_PUBLIC_BASE_URL", "http://sheets.test")
    result = media.render_result(["Rendered"], _png(), None)

    types = [part.type for part in result.content]
    assert types == ["text", "image"]
    assert "Image:" not in result.content[0].text
