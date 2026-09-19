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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Fitzgerald-key colours, keyed by role name (see ``prompt.md``).
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
    return ImageFont.load_default(size=size)


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


def _normalise_entries(
    entries: Sequence[Entry | str | Path], icons_dir: Path
) -> list[Entry]:
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
    if opts.columns:
        cols = max(1, min(opts.columns, n))
    else:
        cols = min(n, max(1, opts.max_columns))
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
    for line, font, _ in header_lines:
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
        icon = ImageOps.contain(icon, (icon_box, icon_box), Image.LANCZOS)
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
# JSON contract (see prompt.md)
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
