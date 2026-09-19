#!/usr/bin/env python
"""Offline tests for the Python catalog and the MCP server (no LLM needed).

Mirrors the contract checked by ``scripts/test_extension.mjs`` for the pi tools:
word-only output, synonym hits, label round-trip, real rendering — here against
the shared Python core and the MCP server (in-memory, no network).

Run from the repo root:
    uv run --extra mcp python scripts/test_mcp.py
"""

from __future__ import annotations

import asyncio
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arasaac_pictograms.catalog import get_catalog  # noqa: E402
from arasaac_pictograms.mcp import create_server  # noqa: E402

FAILED = 0


def ok(message: str) -> None:
    print(f"ok   {message}")


def fail(message: str) -> None:
    global FAILED
    FAILED += 1
    print(f"FAIL: {message}")


def check(condition: bool, message: str) -> None:
    (ok if condition else fail)(message)


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
print("\n== catalog ==")
catalog = get_catalog(ROOT / "icons")

lines = catalog.search_lines("Regen", 5)
check(bool(re.match(r"^1\. Regen\b", lines[0])) if lines else False, "search returns word 'Regen' first")
check(not any(re.search(r"\d+_", line) for line in lines), "search output has no numeric ids")

lines = catalog.search_lines("PKW", 5)
check(any("Auto" in line for line in lines), "synonym 'PKW' surfaces word 'Auto'")

missing = False
try:
    catalog.resolve("does_not_exist")
except KeyError:
    missing = True
check(missing, "unknown word raises")

checked = 0
mismatches = 0
for query in ["Schüler", "Auto", "vor", "Sport", "Regen", "Familie"]:
    for line in catalog.search_lines(query, 12):
        label = line.split(". ", 1)[1].split(" — ")[0].strip()
        checked += 1
        if catalog.label_of(catalog.resolve(label)).lower() != label.lower():
            mismatches += 1
            fail(f"label does not round-trip: {label}")
check(checked > 0 and mismatches == 0, f"{checked - mismatches}/{checked} search labels round-trip")

node = catalog.resolve_layout_node({"type": "row", "children": ["Auto", {"type": "icon", "word": "Berg"}]})
check(
    node["children"][0]["file"].endswith(".png") and node["children"][1]["concept"] == "Berg",
    "layout tree words resolve to files/concepts",
)


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #
print("\n== mcp server ==")


async def exercise() -> None:
    from fastmcp import Client

    out_dir = Path(tempfile.mkdtemp(prefix="arasaac-mcp-test-"))
    server = create_server(ROOT / "icons", output_dir=out_dir)
    async with Client(server) as client:
        tools = {tool.name for tool in await client.list_tools()}
        check(
            tools == {
                "search_pictograms",
                "view_pictogram",
                "render_pictogram_sheet",
                "render_pictogram_layout",
            },
            f"four tools registered ({sorted(tools)})",
        )
        prompts = {prompt.name for prompt in await client.list_prompts()}
        check("pictogram_transcriber" in prompts, "prompt registered")
        resources = {str(resource.uri) for resource in await client.list_resources()}
        check({"arasaac://skill", "arasaac://rules"} <= resources, "resources registered")

        result = await client.call_tool("search_pictograms", {"query": "Regen", "limit": 3})
        check("Regen" in result.content[0].text, "search tool answers by word")

        result = await client.call_tool("view_pictogram", {"word": "Auto"})
        image = next((part for part in result.content if part.type == "image"), None)
        check(image is not None and image.mime_type == "image/png", "view_pictogram returns a PNG")

        result = await client.call_tool(
            "render_pictogram_sheet",
            {
                "words": ["Regen", "alle", "Schüler", "drinnen"],
                "roles": ["NOUN", "NOUN", "PERSON", "MISC"],
                "sentence": "Wenn es regnet, müssen alle Schüler drin bleiben.",
            },
        )
        image = next((part for part in result.content if part.type == "image"), None)
        check(image is not None and len(image.data) > 1000, "render_pictogram_sheet returns an image")
        debug_files = sorted(out_dir.glob("*.png"))
        check(bool(debug_files), f"render_pictogram_sheet writes a local debug file ({len(debug_files)})")
        check(
            any("Datei:" in part.text for part in result.content if part.type == "text"),
            "render text reports the debug file path",
        )

        result = await client.call_tool(
            "render_pictogram_layout",
            {
                "layout": {
                    "type": "grid",
                    "columns": ["Montag", "Dienstag"],
                    "rows": [
                        {"header": "1.", "cells": ["Mathe", "Sport"]},
                        {"header": "2.", "cells": ["Pause", "Regen"]},
                    ],
                },
                "sentence": "Mein Stundenplan",
            },
        )
        image = next((part for part in result.content if part.type == "image"), None)
        check(image is not None, "render_pictogram_layout (grid) returns an image")

        result = await client.call_tool(
            "render_pictogram_layout",
            {
                "layout": {
                    "type": "row",
                    "gap": 30,
                    "children": [
                        {"type": "card", "children": ["Zähne putzen"]},
                        {"type": "arrow", "direction": "right"},
                        {"type": "card", "children": ["Familie"]},
                    ],
                }
            },
        )
        check(
            any(part.type == "image" for part in result.content),
            "render_pictogram_layout (cards + arrow) returns an image",
        )

        bad_role = False
        try:
            await client.call_tool(
                "render_pictogram_layout",
                {"layout": {"type": "icon", "word": "Auto", "role": "NOPE"}},
            )
        except Exception:
            bad_role = True
        check(bad_role, "invalid role is rejected")

        prompt = await client.get_prompt("pictogram_transcriber", {"text": "Hände waschen vor dem Essen"})
        text = prompt.messages[0].content.text
        check(
            "Antworte immer auf Deutsch" in text and "Hände waschen" in text,
            "prompt embeds the recipe and the German text",
        )

        resource = await client.read_resource("arasaac://skill")
        check("name: arasaac-pictograms" in resource[0].text, "skill resource serves SKILL.md")


asyncio.run(exercise())

print("\n" + ("SOME CHECKS FAILED" if FAILED else "ALL CHECKS PASSED"))
sys.exit(1 if FAILED else 0)
