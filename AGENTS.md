# AGENTS.md — arasaac

Project-specific guide for agents working in `/workspaces/dev/arasaac`.
The container-wide guide at `/workspaces/dev/AGENTS.md` still applies; this file
adds what is specific to this project.

## What this is

A helper that turns a German text — a sentence, a situation, a rule, a routine
or a request — into an **ordered ARASAAC pictogram sequence** and renders it as
an image/PDF, so people with limited reading or language comprehension —
especially children in special education — can understand it.

- Idea and background: [`CONCEPT.md`](CONCEPT.md) (see §8 for the roadmap).
- Model rules (the "spec" of the representation): [`prompt.md`](prompt.md).
- Usage: [`README.md`](README.md).

## Architecture (how the pieces fit)

```
two front-ends, one core:

pi agent (.pi/agents/…) ──▶ pi extension (.pi/extensions/pictograms.ts) ─┐
                                                                       │ 4 word-based tools
MCP host (Claude, IDE, …)─▶ arasaac-mcp (src/arasaac_pictograms/mcp.py)─┘
                                        │
                                        ▼
                     src/arasaac_pictograms/catalog.py   (word → file, shared)
                                        │
                                        ▼
              layout.py (Pillow) + assets/fonts/   ← src/arasaac_pictograms/cli.py
                                        │
                                        ▼
        output/sheet_<epoch>.png  ·  MCP image content  ·  prompt.md + skills/
```

Two front-ends (the pi extension and the MCP server) share the same **word
contract** and renderer. `catalog.py` holds the word logic; keep `layout.py`
free of pi/agent specifics and keep LLM logic out of the core.

## Repo map

| Path | Role |
| --- | --- |
| `src/arasaac_pictograms/layout.py` | Pillow renderer: strip layout **and** the free layout engine (`render_layout`: grid/table, cards, canvas, arrows), colour frames, text, PNG/JPG/PDF export |
| `src/arasaac_pictograms/cli.py` | `make-sheet` CLI (entry point) |
| `src/arasaac_pictograms/catalog.py` | Word-based search/resolve (`Catalog`, `get_catalog`): the Python port of the pi extension's word logic |
| `src/arasaac_pictograms/mcp.py` | `arasaac-mcp` MCP server: 4 tools + prompt + resources (optional extra `mcp`) |
| `src/arasaac_pictograms/skill.py` | Locates/reads the generated Agent Skill for the MCP prompt/resource |
| `.pi/extensions/pictograms.ts` | pi tools: `search_pictograms`, `view_pictogram`, `render_pictogram_sheet`, `render_pictogram_layout` |
| `.pi/agents/pictogram-transcriber.md` | Agent definition: system prompt + `tools:` allowlist + pinned model |
| `scripts/run_transcriber.py` | Headless agent runner (only project tools) |
| `scripts/test_extension.mjs` | Offline tool tests (jiti + mock ExtensionAPI, no LLM) |
| `scripts/build_skill.py` | Generates `skills/` from `prompt.md` (`--check` for drift) |
| `scripts/test_mcp.py` | Offline catalog + MCP tests (in-memory client, no LLM) |
| `skills/arasaac-pictograms/` | **generated** Agent Skill (SKILL.md + `references/`); do not edit by hand |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore` | Self-contained image (code + fonts + 338 MB icons), no API key |
| `examples/mcp.json` | MCP host config template (stdio) |
| `download_icons.py` | Downloads the pictograms + `metadata_de.json` (stdlib only) |
| `assets/fonts/NotoSans-*.ttf` | Umlaut-capable fonts for captions |
| `icons/` | **gitignored**, ~338 MB, 13,828 × `[id]_[description].png` + `metadata_de.json` |
| `output/` | **gitignored**, generated sheets |
| `prompt.md`, `CONCEPT.md`, `README.md` | Docs |
| `examples/` | Sample layout JSON: `stundenplan.json` (grid), `karten.json` (cards + arrow) |

## Environment

- Python **3.13**, dependencies managed by **uv**. Core dependency: **Pillow**.
  The MCP server is an optional extra (FastMCP): `uv sync --extra mcp`.
- Run Python via `uv run …`. **Never `source .venv/bin/activate`** — `uv run`
  provisions the environment itself, and the tool shells out to it.
- There are **no system fonts** in the container and Pillow's bundled default
  (Aileron) does **not** render `ä ö ü ß`. The repo bundles Noto Sans; keep it.
  Override with `ARASAAC_FONT=/path/to/font.ttf` if ever needed.
- `icons/`, `.venv/`, `output/`, `__pycache__/` are gitignored. Keep it that way
  (icons are 338 MB; committing them would be a mistake).
- The MCP server writes every rendered sheet to `output/` for local debugging
  (`ARASAAC_OUTPUT_DIR`, `--output-dir`, `--no-save`). That local file is a
  convenience only — the image travels in the tool result; a server path is
  meaningless to a remote client.

## Common tasks

```bash
uv sync                          # install deps (Pillow)
uv sync --extra mcp              # + the MCP server (fastmcp)

# Render directly (filenames or the model's JSON contract):
uv run make-sheet --labels -o sheet.png -o sheet.pdf 2339_Auto.png 2909_Berg.png
uv run make-sheet --json result.json -o sheet.png
uv run make-sheet --help

# Free layouts (timetable, cards): a JSON with a `layout` tree + optional --page-size
uv run make-sheet --json examples/stundenplan.json --icons-dir icons \
  --page-size a4-landscape --icon-size 150 -o plan.png

# Offline tool tests (no LLM, fast):
node scripts/test_extension.mjs
uv run --extra mcp python scripts/test_mcp.py   # catalog + MCP server

# MCP server + skill:
uv run --extra mcp arasaac-mcp                  # stdio; add --transport http for HTTP
python scripts/build_skill.py                   # regenerate the skill from prompt.md
python scripts/build_skill.py --check           # fail if the skill is stale

# Container (self-contained, serves HTTP on :8000/mcp):
docker build -t arasaac-mcp . && docker run --rm -p 8000:8000 arasaac-mcp
docker run --rm -i arasaac-mcp --transport stdio   # stdio for a local host

# Run the agent end-to-end (needs a funded, vision-capable model):
python scripts/run_transcriber.py "Wenn es regnet, müssen alle Schüler drin bleiben."
python scripts/run_transcriber.py --mode json "…" > trace.jsonl   # full tool trace
```

## Hard-won invariants & gotchas

### Model / provider
- The agent's frontmatter pins `model: deepseek-v4.1-flash` and the runner passes
  `--model`. **Do not remove the pin:** without an explicit `--model`, pi may
  resolve to a different, unfunded provider and return `401 CreditsError`.
- The model **must accept images** — `view_pictogram` sends pictograms. Most
  Claude/GPT/DeepSeek-vision models do; check with `pi --list-models` (`images`
  column) before switching.

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
- `resolveWord()` prefers the candidate whose *plain* label matches the query,
  so `Auto` → the icon labelled `Auto`, not `Auto (KFZ)`.
- `render_pictogram_sheet` takes `words` (and optional parallel `roles`), not
  files. It writes `output/sheet_<epoch>.png` via `uv run make-sheet --json`.
- `render_pictogram_layout` takes a **layout tree** whose icon nodes use `word`
  (a bare string is an icon shorthand, a list becomes a column). The extension
  resolves every word to `file`/`concept` before writing the contract, so
  `layout.py` never sees words. Python-side node types: `icon`, `text`, `row`,
  `column`, `card`, `grid`/`table`, `arrow`, `spacer`, `divider`, `canvas`.
  Rendering it uses the same `uv run make-sheet --json` path (the CLI detects a
  `layout` key and calls `render_layout_and_save`).

### Word logic exists twice — keep it in sync
- The word contract is implemented in **two languages**: TypeScript for the pi
  extension (`.pi/extensions/pictograms.ts`) and Python for the MCP server
  (`src/arasaac_pictograms/catalog.py`). They must behave identically. When you
  change search/resolve/label logic, change **both** and run both offline tests
  (`node scripts/test_extension.mjs`, `uv run --extra mcp python scripts/test_mcp.py`).
- `catalog.py` is Pillow-free and holds only the word→pictogram mapping; the MCP
  server (`mcp.py`) does the rendering. Keep LLM logic out of both — the MCP
  server runs **no** model; the host brings it.

### The skill is generated, not hand-written
- `skills/arasaac-pictograms/` is generated from `prompt.md` by
  `scripts/build_skill.py`. Never edit the generated files by hand; edit
  `prompt.md` and re-run the generator. `--check` fails on drift.
- `prompt.md` is the single source: the pi agent body is exactly `prompt.md`, and
  the MCP prompt/resource serve the generated skill. Keep them identical.

### The pi agent is locked down
- `scripts/run_transcriber.py` runs pi with:
  `--no-session --no-extensions --no-skills --no-context-files -e <extension>
  --tools search_pictograms,view_pictogram,render_pictogram_sheet,render_pictogram_layout`.
  Keep it that way: the point is that the agent can call **only** project tools.
- To add a tool: register it in `.pi/extensions/pictograms.ts` **and** add its
  name to `tools:` in the agent frontmatter.
- Project-local `.pi/` resources load only in trusted projects; the runner
  avoids that by loading the extension explicitly with `-e`.

### Rendering
- `make-sheet` outputs format by extension: `.png`, `.jpg`, `.pdf`.
- Roles (Fitzgerald key, `ROLE_COLORS` in `layout.py`): `PERSON` yellow,
  `NOUN` orange, `VERB` green, `QUALITY` blue, `SOCIAL` pink, `MISC` grey.
- Roles can only be passed via `--json` (the contract's `sequence[].role`).
- Pictograms are transparent palette PNGs; the renderer composites them onto
  the background, so keep using RGBA compositing.

### `scripts/test_extension.mjs`
- Loads the TypeScript extension with **jiti** (from the pi install) and a mock
  `ExtensionAPI`. It needs `typebox` aliased to the `.mjs` build explicitly
  (ESM `exports` map); the mock `exec` really runs `uv run make-sheet`.
- It hardcodes `PI=/opt/proto/tools/node/22.23.2/…`; update it if the pi/node
  paths change.

## Conventions

- The input is **not necessarily a sentence**: first work out the goal and the
  core message. A request for a picture (`Ich brauche eine Darstellung von …`)
  is satisfied by depicting its content, never the request itself.
- Design for **very easy understanding** (special-education children): concrete
  icons only, everyday words, one message per strip, aim ≤ 5 pictograms, order =
  meaning (first … then). See `prompt.md` §2.
- Follow the **message order** by default; reduce function words; prefer one
  icon that already encodes several concepts (e.g. the red `Auto`).
- The transcriber **communicates in German** (replies, `sentence` header,
  `meaning`, `notes`, alternative labels) even though the prompt itself is
  English. The rule lives in `prompt.md` §0 and the agent prompt — keep both in
  sync.
- Never emit a misleading icon; verify ambiguous candidates with
  `view_pictogram` (see `prompt.md` for known traps: `verbleiben`, `vor`).
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
