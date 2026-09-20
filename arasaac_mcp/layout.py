"""Render an ordered list of ARASAAC pictograms into a sentence strip.

This module wraps :mod:`Pillow` (PIL).  It takes a sequence of pictogram files
and composes them into a single image (a horizontal "sentence strip" that wraps
into rows if needed).  The result can be saved as PNG/JPEG or as a one-page PDF.

The colour framing follows the Fitzgerald key / ARASAAC colour code:

==============  ==========
role            colour
==============  ==========
PERSON          yellow
NOUN            orange
VERB            green
QUALITY         blue
SOCIAL          pink
MISC            grey
==============  ==========
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont, ImageOps

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Fitzgerald-key colours, keyed by role name (see ``scripts/prompt.md``).
ROLE_COLORS: dict[str, str] = {
    "PERSON": "#FFC800",
    "NOUN": "#F58220",
    "VERB": "#3CB44B",
    "QUALITY": "#2E75B6",
    "SOCIAL": "#FF6FB5",
    "MISC": "#9AA0A6",
}

#: Fallback border colour for entries without a role.
NEUTRAL_BORDER = "#D0D3D6"

_FONT_CANDIDATES = {
    False: [
        "NotoSans-Regular.ttf",
        "DejaVuSans.ttf",
        "LiberationSans-Regular.ttf",
        "Arial.ttf",
    ],
    True: [
        "NotoSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "LiberationSans-Bold.ttf",
        "Arial Bold.ttf",
    ],
}

_FONT_DIRS = [
    "/usr/share/fonts/truetype",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/Library/Fonts",
    "/System/Library/Fonts",
    str(Path.home() / ".fonts"),
    str(Path.home() / ".local/share/fonts"),
]


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class Entry:
    """A single pictogram to place on the sheet."""

    path: Path
    role: str | None = None
    concept: str | None = None

    @property
    def label(self) -> str:
        """Human readable label: explicit concept, else the file description."""
        if self.concept:
            return self.concept
        return label_from_filename(self.path.name)


@dataclass
class SheetOptions:
    """Visual / layout parameters for :func:`render_sheet`."""

    icon_size: int = 300
    columns: int | None = None
    max_columns: int = 6
    gap: int = 28
    margin: int = 48
    padding: int = 16
    frames: bool = True
    labels: bool = False
    sentence: str | None = None
    meaning: str | None = None
    attribution: bool = True
    background: str = "#FFFFFF"
    min_content_width: int = 760
    scale: int = 2
    dpi: int = 96
    # --- general layout engine (see ``render_layout``) -------------------
    text_size: int = 26
    label_size: int = 20
    title_size: int = 34
    #: fixed page size (``"a4"``, ``"a4-landscape"`` or ``"WxH"`` in px) or None.
    page_size: str | tuple[int, int] | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def label_from_filename(name: str) -> str:
    """``"3123_Regen.png"`` -> ``"Regen"``."""
    stem = Path(name).stem
    _, _, description = stem.partition("_")
    description = description or stem
    return description.replace("_", " ").strip()


def _font_candidates(bold: bool) -> Iterable[Path]:
    filenames = _FONT_CANDIDATES[bold]
    env = os.environ.get("ARASAAC_FONT")
    if env:
        env_path = Path(env)
        if not bold:
            yield env_path
        else:
            yield env_path.with_name(f"{env_path.stem}-Bold{env_path.suffix}")

    # Fonts shipped with this repository.
    bundled = Path(__file__).resolve().parents[2] / "assets" / "fonts"
    for name in filenames:
        yield bundled / name

    # System fonts.
    for directory in _FONT_DIRS:
        base = Path(directory)
        for name in filenames:
            yield base / name
            yield base / "dejavu" / name
            yield base / "liberation" / name
            yield base / "noto" / name


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a scalable font that supports German umlauts.

    Falls back to Pillow's bundled font if nothing else is found (which does
    **not** render umlauts, but keeps the tool usable).
    """
    for candidate in _font_candidates(bold):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    # Pillow's default font is a FreeTypeFont when a size is given; the stubs
    # only promise the base class.
    return cast(ImageFont.FreeTypeFont, ImageFont.load_default(size=size))


def wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    """Greedy word wrap that respects ``max_width`` in pixels."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def resolve_icon(name: str | Path, icons_dir: Path) -> Path:
    """Resolve a filename to an existing pictogram path."""
    candidate = Path(name)
    if candidate.is_file():
        return candidate
    resolved = icons_dir / candidate.name
    if resolved.is_file():
        return resolved
    raise FileNotFoundError(f"pictogram not found: {name}")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _normalise_entries(entries: Sequence[Entry | str | Path], icons_dir: Path) -> list[Entry]:
    result: list[Entry] = []
    for item in entries:
        if isinstance(item, Entry):
            result.append(Entry(resolve_icon(item.path, icons_dir), item.role, item.concept))
        else:
            result.append(Entry(resolve_icon(item, icons_dir)))
    return result


def render_sheet(
    entries: Sequence[Entry | str | Path],
    options: SheetOptions | None = None,
    icons_dir: Path | str = Path("icons"),
) -> Image.Image:
    """Compose ``entries`` into a single RGBA image and return it."""
    opts = options or SheetOptions()
    icons_dir = Path(icons_dir)
    items = _normalise_entries(entries, icons_dir)
    if not items:
        raise ValueError("no pictograms to render")

    s = max(1, opts.scale)
    n = len(items)

    # --- geometry ---------------------------------------------------------
    cols = max(1, min(opts.columns, n)) if opts.columns else min(n, max(1, opts.max_columns))
    rows = math.ceil(n / cols)

    pad = opts.padding * s
    icon_box = opts.icon_size * s
    gap = opts.gap * s
    margin = opts.margin * s
    card_w = icon_box + 2 * pad

    label_font = load_font(int(opts.icon_size * 0.10) * s, bold=True)
    label_h = int(label_font.size * 1.6) if opts.labels else 0
    card_h = icon_box + 2 * pad + label_h
    row_gap = gap

    grid_w = cols * card_w + (cols - 1) * gap
    content_w = max(grid_w, opts.min_content_width * s)

    # --- header / footer text --------------------------------------------
    title_font = load_font(int(opts.icon_size * 0.13) * s, bold=True)
    meaning_font = load_font(int(opts.icon_size * 0.10) * s)
    footer_font = load_font(int(opts.icon_size * 0.06) * s)

    scratch = Image.new("RGBA", (1, 1))
    measure = ImageDraw.Draw(scratch)

    header_lines: list[tuple[str, ImageFont.FreeTypeFont, str]] = []
    if opts.sentence:
        for line in wrap_text(measure, opts.sentence, title_font, content_w):
            header_lines.append((line, title_font, "#1A1A1A"))
    if opts.meaning:
        for line in wrap_text(measure, opts.meaning, meaning_font, content_w):
            header_lines.append((line, meaning_font, "#555555"))

    line_gap = int(opts.icon_size * 0.03) * s
    header_h = 0
    for _line, font, _ in header_lines:
        header_h += int(font.size * 1.35) + line_gap // 2
    if header_lines:
        header_h += gap

    footer_text = "Piktogramme: ARASAAC (CC BY-NC-SA)"
    footer_h = 0
    if opts.attribution:
        footer_h = int(footer_font.size * 2) + gap // 2

    # --- canvas -----------------------------------------------------------
    width = margin * 2 + content_w
    height = margin * 2 + header_h + rows * card_h + (rows - 1) * row_gap + footer_h
    canvas = Image.new("RGBA", (int(width), int(height)), opts.background)
    draw = ImageDraw.Draw(canvas)

    # --- header -----------------------------------------------------------
    y = margin
    for line, font, color in header_lines:
        draw.text((margin, y), line, font=font, fill=color)
        y += int(font.size * 1.35) + line_gap // 2
    if header_lines:
        y += gap

    # --- grid -------------------------------------------------------------
    grid_x0 = margin + (content_w - grid_w) // 2
    for index, entry in enumerate(items):
        row, col = divmod(index, cols)
        x0 = grid_x0 + col * (card_w + gap)
        y0 = margin + header_h + row * (card_h + row_gap)

        border = ROLE_COLORS.get((entry.role or "").upper(), NEUTRAL_BORDER)
        if opts.frames:
            draw.rounded_rectangle(
                (x0, y0, x0 + card_w, y0 + card_h),
                radius=pad + 8 * s,
                outline=border,
                width=max(2, 6 * s),
                fill="#FFFFFF" if opts.background != "#FFFFFF" else None,
            )

        icon = Image.open(entry.path).convert("RGBA")
        icon = ImageOps.contain(icon, (icon_box, icon_box), Image.Resampling.LANCZOS)
        ix = x0 + pad + (icon_box - icon.width) // 2
        iy = y0 + pad + (icon_box - icon.height) // 2
        canvas.alpha_composite(icon, (ix, iy))

        if opts.labels and label_h:
            text = entry.label
            text_w = draw.textlength(text, font=label_font)
            while text and text_w > card_w - pad // 2:
                text = text[:-1]
                text_w = draw.textlength(text, font=label_font)
            tx = x0 + (card_w - text_w) // 2
            ty = y0 + pad + icon_box
            draw.text((tx, ty), text, font=label_font, fill="#1A1A1A")

    # --- footer -----------------------------------------------------------
    if opts.attribution:
        fy = height - margin + gap // 4
        draw.text((margin, fy), footer_text, font=footer_font, fill="#888888")

    return canvas


def save_image(image: Image.Image, path: Path | str, dpi: int = 96) -> Path:
    """Save ``image`` as PNG/JPEG, or as a single-page PDF based on extension."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = path.suffix.lower()
    if fmt == ".pdf":
        page = image.convert("RGB")
        page.save(path, "PDF", resolution=dpi)
    elif fmt in (".jpg", ".jpeg"):
        image.convert("RGB").save(path, "JPEG", quality=95, dpi=(dpi, dpi))
    else:
        image.save(path, dpi=(dpi, dpi))
    return path


def render_and_save(
    entries: Sequence[Entry | str | Path],
    outputs: Sequence[Path | str],
    options: SheetOptions | None = None,
    icons_dir: Path | str = Path("icons"),
) -> list[Path]:
    """Render once and write the same sheet to every requested output path."""
    opts = options or SheetOptions()
    sheet = render_sheet(entries, opts, icons_dir=icons_dir)
    dpi = opts.dpi * max(1, opts.scale)
    return [save_image(sheet, path, dpi=dpi) for path in outputs]


# --------------------------------------------------------------------------- #
# JSON contract (see scripts/prompt.md)
# --------------------------------------------------------------------------- #


def entries_from_json(
    data: dict,
    icons_dir: Path | str = Path("icons"),
    alternative: int | str | None = None,
) -> tuple[list[Entry], dict]:
    """Build entries from the model output contract.

    Returns the entries plus a dict with ``sentence``, ``meaning`` and the
    label of the chosen alternative.
    """
    icons_dir = Path(icons_dir)
    meta: dict = {"sentence": data.get("sentence"), "meaning": data.get("meaning")}

    if alternative is None:
        sequence = data.get("sequence", [])
        meta["label"] = "sequence"
        return [
            Entry(resolve_icon(item["file"], icons_dir), item.get("role"), item.get("concept"))
            for item in sequence
        ], meta

    alternatives = data.get("alternatives", [])
    if isinstance(alternative, int):
        chosen = alternatives[alternative]
    else:
        chosen = next((a for a in alternatives if a.get("label") == alternative), None)
        if chosen is None:
            raise KeyError(f"no alternative labelled {alternative!r}")
    meta["label"] = chosen.get("label", str(alternative))
    return [Entry(resolve_icon(f, icons_dir)) for f in chosen["files"]], meta


def load_json(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# General layout engine
# --------------------------------------------------------------------------- #
#
# A sheet is not always a single strip.  A *layout spec* is a small tree of
# nodes that can express grids/timetables, framed cards, connectors, spacers and
# free absolute placement.  The linear sentence strip above is a special case.
#
# Node types (all sizes are logical px, multiplied by ``SheetOptions.scale``):
#
#   icon    {file, concept?, role?, size?, show_label?, frame?, padding?}
#   text    {text, size?, bold?, color?, align?, width?, uppercase?}
#   row     {children, gap?, align?, justify?, padding?, background?, border?, ...}
#   column  {children, gap?, align?, padding?, background?, border?, ...}
#   card    {children, ...}                 # column with frame defaults
#   grid    {columns, rows, ...}            # table / timetable (alias: table)
#   canvas  {width?, height?, children:[{x, y, node}]}   # free placement
#   arrow   {direction?, length?, thickness?, color?}
#   spacer  {width?, height?}
#   divider {orientation?, length?, thickness?, color?}

_LAYOUT_TYPES = "icon, text, row, column, card, grid/table, canvas, arrow, spacer, divider"

#: Logical page sizes at the base DPI (96); scaled by ``SheetOptions.scale``.
PAGE_SIZES: dict[str, tuple[int, int]] = {
    "a4": (794, 1123),
    "a4-landscape": (1123, 794),
    "a3": (1123, 1587),
    "a3-landscape": (1587, 1123),
    "letter": (816, 1056),
    "letter-landscape": (1056, 816),
}


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    radius: float,
    fill: str | None = None,
    outline: str | None = None,
    width: int = 1,
) -> None:
    x0, y0, x1, y1 = box
    radius = int(max(0, min(radius, (x1 - x0) // 2, (y1 - y0) // 2)))
    if radius > 0:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    else:
        draw.rectangle(box, fill=fill, outline=outline, width=width)


def _dashed_line(
    draw: ImageDraw.ImageDraw,
    p0: tuple[float, float],
    p1: tuple[float, float],
    color: str,
    width: int,
    dash: float,
    gap: float,
) -> None:
    (x0, y0), (x1, y1) = p0, p1
    total = math.hypot(x1 - x0, y1 - y0)
    if total <= 0:
        return
    ux, uy = (x1 - x0) / total, (y1 - y0) / total
    pos = 0.0
    while pos < total:
        end = min(pos + dash, total)
        draw.line(
            [(x0 + ux * pos, y0 + uy * pos), (x0 + ux * end, y0 + uy * end)],
            fill=color,
            width=width,
        )
        pos = end + gap


def _dashed_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    color: str,
    width: int,
) -> None:
    x0, y0, x1, y1 = box
    dash = max(width * 3, 8)
    gap = max(width * 2, 6)
    _dashed_line(draw, (x0, y0), (x1, y0), color, width, dash, gap)
    _dashed_line(draw, (x1, y0), (x1, y1), color, width, dash, gap)
    _dashed_line(draw, (x0, y1), (x0, y0), color, width, dash, gap)
    _dashed_line(draw, (x1, y1), (x0, y1), color, width, dash, gap)


class LayoutContext:
    """Shared, resolved settings for a layout render pass."""

    def __init__(self, options: SheetOptions, icons_dir: Path | str) -> None:
        self.opts = options
        self.s = max(1, options.scale)
        self.icons_dir = Path(icons_dir)
        self._fonts: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}
        self.scratch = Image.new("RGBA", (1, 1))
        self.measure = ImageDraw.Draw(self.scratch)

    def px(self, value: float) -> int:
        return round(float(value) * self.s)

    def font(self, size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = (round(size), bool(bold))
        font = self._fonts.get(key)
        if font is None:
            font = load_font(max(1, self.px(size)), bold)
            self._fonts[key] = font
        return font

    def icon(self, name: str | Path) -> Path:
        return resolve_icon(name, self.icons_dir)


class _Node:
    """A measured, paintable layout node."""

    def __init__(self, spec: object, ctx: LayoutContext) -> None:
        self.ctx = ctx
        self.spec = self._normalise(spec)
        self.kind = str(self.spec.get("type", "")).strip().lower()
        self.children: list[_Node] = []
        self.width = 0
        self.height = 0
        handler = getattr(self, f"_measure_{self.kind}", None)
        if handler is None:
            raise ValueError(f"Unbekannter Layout-Typ {self.kind!r}. Erlaubt: {_LAYOUT_TYPES}")
        handler()

    @staticmethod
    def _normalise(spec: object) -> dict:
        if isinstance(spec, str):
            return {"type": "icon", "file": spec}
        if not isinstance(spec, dict):
            raise ValueError(
                f"Layout-Knoten muss ein Objekt oder Dateiname sein, nicht {type(spec).__name__}"
            )
        spec = dict(spec)
        kind = str(spec.get("type", "")).strip().lower()
        if kind == "table":
            spec["type"] = "grid"
        elif kind == "card":
            spec["type"] = "column"
            spec.setdefault("padding", 24)
            spec.setdefault("gap", 14)
            spec.setdefault("align", "center")
            spec.setdefault("border", NEUTRAL_BORDER)
            spec.setdefault("border_width", 3)
            spec.setdefault("radius", 28)
        elif kind == "":
            spec["type"] = "column"
        return spec

    # -- helpers -----------------------------------------------------------

    def _children_specs(self) -> list:
        for key in ("children", "child", "items"):
            if key in self.spec:
                value = self.spec[key]
                return value if isinstance(value, list) else [value]
        return []

    def _build_children(self) -> None:
        self.children = [_Node(item, self.ctx) for item in self._children_specs()]

    def _style(self) -> dict:
        spec, ctx = self.spec, self.ctx
        border = spec.get("border")
        return {
            "padding": ctx.px(spec.get("padding", 0)),
            "gap": ctx.px(spec.get("gap", ctx.opts.gap)),
            "background": spec.get("background"),
            "border": border,
            "border_width": ctx.px(spec.get("border_width", 3)) if border else 0,
            "radius": ctx.px(spec.get("radius", 16)),
            "dashed": bool(spec.get("dashed", False)),
        }

    def _paint_frame_fill(self, canvas: Image.Image, x: float, y: float) -> None:
        if not self.st.get("background"):
            return
        draw = ImageDraw.Draw(canvas)
        _rounded_rect(
            draw,
            (x, y, x + self.width, y + self.height),
            self.st["radius"],
            fill=self.st["background"],
        )

    def _paint_frame_border(self, canvas: Image.Image, x: float, y: float) -> None:
        if not self.st.get("border"):
            return
        draw = ImageDraw.Draw(canvas)
        box = (x, y, x + self.width, y + self.height)
        if self.st["dashed"]:
            _dashed_rect(draw, box, self.st["border"], self.st["border_width"])
        else:
            _rounded_rect(
                draw,
                box,
                self.st["radius"],
                outline=self.st["border"],
                width=self.st["border_width"],
            )

    # -- icon --------------------------------------------------------------

    def _measure_icon(self) -> None:
        ctx, spec = self.ctx, self.spec
        if not spec.get("file"):
            raise ValueError("icon-Knoten braucht ein 'file' (oder vom Agenten ein 'word')")
        self.path = ctx.icon(spec["file"])
        self.icon_box = ctx.px(spec.get("size", ctx.opts.icon_size))
        self.pad = ctx.px(spec.get("padding", ctx.opts.padding))
        self.frame = bool(spec.get("frame", ctx.opts.frames))
        self.role = str(spec.get("role") or "").upper() or None
        concept = spec.get("concept") or spec.get("text")
        self.concept = str(concept) if concept else label_from_filename(self.path.name)
        self.show_label = bool(spec.get("show_label", ctx.opts.labels))
        self.label_text = self.concept if self.show_label else None
        self.label_font = ctx.font(spec.get("label_size", ctx.opts.label_size), bold=True)
        self.label_h = int(self.label_font.size * 1.4) if self.label_text else 0
        self.width = self.icon_box + 2 * self.pad
        self.height = self.icon_box + 2 * self.pad + self.label_h

    def _paint_icon(self, canvas: Image.Image, x: float, y: float) -> None:
        draw = ImageDraw.Draw(canvas)
        if self.frame:
            border = ROLE_COLORS.get(self.role or "", NEUTRAL_BORDER)
            _rounded_rect(
                draw,
                (x, y, x + self.width, y + self.height),
                self.pad + self.ctx.px(6),
                outline=border,
                width=max(2, self.ctx.px(3)),
                fill="#FFFFFF" if self.ctx.opts.background != "#FFFFFF" else None,
            )
        icon = Image.open(self.path).convert("RGBA")
        icon = ImageOps.contain(icon, (self.icon_box, self.icon_box), Image.Resampling.LANCZOS)
        ix = int(x + self.pad + (self.icon_box - icon.width) / 2)
        iy = int(y + self.pad + (self.icon_box - icon.height) / 2)
        canvas.alpha_composite(icon, (ix, iy))
        if self.label_text:
            text = self.label_text
            max_w = self.width - self.ctx.px(6)
            while text and draw.textlength(text, font=self.label_font) > max_w:
                text = text[:-1]
            tw = draw.textlength(text, font=self.label_font)
            tx = x + (self.width - tw) / 2
            ty = y + self.pad + self.icon_box + (self.label_h - self.label_font.size) / 2
            draw.text((tx, ty), text, font=self.label_font, fill="#1A1A1A")

    # -- text --------------------------------------------------------------

    def _measure_text(self) -> None:
        ctx, spec = self.ctx, self.spec
        text = str(spec.get("text", ""))
        if spec.get("uppercase"):
            text = text.upper()
        self.text = text
        self.font = ctx.font(spec.get("size", ctx.opts.text_size), bool(spec.get("bold", False)))
        self.color = spec.get("color", "#1A1A1A")
        self.align = str(spec.get("align", "center")).lower()
        self.pad = ctx.px(spec.get("padding", 0))
        explicit = spec.get("width")
        if explicit:
            self.box_w: float = ctx.px(explicit)
            self.lines = wrap_text(ctx.measure, text, self.font, self.box_w)
        else:
            self.lines = text.split("\n") if text else [""]
            self.box_w = max(
                (ctx.measure.textlength(line, font=self.font) for line in self.lines),
                default=0,
            )
        self.line_h = int(self.font.size * 1.3)
        self.width = int(self.box_w + 2 * self.pad)
        self.height = len(self.lines) * self.line_h + 2 * self.pad

    def _paint_text(self, canvas: Image.Image, x: float, y: float) -> None:
        draw = ImageDraw.Draw(canvas)
        inner_w = self.width - 2 * self.pad
        ty = y + self.pad
        for line in self.lines:
            lw = draw.textlength(line, font=self.font)
            if self.align == "left":
                tx = x + self.pad
            elif self.align == "right":
                tx = x + self.width - self.pad - lw
            else:
                tx = x + self.pad + (inner_w - lw) / 2
            draw.text((tx, ty), line, font=self.font, fill=self.color)
            ty += self.line_h

    # -- row / column ------------------------------------------------------

    def _measure_row(self) -> None:
        ctx = self.ctx
        self.st = self._style()
        self._build_children()
        self.valign = str(self.spec.get("align", "center")).lower()
        self.justify = str(self.spec.get("justify", "start")).lower()
        gap = self.st["gap"]
        self.natural_w = sum(c.width for c in self.children) + gap * max(0, len(self.children) - 1)
        natural_h = max((c.height for c in self.children), default=0)
        explicit_w = self.spec.get("width")
        self.main_w = ctx.px(explicit_w) if explicit_w else self.natural_w
        explicit_h = self.spec.get("height")
        self.cross_h = ctx.px(explicit_h) if explicit_h else natural_h
        self.width = self.main_w + 2 * self.st["padding"]
        self.height = self.cross_h + 2 * self.st["padding"]

    def _cross_offset(self, child: _Node) -> float:
        if self.valign in ("top", "start"):
            return 0
        if self.valign in ("bottom", "end"):
            return self.cross_h - child.height
        return (self.cross_h - child.height) / 2

    def _paint_row(self, canvas: Image.Image, x: float, y: float) -> None:
        self._paint_frame_fill(canvas, x, y)
        pad = self.st["padding"]
        if self.children:
            extra = self.main_w - self.natural_w
            if self.justify in ("space-between", "between") and len(self.children) > 1:
                step = self.st["gap"] + extra / (len(self.children) - 1)
                cx = pad
                for child in self.children:
                    child.paint(canvas, x + cx, y + pad + self._cross_offset(child))
                    cx += child.width + step
            else:
                if self.justify in ("center", "middle"):
                    cx = pad + extra / 2
                elif self.justify in ("end", "right"):
                    cx = pad + extra
                else:
                    cx = pad
                for child in self.children:
                    child.paint(canvas, x + cx, y + pad + self._cross_offset(child))
                    cx += child.width + self.st["gap"]
        self._paint_frame_border(canvas, x, y)

    def _measure_column(self) -> None:
        ctx = self.ctx
        self.st = self._style()
        self._build_children()
        self.align = str(self.spec.get("align", "center")).lower()
        gap = self.st["gap"]
        natural_w = max((c.width for c in self.children), default=0)
        self.main_h = sum(c.height for c in self.children) + gap * max(0, len(self.children) - 1)
        explicit_w = self.spec.get("width")
        self.cross_w = ctx.px(explicit_w) if explicit_w else natural_w
        self.width = self.cross_w + 2 * self.st["padding"]
        self.height = self.main_h + 2 * self.st["padding"]

    def _paint_column(self, canvas: Image.Image, x: float, y: float) -> None:
        self._paint_frame_fill(canvas, x, y)
        pad = self.st["padding"]
        cy = pad
        for child in self.children:
            if self.align in ("left", "start"):
                ox: float = 0
            elif self.align in ("right", "end"):
                ox = self.cross_w - child.width
            else:
                ox = (self.cross_w - child.width) / 2
            child.paint(canvas, x + pad + ox, y + cy)
            cy += child.height + self.st["gap"]
        self._paint_frame_border(canvas, x, y)

    # -- grid / table ------------------------------------------------------

    def _text_node(self, text: str) -> _Node:
        return _Node(
            {
                "type": "text",
                "text": str(text),
                "align": "center",
                "bold": bool(self.spec.get("header_bold", True)),
                "size": self.spec.get("header_size", self.ctx.opts.text_size),
                "color": self.spec.get("header_color", "#1A1A1A"),
                "padding": self.spec.get("header_padding", 4),
            },
            self.ctx,
        )

    def _cell_node(self, cell: object) -> _Node | None:
        if cell is None or cell == "":
            return None
        if isinstance(cell, list):
            return _Node({"type": "column", "gap": 6, "children": cell}, self.ctx)
        if isinstance(cell, str):
            return _Node({"type": "icon", "file": cell}, self.ctx)
        return _Node(cell, self.ctx)

    def _measure_grid(self) -> None:
        ctx, spec = self.ctx, self.spec
        self.st = self._style()
        self.cell_pad = ctx.px(spec.get("cell_padding", 10))
        gap = ctx.px(spec.get("gap", 0))

        self.columns: list[dict] = []
        for column in spec.get("columns", []) or []:
            self.columns.append({"label": column} if isinstance(column, str) else dict(column))
        self.rows_spec: list[dict] = []
        for row in spec.get("rows", []) or []:
            if isinstance(row, list):
                self.rows_spec.append({"header": None, "cells": row})
            else:
                self.rows_spec.append(dict(row))

        ncols = len(self.columns) or max(
            (len(r.get("cells", [])) for r in self.rows_spec), default=0
        )
        while len(self.columns) < ncols:
            self.columns.append({})

        self.col_header_nodes = [
            self._text_node(c["label"]) if c.get("label") else None for c in self.columns
        ]
        self.row_header_nodes = [
            self._text_node(r["header"]) if r.get("header") else None for r in self.rows_spec
        ]
        self.cell_nodes: list[list[_Node | None]] = []
        for row in self.rows_spec:
            cells = list(row.get("cells", []))
            self.cell_nodes.append(
                [self._cell_node(cells[c] if c < len(cells) else None) for c in range(ncols)]
            )

        self.col_w: list[int] = []
        for c in range(ncols):
            width = 0
            col_header = self.col_header_nodes[c]
            if col_header:
                width = max(width, col_header.width)
            for r in range(len(self.cell_nodes)):
                node = self.cell_nodes[r][c]
                if node:
                    width = max(width, node.width)
            explicit = self.columns[c].get("width")
            if explicit:
                width = ctx.px(explicit)
            self.col_w.append(width + 2 * self.cell_pad)

        use_row_header = spec.get("row_header", any(self.row_header_nodes))
        self.rowheader_w = 0
        if use_row_header:
            header_w = max((n.width for n in self.row_header_nodes if n), default=0)
            self.rowheader_w = header_w + 2 * self.cell_pad

        self.header_h = 0
        if any(self.col_header_nodes):
            self.header_h = (
                max((n.height for n in self.col_header_nodes if n), default=0) + 2 * self.cell_pad
            )

        self.row_h: list[int] = []
        for r, row in enumerate(self.cell_nodes):
            height = 0
            row_header = self.row_header_nodes[r]
            if row_header:
                height = max(height, row_header.height)
            for node in row:
                if node:
                    height = max(height, node.height)
            explicit = self.rows_spec[r].get("height")
            if explicit:
                height = ctx.px(explicit)
            self.row_h.append(height + 2 * self.cell_pad)

        self.data_x0 = (self.rowheader_w + gap) if self.rowheader_w else 0
        self.col_xs: list[int] = []
        xx = self.data_x0
        for width in self.col_w:
            self.col_xs.append(xx)
            xx += width + gap
        self.total_w = max(0, xx - gap) if self.col_w else self.rowheader_w

        self.data_y0 = (self.header_h + gap) if self.header_h else 0
        self.row_ys: list[int] = []
        yy = self.data_y0
        for height in self.row_h:
            self.row_ys.append(yy)
            yy += height + gap
        self.total_h = max(0, yy - gap) if self.row_h else self.header_h

        self.width = self.total_w
        self.height = self.total_h

    def _paint_grid(self, canvas: Image.Image, x: float, y: float) -> None:
        self._paint_frame_fill(canvas, x, y)
        ctx = self.ctx
        draw = ImageDraw.Draw(canvas)
        border = self.spec.get("border", NEUTRAL_BORDER)
        border_w = max(1, ctx.px(self.spec.get("border_width", 2)))
        header_bg = self.spec.get("header_background", "#EDEDED")
        cell_bg = self.spec.get("cell_background")

        def cell_box(col: int | None, row: int | None) -> tuple[float, float, float, float]:
            cx = x + (0 if col is None else self.col_xs[col])
            cy = y + (0 if row is None else self.row_ys[row])
            cw = self.rowheader_w if col is None else self.col_w[col]
            ch = self.header_h if row is None else self.row_h[row]
            return cx, cy, cx + cw, cy + ch

        def place(node: _Node | None, box: tuple[float, float, float, float]) -> None:
            if node is None:
                return
            x0, y0, x1, y1 = box
            node.paint(canvas, x0 + (x1 - x0 - node.width) / 2, y0 + (y1 - y0 - node.height) / 2)

        if self.header_h:
            for c in range(len(self.col_w)):
                box = cell_box(c, None)
                draw.rectangle(box, fill=header_bg, outline=border, width=border_w)
                place(self.col_header_nodes[c], box)
        for r in range(len(self.row_h)):
            if self.rowheader_w:
                box = cell_box(None, r)
                draw.rectangle(box, fill=header_bg, outline=border, width=border_w)
                place(self.row_header_nodes[r], box)
            for c in range(len(self.col_w)):
                box = cell_box(c, r)
                draw.rectangle(box, fill=cell_bg, outline=border, width=border_w)
                place(self.cell_nodes[r][c], box)
        self._paint_frame_border(canvas, x, y)

    # -- canvas (free absolute placement) ----------------------------------

    def _measure_canvas(self) -> None:
        ctx = self.ctx
        self.st = self._style()
        self.items: list[tuple[int, int, _Node]] = []
        max_x = max_y = 0
        for item in self.spec.get("children", []) or []:
            if isinstance(item, dict) and "node" in item:
                node = _Node(item["node"], ctx)
                ix, iy = ctx.px(item.get("x", 0)), ctx.px(item.get("y", 0))
            elif isinstance(item, dict):
                node = _Node({k: v for k, v in item.items() if k not in ("x", "y")}, ctx)
                ix, iy = ctx.px(item.get("x", 0)), ctx.px(item.get("y", 0))
            else:
                node, ix, iy = _Node(item, ctx), 0, 0
            self.items.append((ix, iy, node))
            max_x = max(max_x, ix + node.width)
            max_y = max(max_y, iy + node.height)
        pad = self.st["padding"]
        explicit_w = self.spec.get("width")
        explicit_h = self.spec.get("height")
        self.width = (ctx.px(explicit_w) if explicit_w else max_x) + 2 * pad
        self.height = (ctx.px(explicit_h) if explicit_h else max_y) + 2 * pad

    def _paint_canvas(self, canvas: Image.Image, x: float, y: float) -> None:
        self._paint_frame_fill(canvas, x, y)
        pad = self.st["padding"]
        for ix, iy, node in self.items:
            node.paint(canvas, x + pad + ix, y + pad + iy)
        self._paint_frame_border(canvas, x, y)

    # -- arrow / spacer / divider ------------------------------------------

    def _measure_arrow(self) -> None:
        ctx = self.ctx
        self.direction = str(self.spec.get("direction", "right")).lower()
        self.length = ctx.px(self.spec.get("length", 150))
        self.thickness = ctx.px(self.spec.get("thickness", 22))
        self.head = max(self.thickness * 2, ctx.px(44))
        self.color = self.spec.get("color", "#F2B705")
        if self.direction in ("up", "down"):
            self.width, self.height = self.head, self.length
        else:
            self.width, self.height = self.length, self.head

    def _paint_arrow(self, canvas: Image.Image, x: float, y: float) -> None:
        draw = ImageDraw.Draw(canvas)
        t = self.thickness / 2
        head = self.head
        if self.direction == "left":
            cy = y + self.height / 2
            points = [
                (x + self.length, cy - t),
                (x + head, cy - t),
                (x + head, cy - head / 2),
                (x, cy),
                (x + head, cy + head / 2),
                (x + head, cy + t),
                (x + self.length, cy + t),
            ]
        elif self.direction == "up":
            cx = x + self.width / 2
            points = [
                (cx - t, y + self.length),
                (cx - t, y + head),
                (cx - head / 2, y + head),
                (cx, y),
                (cx + head / 2, y + head),
                (cx + t, y + head),
                (cx + t, y + self.length),
            ]
        elif self.direction == "down":
            cx = x + self.width / 2
            points = [
                (cx - t, y),
                (cx - t, y + self.length - head),
                (cx - head / 2, y + self.length - head),
                (cx, y + self.length),
                (cx + head / 2, y + self.length - head),
                (cx + t, y + self.length - head),
                (cx + t, y),
            ]
        else:  # right
            cy = y + self.height / 2
            points = [
                (x, cy - t),
                (x + self.length - head, cy - t),
                (x + self.length - head, cy - head / 2),
                (x + self.length, cy),
                (x + self.length - head, cy + head / 2),
                (x + self.length - head, cy + t),
                (x, cy + t),
            ]
        draw.polygon(points, fill=self.color)

    def _measure_spacer(self) -> None:
        self.width = self.ctx.px(self.spec.get("width", 0))
        self.height = self.ctx.px(self.spec.get("height", 0))

    def _paint_spacer(self, canvas: Image.Image, x: float, y: float) -> None:
        return

    def _measure_divider(self) -> None:
        ctx = self.ctx
        self.orientation = str(self.spec.get("orientation", "horizontal")).lower()
        self.line_length = ctx.px(self.spec.get("length", 200))
        self.line_width = max(1, ctx.px(self.spec.get("thickness", 3)))
        self.color = self.spec.get("color", NEUTRAL_BORDER)
        if self.orientation in ("vertical", "v"):
            self.width, self.height = self.line_width, self.line_length
        else:
            self.width, self.height = self.line_length, self.line_width

    def _paint_divider(self, canvas: Image.Image, x: float, y: float) -> None:
        draw = ImageDraw.Draw(canvas)
        if self.orientation in ("vertical", "v"):
            draw.line(
                (x + self.width / 2, y, x + self.width / 2, y + self.height),
                fill=self.color,
                width=self.line_width,
            )
        else:
            draw.line(
                (x, y + self.height / 2, x + self.width, y + self.height / 2),
                fill=self.color,
                width=self.line_width,
            )

    # -- dispatch ----------------------------------------------------------

    def paint(self, canvas: Image.Image, x: float, y: float) -> None:
        getattr(self, f"_paint_{self.kind}")(canvas, x, y)


def _resolve_page(size: str | tuple[int, int] | None, ctx: LayoutContext) -> tuple[int, int] | None:
    if size is None:
        return None
    if isinstance(size, (tuple, list)):
        return ctx.px(size[0]), ctx.px(size[1])
    key = str(size).strip().lower().replace(" ", "")
    if key in PAGE_SIZES:
        width, height = PAGE_SIZES[key]
        return ctx.px(width), ctx.px(height)
    if "x" in key:
        left, _, right = key.partition("x")
        try:
            return ctx.px(float(left)), ctx.px(float(right))
        except ValueError as error:
            raise ValueError(f"Ung\u00fcltige Seitengr\u00f6\u00dfe: {size!r}") from error
    raise ValueError(
        f"Unbekannte Seitengr\u00f6\u00dfe {size!r}. Erwartet: {', '.join(sorted(PAGE_SIZES))} oder 'BREITExHOEHE'."
    )


def render_layout(
    spec: dict,
    options: SheetOptions | None = None,
    icons_dir: Path | str = Path("icons"),
) -> Image.Image:
    """Render a layout spec (tree of nodes) into a single RGBA image.

    The spec either *is* a node (has a ``type``) or wraps the root node in a
    ``layout`` field.  ``sentence``/``title``, ``meaning`` and ``attribution``
    on the spec override the corresponding :class:`SheetOptions`.
    """
    opts = options or SheetOptions()
    ctx = LayoutContext(opts, icons_dir)

    if isinstance(spec, dict) and "layout" in spec:
        root_spec = spec["layout"]
    elif isinstance(spec, dict) and "type" in spec:
        root_spec = spec
    else:
        raise ValueError("Layout-Spezifikation braucht ein 'layout' oder einen 'type'")
    root = _Node(root_spec, ctx)

    sentence = opts.sentence
    meaning = opts.meaning
    attribution = opts.attribution
    if isinstance(spec, dict):
        sentence = spec.get("sentence") or spec.get("title") or sentence
        meaning = spec.get("meaning") or meaning
        if "attribution" in spec:
            attribution = bool(spec["attribution"])

    margin = ctx.px(opts.margin)
    content_w = max(root.width, ctx.px(opts.min_content_width))

    header_lines: list[tuple[str, ImageFont.FreeTypeFont, str]] = []
    if sentence:
        font = ctx.font(opts.title_size, bold=True)
        header_lines += [
            (line, font, "#1A1A1A") for line in wrap_text(ctx.measure, sentence, font, content_w)
        ]
    if meaning:
        font = ctx.font(opts.text_size)
        header_lines += [
            (line, font, "#555555") for line in wrap_text(ctx.measure, meaning, font, content_w)
        ]
    header_h = sum(int(font.size * 1.35) for _, font, _ in header_lines)
    if header_lines:
        header_h += ctx.px(opts.gap)

    footer_font = ctx.font(opts.label_size * 0.8)
    footer_h = int(footer_font.size * 2) + ctx.px(opts.gap) // 2 if attribution else 0

    page = _resolve_page(opts.page_size, ctx)
    width = margin * 2 + content_w
    height = margin * 2 + header_h + root.height + footer_h
    if page:
        width = max(width, page[0])
        height = max(height, page[1])

    canvas = Image.new("RGBA", (int(width), int(height)), opts.background)
    draw = ImageDraw.Draw(canvas)

    y = margin
    for line, font, color in header_lines:
        draw.text((margin, y), line, font=font, fill=color)
        y += int(font.size * 1.35)
    if header_lines:
        y += ctx.px(opts.gap)

    root.paint(canvas, int((width - root.width) / 2), y)

    if attribution:
        draw.text(
            (margin, height - margin + ctx.px(opts.gap) // 4),
            "Piktogramme: ARASAAC (CC BY-NC-SA)",
            font=footer_font,
            fill="#888888",
        )
    return canvas


def render_layout_and_save(
    spec: dict,
    outputs: Sequence[Path | str],
    options: SheetOptions | None = None,
    icons_dir: Path | str = Path("icons"),
) -> list[Path]:
    """Render a layout spec once and write it to every requested output path."""
    opts = options or SheetOptions()
    sheet = render_layout(spec, opts, icons_dir=icons_dir)
    dpi = opts.dpi * max(1, opts.scale)
    return [save_image(sheet, path, dpi=dpi) for path in outputs]
