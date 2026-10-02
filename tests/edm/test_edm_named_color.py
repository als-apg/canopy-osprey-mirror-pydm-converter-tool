"""EDM palette names become scheme roles under the parity rule (``import.edm``).

An ``index N`` colour names a ``colors.list`` entry; when the scheme's ``import.edm`` map
imports that name and the role's light value equals the hex the EDM path writes today, the
prop becomes ``{"$role", "fallback"}``. Otherwise the literal is kept, and a mismatch adds
one aggregated ``parity: `` note, prepended to the first node's warnings. The fixture and
palette are synthetic: stock EDM palette names, no facility PVs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pydmconverter import react
from pydmconverter.edm.ir_adapter import edm_color_name, edm_file_to_ir
from pydmconverter.edm.parser_helpers import parse_colors_list
from pydmconverter.ir.emit import to_json, to_wire_dict
from pydmconverter.ir.schema import validate_screen_json
from pydmconverter.scheme import load_scheme

FIXTURE = Path(__file__).parent / "fixtures" / "theming.edl"

# Stock EDM palette names. canopy-default imports "Monitor: NORMAL" (OK, #24a148),
# "Monitor: MAJOR" (MAJOR, #da1e28) and "GLOBAL canvas" (Display_Background, #ffffff);
# "Black" is not imported.
PALETTE = """4 0 0

blinkms=500
columns=5
max=0x10000

static 0 "Black" { 0 0 0 }
static 4 "GLOBAL canvas" { 0xbbbb 0xbbbb 0xbbbb }
static 15 "Monitor: NORMAL" { 0x2424 0xa1a1 0x4848 }
static 20 "Monitor: MAJOR" { 0xdada 0x1e1e 0x2828 }
"""


@pytest.fixture
def palette(tmp_path: Path) -> Path:
    path = tmp_path / "colors.list"
    path.write_text(PALETTE, encoding="utf-8", newline="\n")
    return path


@pytest.fixture
def scheme():
    return load_scheme(None)


def _widgets(ir):
    return ir.root.children


# --- the palette name lookup ------------------------------------------------------------------


def test_edm_color_name_reads_the_palette_entry(palette):
    colors = parse_colors_list(str(palette))
    assert edm_color_name("index 4", colors) == "GLOBAL canvas"
    assert edm_color_name("index  20", colors) == "Monitor: MAJOR"


@pytest.mark.parametrize("value", ["rgb 0 0 0", "index 9999", "banana", "", None])
def test_edm_color_name_is_none_without_a_palette_entry(palette, value):
    assert edm_color_name(value, parse_colors_list(str(palette))) is None


def test_edm_color_name_without_palette_is_none():
    assert edm_color_name("index 4", None) is None


# --- conversion with a scheme -----------------------------------------------------------------


def test_mapped_name_with_matching_light_becomes_a_role(palette, scheme):
    widgets = _widgets(edm_file_to_ir(FIXTURE, color_list_path=palette, scheme=scheme))
    assert widgets[0].props["foregroundColor"] == {"$role": "MAJOR", "fallback": "#da1e28"}
    assert widgets[3].props["foregroundColor"] == {"$role": "OK", "fallback": "#24a148"}


def test_unmapped_name_stays_literal(palette, scheme):
    widgets = _widgets(edm_file_to_ir(FIXTURE, color_list_path=palette, scheme=scheme))
    assert widgets[1].props["foregroundColor"] == "#000000"


def test_rgb_literals_stay_literal(palette, scheme):
    widgets = _widgets(edm_file_to_ir(FIXTURE, color_list_path=palette, scheme=scheme))
    assert widgets[2].props["foregroundColor"] == "#0000ff"
    assert widgets[2].props["backgroundColor"] == "#ffffff"


def test_parity_mismatch_keeps_literal_and_leads_the_first_node_warnings(palette, scheme):
    widgets = _widgets(edm_file_to_ir(FIXTURE, color_list_path=palette, scheme=scheme))
    for index in (0, 1, 3):
        assert widgets[index].props["backgroundColor"] == "#bbbbbb"
    first = widgets[0].warnings
    parity = [w for w in first if w.startswith("parity: ")]
    assert len(parity) == 1, first
    note = parity[0]
    assert first[0] == note
    assert "'GLOBAL canvas'" in note and "#bbbbbb" in note and "'Display_Background'" in note
    assert "#ffffff" in note and "3 uses" in note and "bgColor" in note
    for widget in widgets[1:]:
        assert not any(w.startswith("parity: ") for w in widget.warnings)


def test_scheme_output_is_stamped_and_validates(palette, scheme):
    ir = react.convert_to_ir(FIXTURE, color_list_path=palette, scheme=scheme)
    assert ir.schema_version == "1.1"
    assert validate_screen_json(to_wire_dict(ir)) == []


# --- no scheme: byte identity -----------------------------------------------------------------


def test_no_scheme_is_byte_identical_to_scheme_none(palette):
    without = react.convert_to_ir(FIXTURE, color_list_path=palette)
    explicit = react.convert_to_ir(FIXTURE, color_list_path=palette, scheme=None)
    assert to_json(without) == to_json(explicit)
    assert without.schema_version == "1.0"
    widgets = _widgets(without)
    assert widgets[0].props["foregroundColor"] == "#da1e28"
    assert widgets[0].props["backgroundColor"] == "#bbbbbb"
    assert not any(w.startswith("parity: ") for widget in widgets for w in widget.warnings)


def test_scheme_only_changes_the_role_props(palette, scheme):
    """Replacing each role by its fallback gives back the no-scheme output, minus parity notes."""
    plain = to_wire_dict(react.convert_to_ir(FIXTURE, color_list_path=palette))
    themed = to_wire_dict(react.convert_to_ir(FIXTURE, color_list_path=palette, scheme=scheme))

    def strip(value):
        if isinstance(value, dict):
            if "$role" in value:
                return value["fallback"]
            out = {k: strip(v) for k, v in value.items()}
            if out.get("warnings") == []:
                del out["warnings"]  # the parity note was a node's only warning
            return out
        if isinstance(value, list):
            return [strip(v) for v in value if not (isinstance(v, str) and v.startswith("parity: "))]
        return value

    assert (plain.pop("schemaVersion"), themed.pop("schemaVersion")) == ("1.0", "1.1")
    assert strip(themed) == strip(plain)


# --- through convert_bytes --------------------------------------------------------------------


def test_convert_bytes_edl_passes_scheme(palette, scheme):
    ir = react.convert_bytes(FIXTURE.read_bytes(), kind="edl", color_list_path=palette, scheme=scheme)
    widgets = _widgets(ir)
    assert widgets[0].props["foregroundColor"] == {"$role": "MAJOR", "fallback": "#da1e28"}
    assert widgets[0].warnings[0].startswith("parity: ")
    assert ir.schema_version == "1.1"
