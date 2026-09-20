"""MCP server integration: tools, prompt, resources and the sheet route.

These tests drive the real FastMCP server in-memory (``fastmcp.Client``) and
its ASGI app (``starlette.testclient``), but with the synthetic icon library and
a temporary output directory, so nothing touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from helpers import make_png
from starlette.testclient import TestClient

from arasaac_mcp.mcp import create_server
from arasaac_mcp.mcp.server import main as server_main


def _texts(result) -> str:
    return "\n".join(part.text for part in result.content if part.type == "text")


def _image_url(text: str) -> str:
    return next((line.split()[-1] for line in text.splitlines() if line.startswith("Image: ")), "")


@pytest.fixture
def server(icons_dir: Path, output_dir: Path):
    return create_server(icons_dir, output_dir=output_dir, fetch_missing=False)


# --------------------------------------------------------------------------- #
# surface
# --------------------------------------------------------------------------- #


async def test_server_registers_the_four_tools(server) -> None:
    async with Client(server) as client:
        tools = {tool.name for tool in await client.list_tools()}
    assert tools == {
        "search_pictograms",
        "view_pictogram",
        "render_pictogram_sheet",
        "render_pictogram_layout",
    }


async def test_server_registers_prompt_and_resources(server) -> None:
    async with Client(server) as client:
        prompts = {prompt.name for prompt in await client.list_prompts()}
        resources = {str(resource.uri) for resource in await client.list_resources()}

    assert "pictogram_transcriber" in prompts
    assert {"arasaac://skill", "arasaac://rules"} <= resources
    assert {
        "arasaac://rules/core",
        "arasaac://rules/workflow",
        "arasaac://rules/design",
        "arasaac://rules/layouts",
        "arasaac://rules/contract",
        "arasaac://rules/sources",
    } <= resources
    assert not any(uri.startswith("ui://") for uri in resources)


# --------------------------------------------------------------------------- #
# tools end to end
# --------------------------------------------------------------------------- #


async def test_search_tool_answers_by_word(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_pictograms", {"query": "Regen", "limit": 3})
    assert "Regen" in result.content[0].text


async def test_view_tool_reports_url_without_image(server, output_dir: Path) -> None:
    async with Client(server) as client:
        result = await client.call_tool("view_pictogram", {"word": "Auto"})
    text = _texts(result)
    assert 'Show "Auto (KFZ)"' in text
    assert _image_url(text).startswith("http")
    assert not any(part.type == "image" for part in result.content)
    assert list(output_dir.glob("icon_*"))


async def test_render_sheet_tool_saves_and_reports_url(
    server, output_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARASAAC_PUBLIC_BASE_URL", "http://sheets.test")
    async with Client(server) as client:
        result = await client.call_tool(
            "render_pictogram_sheet",
            {
                "words": ["Regen", "rot"],
                "roles": ["NOUN", "QUALITY"],
                "sentence": "Test",
            },
        )

    text = _texts(result)
    url = _image_url(text)
    saved = sorted(output_dir.glob("sheet_*.png"))
    assert saved
    assert url == f"http://sheets.test/sheet/{saved[-1].name}"
    assert "File: " in text
    assert result.structured_content is None
    assert not any(part.type == "image" for part in result.content)


async def test_render_layout_tool_grid(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "render_pictogram_layout",
            {
                "layout": {
                    "type": "grid",
                    "columns": ["Tag"],
                    "rows": [{"header": "1.", "cells": ["Regen", None]}],
                },
                "sentence": "Plan",
            },
        )
    assert _image_url(_texts(result)).startswith("http")


async def test_render_layout_tool_cards_and_arrow(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "render_pictogram_layout",
            {
                "layout": {
                    "type": "row",
                    "gap": 30,
                    "children": [
                        {"type": "card", "children": ["Regen"]},
                        {"type": "arrow", "direction": "right"},
                        {"type": "card", "children": ["Berg"]},
                    ],
                }
            },
        )
    assert _image_url(_texts(result)).startswith("http")


async def test_invalid_role_is_rejected(server) -> None:
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "render_pictogram_layout",
                {"layout": {"type": "icon", "word": "Regen", "role": "NOPE"}},
            )


async def test_unknown_word_is_rejected(server) -> None:
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("view_pictogram", {"word": "Zebra"})


# --------------------------------------------------------------------------- #
# no-save mode
# --------------------------------------------------------------------------- #


async def test_no_save_returns_image_blocks(icons_dir: Path) -> None:
    server = create_server(icons_dir, save=False, fetch_missing=False)
    async with Client(server) as client:
        view = await client.call_tool("view_pictogram", {"word": "Regen"})
        sheet = await client.call_tool("render_pictogram_sheet", {"words": ["Regen"]})

    assert [part.type for part in view.content] == ["text", "image"]
    assert [part.type for part in sheet.content] == ["text", "image"]
    assert not any("Image: " in part.text for part in view.content if part.type == "text")


# --------------------------------------------------------------------------- #
# prompt & resources
# --------------------------------------------------------------------------- #


async def test_prompt_embeds_recipe_and_text(server) -> None:
    async with Client(server) as client:
        prompt = await client.get_prompt(
            "pictogram_transcriber", {"text": "Hände waschen vor dem Essen"}
        )
    text = prompt.messages[0].content.text
    assert "Antworte immer auf Deutsch" in text
    assert "Hände waschen vor dem Essen" in text


async def test_skill_resource_serves_skill_markdown(server) -> None:
    async with Client(server) as client:
        resource = await client.read_resource("arasaac://skill")
    text = resource[0].text
    assert "name: arasaac" in text
    assert "arasaac://rules" in text


async def test_rules_resource_serves_full_recipe(server) -> None:
    async with Client(server) as client:
        rules = await client.read_resource("arasaac://rules")
    assert "Antworte immer auf Deutsch" in rules[0].text


async def test_recipe_part_resource(server) -> None:
    async with Client(server) as client:
        part = await client.read_resource("arasaac://rules/design")
    assert "## 5. Core principle" in part[0].text


# --------------------------------------------------------------------------- #
# /sheet route
# --------------------------------------------------------------------------- #


def test_sheet_route_serves_existing_file(server, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    png = make_png(output_dir / "sheet_test.png")
    with TestClient(server.http_app()) as client:
        response = client.get("/sheet/sheet_test.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == png.read_bytes()


def test_sheet_route_missing_file_is_404(server, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with TestClient(server.http_app()) as client:
        assert client.get("/sheet/nope.png").status_code == 404


@pytest.mark.parametrize("name", ["../secret.png", "sub/secret.png", "..%2Fsecret.png"])
def test_sheet_route_rejects_traversal(server, output_dir: Path, name: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with TestClient(server.http_app()) as client:
        assert client.get(f"/sheet/{name}").status_code == 404


def test_sheet_route_without_output_dir_is_404(icons_dir: Path) -> None:
    server = create_server(icons_dir, save=False, fetch_missing=False)
    with TestClient(server.http_app()) as client:
        assert client.get("/sheet/anything.png").status_code == 404


# --------------------------------------------------------------------------- #
# lazy fetch through the server
# --------------------------------------------------------------------------- #


async def test_server_fetch_missing_uses_static_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "metadata_de.json").write_text(
        json.dumps([{"_id": 42, "keywords": [{"keyword": "Regen"}]}]), encoding="utf-8"
    )
    static = tmp_path / "static"
    make_png(static / "42" / "42_500.png")
    cache = tmp_path / "cache"
    monkeypatch.setenv("ARASAAC_STATIC_URL", static.as_uri())

    server = create_server(
        icons, output_dir=tmp_path / "output", fetch_missing=True, cache_dir=cache
    )
    async with Client(server) as client:
        result = await client.call_tool("render_pictogram_sheet", {"words": ["Regen"]})

    assert _image_url(_texts(result)).startswith("http")
    assert (cache / "42_Regen.png").is_file()


async def test_server_without_fetch_fails_on_missing_icon(icons_dir: Path) -> None:
    (icons_dir / "1_Regen.png").unlink()
    server = create_server(icons_dir, save=False, fetch_missing=False)
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("render_pictogram_sheet", {"words": ["Regen"]})


# --------------------------------------------------------------------------- #
# create_server / main wiring
# --------------------------------------------------------------------------- #


async def test_create_server_uses_output_dir_env(
    icons_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    renders = tmp_path / "renders"
    monkeypatch.setenv("ARASAAC_OUTPUT_DIR", str(renders))
    server = create_server(icons_dir, fetch_missing=False)

    async with Client(server) as client:
        await client.call_tool("render_pictogram_sheet", {"words": ["Regen"]})

    assert list(renders.glob("sheet_*.png"))


class _FakeServer:
    def __init__(self) -> None:
        self.runs: list[dict] = []

    def run(self, **kwargs) -> None:
        self.runs.append(kwargs)


def _capture_server(monkeypatch: pytest.MonkeyPatch):
    from arasaac_mcp.mcp import server as server_module

    captured: dict = {}
    fake = _FakeServer()

    def fake_create_server(icons_dir=None, **kwargs):
        captured["icons_dir"] = icons_dir
        captured["kwargs"] = kwargs
        return fake

    monkeypatch.setattr(server_module, "create_server", fake_create_server)
    return captured, fake


def test_main_runs_stdio_by_default(icons_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured, fake = _capture_server(monkeypatch)

    assert server_main(["--icons-dir", str(icons_dir)]) == 0

    assert fake.runs == [{"transport": "stdio"}]
    assert captured["icons_dir"] == icons_dir
    assert captured["kwargs"] == {
        "output_dir": None,
        "save": True,
        "fetch_missing": None,
        "cache_dir": None,
    }


def test_main_runs_http_with_host_and_port(
    icons_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, fake = _capture_server(monkeypatch)

    assert (
        server_main(
            [
                "--icons-dir",
                str(icons_dir),
                "--transport",
                "http",
                "--host",
                "0.0.0.0",
                "--port",
                "9000",
            ]
        )
        == 0
    )

    assert fake.runs == [{"transport": "http", "host": "0.0.0.0", "port": 9000}]


def test_main_passes_offline_and_output_flags(
    icons_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured, _ = _capture_server(monkeypatch)

    server_main(
        [
            "--icons-dir",
            str(icons_dir),
            "--no-save",
            "--no-fetch",
            "--output-dir",
            str(tmp_path / "out"),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )

    assert captured["kwargs"]["save"] is False
    assert captured["kwargs"]["fetch_missing"] is False
    assert captured["kwargs"]["output_dir"] == tmp_path / "out"
    assert captured["kwargs"]["cache_dir"] == tmp_path / "cache"


def test_main_rejects_missing_icons_dir(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        server_main(["--icons-dir", str(tmp_path / "missing")])
    assert excinfo.value.code == 2


def test_main_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        server_main(["--help"])
    assert excinfo.value.code == 0
