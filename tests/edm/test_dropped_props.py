"""Dropped-prop recording: EDM props the adapter never uses, and Qt props the builder cannot map.

A prop the converter silently discards is a fidelity loss nobody sees. The EDM
adapter records, per object, every key that is neither mapped to a Qt prop nor read
by any adapter path (channel attrs, alarm/pip rules, class fixups, visibility); the
IR builder records every Qt prop its widget's ``qtPropMap`` has no entry for. Both
land in ``dropped_props``, which is never emitted on the wire.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pydmconverter.edm import edm_qt, ir_adapter
from pydmconverter.edm.ir_adapter import edm_file_to_ir, edm_group_to_source_nodes
from pydmconverter.edm.parser import EDMFileParser, EDMObject
from pydmconverter.edm.parser_helpers import parse_colors_list
from pydmconverter.ir.builder import IRBuilder
from pydmconverter.ir.emit import to_json, to_wire_dict
from pydmconverter.ir.registry import VendoredRegistry
from pydmconverter.ir.source import SourceNode

FIXTURES = Path(__file__).parent / "fixtures"
EDL_FIXTURES = sorted(FIXTURES.glob("*.edl"))
COLORS = FIXTURES / "colors.list"


def _source_nodes(path: Path) -> list[SourceNode]:
    parser = EDMFileParser(str(path), str(path.with_suffix(".ui")), calc_reuse_short=False)
    return edm_group_to_source_nodes(parser.ui, colors=parse_colors_list(str(COLORS)))


def _walk(nodes: list[SourceNode]):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _literals(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _adapter_read_names() -> tuple[set[str], dict[str, set[str]]]:
    """String literals of the adapter, split into shared code and per-class fixups.

    Any prop key the adapter reads is a string literal in its source. Literals in a
    ``_CLASS_FIXUPS`` function (and in module constants only that fixup uses, e.g.
    ``_BAR_UNMAPPED_PROPS``) are reads for that class alone; everything else — the
    mapping loop, channel attrs, rules, visibility, class resolution — is shared.
    """
    tree = ast.parse(Path(ir_adapter.__file__).read_text())
    fixup_names = {fn.__name__ for fn in ir_adapter._CLASS_FIXUPS.values()}
    users: dict[str, set[str]] = {}  # module-level name -> top-level functions that load it
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef):
            for n in ast.walk(stmt):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    users.setdefault(n.id, set()).add(stmt.name)
    shared = _literals(ast.parse(Path(edm_qt.__file__).read_text()))
    per_fixup: dict[str, set[str]] = {name: set() for name in fixup_names}
    for stmt in tree.body:
        owner = None
        if isinstance(stmt, ast.FunctionDef) and stmt.name in fixup_names:
            owner = stmt.name
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            fn_users = set().union(*(users.get(name, set()) for name in names)) if names else set()
            if len(fn_users) == 1 and fn_users <= fixup_names:
                owner = next(iter(fn_users))
        if owner is None:
            shared |= _literals(stmt)
        else:
            per_fixup[owner] |= _literals(stmt)
    return shared, per_fixup


SHARED_READS, FIXUP_READS = _adapter_read_names()


def _reads_for(raw_class: str | None) -> set[str]:
    fixup = ir_adapter._CLASS_FIXUPS.get((raw_class or "").lower())
    return SHARED_READS | (FIXUP_READS[fixup.__name__] if fixup else set())


def test_every_fixture_is_covered():
    assert len(EDL_FIXTURES) >= 20


@pytest.mark.parametrize("path", EDL_FIXTURES, ids=lambda p: p.stem)
def test_no_recorded_name_is_read_by_the_adapter(path: Path):
    """A dropped key is never mapped and never named by any adapter path that runs for its class."""
    for node in _walk(_source_nodes(path)):
        for name in node.dropped_props:
            assert name not in edm_qt.EDM_TO_QT_PROP, f"{path.name}: mapped key {name!r} recorded as dropped"
            assert name not in _reads_for(node.raw_class), (
                f"{path.name}: {name!r} is read by the adapter for {node.raw_class} yet recorded"
            )
            assert name in node.raw_props, f"{path.name}: {name!r} is not a prop of {node.raw_class}"


@pytest.mark.parametrize("path", EDL_FIXTURES, ids=lambda p: p.stem)
def test_dropped_props_have_no_duplicates(path: Path):
    for node in _walk(_source_nodes(path)):
        assert len(node.dropped_props) == len(set(node.dropped_props))


def test_class_specific_read_is_a_loss_elsewhere():
    """showScale is read only by the bar fixup (to warn); on a meter nothing uses it."""
    assert "showScale" in FIXUP_READS["_fixup_bar"]
    assert "showScale" not in SHARED_READS
    meters = [n for n in _walk(_source_nodes(FIXTURES / "meter.edl")) if n.raw_class == "activeMeterClass"]
    assert any("showScale" in n.dropped_props for n in meters)


def test_top_shadow_color_is_recorded_as_a_loss():
    """topShadowColor is unmapped and unread: every occurrence on a mapped widget is recorded."""
    count = sum(
        node.dropped_props.count("topShadowColor") for path in EDL_FIXTURES for node in _walk(_source_nodes(path))
    )
    assert count == 7


def test_unknown_widget_records_nothing():
    """An unknown-widget keeps every original prop verbatim, so nothing is lost."""
    nodes = _source_nodes(FIXTURES / "unknown.edl")
    unknown = [n for n in _walk(nodes) if n.qt_class is None and n.registry_id is None]
    assert unknown, "fixture should contain an unmapped EDM class"
    assert all(n.dropped_props == [] for n in unknown)


def test_reads_are_tracked_per_object_and_properties_restored():
    """Tracking must not leak: the object's own dict is back in place after conversion."""
    obj = EDMObject(
        name="activeXTextDspClass",
        x=1,
        y=2,
        width=30,
        height=10,
        properties={"controlPv": "PV:A", "topShadowColor": "index 1", "fooBar": 3, "visPv": "PV:V"},
    )
    original = obj.properties
    parent = type("G", (), {"objects": [obj]})()
    (node,) = edm_group_to_source_nodes(parent)
    assert obj.properties is original
    assert type(obj.properties) is dict
    assert "topShadowColor" in node.dropped_props
    assert "fooBar" in node.dropped_props
    assert "controlPv" not in node.dropped_props  # read by the channel-attr path
    assert "visPv" not in node.dropped_props  # read by the visibility path
    assert node.raw_props == original


def test_builder_records_unmapped_qt_props():
    """A Qt prop with no qtPropMap entry is dropped by the builder, and recorded."""
    node = SourceNode(
        qt_class="PyDMLabel",
        qt_props={"channel": "ca://PV:A", "notARealQtProp": 1},
        geometry=(0, 0, 10, 10),
        dropped_props=["edmOnlyKey"],
    )
    screen = IRBuilder(VendoredRegistry()).build_screen(
        screen_id="s", title="S", source_type="edl-converter", size=(100, 100), top_level=[node]
    )
    (widget,) = screen.root.children
    assert widget.dropped_props == ["edmOnlyKey", "notARealQtProp"]
    assert "channel" not in widget.dropped_props


def test_dropped_props_never_reach_the_wire():
    screen = edm_file_to_ir(FIXTURES / "misc_buttons.edl", color_list_path=COLORS)
    assert any(child.dropped_props for child in screen.root.children)
    assert "droppedProps" not in to_json(screen)
    assert "dropped_props" not in to_json(screen)
    assert "droppedProps" not in to_wire_dict(screen)["root"]["children"][0]
