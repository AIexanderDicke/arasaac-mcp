"""The package's public surface must stay importable and stable."""

from __future__ import annotations

import arasaac_mcp
from arasaac_mcp import ROLE_COLORS, VALID_ROLES
from arasaac_mcp.layout import PAGE_SIZES


def test_all_names_are_importable() -> None:
    for name in arasaac_mcp.__all__:
        assert hasattr(arasaac_mcp, name), f"missing public name: {name}"


def test_valid_roles_match_the_fitzgerald_key() -> None:
    assert set(VALID_ROLES) == {"PERSON", "NOUN", "VERB", "QUALITY", "SOCIAL", "MISC"}


def test_role_colours_are_hex_and_cover_every_role() -> None:
    assert set(ROLE_COLORS) == set(VALID_ROLES)
    for colour in ROLE_COLORS.values():
        assert colour.startswith("#") and len(colour) == 7


def test_page_sizes_cover_the_documented_aliases() -> None:
    assert {"a4", "a4-landscape", "letter"} <= set(PAGE_SIZES)
