#!/usr/bin/env python
"""Offline tests for the Python catalog and the MCP server (no LLM needed).

Checks the word contract: word-only output, synonym hits, label round-trip,
real rendering — against the Python core and the MCP server (in-memory, no
network).

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


def image_url_ok(url: str) -> bool:
    """The host shows this URL as a web preview; no inline base64 any more."""
    return url.startswith("http") and url.endswith(".png")


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
        tool_list = await client.list_tools()
        tools = {tool.name for tool in tool_list}
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
        check(
            {"arasaac://skill", "arasaac://rules"} <= resources,
            "resources registered (no viewer resource any more)",
        )
        check(
            not any(str(r).startswith("ui://") for r in resources),
            "no ui:// viewer resource remains",
        )

        result = await client.call_tool("search_pictograms", {"query": "Regen", "limit": 3})
        check("Regen" in result.content[0].text, "search tool answers by word")

        result = await client.call_tool("view_pictogram", {"word": "Auto"})
        view_text = "\n".join(part.text for part in result.content if part.type == "text")
        check("Zeige \"Auto\"" in view_text, "view_pictogram reports the label")
        check(
            image_url_ok(next((l.split()[-1] for l in view_text.splitlines() if l.startswith("Bild: ")), "")),
            "view_pictogram reports the icon URL (no image block dumped as JSON)",
        )
        check(
            not any(part.type == "image" for part in result.content),
            "view_pictogram carries no image block when saving is on",
        )

        result = await client.call_tool(
            "render_pictogram_sheet",
            {
                "words": ["Regen", "alle", "Schüler", "drinnen"],
                "roles": ["NOUN", "NOUN", "PERSON", "MISC"],
                "sentence": "Wenn es regnet, müssen alle Schüler drin bleiben.",
            },
        )
        text = "\n".join(part.text for part in result.content if part.type == "text")
        image_url = next((line.split()[-1] for line in text.splitlines() if line.startswith("Bild: ")), "")
        check(
            image_url_ok(image_url),
            "render text reports the image URL (the host previews it)",
        )
        debug_files = sorted(out_dir.glob("*.png"))
        check(bool(debug_files), f"render_pictogram_sheet writes a local debug file ({len(debug_files)})")
        check(
            image_url.endswith("/" + debug_files[-1].name) if debug_files else False,
            "image URL points at the saved debug file",
        )
        check(
            result.structured_content is None,
            "render result carries no structuredContent (hosts dump it as JSON)",
        )
        check(
            not any(part.type == "image" for part in result.content),
            "saved render keeps the base64 blob out of the chat content",
        )
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
        grid_text = "\n".join(part.text for part in result.content if part.type == "text")
        check(
            image_url_ok(next((l.split()[-1] for l in grid_text.splitlines() if l.startswith("Bild: ")), "")),
            "render_pictogram_layout (grid) reports an image URL",
        )

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
        cards_text = "\n".join(part.text for part in result.content if part.type == "text")
        check(
            image_url_ok(next((l.split()[-1] for l in cards_text.splitlines() if l.startswith("Bild: ")), "")),
            "render_pictogram_layout (cards + arrow) reports an image URL",
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
