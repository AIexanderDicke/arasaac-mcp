# ARASAAC pictogram strips

Turn an ordered list of ARASAAC pictograms into a single image or PDF — a
*sentence strip* for AAC (augmentative and alternative communication).

The bundled agent goes one step further: it takes a German text — a sentence,
a situation, a rule, a routine or a request — and **designs** the pictogram
sequence that conveys it as clearly as possible. The target audience is people
with limited reading or language comprehension, especially **children in
special education**. See [`prompt.md`](./prompt.md) for the rules and
[`CONCEPT.md`](./CONCEPT.md) for the background.

## Install

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

This installs [Pillow](https://python-pillow.org/) (image composition, can also
write one-page PDFs). Noto Sans fonts (umlaut-capable) live in `assets/fonts/`.

## Usage

```bash
# minimal: just the ordered filenames
uv run make-sheet 2339_Auto.png 2909_Berg.png -o strip.png

# with the written sentence, paraphrased meaning and per-icon labels
uv run make-sheet \
  --sentence "Wenn es regnet, müssen alle Schüler drin bleiben." \
  --meaning  "Bei Regen bleiben alle Schüler im Gebäude." \
  --labels \
  -o strip.png -o strip.pdf \
  3123_Regen.png 36081_alle.png 32666_Schüler.png 5439_drinnen.png

# straight from the model output contract (roles -> Fitzgerald colour frames)
uv run make-sheet --json result.json -o strip.png
uv run make-sheet --json result.json --alternative mit-verpflichtung -o alt.pdf
```

Filenames may be given as positional arguments (space/comma separated), or on
stdin with `-`. Output format is chosen by the extension: `.png`, `.jpg`, `.pdf`.

### Free layouts (tables, cards, canvases)

Pass a `--json` file with a `layout` tree instead of a `sequence` to arrange the
pictograms in **more than one dimension** — a timetable, a card sheet, or free
absolute positions:

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

```bash
uv run make-sheet --json stundenplan.json --page-size a4-landscape -o plan.png
```

Node types (all sizes in px; see `src/arasaac_pictograms/layout.py`):

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
[`examples/`](./examples).

### Options

| Option | Meaning |
| --- | --- |
| `-o/--output FILE` | Output path, repeatable. Default `pictogram_strip.png`. |
| `--json FILE` | Read `{sentence, meaning, sequence, alternatives}` **or** a `{layout}` tree. |
| `--alternative N\|LABEL` | Render an alternative from the JSON instead. |
| `--sentence/--meaning TEXT` | Header / sub-header text. |
| `--labels` | Print the pictogram description under each icon. |
| `--no-frames` | Disable Fitzgerald colour frames. |
| `--no-attribution` | Hide the “Piktogramme: ARASAAC (CC BY-NC-SA)” credit. |
| `--icon-size N` | Icon box size in px (default 300). |
| `--columns N` / `--max-columns N` | Force / limit the column count (default wraps at 6). |
| `--page-size SIZE` | Fixed page for layouts: `a4`, `a4-landscape`, `letter` or `WxH`. |
| `--scale N` | Supersampling factor (default 2 → crisp PNG/PDF). |

Roles and their colours: `PERSON` yellow, `NOUN` orange, `VERB` green,
`QUALITY` blue, `SOCIAL` pink, `MISC` grey.

## Agent (pi)

The agent works on **any German input**, not just sentences. It first works out
the goal and core message, then designs a sequence that is understandable from
the pictures alone (concrete icons, everyday words, ≤ ~5 pictograms, order =
meaning). The rules live in [`prompt.md`](./prompt.md).

`.pi/extensions/pictograms.ts` registers four **word-based** tools (the agent
never sees numeric IDs or file names):

| Tool | Purpose |
| --- | --- |
| `search_pictograms({ query })` | Search German keywords + ARASAAC metadata (synonyms, tags); returns words. Shared words get a qualifier, e.g. `Auto (KFZ)`. |
| `view_pictogram({ word })` | Return the pictogram image for visual verification. |
| `render_pictogram_sheet({ words, roles?, sentence?, meaning? })` | Render the ordered words to a single strip image. |
| `render_pictogram_layout({ layout, sentence?, page_size? })` | Render a free arrangement — timetable `grid`, `card`s with `arrow`s, or a `canvas`. Icon nodes use `word`. |

`.pi/agents/pictogram-transcriber.md` holds the system prompt and a `tools:`
allowlist, so the agent can call **only** these four tools. The model is pinned
in its frontmatter (`model: deepseek-v4.1-flash`).

The agent talks **German**: replies, the `sentence` header, the `meaning`
explanation, the `notes` and alternative labels are all in German, regardless
of the English tool output. See [`prompt.md`](./prompt.md) §0.

```bash
# Run the agent headless (uses only the project tools):
python scripts/run_transcriber.py "Wenn es regnet, müssen alle Schüler drin bleiben."
python scripts/run_transcriber.py --mode json "…" > trace.jsonl   # full tool trace

# Test the tools without an LLM:
node scripts/test_extension.mjs
```

Rendering runs `uv run make-sheet`, so **no venv activation is needed**.

## Library

```python
from arasaac_pictograms import Entry, SheetOptions, render_and_save, render_layout_and_save

render_and_save(
    [Entry("icons/3123_Regen.png", role="NOUN"), "36081_alle.png"],
    ["strip.png", "strip.pdf"],
    SheetOptions(sentence="Es regnet.", labels=True),
    icons_dir="icons",
)

# Free layout: a small grid.
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

## Files

- `download_icons.py` — download all ARASAAC pictograms for a language.
- `icons/` — ~13,800 pictograms (`[id]_[description].png`).
- `src/arasaac_pictograms/layout.py` — Pillow-based composition (strips + free layout trees).
- `src/arasaac_pictograms/cli.py` — the `make-sheet` command.
- `examples/` — sample layout JSON (timetable, cards).
- `prompt.md` — rules for the model that picks the pictograms.
- `CONCEPT.md` — concept and background.

## License

ARASAAC pictograms are **CC BY-NC-SA**. See `CONCEPT.md`.
