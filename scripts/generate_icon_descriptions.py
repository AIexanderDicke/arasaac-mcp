#!/usr/bin/env python
"""Generate a detailed German description for every ARASAAC pictogram.

For each ``<icons-dir>/[id]_[name].png`` the PNG is sent once to a
vision-capable, OpenAI-compatible chat-completions endpoint (OpenRouter by
default) and the structured answer is written to
``<out-dir>/[id]_[name]_description.<md|txt>``.

The job is cached and resumable: a non-empty description file is skipped, so
stopping and re-running continues where it left off.  Only the standard library
is used, mirroring ``scripts/download_icons.py`` and ``arasaac_mcp/fetch.py``.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, NamedTuple

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash-vision-exp"
DEFAULT_API_KEY_ENV = "OPENROUTER_API_KEY"
#: Cloudflare in front of some endpoints blocks Python's default User-Agent
#: (error 1010), so identify the tool explicitly.
USER_AGENT = "arasaac-mcp/0.1 (+https://github.com/aiexanderdicke/arasaac)"
#: Optional OpenRouter attribution headers.
HTTP_REFERER = "https://github.com/aiexanderdicke/arasaac"
APP_TITLE = "arasaac-mcp"

LANGUAGE_NAMES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
}

_ICON_RE = re.compile(r"^(\d+)_(.*)\.png$")


class IconTarget(NamedTuple):
    """One icon scheduled for description."""

    pic_id: int
    name: str
    png: Path
    path: Path


def _default_icons_dir() -> Path:
    env = os.environ.get("ARASAAC_ICONS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "icons"


def parse_icon_filename(filename: str) -> tuple[int, str] | None:
    """Split ``[id]_[name].png`` into ``(id, name)``; ``None`` if it does not match."""
    match = _ICON_RE.match(filename)
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def target_path(out_dir: Path, pic_id: int, name: str, filetype: str) -> Path:
    """The description file for one icon: ``[id]_[name]_description.<ext>``."""
    if filetype not in ("md", "txt"):
        raise ValueError(f"unsupported filetype: {filetype!r}")
    return Path(out_dir) / f"{pic_id}_{name}_description.{filetype}"


def load_metadata(icons_dir: Path) -> dict[int, dict[str, Any]]:
    """Map ARASAAC id -> metadata entry from ``metadata_de.json`` (empty if absent)."""
    path = Path(icons_dir) / "metadata_de.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[int, dict[str, Any]] = {}
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict) or entry.get("_id") is None:
                continue
            try:
                result[int(entry["_id"])] = entry
            except (TypeError, ValueError):
                continue
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def metadata_context(entry: dict[str, Any] | None) -> dict[str, list[str]]:
    """Extract ``keywords``/``tags``/``categories`` from one metadata entry."""
    if not entry:
        return {"keywords": [], "tags": [], "categories": []}
    keywords: list[str] = []
    for item in entry.get("keywords") or []:
        if isinstance(item, dict):
            keyword = str(item.get("keyword", "")).strip()
            if keyword:
                keywords.append(keyword)
        elif item:
            keywords.append(str(item))
    tags = [str(value) for value in (entry.get("tags") or [])]
    categories = [str(value) for value in (entry.get("categories") or [])]
    return {
        "keywords": _dedupe(keywords),
        "tags": _dedupe(tags),
        "categories": _dedupe(categories),
    }


def build_prompt(name: str, pic_id: int, context: dict[str, list[str]], lang: str) -> str:
    """The instruction sent alongside the image; asks for German JSON output."""
    lang_name = LANGUAGE_NAMES.get(lang, lang)
    lines = [
        "Du beschreibst ein ARASAAC-Piktogramm für eine barrierefreie Kommunikationshilfe.",
        f"Antworte in der Sprache '{lang}' ({lang_name}).",
        "",
        f'Piktogramm: "{name}" (ARASAAC-ID {pic_id}).',
    ]
    for label, key in (
        ("Schlüsselwörter", "keywords"),
        ("Themen", "tags"),
        ("Kategorien", "categories"),
    ):
        values = context.get(key) or []
        if values:
            lines.append(f"{label}: {', '.join(values)}")
    lines += [
        "",
        "Beschreibe, was im Bild zu sehen ist, welche Bedeutung und Verwendung das",
        "Piktogramm hat und welche Synonyme passen.",
        "Antworte ausschließlich mit einem JSON-Objekt mit den Feldern:",
        '"description" (string), "visual" (string), "usage" (string), '
        '"synonyms" (list of strings), "caveats" (string or null).',
    ]
    return "\n".join(lines)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def render_description(data: dict[str, Any], pic_id: int, name: str, filetype: str) -> str:
    """Render the model's structured JSON into the description file body."""
    description = _as_text(data.get("description"))
    visual = _as_text(data.get("visual"))
    usage = _as_text(data.get("usage"))
    synonyms = [str(value) for value in (data.get("synonyms") or []) if str(value).strip()]
    caveats = _as_text(data.get("caveats")) or "Keine."

    if filetype == "md":
        parts = [
            f"# {name} (ARASAAC {pic_id})",
            "",
            "## Gezeigt im Bild",
            "",
            visual or "Keine Angabe.",
            "",
            "## Bedeutung und Verwendung",
            "",
            description or "Keine Angabe.",
        ]
        if usage:
            parts += ["", usage]
        parts += ["", "## Synonyme und Stichwörter", ""]
        parts += [f"- {value}" for value in synonyms] if synonyms else ["Keine."]
        parts += ["", "## Hinweise", "", caveats]
        return "\n".join(parts).rstrip() + "\n"

    parts = [
        f"{name} (ARASAAC {pic_id})",
        "",
        "Gezeigt im Bild:",
        visual or "Keine Angabe.",
        "",
        "Bedeutung und Verwendung:",
        description or "Keine Angabe.",
    ]
    if usage:
        parts += ["", usage]
    parts += ["", "Synonyme und Stichwörter:"]
    parts += [f"- {value}" for value in synonyms] if synonyms else ["Keine."]
    parts += ["", "Hinweise:", caveats]
    return "\n".join(parts).rstrip() + "\n"


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def parse_model_response(body: str) -> dict[str, Any]:
    """Extract the JSON description from a chat-completion body (or raw content)."""
    text = (body or "").strip()
    payload = _try_json(text)
    if isinstance(payload, dict) and "choices" in payload:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError("unexpected chat completion response shape") from exc
        text = str(content)
    elif isinstance(payload, dict):
        return payload

    result = _try_json(_strip_code_fence(text))
    if not isinstance(result, dict):
        raise ValueError(f"model response is not a JSON object: {text[:200]!r}")
    return result


def request_description(
    image_bytes: bytes,
    prompt: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float,
) -> str:
    """POST the image + prompt to an OpenAI-compatible endpoint, return the body."""
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
            "HTTP-Referer": HTTP_REFERER,
            "X-Title": APP_TITLE,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a same-directory temp file + ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def collect_targets(
    icons_dir: Path,
    out_dir: Path,
    filetype: str,
    *,
    force: bool = False,
    limit: int = 0,
) -> list[IconTarget]:
    """Icons to describe, naturally sorted by id, minus cached ones (unless forced)."""
    try:
        names = os.listdir(icons_dir)
    except FileNotFoundError:
        return []

    parsed: list[tuple[int, str, str]] = []
    for filename in names:
        if not filename.endswith(".png"):
            continue
        split = parse_icon_filename(filename)
        if split is None:
            continue
        parsed.append((split[0], split[1], filename))
    parsed.sort(key=lambda item: (item[0], item[2]))

    targets: list[IconTarget] = []
    for pic_id, name, filename in parsed:
        png = Path(icons_dir) / filename
        if not png.is_file():
            continue
        path = target_path(out_dir, pic_id, name, filetype)
        if not force and path.is_file() and path.stat().st_size > 0:
            continue
        targets.append(IconTarget(pic_id, name, png, path))

    if limit > 0:
        targets = targets[:limit]
    return targets


def _describe_icon(
    target: IconTarget,
    *,
    metadata: dict[int, dict[str, Any]],
    lang: str,
    filetype: str,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float,
    retries: int,
) -> str:
    """Describe one icon; returns ``"ok"`` or ``"failed"`` (never writes partials)."""
    image_bytes = target.png.read_bytes()
    context = metadata_context(metadata.get(target.pic_id))
    prompt = build_prompt(target.name, target.pic_id, context, lang)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            body = request_description(
                image_bytes,
                prompt,
                model=model,
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
            )
            data = parse_model_response(body)
            text = render_description(data, target.pic_id, target.name, filetype)
            write_text_atomic(target.path, text)
            return "ok"
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.25 * (2**attempt))

    print(
        f"  failed {target.pic_id}_{target.name}: {last_error}",
        file=sys.stderr,
        flush=True,
    )
    return "failed"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--icons-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--filetype", choices=("md", "txt"), default="md")
    parser.add_argument("--lang", default="de")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=os.environ.get(DEFAULT_API_KEY_ENV, ""))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.icons_dir is None:
        args.icons_dir = _default_icons_dir()
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    icons_dir: Path = args.icons_dir
    out_dir: Path = args.out_dir if args.out_dir is not None else icons_dir / "descriptions"

    targets = collect_targets(icons_dir, out_dir, args.filetype, force=args.force, limit=args.limit)

    if args.dry_run:
        for target in targets:
            print(target.path)
        print(f"{len(targets)} icon(s) to describe (dry run)", flush=True)
        return 0

    if not args.api_key:
        print(
            f"error: no API key (set {DEFAULT_API_KEY_ENV} or pass --api-key)",
            file=sys.stderr,
            flush=True,
        )
        return 2

    if not targets:
        print(f"Nothing to do: all descriptions present in {out_dir}", flush=True)
        return 0

    metadata = load_metadata(icons_dir)
    total = len(targets)
    counts = {"ok": 0, "failed": 0, "skipped": 0}
    print(f"Describing {total} icon(s) -> {out_dir}", flush=True)

    futures = {}
    interrupted = False
    executor = ThreadPoolExecutor(max_workers=args.workers)
    try:
        for target in targets:
            future = executor.submit(
                _describe_icon,
                target,
                metadata=metadata,
                lang=args.lang,
                filetype=args.filetype,
                model=args.model,
                base_url=args.base_url,
                api_key=args.api_key,
                timeout=args.timeout,
                retries=args.retries,
            )
            futures[future] = target
        for index, future in enumerate(as_completed(futures), 1):
            counts[future.result()] += 1
            print(
                f"  {index}/{total} "
                f"(ok={counts['ok']} skipped={counts['skipped']} failed={counts['failed']})",
                flush=True,
            )
    except KeyboardInterrupt:
        interrupted = True
        for future in futures:
            future.cancel()
    finally:
        executor.shutdown(wait=True)

    if interrupted:
        print(
            f"Interrupted: {counts} - re-run to resume where it stopped.",
            file=sys.stderr,
            flush=True,
        )
        return 130

    print(f"Done: {counts}", flush=True)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
