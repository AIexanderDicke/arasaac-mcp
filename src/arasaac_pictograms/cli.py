"""Command line interface: build a pictogram strip from a sorted icon list."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .layout import (
    Entry,
    SheetOptions,
    entries_from_json,
    load_json,
    render_and_save,
    resolve_icon,
)

DEFAULT_ICONS_DIR = Path("icons")


def _split_files(values: list[str]) -> list[str]:
    names: list[str] = []
    for value in values:
        for part in value.replace(",", " ").split():
            if part:
                names.append(part)
    return names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make-sheet",
        description=(
            "Arrange an ordered list of ARASAAC pictograms into a single "
            "image or PDF (a 'sentence strip')."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "icons",
        nargs="*",
        help="pictogram filenames in order ('-' reads a list from stdin).",
    )
    parser.add_argument(
        "--json",
        type=Path,
        metavar="FILE",
        help="read the model output contract (sequence/alternatives) from JSON.",
    )
    parser.add_argument(
        "--alternative",
        metavar="N|LABEL",
        help="render an alternative instead of the primary sequence.",
    )
    parser.add_argument(
        "--icons-dir",
        type=Path,
        default=DEFAULT_ICONS_DIR,
        help="directory containing the pictogram PNGs.",
    )
    parser.add_argument(
        "-o",
        "--output",
        action="append",
        type=Path,
        default=None,
        metavar="FILE",
        help="output path; repeatable. Extension selects the format (.png/.jpg/.pdf).",
    )
    parser.add_argument("--sentence", help="sentence text drawn above the strip.")
    parser.add_argument("--meaning", help="plain-language paraphrase drawn below it.")
    parser.add_argument("--labels", action="store_true", help="print a label under each icon.")
    parser.add_argument("--no-frames", action="store_true", help="disable colour frames.")
    parser.add_argument("--no-attribution", action="store_true", help="hide the ARASAAC credit.")
    parser.add_argument("--icon-size", type=int, default=300, help="icon box size in px.")
    parser.add_argument("--columns", type=int, default=None, help="force a column count.")
    parser.add_argument("--max-columns", type=int, default=6, help="wrap after this many icons.")
    parser.add_argument("--gap", type=int, default=28, help="space between cards.")
    parser.add_argument("--margin", type=int, default=48, help="outer margin.")
    parser.add_argument("--padding", type=int, default=16, help="padding inside a card.")
    parser.add_argument("--scale", type=int, default=2, help="supersampling factor.")
    parser.add_argument("--dpi", type=int, default=96, help="logical resolution.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    entries: list[Entry] = []
    sentence = args.sentence
    meaning = args.meaning

    if args.json:
        data = load_json(args.json)
        alternative: int | str | None = None
        if args.alternative is not None:
            alternative = int(args.alternative) if args.alternative.isdigit() else args.alternative
        entries, meta = entries_from_json(data, args.icons_dir, alternative)
        sentence = sentence or meta.get("sentence")
        meaning = meaning or meta.get("meaning")

    names = _split_files(args.icons)
    if "-" in names:
        names.remove("-")
        names.extend(_split_files([sys.stdin.read()]))
    if names:
        entries.extend(Entry(resolve_icon(name, args.icons_dir)) for name in names)

    if not entries:
        build_parser().error("no pictograms given (pass filenames, --json, or '-' for stdin)")

    outputs = args.output or [Path("pictogram_strip.png")]
    options = SheetOptions(
        icon_size=args.icon_size,
        columns=args.columns,
        max_columns=args.max_columns,
        gap=args.gap,
        margin=args.margin,
        padding=args.padding,
        frames=not args.no_frames,
        labels=args.labels,
        sentence=sentence,
        meaning=meaning,
        attribution=not args.no_attribution,
        scale=args.scale,
        dpi=args.dpi,
    )

    written = render_and_save(entries, outputs, options, icons_dir=args.icons_dir)
    for path in written:
        print(path)
    print(", ".join(entry.path.name for entry in entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
