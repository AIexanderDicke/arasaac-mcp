"""The ``make-sheet`` command line entry point (:mod:`arasaac_mcp.cli`)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from arasaac_mcp import cli


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# parser / helpers
# --------------------------------------------------------------------------- #


def test_parser_defaults() -> None:
    args = cli.build_parser().parse_args([])
    assert args.icons == []
    assert args.icons_dir == Path("icons")
    assert args.output is None
    assert args.icon_size == 300
    assert args.max_columns == 6
    assert args.gap == 28
    assert args.margin == 48
    assert args.padding == 16
    assert args.scale == 2
    assert args.dpi == 96
    assert args.labels is False
    assert args.page_size is None


def test_split_files_handles_commas_spaces_and_empties() -> None:
    assert cli._split_files(["a,b", "c d", "", "e"]) == ["a", "b", "c", "d", "e"]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"layout": {"type": "row"}}, True),
        ({"type": "row"}, True),
        ({"sequence": []}, False),
        ({"type": "row", "sequence": []}, False),
        ("not a dict", False),
        (None, False),
    ],
)
def test_looks_like_layout(data: object, expected: bool) -> None:
    assert cli._looks_like_layout(data) is expected


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def test_main_renders_filenames(icons_dir: Path, tmp_path: Path, capsys) -> None:
    output = tmp_path / "sheet.png"
    rc = cli.main(["--icons-dir", str(icons_dir), "-o", str(output), "1_Regen.png", "6_rot.png"])

    assert rc == 0
    assert output.is_file()
    printed = capsys.readouterr().out
    assert str(output) in printed
    assert "1_Regen.png, 6_rot.png" in printed


def test_main_reads_filenames_from_stdin(
    icons_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "stdin.png"
    monkeypatch.setattr("sys.stdin", io.StringIO("1_Regen.png 6_rot.png"))

    rc = cli.main(["--icons-dir", str(icons_dir), "-o", str(output), "-"])

    assert rc == 0
    assert output.is_file()


def test_main_default_output_path(
    icons_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["--icons-dir", str(icons_dir), "1_Regen.png"])
    assert rc == 0
    assert (tmp_path / "pictogram_strip.png").is_file()


def test_main_json_sequence(icons_dir: Path, tmp_path: Path, capsys) -> None:
    contract = _write(
        tmp_path / "contract.json",
        {
            "sentence": "Es regnet.",
            "sequence": [
                {"file": "1_Regen.png", "role": "NOUN"},
                {"file": "6_rot.png"},
            ],
        },
    )
    output = tmp_path / "seq.png"
    rc = cli.main(["--icons-dir", str(icons_dir), "--json", str(contract), "-o", str(output)])

    assert rc == 0
    assert output.is_file()
    assert "1_Regen.png, 6_rot.png" in capsys.readouterr().out


def test_main_json_alternative_by_label(icons_dir: Path, tmp_path: Path) -> None:
    contract = _write(
        tmp_path / "contract.json",
        {"alternatives": [{"label": "kurz", "files": ["6_rot.png"]}]},
    )
    output = tmp_path / "alt.png"
    rc = cli.main(
        [
            "--icons-dir",
            str(icons_dir),
            "--json",
            str(contract),
            "--alternative",
            "kurz",
            "-o",
            str(output),
        ]
    )
    assert rc == 0 and output.is_file()


def test_main_json_alternative_by_index(icons_dir: Path, tmp_path: Path) -> None:
    contract = _write(
        tmp_path / "contract.json",
        {
            "alternatives": [
                {"label": "a", "files": ["1_Regen.png"]},
                {"label": "b", "files": ["6_rot.png"]},
            ]
        },
    )
    output = tmp_path / "alt.png"
    rc = cli.main(
        [
            "--icons-dir",
            str(icons_dir),
            "--json",
            str(contract),
            "--alternative",
            "1",
            "-o",
            str(output),
        ]
    )
    assert rc == 0 and output.is_file()


def test_main_json_layout(icons_dir: Path, tmp_path: Path, capsys) -> None:
    layout = _write(
        tmp_path / "layout.json",
        {"sentence": "Plan", "layout": {"type": "row", "children": ["1_Regen.png", "6_rot.png"]}},
    )
    output = tmp_path / "layout.png"
    rc = cli.main(["--icons-dir", str(icons_dir), "--json", str(layout), "-o", str(output)])

    assert rc == 0
    assert output.is_file()
    # A layout render does not print the positional filenames line.
    assert "1_Regen.png, 6_rot.png" not in capsys.readouterr().out


def test_main_json_layout_with_page_size(icons_dir: Path, tmp_path: Path) -> None:
    layout = _write(
        tmp_path / "layout.json",
        {"layout": {"type": "icon", "file": "1_Regen.png"}},
    )
    output = tmp_path / "a4.png"
    rc = cli.main(
        [
            "--icons-dir",
            str(icons_dir),
            "--json",
            str(layout),
            "--page-size",
            "a4-landscape",
            "-o",
            str(output),
        ]
    )
    assert rc == 0 and output.is_file()


def test_main_writes_pdf_by_extension(icons_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "sheet.pdf"
    cli.main(["--icons-dir", str(icons_dir), "-o", str(output), "1_Regen.png"])
    assert output.read_bytes().startswith(b"%PDF")


def test_main_rejects_missing_input(icons_dir: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--icons-dir", str(icons_dir)])
    assert excinfo.value.code == 2


def test_main_rejects_layout_plus_filenames(icons_dir: Path, tmp_path: Path) -> None:
    layout = _write(tmp_path / "layout.json", {"layout": {"type": "icon", "file": "1_Regen.png"}})
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--icons-dir", str(icons_dir), "--json", str(layout), "1_Regen.png"])
    assert excinfo.value.code == 2


def test_main_missing_pictogram_raises(icons_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        cli.main(["--icons-dir", str(icons_dir), "-o", str(tmp_path / "x.png"), "nope.png"])
