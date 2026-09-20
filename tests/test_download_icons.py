"""The bulk download helper (:mod:`scripts.download_icons`).

Only the pure helpers and the download/main control flow are exercised; the
HTTP calls are replaced with a stub so the tests stay offline.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    path = REPO_ROOT / "scripts" / "download_icons.py"
    spec = importlib.util.spec_from_file_location("download_icons", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def download_icons() -> ModuleType:
    return _load()


def _http_error(url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)


def test_slug_normalises_text(download_icons: ModuleType) -> None:
    assert download_icons.slug("Augen öffnen") == "Augen_öffnen"
    assert download_icons.slug("a/b:c") == "a_b_c"
    assert download_icons.slug("") == "pictogram"
    assert len(download_icons.slug("x" * 200)) <= 60


def test_filename_uses_first_keyword(download_icons: ModuleType) -> None:
    assert download_icons.filename({"_id": 7, "keywords": [{"keyword": "Regen"}]}) == "7_Regen.png"
    assert download_icons.filename({"_id": 8, "keywords": []}) == "8.png"
    assert download_icons.filename({"_id": 9, "keywords": [{"keyword": ""}]}) == "9.png"


def test_download_skips_existing_file(download_icons: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "icons"
    out.mkdir()
    (out / "7_Regen.png").write_bytes(b"already here")

    assert download_icons.download({"_id": 7, "keywords": [{"keyword": "Regen"}]}, out, 500) == "skipped"


def test_download_falls_back_to_smaller_size(
    download_icons: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        calls.append(url)
        if url.endswith("_500.png"):
            raise _http_error(url)
        return b"png-bytes"

    monkeypatch.setattr(download_icons, "fetch", fake_fetch)
    out = tmp_path / "icons"
    out.mkdir()

    result = download_icons.download({"_id": 7, "keywords": [{"keyword": "Regen"}]}, out, 500)

    assert result == "ok"
    assert (out / "7_Regen.png").read_bytes() == b"png-bytes"
    assert any(url.endswith("_300.png") for url in calls)


def test_download_reports_failure_when_all_sizes_missing(
    download_icons: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download_icons, "fetch", lambda url: (_ for _ in ()).throw(_http_error(url)))
    out = tmp_path / "icons"
    out.mkdir()

    assert download_icons.download({"_id": 7, "keywords": []}, out, 500) == "failed"
    assert not (out / "7.png").exists()


def test_main_downloads_metadata_and_icons(
    download_icons: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pictures = [
        {"_id": 1, "keywords": [{"keyword": "Regen"}]},
        {"_id": 2, "keywords": [{"keyword": "Auto"}]},
    ]

    def fake_fetch(url: str) -> bytes:
        if url.startswith(download_icons.API):
            return json.dumps(pictures).encode("utf-8")
        return b"png-bytes"

    monkeypatch.setattr(download_icons, "fetch", fake_fetch)
    out = tmp_path / "icons"
    monkeypatch.setattr("sys.argv", ["download_icons.py", "--out", str(out), "--workers", "2"])

    rc = download_icons.main()

    assert rc == 0
    assert (out / "metadata_de.json").is_file()
    assert (out / "1_Regen.png").is_file()
    assert (out / "2_Auto.png").is_file()


def test_main_returns_nonzero_on_failures(
    download_icons: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pictures = [{"_id": 1, "keywords": [{"keyword": "Regen"}]}]

    def fake_fetch(url: str) -> bytes:
        if url.startswith(download_icons.API):
            return json.dumps(pictures).encode("utf-8")
        raise _http_error(url)

    monkeypatch.setattr(download_icons, "fetch", fake_fetch)
    monkeypatch.setattr("sys.argv", ["download_icons.py", "--out", str(tmp_path / "icons")])

    assert download_icons.main() == 1
