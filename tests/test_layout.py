"""The Pillow renderer: sentence strips, the layout engine and file output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from arasaac_mcp.layout import (
    PAGE_SIZES,
    ROLE_COLORS,
    Entry,
    SheetOptions,
    entries_from_json,
    label_from_filename,
    load_font,
    render_and_save,
    render_layout,
    render_layout_and_save,
    render_sheet,
    resolve_icon,
    save_image,
    wrap_text,
)


def _opts(**kwargs) -> SheetOptions:
    kwargs.setdefault("scale", 1)
    kwargs.setdefault("attribution", False)
    return SheetOptions(**kwargs)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("3123_Regen.png", "Regen"),
        ("10138_Augen_öffnen.png", "Augen öffnen"),
        ("noid.png", "noid"),
        ("Regen.png", "Regen"),
    ],
)
def test_label_from_filename(name: str, expected: str) -> None:
    assert label_from_filename(name) == expected


def test_resolve_icon_accepts_direct_path_and_icons_dir(tmp_path: Path, icons_dir: Path) -> None:
    direct = icons_dir / "1_Regen.png"
    assert resolve_icon(direct, icons_dir) == direct
    assert resolve_icon("1_Regen.png", icons_dir) == direct


def test_resolve_icon_missing_raises(icons_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_icon("nope.png", icons_dir)


def test_load_font_returns_requested_size() -> None:
    font = load_font(24)
    assert font.size == 24


def test_load_font_honours_env_font(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARASAAC_FONT", str(repo_root / "assets" / "fonts" / "NotoSans-Regular.ttf"))
    assert Path(load_font(18).path).name == "NotoSans-Regular.ttf"


@pytest.mark.regression
@pytest.mark.xfail(
    reason="arasaac_mcp/layout.py resolves the bundled fonts with parents[2], "
    "which points above the repo root in the flat layout; the bundled Noto Sans "
    "is never found and the umlaut-incapable Pillow default is used instead.",
)
def test_load_font_uses_bundled_noto_sans_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARASAAC_FONT", raising=False)
    assert Path(load_font(18).path).name == "NotoSans-Regular.ttf"


def test_wrap_text_respects_max_width() -> None:
    font = load_font(20)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = wrap_text(draw, "eins zwei drei vier fünf sechs sieben", font, 80)
    assert len(lines) > 1
    assert all(draw.textlength(line, font=font) <= 80 for line in lines)


def test_wrap_text_keeps_explicit_line_breaks() -> None:
    font = load_font(20)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    assert wrap_text(draw, "a\nb", font, 1000) == ["a", "b"]


def test_wrap_text_empty_string() -> None:
    font = load_font(20)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    assert wrap_text(draw, "", font, 100) == [""]


# --------------------------------------------------------------------------- #
# render_sheet
# --------------------------------------------------------------------------- #


def test_render_sheet_empty_raises() -> None:
    with pytest.raises(ValueError, match="no pictograms"):
        render_sheet([], _opts())


def test_render_sheet_basic_geometry(icons_dir: Path) -> None:
    image = render_sheet([Entry(icons_dir / "1_Regen.png")], _opts(), icons_dir=icons_dir)
    assert image.mode == "RGBA"
    assert image.size == (856, 428)


def test_render_sheet_accepts_strings_paths_and_entries(icons_dir: Path) -> None:
    image = render_sheet(
        ["1_Regen.png", Path("6_rot.png"), Entry(icons_dir / "7_Berg.png")],
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.width > 0


def test_render_sheet_labels_add_height(icons_dir: Path) -> None:
    base = render_sheet([Entry(icons_dir / "1_Regen.png")], _opts(), icons_dir=icons_dir)
    labelled = render_sheet(
        [Entry(icons_dir / "1_Regen.png")], _opts(labels=True), icons_dir=icons_dir
    )
    assert labelled.height > base.height


def test_render_sheet_sentence_and_meaning_add_header(icons_dir: Path) -> None:
    plain = render_sheet([Entry(icons_dir / "1_Regen.png")], _opts(), icons_dir=icons_dir)
    headed = render_sheet(
        [Entry(icons_dir / "1_Regen.png")],
        _opts(sentence="Es regnet stark.", meaning="Der Regen fällt."),
        icons_dir=icons_dir,
    )
    assert headed.height > plain.height


def test_render_sheet_attribution_adds_footer(icons_dir: Path) -> None:
    without = render_sheet([Entry(icons_dir / "1_Regen.png")], _opts(), icons_dir=icons_dir)
    with_attr = render_sheet(
        [Entry(icons_dir / "1_Regen.png")],
        _opts(attribution=True),
        icons_dir=icons_dir,
    )
    assert with_attr.height > without.height


def test_render_sheet_role_colour_frame(icons_dir: Path) -> None:
    image = render_sheet(
        [Entry(icons_dir / "1_Regen.png", role="NOUN")], _opts(), icons_dir=icons_dir
    )
    # Top edge of the single card, away from the rounded corners.
    pixel = image.getpixel((428, 48))
    expected = tuple(int(ROLE_COLORS["NOUN"][i : i + 2], 16) for i in (1, 3, 5)) + (255,)
    assert pixel == expected


def test_render_sheet_neutral_frame_without_role(icons_dir: Path) -> None:
    image = render_sheet([Entry(icons_dir / "1_Regen.png")], _opts(), icons_dir=icons_dir)
    assert image.getpixel((428, 48)) != (255, 255, 255, 255)


def test_render_sheet_no_frames_leaves_background(icons_dir: Path) -> None:
    image = render_sheet(
        [Entry(icons_dir / "1_Regen.png", role="NOUN")],
        _opts(frames=False),
        icons_dir=icons_dir,
    )
    assert image.getpixel((428, 48)) == (255, 255, 255, 255)


def test_render_sheet_columns_force_wrapping(icons_dir: Path) -> None:
    entries = [Entry(icons_dir / name) for name in ("1_Regen.png", "6_rot.png", "7_Berg.png")]
    three = render_sheet(entries, _opts(columns=3), icons_dir=icons_dir)
    two = render_sheet(entries, _opts(columns=2), icons_dir=icons_dir)
    assert two.height > three.height
    assert two.width < three.width


def test_render_sheet_max_columns_wraps(icons_dir: Path) -> None:
    names = ["1_Regen.png", "6_rot.png", "7_Berg.png"]
    entries = [Entry(icons_dir / name) for name in names]
    one_row = render_sheet(entries, _opts(max_columns=6), icons_dir=icons_dir)
    wrapped = render_sheet(entries, _opts(max_columns=2), icons_dir=icons_dir)
    assert wrapped.height > one_row.height


def test_render_sheet_scale_zero_is_treated_as_one(icons_dir: Path) -> None:
    image = render_sheet(
        [Entry(icons_dir / "1_Regen.png")], _opts(scale=0), icons_dir=icons_dir
    )
    assert image.size == (856, 428)


def test_render_sheet_columns_zero_behaves_like_unset(icons_dir: Path) -> None:
    entries = [Entry(icons_dir / n) for n in ("1_Regen.png", "6_rot.png")]
    image = render_sheet(entries, _opts(columns=0), icons_dir=icons_dir)
    assert image.width > 0


def test_render_sheet_background_option(icons_dir: Path) -> None:
    image = render_sheet(
        [Entry(icons_dir / "1_Regen.png")], _opts(background="#000000"), icons_dir=icons_dir
    )
    assert image.getpixel((0, 0)) == (0, 0, 0, 255)


# --------------------------------------------------------------------------- #
# save_image / render_and_save
# --------------------------------------------------------------------------- #


def test_save_image_formats(tmp_path: Path, icons_dir: Path) -> None:
    image = render_sheet([Entry(icons_dir / "1_Regen.png")], _opts(), icons_dir=icons_dir)

    png = save_image(image, tmp_path / "nested" / "sheet.png")
    jpg = save_image(image, tmp_path / "sheet.jpg")
    pdf = save_image(image, tmp_path / "sheet.pdf")

    assert png.is_file() and Image.open(png).format == "PNG"
    assert jpg.is_file() and Image.open(jpg).format == "JPEG"
    assert pdf.is_file() and pdf.read_bytes().startswith(b"%PDF")


def test_render_and_save_writes_every_output(tmp_path: Path, icons_dir: Path) -> None:
    outputs = [tmp_path / "a.png", tmp_path / "b.jpg", tmp_path / "c.pdf"]
    written = render_and_save(
        [Entry(icons_dir / "1_Regen.png")], outputs, _opts(), icons_dir=icons_dir
    )
    assert written == outputs
    assert all(path.is_file() for path in outputs)


def test_render_layout_and_save_writes_output(tmp_path: Path, icons_dir: Path) -> None:
    spec = {"type": "icon", "file": "1_Regen.png"}
    written = render_layout_and_save(
        spec, [tmp_path / "layout.png"], _opts(), icons_dir=icons_dir
    )
    assert written[0].is_file()


# --------------------------------------------------------------------------- #
# entries_from_json
# --------------------------------------------------------------------------- #


def test_entries_from_json_sequence(icons_dir: Path) -> None:
    data = {
        "sentence": "Es regnet.",
        "meaning": "Regen fällt.",
        "sequence": [
            {"file": "1_Regen.png", "role": "NOUN", "concept": "Regen"},
            {"file": "6_rot.png"},
        ],
    }
    entries, meta = entries_from_json(data, icons_dir)

    assert [entry.role for entry in entries] == ["NOUN", None]
    assert entries[0].concept == "Regen"
    assert meta == {"sentence": "Es regnet.", "meaning": "Regen fällt.", "label": "sequence"}


def test_entries_from_json_alternative_by_index(icons_dir: Path) -> None:
    data = {
        "sequence": [{"file": "1_Regen.png"}],
        "alternatives": [{"label": "kurz", "files": ["6_rot.png"]}],
    }
    entries, meta = entries_from_json(data, icons_dir, alternative=0)
    assert [entry.path.name for entry in entries] == ["6_rot.png"]
    assert meta["label"] == "kurz"


def test_entries_from_json_alternative_by_label(icons_dir: Path) -> None:
    data = {"alternatives": [{"label": "kurz", "files": ["6_rot.png"]}]}
    entries, meta = entries_from_json(data, icons_dir, alternative="kurz")
    assert [entry.path.name for entry in entries] == ["6_rot.png"]


def test_entries_from_json_unknown_alternative_label(icons_dir: Path) -> None:
    with pytest.raises(KeyError):
        entries_from_json({"alternatives": []}, icons_dir, alternative="fehlt")


def test_entries_from_json_missing_file_raises(icons_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        entries_from_json({"sequence": [{"file": "nope.png"}]}, icons_dir)


# --------------------------------------------------------------------------- #
# render_layout
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "icon", "file": "1_Regen.png"},
        {"type": "text", "text": "Hallo"},
        {"type": "row", "children": ["1_Regen.png", "6_rot.png"], "gap": 10},
        {"type": "column", "children": ["1_Regen.png", "6_rot.png"]},
        {"type": "card", "children": ["1_Regen.png"]},
        {
            "type": "grid",
            "columns": ["A", "B"],
            "rows": [{"header": "1.", "cells": ["1_Regen.png", None]}],
        },
        {"type": "table", "columns": ["A"], "rows": [["1_Regen.png"]]},
        {"type": "canvas", "children": [{"x": 10, "y": 10, "node": {"type": "icon", "file": "1_Regen.png"}}]},
        {"type": "arrow", "direction": "right"},
        {"type": "arrow", "direction": "left"},
        {"type": "arrow", "direction": "up"},
        {"type": "arrow", "direction": "down"},
        {"type": "spacer", "width": 10, "height": 20},
        {"type": "divider", "orientation": "horizontal"},
        {"type": "divider", "orientation": "vertical"},
    ],
)
def test_render_layout_node_types(spec: dict, icons_dir: Path) -> None:
    image = render_layout(spec, _opts(), icons_dir=icons_dir)
    assert image.mode == "RGBA"
    assert image.width > 0 and image.height > 0


def test_render_layout_accepts_wrapped_and_unwrapped_spec(icons_dir: Path) -> None:
    wrapped = render_layout(
        {"layout": {"type": "icon", "file": "1_Regen.png"}}, _opts(), icons_dir=icons_dir
    )
    direct = render_layout({"type": "icon", "file": "1_Regen.png"}, _opts(), icons_dir=icons_dir)
    assert wrapped.size == direct.size


def test_render_layout_requires_layout_or_type(icons_dir: Path) -> None:
    with pytest.raises(ValueError, match="layout"):
        render_layout({"foo": 1}, _opts(), icons_dir=icons_dir)


def test_render_layout_unknown_type_raises(icons_dir: Path) -> None:
    with pytest.raises(ValueError, match="Unbekannter Layout-Typ"):
        render_layout({"type": "nope"}, _opts(), icons_dir=icons_dir)


def test_render_layout_icon_requires_file(icons_dir: Path) -> None:
    with pytest.raises(ValueError, match="file"):
        render_layout({"type": "icon"}, _opts(), icons_dir=icons_dir)


def test_render_layout_spec_overrides_header(icons_dir: Path) -> None:
    plain = render_layout({"type": "icon", "file": "1_Regen.png"}, _opts(), icons_dir=icons_dir)
    titled = render_layout(
        {"title": "Titel", "type": "icon", "file": "1_Regen.png"}, _opts(), icons_dir=icons_dir
    )
    with_meaning = render_layout(
        {"meaning": "Sinn", "type": "icon", "file": "1_Regen.png"}, _opts(), icons_dir=icons_dir
    )
    assert titled.height > plain.height
    assert with_meaning.height > plain.height


def test_render_layout_attribution_can_be_disabled_per_spec(icons_dir: Path) -> None:
    with_attr = render_layout(
        {"attribution": True, "type": "icon", "file": "1_Regen.png"},
        _opts(),
        icons_dir=icons_dir,
    )
    without = render_layout(
        {"attribution": False, "type": "icon", "file": "1_Regen.png"},
        _opts(),
        icons_dir=icons_dir,
    )
    assert with_attr.height > without.height


@pytest.mark.parametrize("page", ["a3", "a4-landscape"])
def test_render_layout_page_size_is_applied(page: str, icons_dir: Path) -> None:
    image = render_layout(
        {"type": "icon", "file": "1_Regen.png"},
        _opts(page_size=page),
        icons_dir=icons_dir,
    )
    assert image.size == PAGE_SIZES[page]


def test_render_layout_page_size_wxh(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "icon", "file": "1_Regen.png"},
        _opts(page_size="2000x1500"),
        icons_dir=icons_dir,
    )
    assert image.size == (2000, 1500)


def test_render_layout_page_size_tuple(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "icon", "file": "1_Regen.png"},
        _opts(page_size=(1600, 1200)),
        icons_dir=icons_dir,
    )
    assert image.size == (1600, 1200)


@pytest.mark.parametrize("bad", ["huge", "10x", "axb", "x100"])
def test_render_layout_unknown_page_size_raises(bad: str, icons_dir: Path) -> None:
    with pytest.raises(ValueError, match="Seitengr"):
        render_layout(
            {"type": "icon", "file": "1_Regen.png"},
            _opts(page_size=bad),
            icons_dir=icons_dir,
        )


def test_render_layout_row_justify_and_column_align(icons_dir: Path) -> None:
    for justify in ("start", "center", "end", "space-between"):
        image = render_layout(
            {"type": "row", "justify": justify, "width": 600, "children": ["1_Regen.png", "6_rot.png"]},
            _opts(),
            icons_dir=icons_dir,
        )
        assert image.width > 0
    for align in ("left", "center", "right"):
        image = render_layout(
            {"type": "column", "align": align, "children": ["1_Regen.png", "6_rot.png"]},
            _opts(),
            icons_dir=icons_dir,
        )
        assert image.height > 0


def test_render_layout_dashed_card(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "card", "dashed": True, "border": "#8CC63F", "children": ["1_Regen.png"]},
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.width > 0


def test_render_layout_grid_with_row_header_and_empty_cells(icons_dir: Path) -> None:
    spec = {
        "type": "grid",
        "columns": [{"label": "A", "width": 120}, "B"],
        "row_header": True,
        "rows": [
            {"header": "1.", "cells": ["1_Regen.png", None]},
            {"header": "2.", "cells": ["", "6_rot.png"]},
        ],
    }
    image = render_layout(spec, _opts(), icons_dir=icons_dir)
    assert image.width > 0 and image.height > 0


def test_render_layout_canvas_explicit_size(icons_dir: Path) -> None:
    spec = {
        "type": "canvas",
        "width": 400,
        "height": 300,
        "children": [{"x": 0, "y": 0, "node": {"type": "icon", "file": "1_Regen.png"}}],
    }
    image = render_layout(spec, _opts(), icons_dir=icons_dir)
    assert image.width >= 400
    assert image.height >= 300


def test_render_layout_text_uppercase_and_width(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "text", "text": "hallo welt", "uppercase": True, "width": 60},
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.width > 0


def test_render_layout_arrow_direction_swaps_axes(icons_dir: Path) -> None:
    horizontal = render_layout({"type": "arrow", "direction": "right"}, _opts(), icons_dir=icons_dir)
    vertical = render_layout({"type": "arrow", "direction": "up"}, _opts(), icons_dir=icons_dir)
    # The arrow is centred in a min-width canvas; the icon-sized box differs.
    assert horizontal.height < vertical.height


def test_load_font_bold_with_env_font_does_not_crash(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARASAAC_FONT", str(repo_root / "assets" / "fonts" / "NotoSans-Regular.ttf"))
    assert load_font(18, bold=True).size == 18


def test_render_sheet_truncates_overlong_label(icons_dir: Path) -> None:
    entry = Entry(icons_dir / "1_Regen.png", concept="X" * 200)
    image = render_sheet([entry], _opts(labels=True), icons_dir=icons_dir)
    assert image.width > 0


def test_render_layout_truncates_overlong_icon_label(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "icon", "file": "1_Regen.png", "show_label": True, "concept": "X" * 200},
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.width > 0


def test_render_layout_rejects_a_nested_non_node(icons_dir: Path) -> None:
    with pytest.raises(ValueError, match="Layout-Knoten"):
        render_layout({"type": "row", "children": [42]}, _opts(), icons_dir=icons_dir)


def test_render_layout_typeless_node_becomes_column(icons_dir: Path) -> None:
    image = render_layout(
        {"layout": {"children": ["1_Regen.png"]}}, _opts(), icons_dir=icons_dir
    )
    assert image.height > 0


def test_render_layout_empty_row_is_allowed(icons_dir: Path) -> None:
    image = render_layout({"type": "row"}, _opts(), icons_dir=icons_dir)
    assert image.width > 0


def test_render_layout_frame_background_and_zero_radius(icons_dir: Path) -> None:
    image = render_layout(
        {
            "type": "row",
            "background": "#EEEEEE",
            "border": "#333333",
            "radius": 0,
            "children": ["1_Regen.png"],
        },
        _opts(),
        icons_dir=icons_dir,
    )
    colors = {color for _, color in image.getcolors(maxcolors=1_000_000)}
    assert (238, 238, 238, 255) in colors  # the frame background was painted


@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_render_layout_text_alignments(align: str, icons_dir: Path) -> None:
    image = render_layout(
        {"type": "text", "text": "Hallo", "align": align}, _opts(), icons_dir=icons_dir
    )
    assert image.width > 0


@pytest.mark.parametrize("valign", ["top", "bottom", "center"])
def test_render_layout_row_cross_alignment(valign: str, icons_dir: Path) -> None:
    image = render_layout(
        {"type": "row", "align": valign, "children": ["1_Regen.png", "6_rot.png"]},
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.height > 0


def test_render_layout_grid_cell_can_be_a_list(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "grid", "columns": ["A"], "rows": [{"cells": [["1_Regen.png", "6_rot.png"]]}]},
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.height > 0


def test_render_layout_grid_pads_missing_columns(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "grid", "columns": ["A"], "rows": [{"cells": ["1_Regen.png", "6_rot.png"]}]},
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.width > 0


def test_render_layout_grid_infers_columns_when_omitted(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "grid", "rows": [{"cells": ["1_Regen.png", "6_rot.png"]}]},
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.width > 0


def test_render_layout_zero_sized_dashed_frame(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "row", "border": "#000000", "dashed": True}, _opts(), icons_dir=icons_dir
    )
    assert image.width > 0


def test_render_layout_grid_explicit_row_height(icons_dir: Path) -> None:
    image = render_layout(
        {"type": "grid", "columns": ["A"], "rows": [{"height": 200, "cells": ["1_Regen.png"]}]},
        _opts(),
        icons_dir=icons_dir,
    )
    assert image.height >= 200


def test_render_layout_canvas_accepts_inline_and_bare_children(icons_dir: Path) -> None:
    spec = {
        "type": "canvas",
        "children": [
            {"type": "text", "text": "inline", "x": 5, "y": 5},
            "1_Regen.png",
        ],
    }
    image = render_layout(spec, _opts(), icons_dir=icons_dir)
    assert image.width > 0
