"""Tests for named colours becoming scheme roles (``pydmconverter.bob.colors.named_color``).

The parity rule: a Phoebus colour name the scheme imports becomes ``{"$role", "fallback"}``
only when the role's light value equals the hex the converter writes today; otherwise the
literal is kept and one aggregated ``parity: `` note per (name, saved RGB, role light) is
prepended to the first non-declarer child of root. All panels and schemes are synthetic.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pydmconverter.bob.coercion import BUILTIN_NAMED_COLORS, coerce, color_from_element, color_from_text
from pydmconverter.bob.colors import ColorContext, named_color
from pydmconverter.bob.ir_adapter import bob_bytes_to_ir
from pydmconverter.ir.emit import to_json, to_wire_dict
from pydmconverter.scheme import SchemeResult, load_scheme

# Synthetic scheme: Text keeps Phoebus black; Grid is overridden; Display_Background is white.
_ROLES = {
    "Text": "#000000",
    "Grid": "#c6c6c6",
    "Display_Background": "#ffffff",
    "Transparent": "#ffffff00",
    "Read_Background": "#f0f0f0",
}
_IMPORTS = {
    "phoebus": {name: name for name in _ROLES} | {"Ghost": "NoSuchRole"},
    "edm": {"GLOBAL canvas": "Display_Background"},
}


def _scheme() -> SchemeResult:
    roles = list(_ROLES)
    flat = {"roles": roles, "light": [_ROLES[r] for r in roles], "dark": ["#101010"] * len(roles)}
    return SchemeResult(flat=flat, imports=_IMPORTS, meta={})


def _ctx(**kwargs) -> ColorContext:
    return ColorContext.from_scheme(_scheme(), dict(BUILTIN_NAMED_COLORS), **kwargs)


def _color(name: str | None = None, rgb: tuple[int, int, int] | None = None, tag: str = "foreground_color"):
    attrs = "" if name is None else f' name="{name}"'
    if rgb is not None:
        attrs += f' red="{rgb[0]}" green="{rgb[1]}" blue="{rgb[2]}"'
    return ET.fromstring(f"<{tag}><color{attrs}/></{tag}>")


# --------------------------------------------------------------------------
# named_color: the rule itself
# --------------------------------------------------------------------------
def test_mapped_and_equal_gives_role():
    ctx = _ctx()
    assert named_color("Text", (0, 0, 0, 255), "foreground_color", ctx) == {"$role": "Text", "fallback": "#000000"}
    assert ctx.parity_notes() == []


def test_mapped_transparent_compares_alpha():
    ctx = _ctx()
    assert named_color("Transparent", (255, 255, 255, 0), "background_color", ctx) == {
        "$role": "Transparent",
        "fallback": "#ffffff00",
    }


def test_mapped_and_different_gives_literal_and_one_aggregated_note():
    ctx = _ctx()
    for slot in ("foreground_color", "background_color", "foreground_color"):
        assert named_color("Grid", (128, 128, 128, 255), slot, ctx) == "#808080"
    notes = ctx.parity_notes()
    assert len(notes) == 1
    note = notes[0]
    assert note.startswith("parity: ")
    assert "'Grid'" in note and "#808080" in note and "#c6c6c6" in note
    assert "3 uses" in note
    assert "foreground_color, background_color" in note


def test_parity_notes_keyed_by_saved_rgb():
    ctx = _ctx()
    named_color("Grid", (128, 128, 128, 255), "a", ctx)
    named_color("Grid", (1, 2, 3, 255), "a", ctx)
    named_color("Grid", (1, 2, 3, 255), "b", ctx)
    notes = ctx.parity_notes()
    assert len(notes) == 2
    assert "1 use:" in notes[0] and "#808080" in notes[0]
    assert "2 uses" in notes[1] and "#010203" in notes[1]


@pytest.mark.parametrize("name", ["Background", "Ghost", None])
def test_unmapped_gives_literal(name):
    # Background is not imported; Ghost is imported to a role the scheme lacks; None is unnamed.
    ctx = _ctx()
    assert named_color(name, (255, 255, 255, 255), "background_color", ctx) == "#ffffff"
    assert ctx.parity_notes() == []


def test_no_context_gives_literal():
    assert named_color("Text", (0, 0, 0, 255), "foreground_color", None) == "#000000"


def test_import_kind_selects_the_map():
    ctx = _ctx(import_kind="edm")
    assert named_color("GLOBAL canvas", (255, 255, 255, 255), "bg", ctx) == {
        "$role": "Display_Background",
        "fallback": "#ffffff",
    }
    assert named_color("Text", (0, 0, 0, 255), "fg", ctx) == "#000000"


# --------------------------------------------------------------------------
# coercion routed through named_color
# --------------------------------------------------------------------------
def test_color_from_element_named_maps_to_role():
    assert color_from_element(_color("Text", (9, 9, 9)), ctx=_ctx()) == {"$role": "Text", "fallback": "#000000"}


def test_color_from_element_unknown_name_uses_saved_rgb_for_parity():
    # Display_Background is not a Phoebus built-in, so today's hex is the saved RGB.
    ctx = _ctx()
    assert color_from_element(_color("Display_Background", (255, 255, 255)), ctx=ctx) == {
        "$role": "Display_Background",
        "fallback": "#ffffff",
    }
    assert color_from_element(_color("Display_Background", (250, 250, 250)), ctx=ctx) == "#fafafa"
    assert len(ctx.parity_notes()) == 1


def test_color_from_element_slot_is_the_property_tag():
    ctx = _ctx()
    color_from_element(_color("Grid", tag="line_color"), ctx=ctx)
    assert "line_color" in ctx.parity_notes()[0]


def test_color_from_element_unnamed_stays_literal():
    assert color_from_element(_color(rgb=(0, 0, 0)), ctx=_ctx()) == "#000000"


@pytest.mark.parametrize(
    "elem",
    [
        _color("Text", (9, 9, 9)),
        _color("Grid", (1, 2, 3)),
        _color("Display_Background", (255, 255, 255)),
        _color("NotAName", (10, 20, 30)),
        _color("NotAName"),
        _color(rgb=(1, 2, 3)),
        _color(),
    ],
)
def test_no_scheme_is_identical_to_today(elem):
    plain_warnings: list[str] = []
    ctx_warnings: list[str] = []
    assert color_from_element(elem, None, ctx_warnings, None) == color_from_element(elem, None, plain_warnings)
    assert ctx_warnings == plain_warnings


def test_color_from_text_name_maps_and_hex_stays_literal():
    ctx = _ctx()
    assert color_from_text("Text", ctx=ctx) == {"$role": "Text", "fallback": "#000000"}
    assert color_from_text("#000000", ctx=ctx) == "#000000"
    assert color_from_text("#00000080", ctx=ctx) == "#000000"  # today's 6-digit truncation kept
    assert color_from_text("0,0,0", ctx=ctx) == "#000000"


def test_coerce_with_ctx_maps_a_named_string():
    assert coerce("color", " Text ", ctx=_ctx()) == {"$role": "Text", "fallback": "#000000"}
    assert coerce("color", "Text") == "#000000"
    assert coerce("color", "Grid", ctx=_ctx()) == "#808080"


def test_context_named_table_used_when_no_explicit_table():
    ctx = ColorContext.from_scheme(_scheme(), {"Text": (0, 0, 0, 255), "Custom": (0, 0, 0, 255)})
    # "Custom" is in the context's table but not imported by the scheme: literal.
    assert color_from_text("Custom", ctx=ctx) == "#000000"
    assert color_from_text("Text", ctx=ctx) == {"$role": "Text", "fallback": "#000000"}


# --------------------------------------------------------------------------
# Whole panels through bob_bytes_to_ir(scheme=...)
# --------------------------------------------------------------------------
_DECLARER_BUTTON = """
<widget type="action_button" version="3.0.0">
  <name>B</name>
  <pv_name>loc://flag&lt;VLong&gt;(0)</pv_name>
  <actions><action type="write_pv"><pv_name>$(pv_name)</pv_name><value>1</value>
  <description>Go</description></action></actions>
</widget>
"""


def _panel(body: str, background: str = "") -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<display version="2.0.0"><name>t</name>{background}{body}</display>'
    ).encode()


def _textupdate(name: str, color_xml: str) -> str:
    return (
        f'<widget type="textupdate" version="2.0.0"><name>{name}</name><pv_name>sim://x</pv_name>'
        f"<foreground_color>{color_xml}</foreground_color></widget>"
    )


_PANEL = _panel(
    _DECLARER_BUTTON
    + _textupdate("T1", '<color name="Text" red="0" green="0" blue="0"/>')
    + _textupdate("T2", '<color name="Grid" red="128" green="128" blue="128"/>')
    + _textupdate("T3", '<color name="Grid" red="128" green="128" blue="128"/>'),
    '<background_color><color name="Display_Background" red="255" green="255" blue="255"/></background_color>',
)


def _children(wire: dict) -> list[dict]:
    return wire["root"]["children"]


def test_no_scheme_panel_output_identical_to_today():
    assert to_json(bob_bytes_to_ir(_PANEL, scheme=None)) == to_json(bob_bytes_to_ir(_PANEL))


def test_named_display_background_becomes_role():
    wire = to_wire_dict(bob_bytes_to_ir(_PANEL, scheme=_scheme()))
    assert wire["root"]["props"]["backgroundColor"] == {"$role": "Display_Background", "fallback": "#ffffff"}


def test_named_display_background_with_default_scheme_becomes_role():
    wire = to_wire_dict(bob_bytes_to_ir(_PANEL, scheme=load_scheme(None)))
    assert wire["root"]["props"]["backgroundColor"] == {"$role": "Display_Background", "fallback": "#ffffff"}


def test_widget_props_map_and_keep_literals():
    children = _children(to_wire_dict(bob_bytes_to_ir(_PANEL, scheme=_scheme())))
    colors = [c["props"].get("foregroundColor") for c in children if c["props"].get("pv") == "sim://x"]
    assert colors == [{"$role": "Text", "fallback": "#000000"}, "#808080", "#808080"]


def test_parity_notes_land_on_first_non_declarer_child():
    children = _children(to_wire_dict(bob_bytes_to_ir(_PANEL, scheme=_scheme())))
    declarer, first = children[0], children[1]
    # Declarers come first in top_level: a hidden 0x0 pv-label for the loc:// initializer.
    assert declarer["type"] == "pv-label"
    assert (declarer["geometry"]["width"], declarer["geometry"]["height"]) == (0, 0)
    assert not [w for w in declarer.get("warnings", []) if w.startswith("parity: ")]

    parity = [w for w in first.get("warnings", []) if w.startswith("parity: ")]
    assert len(parity) == 1
    assert "'Grid'" in parity[0] and "2 uses" in parity[0]
    assert first["warnings"][0] == parity[0]  # prepended
    for child in children[2:]:
        assert not [w for w in child.get("warnings", []) if w.startswith("parity: ")]


def test_parity_notes_are_per_document():
    scheme = _scheme()
    first = _children(to_wire_dict(bob_bytes_to_ir(_PANEL, scheme=scheme)))[1]
    second = _children(to_wire_dict(bob_bytes_to_ir(_PANEL, scheme=scheme)))[1]
    assert first["warnings"] == second["warnings"]
    assert "2 uses" in next(w for w in second["warnings"] if w.startswith("parity: "))


def test_no_parity_note_when_everything_maps():
    panel = _panel(_DECLARER_BUTTON + _textupdate("T1", '<color name="Text" red="0" green="0" blue="0"/>'))
    children = _children(to_wire_dict(bob_bytes_to_ir(panel, scheme=_scheme())))
    for child in children:
        assert not [w for w in child.get("warnings", []) if w.startswith("parity: ")]
