"""Environment lookups for the MCP tools (:mod:`arasaac_mcp.mcp.context`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arasaac_mcp.mcp import context


def test_public_base_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARASAAC_PUBLIC_BASE_URL", raising=False)
    assert context.public_base_url() == "http://localhost:8000"


def test_public_base_url_env_override_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARASAAC_PUBLIC_BASE_URL", "https://sheets.test/")
    assert context.public_base_url() == "https://sheets.test"


def test_default_output_dir_default_is_cwd_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARASAAC_OUTPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert context.default_output_dir() == tmp_path / "output"


def test_default_output_dir_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARASAAC_OUTPUT_DIR", str(tmp_path / "renders"))
    assert context.default_output_dir() == tmp_path / "renders"


@pytest.mark.parametrize("value", ["off", "0", "false", "no", "never", "OFF", " off "])
def test_fetch_missing_disabled_values(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARASAAC_FETCH", value)
    assert context.fetch_missing_enabled() is False


@pytest.mark.parametrize("value", ["auto", "on", "1", "true", "yes"])
def test_fetch_missing_enabled_values(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARASAAC_FETCH", value)
    assert context.fetch_missing_enabled() is True


def test_fetch_missing_defaults_to_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARASAAC_FETCH", raising=False)
    assert context.fetch_missing_enabled() is True


def test_default_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ARASAAC_CACHE_DIR", raising=False)
    assert context.default_cache_dir() is None
    monkeypatch.setenv("ARASAAC_CACHE_DIR", str(tmp_path / "cache"))
    assert context.default_cache_dir() == tmp_path / "cache"


def test_default_fetch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARASAAC_FETCH_SIZE", raising=False)
    assert context.default_fetch_size() == 500
    monkeypatch.setenv("ARASAAC_FETCH_SIZE", "300")
    assert context.default_fetch_size() == 300


def test_default_fetch_size_falls_back_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARASAAC_FETCH_SIZE", "not-a-number")
    assert context.default_fetch_size() == 500
