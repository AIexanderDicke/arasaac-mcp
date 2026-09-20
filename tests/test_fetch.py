"""On-demand ARASAAC download (:mod:`arasaac_mcp.fetch`).

The download is exercised through ``urllib``'s ``file://`` handler, so the
tests are offline and deterministic while still covering the real URL
construction, size fallback and atomic-write code paths.
"""

from __future__ import annotations

import pytest

from arasaac_mcp.fetch import (
    DEFAULT_STATIC_URL,
    PictogramFetchError,
    default_static_url,
    fetch_pictogram,
)
from helpers import make_png


def test_default_static_url_uses_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARASAAC_STATIC_URL", raising=False)
    assert default_static_url() == DEFAULT_STATIC_URL


def test_default_static_url_env_override_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARASAAC_STATIC_URL", "https://example.test/icons/")
    assert default_static_url() == "https://example.test/icons"


def test_fetch_downloads_requested_size(tmp_path) -> None:
    static = tmp_path / "static"
    source = make_png(static / "42" / "42_500.png", color="#112233")
    dest = tmp_path / "cache" / "42_icon.png"

    result = fetch_pictogram(42, dest, size=500, static_url=static.as_uri())

    assert result == dest
    assert dest.read_bytes() == source.read_bytes()


def test_fetch_falls_back_to_300_when_500_missing(tmp_path) -> None:
    static = tmp_path / "static"
    source = make_png(static / "7" / "7_300.png")
    dest = tmp_path / "7_icon.png"

    fetch_pictogram(7, dest, size=500, static_url=static.as_uri())

    assert dest.read_bytes() == source.read_bytes()


def test_fetch_falls_back_to_2500_when_smaller_missing(tmp_path) -> None:
    static = tmp_path / "static"
    source = make_png(static / "9" / "9_2500.png")
    dest = tmp_path / "9_icon.png"

    fetch_pictogram(9, dest, size=500, static_url=static.as_uri())

    assert dest.read_bytes() == source.read_bytes()


def test_fetch_creates_missing_destination_parent(tmp_path) -> None:
    static = tmp_path / "static"
    make_png(static / "5" / "5_500.png")
    dest = tmp_path / "a" / "b" / "c" / "5_icon.png"

    fetch_pictogram(5, dest, static_url=static.as_uri())

    assert dest.is_file()


def test_fetch_raises_when_all_sizes_missing(tmp_path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    dest = tmp_path / "10_icon.png"

    with pytest.raises(PictogramFetchError) as excinfo:
        fetch_pictogram(10, dest, size=500, static_url=static.as_uri())

    message = str(excinfo.value)
    assert "10" in message
    assert "500px" in message and "300px" in message and "2500px" in message
    assert not dest.exists()


def test_fetch_rejects_empty_body_and_continues(tmp_path) -> None:
    static = tmp_path / "static"
    empty = static / "11" / "11_500.png"
    empty.parent.mkdir(parents=True)
    empty.write_bytes(b"")
    source = make_png(static / "11" / "11_300.png")
    dest = tmp_path / "11_icon.png"

    fetch_pictogram(11, dest, size=500, static_url=static.as_uri())

    assert dest.read_bytes() == source.read_bytes()


def test_fetch_empty_body_only_is_an_error(tmp_path) -> None:
    static = tmp_path / "static"
    empty = static / "12" / "12_500.png"
    empty.parent.mkdir(parents=True)
    empty.write_bytes(b"")
    dest = tmp_path / "12_icon.png"

    with pytest.raises(PictogramFetchError):
        fetch_pictogram(12, dest, size=500, static_url=static.as_uri())

    assert not dest.exists()


def test_fetch_is_atomic_and_leaves_no_temp_files(tmp_path) -> None:
    static = tmp_path / "static"
    make_png(static / "13" / "13_500.png")
    dest = tmp_path / "cache" / "13_icon.png"

    fetch_pictogram(13, dest, static_url=static.as_uri())

    leftovers = [p.name for p in dest.parent.iterdir() if p != dest]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_fetch_cleans_up_when_the_final_replace_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static = tmp_path / "static"
    make_png(static / "16" / "16_500.png")
    dest = tmp_path / "cache" / "16_icon.png"

    def boom(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr("arasaac_mcp.fetch.os.replace", boom)

    with pytest.raises(OSError, match="disk full"):
        fetch_pictogram(16, dest, static_url=static.as_uri())

    assert not dest.exists()
    leftovers = [p.name for p in dest.parent.iterdir()]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_fetch_tries_fallbacks_for_a_non_standard_size(tmp_path) -> None:
    static = tmp_path / "static"
    source = make_png(static / "14" / "14_300.png")
    dest = tmp_path / "14_icon.png"

    fetch_pictogram(14, dest, size=999, static_url=static.as_uri())

    assert dest.read_bytes() == source.read_bytes()


def test_fetch_static_url_is_normalised(tmp_path) -> None:
    static = tmp_path / "static"
    make_png(static / "15" / "15_500.png")
    dest = tmp_path / "15_icon.png"

    fetch_pictogram(15, dest, static_url=static.as_uri() + "/")

    assert dest.is_file()
