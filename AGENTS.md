# AGENTS.md — arasaac

Project-specific guide for agents working in `/workspaces/dev/arasaac`.
The container-wide guide at `/workspaces/dev/AGENTS.md` still applies; this file
adds what is specific to this project.

## What this is

A helper that turns a German sentence into an **ordered ARASAAC pictogram
sequence** and renders it as an image/PDF, so people with limited reading or
language comprehension can understand the sentence.

- Idea and background: [`CONCEPT.md`](CONCEPT.md) (see §8 for the roadmap).
- Model rules (the "spec" of the transcription): [`prompt.md`](prompt.md).
- Usage: [`README.md`](README.md).

## Architecture (how the pieces fit)

```
pi agent (.pi/agents/pictogram-transcriber.md)
  │  system prompt from prompt.md + tools allowlist
  ▼
pi extension (.pi/extensions/pictograms.ts)  → 3 word-based tools
  │  render_pictogram_sheet
  ▼
uv run make-sheet  (src/arasaac_pictograms/cli.py)
  ▼
src/arasaac_pictograms/layout.py  (Pillow) + assets/fonts/
  ▼
output/sheet_<epoch>.png
```

Two consumers share the same renderer: the pi tools now, and (planned) an
MCP server + skill later. Keep `layout.py` free of pi/agent specifics.

## Repo map

| Path | Role |
| --- | --- |
| `src/arasaac_pictograms/layout.py` | Pillow renderer: grid/strip layout, colour frames, text, PNG/JPG/PDF export |
| `src/arasaac_pictograms/cli.py` | `make-sheet` CLI (entry point) |
| `.pi/extensions/pictograms.ts` | pi tools: `search_pictograms`, `view_pictogram`, `render_pictogram_sheet` |
| `.pi/agents/pictogram-transcriber.md` | Agent definition: system prompt + `tools:` allowlist + pinned model |
| `scripts/run_transcriber.py` | Headless agent runner (only project tools) |
| `scripts/test_extension.mjs` | Offline tool tests (jiti + mock ExtensionAPI, no LLM) |
| `download_icons.py` | Downloads the pictograms + `metadata_de.json` (stdlib only) |
| `assets/fonts/NotoSans-*.ttf` | Umlaut-capable fonts for captions |
| `icons/` | **gitignored**, ~338 MB, 13,828 × `[id]_[description].png` + `metadata_de.json` |
| `output/` | **gitignored**, generated sheets |
| `prompt.md`, `CONCEPT.md`, `README.md` | Docs |

## Environment

- Python **3.13**, dependencies managed by **uv**. Only dependency: **Pillow**.
- Run Python via `uv run …`. **Never `source .venv/bin/activate`** — `uv run`
  provisions the environment itself, and the tool shells out to it.
- There are **no system fonts** in the container and Pillow's bundled default
  (Aileron) does **not** render `ä ö ü ß`. The repo bundles Noto Sans; keep it.
  Override with `ARASAAC_FONT=/path/to/font.ttf` if ever needed.
- `icons/`, `.venv/`, `output/`, `__pycache__/` are gitignored. Keep it that way
  (icons are 338 MB; committing them would be a mistake).

## Common tasks

```bash
uv sync                          # install deps (Pillow)

# Render directly (filenames or the model's JSON contract):
uv run make-sheet --labels -o sheet.png -o sheet.pdf 2339_Auto.png 2909_Berg.png
uv run make-sheet --json result.json -o sheet.png
uv run make-sheet --help

# Offline tool tests (no LLM, fast):
node scripts/test_extension.mjs

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

### The pi agent is locked down
- `scripts/run_transcriber.py` runs pi with:
  `--no-session --no-extensions --no-skills --no-context-files -e <extension>
  --tools search_pictograms,view_pictogram,render_pictogram_sheet`.
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

- Output the **sentence order** by default; reduce function words; prefer one
  icon that already encodes several concepts (e.g. the red `Auto`).
- The transcriber **communicates in German** (replies, `meaning`, `notes`,
  alternative labels) even though the prompt itself is English. The rule lives
  in `prompt.md` §0 and the agent prompt — keep both in sync.
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

- Branch `master`, one initial commit, **no remote** configured.
- Generated/vendored content is ignored. Before committing, confirm
  `git status --short` shows only intended source/doc changes.
