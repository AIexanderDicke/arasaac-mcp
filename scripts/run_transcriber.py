#!/usr/bin/env python
"""Run the pictogram-transcriber agent headless, with only its own tools.

Reads the agent definition (frontmatter `tools:` + body system prompt) and
starts `pi` with:
  * only the project extension, no discovered extensions/skills/context files
  * `--tools <allowlist>` so the agent can call nothing else
  * the agent body as appended system prompt

Example:
    python scripts/run_transcriber.py "Wenn es regnet, müssen alle Schüler drin bleiben."
    python scripts/run_transcriber.py --mode json "Ein rotes Auto steht vor einem Berg."
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT = ROOT / ".pi" / "agents" / "pictogram-transcriber.md"
DEFAULT_EXTENSION = ROOT / ".pi" / "extensions" / "pictograms.ts"


def parse_agent(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        raise SystemExit(f"{path}: missing YAML frontmatter")
    frontmatter: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if value:
            frontmatter[key.strip()] = value.strip()
    return frontmatter, match.group(2).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sentence", help="German sentence to transcribe.")
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT)
    parser.add_argument("--extension", type=Path, default=DEFAULT_EXTENSION)
    parser.add_argument("--model", help="Override the model (provider/id).")
    parser.add_argument(
        "--mode",
        choices=["text", "json"],
        default="text",
        help="'text' prints only the final answer; 'json' streams all events.",
    )
    parser.add_argument("--cwd", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true", help="Print the command and exit.")
    args = parser.parse_args(argv)

    frontmatter, body = parse_agent(args.agent)
    tools = [tool.strip() for tool in frontmatter.get("tools", "").split(",") if tool.strip()]
    if not tools:
        raise SystemExit(f"{args.agent}: no `tools:` allowlist in frontmatter")

    command = [
        "pi",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-context-files",
        "-e",
        str(args.extension),
        "--tools",
        ",".join(tools),
        "--append-system-prompt",
        body,
    ]
    model = args.model or frontmatter.get("model")
    if model:
        command += ["--model", model]
    if args.mode == "text":
        command += ["-p"]
    else:
        command += ["--mode", "json", "-p"]
    command.append(args.sentence)

    if args.dry_run:
        print(" ".join(command[:8]), "...")
        print(f"tools: {tools}")
        print(f"prompt chars: {len(body)}")
        return 0

    print(f"# agent={frontmatter.get('name', '?')} tools={tools}", file=sys.stderr)
    return subprocess.call(command, cwd=args.cwd)


if __name__ == "__main__":
    sys.exit(main())
