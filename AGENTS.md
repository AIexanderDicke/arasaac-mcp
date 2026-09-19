# AGENTS.md — arasaac

Project-specific guide for agents working in `/workspaces/dev/arasaac`.
The container-wide guide at `/workspaces/dev/AGENTS.md` still applies; this file
adds what is specific to this project and is the **single setup/usage reference**
(the [`README.md`](README.md) is deliberately a short human overview).

## What this is

A helper that turns a German text — a sentence, a situation, a rule, a routine
or a request — into an **ordered ARASAAC pictogram sequence** and renders it as
an image/PDF, so people with limited reading or language comprehension —
especially children in special education — can understand it.

- Idea and background: [`CONCEPT.md`](CONCEPT.md) (see §8 for the roadmap).
- Model rules (the "spec" of the representation): [`scripts/prompt.md`](scripts/prompt.md).
- User-facing overview: [`README.md`](README.md).

## Architecture (how the pieces fit)

```
one front-end, one core:

MCP host (Claude, IDE, …) ─▶ arasaac-mcp (src/arasaac_pictograms/mcp.py)
                                        │ 4 word-based tools
                                        ▼
                     src/arasaac_pictograms/catalog.py   (word → file)
                                        │
                                        ▼
              layout.py (Pillow) + assets/fonts/   ← src/arasaac_pictograms/cli.py
                                        │
                                        ▼
        output/sheet_<epoch>.png  ·  MCP image content  ·  scripts/prompt.md + skills/
```

The MCP server owns the **word contract** and the renderer. `catalog.py` holds the
word logic; keep `layout.py` free of host specifics and keep LLM logic out of the
core.

## Repo map

| Path | Role |
| --- | --- |
| `src/arasaac_pictograms/layout.py` | Pillow renderer: strip layout **and** the free layout engine (`render_layout`: grid/table, cards, canvas, arrows), colour frames, text, PNG/JPG/PDF export |
| `src/arasaac_pictograms/cli.py` | `make-sheet` CLI (entry point) |
| `src/arasaac_pictograms/catalog.py` | Word-based search/resolve (`Catalog`, `get_catalog`): the word→pictogram mapping underneath the tools |
| `src/arasaac_pictograms/mcp.py` | `arasaac-mcp` MCP server: 4 tools + prompt + resources (optional extra `mcp`) |
| `src/arasaac_pictograms/skill.py` | Locates/reads the generated Agent Skill for the MCP prompt/resource |
| `scripts/build_skill.py` | Generates `skills/` from `scripts/prompt.md` (`--check` for drift) |
| `scripts/test_mcp.py` | Offline catalog + MCP tests (in-memory client, no LLM) |
| `scripts/mcp_up.sh` | Start/restart relay + MCP server in tmux without killing the VS Code forwarded port |
| `scripts/port_relay.py` | Stable TCP relay in front of the MCP server (keeps the forwarded port bound) |
| `skills/arasaac-pictograms/` | **generated** Agent Skill (SKILL.md + `references/`); do not edit by hand |
| `Dockerfile`, `Dockerfile.icons`, `docker-compose.yml`, `.dockerignore` | App image (code + fonts) and the ~338 MB icon base image it is based on; no API key |
| `.github/workflows/` | `docker.yml` builds the app image; `icons-image.yml` publishes the icon base image (the only job that hits ARASAAC) |
| `examples/mcp.json` | MCP host config template (stdio) |
| `scripts/download_icons.py` | Downloads the pictograms + `metadata_de.json` (stdlib only) |
| `assets/fonts/NotoSans-*.ttf` | Umlaut-capable fonts for captions |
| `icons/` | **gitignored**, ~338 MB, 13,828 × `[id]_[description].png` + `metadata_de.json` |
| `output/` | **gitignored**, generated sheets |
| `scripts/prompt.md`, `CONCEPT.md`, `README.md` | Docs |
| `examples/` | Sample layout JSON: `stundenplan.json` (grid), `karten.json` (cards + arrow) |

## Setup

- Python **3.13**, dependencies managed by **uv**. Core dependency: **Pillow**.
  The MCP server is an optional extra (FastMCP).
- Run Python via `uv run …`. **Never `source .venv/bin/activate`** — `uv run`
  provisions the environment itself, and the tools shell out to it.

```bash
uv sync                          # install deps (Pillow)
uv sync --extra mcp              # + the MCP server (fastmcp)
```

- **Icons are not in git** (`icons/`, ~338 MB). Fetch them once (stdlib only,
  no deps needed):

```bash
uv run python scripts/download_icons.py --lang de --size 500   # writes icons/ + metadata_de.json
```

- There are **no system fonts** in the container and Pillow's bundled default
  (Aileron) does **not** render `ä ö ü ß`. The repo bundles Noto Sans; keep it.
- `icons/`, `.venv/`, `output/`, `__pycache__/` are gitignored. Keep it that way
  (icons are 338 MB; committing them would be a mistake).

### Environment variables

| Variable | Used by | Meaning |
| --- | --- | --- |
| `ARASAAC_ICONS_DIR` | catalog, MCP | Pictogram directory (default `./icons`, else `../icons`) |
| `ARASAAC_OUTPUT_DIR` | MCP | Where debug renders are written (default `./output`) |
| `ARASAAC_PUBLIC_BASE_URL` | MCP | Base URL for image links (default `http://localhost:8000`) |
| `ARASAAC_TRANSPORT` | MCP | `stdio` (default), `http` or `sse` |
| `ARASAAC_HOST` / `ARASAAC_PORT` | MCP | HTTP/SSE bind address (default `127.0.0.1:8000`) |
| `ARASAAC_SKILL_DIR` | skill | Override the generated skill location |
| `ARASAAC_FONT` | layout | Override the bundled Noto Sans font |
| `ARASAAC_PORT` / `ARASAAC_INTERNAL_PORT` | `mcp_up.sh` | Public relay port (`8000`) / internal server port (`8001`) |
| `ARASAAC_HOST` | `mcp_up.sh` | Internal server host (default `127.0.0.1`) |
| `ARASAAC_RELAY_SESSION` / `ARASAAC_MCP_SESSION` | `mcp_up.sh` | tmux session names |

## Usage

### CLI — `make-sheet`

```bash
uv run make-sheet --labels -o sheet.png -o sheet.pdf 2339_Auto.png 2909_Berg.png
uv run make-sheet --json result.json -o sheet.png
uv run make-sheet --help
```

Filenames are positional (space/comma separated) or on stdin with `-`; the
output format is chosen by extension (`.png`, `.jpg`, `.pdf`). `--json` reads
either the model output contract (`{sentence, meaning, sequence, alternatives}`,
roles → Fitzgerald colour frames) or a free `{layout}` tree. Roles can only be
passed via `--json` (`sequence[].role`).

Key options (full list in `cli.py`): `-o/--output` (repeatable, default
`pictogram_strip.png`), `--json`, `--alternative N|LABEL`, `--sentence`,
`--meaning`, `--labels`, `--no-frames`, `--no-attribution`, `--icon-size`
(300), `--columns`, `--max-columns` (6), `--gap` (28), `--margin` (48),
`--padding` (16), `--scale` (2), `--dpi` (96), `--page-size`.

Roles (Fitzgerald key, `ROLE_COLORS` in `layout.py`): `PERSON` yellow,
`NOUN` orange, `VERB` green, `QUALITY` blue, `SOCIAL` pink, `MISC` grey.

### Free layouts (timetables, cards, canvases)

Pass a `--json` file with a `layout` tree to arrange pictograms in more than one
dimension:

```bash
uv run make-sheet --json examples/stundenplan.json --icons-dir icons \
  --page-size a4-landscape --icon-size 150 -o plan.png
```

```json
{
  "sentence": "Mein Stundenplan",
  "layout": {
    "type": "grid",
    "columns": ["Montag", "Dienstag"],
    "rows": [
      {"header": "1.", "cells": ["36373_Mathe.png", "10258_Sport.png"]},
      {"header": "2.", "cells": ["24503_Pause.png", "24903_Schwimmen.png"]}
    ]
  }
}
```

Node types (all sizes in px; see `layout.py`):

| Node | Purpose |
| --- | --- |
| `icon` | one pictogram (`file`, `role?`, `concept?`, `size?`, `show_label?`, `frame?`) |
| `text` | caption/heading (`text`, `size?`, `bold?`, `align?`, `color?`) |
| `row` / `column` | children laid out horizontally / stacked (`children`, `gap?`, `align?`, `padding?`) |
| `card` | framed column (`border?`, `border_width?`, `dashed?`, `radius?`, `background?`) |
| `grid` (alias `table`) | timetable/table (`columns`, `rows` with `header`+`cells`, `border?`, `header_background?`) |
| `arrow` | connector (`direction?`, `length?`, `thickness?`, `color?`) |
| `spacer` / `divider` | empty space / a line |
| `canvas` | free placement (`width?`, `height?`, `children` of `{x, y, node}`) |

Lists are stacked as columns; a bare string is an icon shorthand. A complete
card sheet (`row` of `card`s + `arrow`, dashed consequence boxes) is in
[`examples/`](./examples). `--page-size` accepts `a4`, `a4-landscape`, `letter`
or `WxH`.

### MCP server — `arasaac-mcp`

The host brings the model; the server runs **no LLM** and needs **no API key** —
it only searches, shows and renders pictograms.

```bash
uv run --extra mcp arasaac-mcp                    # stdio (default)
uv run --extra mcp arasaac-mcp --transport http   # streamable HTTP on /mcp
uv run --extra mcp python scripts/test_mcp.py     # offline tests, no LLM
```

| Surface | Name | Purpose |
| --- | --- | --- |
| tool | `search_pictograms` | German word search (descriptions + metadata) |
| tool | `view_pictogram` | pictogram icon — URL-based (image block only with `--no-save`) |
| tool | `render_pictogram_sheet` | ordered word sequence → strip image |
| tool | `render_pictogram_layout` | layout tree (grid/cards/canvas) → image |
| prompt | `pictogram_transcriber` | full recipe + the German text |
| resource | `arasaac://skill` | the Agent Skill (`SKILL.md`) |
| resource | `arasaac://rules` | the full recipe (skill + references) |
| HTTP | `GET /sheet/<name>` | serves a rendered sheet/icon PNG |

Rendered sheets and viewed icons are saved to `output/` (override with
`--output-dir` / `ARASAAC_OUTPUT_DIR`, disable with `--no-save`) and served
under `/sheet/<name>`; the tool's text block reports the URL. The base URL
defaults to `http://localhost:8000` (`ARASAAC_PUBLIC_BASE_URL`).

#### Connecting a host

The server speaks **stdio** (default) or **streamable HTTP** (`/mcp`). A stdio
entry (Claude Desktop, Claude Code, …) looks like
[`examples/mcp.json`](examples/mcp.json):

```json
{
  "mcpServers": {
    "arasaac-pictograms": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "arasaac-mcp"],
      "cwd": "/path/to/arasaac",
      "env": { "ARASAAC_ICONS_DIR": "/path/to/arasaac/icons" }
    }
  }
}
```

For a long-running container or HTTP host, point the client at
`http://HOST:8000/mcp` instead.

#### Keeping the forwarded port alive (VS Code)

The VS Code port forwarder binds once and does not retry, so restarting the MCP
server would kill the forwarded port. `scripts/port_relay.py` keeps a permanent
listener and re-resolves its upstream per connection:

```bash
scripts/mcp_up.sh                # start relay (8000) + server (8001)
scripts/mcp_up.sh --force        # restart only the MCP server
```

Both run in tmux (`arasaac-relay`, `arasaac-mcp`); logs in
`/tmp/arasaac-relay.log` and `/tmp/arasaac-mcp.log`.

### Skill generation

`skills/arasaac-pictograms/` (SKILL.md + on-demand `references/`) is generated
from `scripts/prompt.md` — the single source of truth:

```bash
python scripts/build_skill.py           # regenerate after editing scripts/prompt.md
python scripts/build_skill.py --check   # fail if the skill is stale
```

### Docker

Two images:

- `Dockerfile.icons` → the **icon base image**
  (`ghcr.io/aiexanderdicke/arasaac-icons:de-500`), which only adds the ~338 MB
  pictogram set. It is published rarely by the `Icon base image` workflow — the
  one job that downloads from ARASAAC.
- `Dockerfile` → the **app image**, based on the icon image and adding code and
  fonts. Layers are shared, so CI and code-only rebuilds never re-copy the
  icons.

The image bundles code, fonts and pictograms, so it runs **offline** and needs
**no API key**:

```bash
docker build -t arasaac-mcp .          # pulls the published icon base image
docker run --rm -p 8000:8000 arasaac-mcp --transport http --host 0.0.0.0   # :8000/mcp
docker run --rm -i arasaac-mcp --transport stdio                            # stdio
docker compose up --build                                                   # HTTP + output volume
```

Compose sets transport/host/port via `ARASAAC_TRANSPORT` / `ARASAAC_HOST` /
`ARASAAC_PORT` (CLI flags override). The container runs unprivileged with a
writable `output` volume.

To build fully locally (no GHCR), build the base once from a checkout that has
`icons/` and point the app build at it:

```bash
uv run python scripts/download_icons.py --lang de --size 500
docker build -f Dockerfile.icons -t arasaac-icons:de-500 .
docker build --build-arg ICONS_IMAGE=arasaac-icons:de-500 -t arasaac-mcp .
```

### Library

```python
from arasaac_pictograms import Entry, SheetOptions, render_and_save, render_layout_and_save

render_and_save(
    [Entry("icons/3123_Regen.png", role="NOUN"), "36081_alle.png"],
    ["strip.png", "strip.pdf"],
    SheetOptions(sentence="Es regnet.", labels=True),
    icons_dir="icons",
)

render_layout_and_save(
    {
        "sentence": "Stundenplan",
        "layout": {
            "type": "grid",
            "columns": ["Montag", "Dienstag"],
            "rows": [{"header": "1.", "cells": ["36373_Mathe.png", "10258_Sport.png"]}],
        },
    },
    ["stundenplan.png"],
    SheetOptions(page_size="a4-landscape", labels=False),
    icons_dir="icons",
)
```

## Hard-won invariants & gotchas

### Model / provider
- The host brings the model; the MCP server runs none. The model **must accept
  images** — `view_pictogram` sends pictograms. Most Claude/GPT/DeepSeek-vision
  models do.

### The agent tool contract is WORD-BASED
- The agent must **never** see or handle numeric IDs or file names. It searches
  and refers to pictograms by German words only; tools resolve words to files.
- `search_pictograms` searches filenames **and** `metadata_de.json` (German
  `keywords`, English `tags`/`categories`) and returns words, not files.
- Matching is **AND** across query tokens; a token that matches nothing yields
  no results. Stem matching is forgiving (`rotes`→`rot`, `Autos`→`Auto`).
- Many words map to several icons. Search disambiguates by appending a unique
  synonym: `Auto (KFZ)`, `Schüler (Student)`. **Labels must round-trip**: the
  label shown in a search result must resolve back to the same pictogram. The
  offline test enforces this.
- `Catalog.resolve()` prefers the candidate whose *plain* label matches the
  query, so `Auto` → the icon labelled `Auto`, not `Auto (KFZ)`.
- `render_pictogram_sheet` takes `words` (and optional parallel `roles`), not
  files. It writes `output/sheet_<epoch>.png` via `uv run make-sheet --json`.
- `render_pictogram_layout` takes a **layout tree** whose icon nodes use `word`
  (a bare string is an icon shorthand, a list becomes a column). The MCP server
  resolves every word to `file`/`concept` before writing the contract, so
  `layout.py` never sees words. Python-side node types: `icon`, `text`, `row`,
  `column`, `card`, `grid`/`table`, `arrow`, `spacer`, `divider`, `canvas`.
  Rendering it uses the same `uv run make-sheet --json` path (the CLI detects a
  `layout` key and calls `render_layout_and_save`).

### Word logic lives in Python
- The word contract is implemented in `src/arasaac_pictograms/catalog.py`.
  When you change search/resolve/label logic, run the offline test
  (`uv run --extra mcp python scripts/test_mcp.py`).
- `catalog.py` is Pillow-free and holds only the word→pictogram mapping; the MCP
  server (`mcp.py`) does the rendering. Keep LLM logic out of both — the MCP
  server runs **no** model; the host brings it.

### The skill is generated, not hand-written
- `skills/arasaac-pictograms/` is generated from `scripts/prompt.md` by
  `scripts/build_skill.py`. Never edit the generated files by hand; edit
  `scripts/prompt.md` and re-run the generator. `--check` fails on drift.
- `scripts/prompt.md` is the single source: the MCP prompt/resource serve the generated
  skill. Keep them identical.

### Image delivery: web preview (no widget, no inline base64)
- An `image` content block reaches the model but is **not shown to the user** in
  most hosts, and dumping base64 into the result lands as a raw text blob in
  the chat (observed in the ChatGPT desktop app). A tried MCP Apps widget
  (`ui://` + ext-apps bridge) rendered, but the sandbox blocked both inline
  `data:` images and `http://localhost` loads — so the widget was removed.
- Instead: the render tools save the PNG to `output/`, serve it via a fastmcp
  `custom_route` (`GET /sheet/<name>` under `ARASAAC_PUBLIC_BASE_URL`, default
  `http://localhost:8000` — matches the container port-forward used by the
  ChatGPT desktop app) and report the URL in the **text block**.
- The **model must echo the URL as a plain link** in its reply — that is what
  produces the host's web preview card: ChatGPT renders URLs in the assistant
  message client-side (localhost reachable). The render tools' descriptions
  say so, and forbid the markdown-image form (`![…]`), which ChatGPT loads
  through a backend proxy that cannot reach localhost (broken image).
- **No `structuredContent` in render results** — ChatGPT dumps it as a raw
  JSON object into the chat. Everything travels in the text block.
- **`view_pictogram` is URL-based too** (same reason): the icon is copied into
  `output/` as `icon_<ts>_<id>_<name>.png`, served under `/sheet/`, and the
  result is text-only. An image content block is returned only without saving
  (`--no-save`) for hosts that pass images to the model. Its description also
  forbids the markdown-image echo.
- Don't inline base64 PNGs in the result either — that produces the giant
  blob. `--no-save` still returns an image content block for the model.

### Rendering
- `make-sheet` outputs format by extension: `.png`, `.jpg`, `.pdf`.
- Roles (Fitzgerald key, `ROLE_COLORS` in `layout.py`): `PERSON` yellow,
  `NOUN` orange, `VERB` green, `QUALITY` blue, `SOCIAL` pink, `MISC` grey.
- Roles can only be passed via `--json` (the contract's `sequence[].role`).
- Pictograms are transparent palette PNGs; the renderer composites them onto
  the background, so keep using RGBA compositing.

## Conventions

- The input is **not necessarily a sentence**: first work out the goal and the
  core message. A request for a picture (`Ich brauche eine Darstellung von …`)
  is satisfied by depicting its content, never the request itself.
- Design for **very easy understanding** (special-education children): concrete
  icons only, everyday words, one message per strip, aim ≤ 5 pictograms, order =
  meaning (first … then). See `scripts/prompt.md` §2.
- Follow the **message order** by default; reduce function words; prefer one
  icon that already encodes several concepts (e.g. the red `Auto`).
- The transcriber **communicates in German** (replies, `sentence` header,
  `meaning`, `notes`, alternative labels) even though the prompt itself is
  English. The rule lives in `scripts/prompt.md` §0.
- Never emit a misleading icon; verify ambiguous candidates with
  `view_pictogram` (see `scripts/prompt.md` for known traps: `verbleiben`, `vor`).
- Aim ≤ 5 pictograms, hard cap ~8.
- Keep this file and `README.md`/`CONCEPT.md` in sync when the architecture
  changes.

## Licensing & secrets

- ARASAAC pictograms are **CC BY-NC-SA** (attribution, non-commercial,
  share-alike). The renderer adds an attribution footer by default; keep it.
- Secrets are environment variables only. Never write API keys to files.

## Git

- Branch `feat/mcp-skill` for the MCP + skill work (base commit 177f0a9).
  `master` and `main` hold the pre-existing history; a remote `origin`
  (`github.com/AIexanderDicke/arasaac-mcp.git`) now exists — do not push unless
  asked.
- Generated/vendored content is ignored. Before committing, confirm
  `git status --short` shows only intended source/doc changes.
