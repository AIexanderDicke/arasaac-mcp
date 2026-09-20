"""Fixtures shared by the arasaac test suite.

The suite is offline by default: the synthetic library built here is enough for
the catalog, the renderer, the CLI and the MCP tools.  Only tests marked
``integration`` touch the real, large pictogram set that the repository ships
for local development.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import build_icons_dir  # noqa: E402

from arasaac_mcp.catalog import _CATALOG_CACHE, _INDEX_CACHE, Catalog  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_caches() -> None:
    """Keep the module-level index/catalog caches from leaking between tests."""
    _INDEX_CACHE.clear()
    _CATALOG_CACHE.clear()
    yield
    _INDEX_CACHE.clear()
    _CATALOG_CACHE.clear()


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def icons_dir(tmp_path: Path) -> Path:
    """A small synthetic icons directory with PNGs and metadata."""
    return build_icons_dir(tmp_path / "library")


@pytest.fixture
def catalog(icons_dir: Path) -> Catalog:
    return Catalog(icons_dir)


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "output"


@pytest.fixture
def real_icons_dir(repo_root: Path) -> Path:
    """The real pictogram directory, skipped when the index is unavailable."""
    icons = repo_root / "icons"
    if not (icons / "metadata_de.json").is_file():
        pytest.skip("icons/metadata_de.json is not available")
    return icons
