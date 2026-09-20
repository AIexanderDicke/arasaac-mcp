# A more general layout engine

*Growing the layout tree in [`arasaac_mcp/layout.py`](../arasaac_mcp/layout.py)
from a single sheet into multi-page documents with pagination and templates.*

## 1. Goal and problem

A sentence strip is the default, but not every message is a straight line. The
layout tree (`render_layout`) already covers tables, cards, arrows and free
placement. What is still missing is **multiple pages per document, presets and
automatic breaks for long tables**.

Today `render_layout` renders exactly **one** canvas: the width/height is
`max(content, page_size)`, there is one global header (`sentence`/`meaning`) and
a fixed attribution. When the content grows past the page, the image simply
grows instead of breaking.

**Goal:** a document model with multiple pages, automatic pagination and
reusable templates — without breaking the strip path or the MCP signature.

## 2. Current state in code

### 2.1 Two render paths

- `render_sheet` draws the classic strip from `Entry` objects; `render_and_save`
  writes it.
- `render_layout` draws a tree; `render_layout_and_save` saves it.
- `SheetOptions` carries every visual parameter (`gap`, `margin`, `padding`,
  `icon_size`, `page_size`, `text_size`, `label_size`, `title_size`,
  `min_content_width`, `scale`, `dpi`, `background`, `attribution`).

### 2.2 Nodes and dispatch

`_Node.__init__` normalises the spec and calls `_measure_<kind>`; `paint` calls
`_paint_<kind>`. An unknown `type` raises against `_LAYOUT_TYPES`.

| `type` | Alias / normalisation | Measure / paint |
| --- | --- | --- |
| `icon` | filename string → `icon` | `_measure_icon` / `_paint_icon` |
| `text` | — | `_measure_text` / `_paint_text` |
| `row` | — | `_measure_row` / `_paint_row` |
| `column` | `card` → `column` (border defaults), `""` → `column` | `_measure_column` / `_paint_column` |
| `grid` | `table` → `grid` | `_measure_grid` / `_paint_grid` |
| `canvas` | — | `_measure_canvas` / `_paint_canvas` |
| `arrow` | — | `_measure_arrow` / `_paint_arrow` |
| `spacer` | — | `_measure_spacer` / `_paint_spacer` |
| `divider` | — | `_measure_divider` / `_paint_divider` |

`LayoutContext` bundles `scale`, `px()`, the font cache and `icon()`.

### 2.3 Page size and output

- `_resolve_page` knows `PAGE_SIZES` (`a4`, `a4-landscape`, `a3`,
  `a3-landscape`, `letter`, `letter-landscape`), a free `WxH` and tuples.
- `render_layout` builds **one** `Image` sized
  `max(margin*2 + content, page)` and paints the root node centred.
- `save_image` writes PNG/JPEG or a **single-page** PDF
  (`image.convert("RGB").save(path, "PDF", ...)`).
- `render_layout_and_save` renders once and writes the same image to every
  output path.

### 2.4 Grid, canvas, connectors

- `_measure_grid` measures columns (`columns`, optionally `{label, width}`),
  rows (`{header, cells}`), `row_header`, `cell_padding`, `header_background`
  and optional `height`/`width`; `_paint_grid` draws the cells and centres
  nodes. A cell may be a list (→ column); `None`/`""` stays empty.
- `_measure_canvas` places `{x, y, node}` absolutely, with optional
  `width`/`height`.
- `_measure_arrow` only knows `right`/`left`/`up`/`down` as straight arrows, no
  orthogonal paths.
- Role colours (`ROLE_COLORS`) only apply in `_paint_icon`; grid cells and
  headers stay neutral.

### 2.5 Word resolution, MCP and examples

- `catalog.resolve_layout_node` replaces `word` → `file`/`concept` before
  `layout.py` sees the tree; `layout.py` never knows words.
- MCP: `render_pictogram_layout` (`arasaac_mcp/mcp/render_pictogram_layout.py`)
  passes the raw tree through.
- CLI: `make-sheet --json` detects a layout spec via `_looks_like_layout` and
  calls `render_layout_and_save`.
- Examples: `examples/stundenplan.json` (grid), `examples/karten.json` (cards +
  arrow).
- Tests: `tests/test_layout.py` (e.g. `test_render_layout_page_size_is_applied`,
  `test_render_layout_grid_with_row_header_and_empty_cells`,
  `test_render_layout_arrow_direction_swaps_axes`) and `tests/test_mcp_tools.py`.

## 3. Observed gaps

1. **One page, one image** — `render_layout` returns exactly one `Image`; there
   is no multi-page document.
2. **No break/overflow handling** — `_measure_grid`/`_measure_column` do not know
   `page_size`; content that is too tall enlarges the canvas.
3. **No multi-page PDF** — `save_image` saves only one page.
4. **No templates/presets** — every caller writes the raw tree (see
   `examples/`); the MCP tool only takes `layout`.
5. **Only one global header** — `sentence`/`meaning` apply to the whole image;
   repeated headers/footers or section headings are missing.
6. **Only straight connectors** — no orthogonal/elbow arrow for flow diagrams.
7. **Role colour only on icons** — grid cells and headers do not pick up
   `ROLE_COLORS`.

## 4. Plan

### Phase 1 — Internal document model

Add a pagination step that slices the measured tree into pages. `render_layout`
stays as a single-page facade; new is e.g.
`render_layout_pages(spec, options, icons_dir) -> list[Image]`.

- Files: `arasaac_mcp/layout.py`.
- Tests: `tests/test_layout.py` — a one-page spec yields exactly one page and the
  existing geometry is unchanged.

### Phase 2 — `page`/`document` node and grid breaking

Add a document/page node and break long `grid`s across
`SheetOptions.page_size` (row chunking based on `row_h`, `header_h`, `margin`,
`footer_h`). Repeat column headers on every page.

- Files: `arasaac_mcp/layout.py` (`_measure_grid`, new `_measure_page`).
- Tests: a long table produces several pages; the column header repeats.

### Phase 3 — Multi-page PDF

Extend `save_image` to take a list of images (`save_all=True,
append_images=[...]`) and feed `render_layout_and_save` with multiple pages;
PNG/JPEG stay at the first page or get a per-page suffix.

- Files: `arasaac_mcp/layout.py` (`save_image`, `render_layout_and_save`),
  `arasaac_mcp/cli.py`.
- Tests: a multi-page PDF; `make-sheet --json` writes it.

### Phase 4 — Templates/presets

Named templates (timetable, social story/cards, routine) as Python builders or
JSON in `arasaac_mcp/templates/`, with a `template` argument in the MCP tool and
in `make-sheet`. The templates reproduce `examples/`.

- Files: new `arasaac_mcp/templates/`,
  `arasaac_mcp/mcp/render_pictogram_layout.py`, `arasaac_mcp/cli.py`.
- Tests: `tests/test_mcp_tools.py` — a template produces the same structure as
  the example JSON.

### Phase 5 — Running headers/footers

Per-page repeated headers/footers and section headings instead of one global
`sentence`/`meaning`; `attribution` stays the default footer.

- Files: `arasaac_mcp/layout.py`,
  `arasaac_mcp/mcp/render_pictogram_layout.py`.
- Tests: header on every page, attribution once per page.

### Phase 6 — Orthogonal connectors

Add a `connector`/`polyline` node for elbows between boxes, building on
`_measure_arrow`/`_paint_arrow`.

- Files: `arasaac_mcp/layout.py`, `scripts/prompt.md` §9 (node table).
- Tests: `tests/test_layout.py` — direction/elbow geometry.

## 5. Invariants

- `layout.py` stays **Pillow-only** and host-neutral (no words, no MCP or LLM
  logic).
- The strip path `render_sheet`/`render_and_save` and the CLI output stay
  unchanged.
- The `catalog.resolve_layout_node` contract (word → `file`/`concept`) and
  `_looks_like_layout` in `cli.py` stay valid.
- The MCP signature of `render_pictogram_layout` stays backward compatible; new
  arguments (`template`, `page_breaks`, …) are optional.
- `scale`/`dpi` supersampling and RGBA compositing are preserved.

## 6. Acceptance / measurement

- `examples/stundenplan.json` renders across **two** pages when the page is
  full, with a repeated column header.
- A long table breaks automatically without enlarging the canvas.
- A template produces the same output as the corresponding example JSON without
  the caller writing the tree by hand.
- `make-sheet --json … -o plan.pdf` writes a multi-page PDF.
