"""Corpus tests: the Phoebus ``.bob`` adapter over a real site's panel tree.

The corpus is never committed. Every test here reads its root from the
``PHOEBUS_CORPUS`` environment variable and skips, with the reason, when it is unset,
so ``pytest tests/bob`` passes on a machine without the panels. Which files count is
fixed by :mod:`tests.bob.corpus_manifest` (glob, exclusions, symlink rule).

Three groups of tests:

* **Milestones** — six panels that exercise every milestone construct. Each converts
  with no unknown widget, validates against the IR schema through both
  :func:`bob_file_to_ir` and ``convert_bytes(kind="bob")``, is byte-stable across two
  runs and equals its golden. Goldens live only under the corpus root, in
  :data:`GOLDEN_DIR`, never in this repository; a missing golden is written from the
  current output on first run (set ``PHOEBUS_UPDATE_GOLDENS=1`` to rewrite them all).
  Focused tests pin the proposal's acceptance points so a regenerated golden cannot
  silently change them.
* **Whole corpus** — alarm-boilerplate count, initializer accounting, emitted-PV
  hygiene, mapped-widget ratio, ``.opi`` action targets and the timing budget.
* **Report** — the coverage report, printed (run with ``-s`` to see it), not gated
  beyond the assertions above.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from pydmconverter.bob.ir_adapter import bob_file_to_ir
from pydmconverter.bob.local_pv import is_gateway_channel, local_pv_key
from pydmconverter.bob.parser import BobDisplay, BobWidget, parse_bob
from pydmconverter.bob.rules import RuleContext
from pydmconverter.bob.scripts import match_alarm_boilerplate, mentions_severity
from pydmconverter.ir.emit import to_json, to_wire_dict
from pydmconverter.ir.macros import normalize_macro_syntax
from pydmconverter.ir.model import ScreenIR, WidgetNode
from pydmconverter.ir.schema import validate_screen_json
from pydmconverter.react import convert_bytes
from tests.bob.corpus_manifest import CORPUS_ENV, Manifest, corpus_root, load_manifest, output_path

GOLDEN_DIR = PurePosixPath(".goldens/pydmconverter")
UPDATE_GOLDENS_ENV = "PHOEBUS_UPDATE_GOLDENS"

MILESTONES = (
    "bts/BTSView.bob",
    "bts/embedded/_tv.bob",
    "bts/embedded/_PulseMagKnobDevice.bob",
    "gtb/common/embedded/_bpm.bob",
    "common/embedded/_KnobDevice.bob",
    "common/GregLauncher/Launcher/_injectorLauncher.bob",
)

# Acceptance numbers from the proposal, measured on the curated corpus.
ALARM_BOILERPLATE_COUNT = 5598
OPI_ACTION_TARGETS = 552
MIN_MAPPED_RATIO = 0.90
BTSVIEW_BUDGET_S = 1.0
CORPUS_BUDGET_S = 60.0

_MACRO_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.\-]*)\}")
_LOC_INIT_RE = re.compile(r"^loc://[^<(?]*(?:<[^>]*>)?\(")

# Warning categories for the report, first match wins. Patterns match the text after
# the "<widget>: " prefix.
WARNING_CATEGORIES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern))
    for label, pattern in (
        ("unknown named colour (saved RGB used)", r"^unknown named color "),
        ("no registry entry (unknown-widget)", r"^No registry entry for "),
        ("tier-2 script", r"^script needs the script runtime \(tier 2\)"),
        ("tier-2 execute action", r"^execute action needs the script runtime"),
        ("tier-2 rule formula binding", r"^rule .* needs the script runtime \(tier 2\): formula binding"),
        ("tier-2 trace formula binding", r"^trace .* needs the script runtime \(tier 2\): formula binding"),
        ("formula PV not lowered", r"^formula PV not lowered: "),
        ("formula has no reader", r"^formula \S+ has no reader "),
        ("pvStr-on-gateway", r"^rule compares PV text; "),
        ("unsupported rule target", r"^unsupported rule target "),
        ("unsupported rule expression", r"^unsupported rule expression"),
        ("background_color rule on transparent widget", r"^background_color rule ignored on a transparent"),
        ("rule without static default", r"^rule .* not lowered: its target has no static value"),
        ("alarm boilerplate skipped", r"^alarm-colour script not lowered"),
        ("shell command as execute", r"^shell command carried as execute action"),
        (".opi open_display target", r"^open_display target .* is a legacy \.opi"),
        ("open_display without file", r"^open_display with no file"),
        ("open_display target unknown", r"^open_display target .* unknown; using replace"),
        ("image not copied", r"^image .* not copied"),
        ("bool_button images", r"^on/off images not carried"),
        ("tabs", r"^Phoebus tabs need a registry qtPropMap"),
        ("local PV type unsupported", r"^local PV type .* not supported"),
        ("array local PV initializer", r"^array local PV initializer not supported"),
    )
)


# --------------------------------------------------------------------------
# Walks and small helpers
# --------------------------------------------------------------------------
def _nodes(node: WidgetNode) -> Iterator[WidgetNode]:
    yield node
    for child in node.children:
        yield from _nodes(child)


def _widgets(widgets: list[BobWidget]) -> Iterator[BobWidget]:
    for widget in widgets:
        yield widget
        yield from _widgets(widget.children)


def _warnings(screen: ScreenIR) -> list[str]:
    return [message for node in _nodes(screen.root) for message in node.warnings]


def _unknown_widgets(screen: ScreenIR) -> list[str]:
    return [str(node.props.get("originalClass")) for node in _nodes(screen.root) if node.type == "unknown-widget"]


def _category(message: str) -> str:
    text = message.split(": ", 1)[1] if ": " in message else message
    for label, pattern in WARNING_CATEGORIES:
        if pattern.search(text):
            return label
    return "other"


def _is_declarer(node: WidgetNode) -> bool:
    geometry = node.geometry
    return (
        node.type == "pv-label"
        and geometry.width == 0
        and geometry.height == 0
        and "&init=" in str(node.props.get("pv", ""))
    )


def _emitted_pvs(screen: ScreenIR) -> Iterator[str]:
    """Every PV the IR hands the runtime: channels, curves, action targets, rules, formulas."""
    for node in _nodes(screen.root):
        props = node.props
        for key in ("pv", "readbackPV"):
            if isinstance(props.get(key), str):
                yield props[key]
        for curve in props.get("curves") or []:
            for key in ("x_channel", "y_channel"):
                if isinstance(curve.get(key), str):
                    yield curve[key]
        for action in props.get("actions") or []:
            if isinstance(action, dict) and isinstance(action.get("pvName"), str):
                yield action["pvName"]
        for rule in node.rules:
            for pv in rule.pvs:
                yield pv.name
    for formula in screen.formulas:
        yield from formula.bindings.values()


def _macro_refs(value: Any) -> set[str]:
    """``${NAME}`` references in a wire value, ignoring ``meta`` and ``warnings`` text."""
    if isinstance(value, str):
        return set(_MACRO_REF_RE.findall(value))
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in ("meta", "warnings"):
                found |= _macro_refs(item)
    elif isinstance(value, list):
        for item in value:
            found |= _macro_refs(item)
    return found


# --------------------------------------------------------------------------
# Corpus fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def manifest() -> Manifest:
    root = corpus_root()
    if root is None:
        pytest.skip(f"{CORPUS_ENV} not set: the Phoebus corpus is not committed; point it at a panel tree")
    if not root.is_dir():
        pytest.skip(f"{CORPUS_ENV}={root} is not a directory")
    return load_manifest(root)


@dataclass
class Converted:
    """The whole curated corpus, parsed and converted once per module."""

    manifest: Manifest
    screens: dict[PurePosixPath, ScreenIR] = field(default_factory=dict)
    displays: dict[PurePosixPath, BobDisplay] = field(default_factory=dict)
    seconds: float = 0.0


@pytest.fixture(scope="module")
def converted(manifest: Manifest) -> Converted:
    result = Converted(manifest=manifest)
    start = time.perf_counter()
    for entry in manifest.entries:
        result.screens[entry.rel] = bob_file_to_ir(entry.source)
    result.seconds = time.perf_counter() - start
    for entry in manifest.entries:
        result.displays[entry.rel] = parse_bob(entry.source)
    return result


@pytest.fixture(scope="module")
def written(converted: Converted, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The converted corpus written out, each screen at its entry's (symlink) path."""
    out = tmp_path_factory.mktemp("corpus-out")
    for rel, screen in converted.screens.items():
        target = out / output_path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(to_json(screen), encoding="utf-8", newline="")
    return out


def _milestone(manifest: Manifest, rel: str) -> ScreenIR:
    return bob_file_to_ir(manifest.entry(rel).source)


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------
def test_manifest_applies_the_committed_rules(manifest: Manifest):
    rels = {entry.rel for entry in manifest.entries}
    assert manifest.entries, "no .bob files found under the corpus root"
    assert not any(rel.parts[0] in {"examples", "autogen", "templates"} for rel in rels)
    assert not any(rel.parts[0].startswith("synced_files") for rel in rels)
    assert all(entry.source.is_file() for entry in manifest.entries)
    assert not rels & set(manifest.dangling)
    for entry in manifest.entries:
        if entry.rerooted:
            # Written at the link's own path, read from the corpus copy.
            assert (manifest.root / entry.rel).is_symlink()
            assert entry.source != manifest.root / entry.rel


# --------------------------------------------------------------------------
# Milestones: goldens, schema, both entry points
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rel", MILESTONES)
def test_milestone_converts_cleanly(manifest: Manifest, rel: str):
    entry = manifest.entry(rel)
    screen = bob_file_to_ir(entry.source)
    assert _unknown_widgets(screen) == []
    assert validate_screen_json(to_wire_dict(screen)) == []

    from_bytes = convert_bytes(entry.source.read_bytes(), kind="bob")
    assert _unknown_widgets(from_bytes) == []
    assert validate_screen_json(to_wire_dict(from_bytes)) == []


@pytest.mark.parametrize("rel", MILESTONES)
def test_milestone_golden(manifest: Manifest, rel: str):
    first = to_json(_milestone(manifest, rel))
    second = to_json(_milestone(manifest, rel))
    assert first == second, "output is not byte-stable across two runs"

    golden = manifest.root / GOLDEN_DIR / output_path(PurePosixPath(rel))
    if os.environ.get(UPDATE_GOLDENS_ENV) or not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(first, encoding="utf-8", newline="")
    assert golden.read_text(encoding="utf-8") == first


def test_btsview_acceptance(manifest: Manifest):
    screen = _milestone(manifest, "bts/BTSView.bob")

    warnings = _warnings(screen)
    assert len(warnings) == 1, warnings
    assert warnings[0].startswith("Action Button_7: shell command carried as execute action")

    first = screen.root.children[0]
    assert _is_declarer(first)
    assert first.props["pv"] == "loc://testtriggercolorcode?type=int&init=1"

    leds = [node for node in _nodes(screen.root) if node.type == "pv-led"]
    assert [led.props["pv"] for led in leds] == ["fox://f-001"]
    assert [(f.name, sorted(f.bindings.values())) for f in screen.formulas] == [("f-001", ["CCD:Paddles:Status"])]

    # Requirement 9: every referenced macro declared, display <macros> as defaults.
    wire = to_wire_dict(screen)
    referenced = _macro_refs(wire["root"]) | _macro_refs(wire["formulas"])
    names = [macro.name for macro in screen.macros]
    assert names == sorted(referenced | {"P", "R"})
    defaults = {macro.name: macro.default for macro in screen.macros}
    assert defaults["P"] == "ALS:"
    assert defaults["R"] == "STATION3-KNOB:"
    assert all(defaults[name] == "" for name in names if name not in {"P", "R"})

    # Requirement 8: action targets rewritten, relative refs kept.
    targets = [
        action["file"]
        for node in _nodes(screen.root)
        for action in node.props.get("actions") or []
        if isinstance(action, dict) and action.get("type") == "open_display"
    ]
    assert targets and all(target.endswith(".screen.json") for target in targets)
    assert any(target.startswith("../common/") for target in targets)


def test_btsview_embedded_panels_resolve_under_symlink_rule(converted: Converted, written: Path):
    screen = converted.screens[PurePosixPath("bts/BTSView.bob")]
    base = written / "bts"
    files = sorted({str(n.props["file"]) for n in _nodes(screen.root) if n.type == "embedded-display"})
    assert "embedded/_bpm.screen.json" in files
    assert "embedded/_KnobDevice.screen.json" in files
    for ref in files:
        child = base / ref
        assert child.is_file(), f"BTSView embeds {ref}, not produced by the corpus run"
        assert validate_screen_json(json.loads(child.read_text(encoding="utf-8"))) == []


def test_btsview_converts_within_budget(manifest: Manifest):
    source = manifest.entry("bts/BTSView.bob").source
    bob_file_to_ir(source)  # warm imports and the vendored registry
    start = time.perf_counter()
    bob_file_to_ir(source)
    assert time.perf_counter() - start < BTSVIEW_BUDGET_S


def test_tv_acceptance(manifest: Manifest):
    screen = _milestone(manifest, "bts/embedded/_tv.bob")
    warnings = _warnings(screen)
    assert len(warnings) == 4, warnings
    tier2 = [w for w in warnings if _category(w) == "tier-2 script"]
    images = [w for w in warnings if _category(w) == "bool_button images"]
    assert len(tier2) == 1 and len(images) == 3

    (paddle,) = [n for n in _nodes(screen.root) if any(_category(w) == "tier-2 script" for w in n.warnings)]
    assert paddle.meta is not None and paddle.meta.comment
    display = parse_bob(manifest.entry("bts/embedded/_tv.bob").source)
    (script,) = [s for w in _widgets(display.widgets) for s in w.scripts]
    assert script.text is not None and script.text.strip() in paddle.meta.comment

    buttons = [n for n in _nodes(screen.root) if n.type == "pv-button"]
    assert buttons
    assert all(n.props["readbackPV"] == n.props["pv"] for n in buttons)


def test_knob_device_acceptance(manifest: Manifest):
    screen = _milestone(manifest, "common/embedded/_KnobDevice.bob")
    buttons = [n for n in _nodes(screen.root) if n.type == "regular-button"]
    assert any(len(n.props.get("actions") or []) == 16 for n in buttons)
    conditions = [c.expression for n in _nodes(screen.root) for r in n.rules for c in r.conditions]
    assert any("${COLOR_CODE}" in condition for condition in conditions)


def test_bpm_curves(manifest: Manifest):
    screen = _milestone(manifest, "gtb/common/embedded/_bpm.bob")
    (plot,) = [n for n in _nodes(screen.root) if n.type == "waveform-plot"]
    curves = plot.props["curves"]
    assert len(curves) == 1
    assert curves[0]["x_channel"] == "${BPM_X}"
    assert curves[0]["y_channel"] == "${BPM_Y}"


def test_mem_family_loc_formulas(manifest: Manifest):
    """Requirement 5: the hoststats/iocstats ``MEM_*`` scripts lower to formulas."""
    details = _milestone(manifest, "controls/hoststats/details.bob")
    assert len(details.formulas) == 2
    channels = [n.props.get("pv") for n in _nodes(details.root)]
    assert "fox://f-001" in channels
    no_reader = [w for w in _warnings(details) if _category(w) == "formula has no reader"]
    assert len(no_reader) == 1 and "MEM_FREE" in no_reader[0]

    host = _milestone(manifest, "controls/hoststats/embedded/_host.bob")
    # MEM_LOAD is the first loc-formula in document order.
    mem_load = host.formulas[0]
    assert (mem_load.name, mem_load.bindings) == ("f-001", {"0": "${P}:MEM_MAX", "1": "${P}:MEM_FREE"})
    assert "fox://f-001" in [n.props.get("pv") for n in _nodes(host.root)]

    stats = _milestone(manifest, "controls/iocstats/stats.bob")
    names = {f"fox://{formula.name}" for formula in stats.formulas}
    pvs = list(_emitted_pvs(stats))
    assert names and names & set(pvs)
    assert not any(local_pv_key(pv) == "loc://MEM_USED" for pv in pvs)


# --------------------------------------------------------------------------
# Whole corpus
# --------------------------------------------------------------------------
@dataclass
class Census:
    boilerplate: int = 0
    boilerplate_skipped: int = 0
    unmatched_severity: list[str] = field(default_factory=list)
    initializers: int = 0
    initializers_in_channel: int = 0
    initializers_in_declarer: int = 0
    initializers_warned: int = 0
    initializers_dropped: list[str] = field(default_factory=list)
    declarers: int = 0
    opi_targets: int = 0
    formula_pvs: Counter = field(default_factory=Counter)


def _references(widget: BobWidget) -> Iterator[str]:
    """Every PV a widget names: own, actions, rules, scripts."""
    for value in (widget.props.get("pv_name"), *(a.fields.get("pv_name") for a in widget.actions)):
        if isinstance(value, str):
            yield value
    for rule in widget.rules:
        for pv, _trigger in rule.pvs:
            yield pv
    for script in widget.scripts:
        for pv, _trigger in script.pvs:
            yield pv


def _trace_pvs(widget: BobWidget) -> Iterator[str]:
    traces = widget.props.get("traces")
    if traces is None or isinstance(traces, str):
        return
    for trace in traces.findall("trace"):
        for tag in ("x_pv", "y_pv"):
            text = trace.findtext(tag)
            if text:
                yield text


def _census(converted: Converted) -> Census:
    census = Census()
    for rel, display in converted.displays.items():
        screen = converted.screens[rel]
        warnings = _warnings(screen)
        init_warned = {
            w.split(": ", 1)[0]
            for w in warnings
            if _category(w) in {"local PV type unsupported", "array local PV initializer"}
        }
        emitted_inits: dict[str, str] = {}
        for node in _nodes(screen.root):
            pv = node.props.get("pv")
            if isinstance(pv, str) and "&init=" in pv:
                emitted_inits.setdefault(local_pv_key(pv), "declarer" if _is_declarer(node) else "channel")
            if _is_declarer(node):
                census.declarers += 1
        seen: set[str] = set()
        for widget in _widgets(display.widgets):
            for script in widget.scripts:
                if not mentions_severity(script):
                    continue
                ctx = RuleContext()
                if match_alarm_boilerplate(script, widget, ctx) is not None:
                    census.boilerplate += 1
                elif ctx.warnings:
                    census.boilerplate_skipped += 1
                else:
                    census.unmatched_severity.append(f"{rel}: {widget.name}: {script.name}")
            for action in widget.actions:
                target = str(action.fields.get("file") or "").strip()
                if action.type == "open_display" and target.lower().endswith(".opi"):
                    census.opi_targets += 1
            for pv in _references(widget):
                if not _LOC_INIT_RE.match(normalize_macro_syntax(pv).strip()):
                    continue
                key = local_pv_key(pv)
                if key in seen:
                    continue
                seen.add(key)
                census.initializers += 1
                where = emitted_inits.get(key)
                if where == "declarer":
                    census.initializers_in_declarer += 1
                elif where == "channel":
                    census.initializers_in_channel += 1
                elif widget.name in init_warned:
                    census.initializers_warned += 1
                else:
                    census.initializers_dropped.append(f"{rel}: {widget.name}: {pv}")
            pv_name = widget.props.get("pv_name")
            if isinstance(pv_name, str) and pv_name.strip().startswith("="):
                census.formula_pvs["widget pv_name"] += 1
            census.formula_pvs["rule pv"] += sum(
                1 for r in widget.rules for pv, _ in r.pvs if pv.strip().startswith("=")
            )
            census.formula_pvs["trace pv"] += sum(1 for pv in _trace_pvs(widget) if pv.strip().startswith("="))
    return census


@pytest.fixture(scope="module")
def census(converted: Converted) -> Census:
    return _census(converted)


def test_corpus_converts_within_budget(converted: Converted):
    assert converted.seconds < CORPUS_BUDGET_S


def test_every_corpus_screen_validates(converted: Converted):
    failures = {
        str(rel): errors[:3]
        for rel, screen in converted.screens.items()
        if (errors := validate_screen_json(to_wire_dict(screen)))
    }
    assert failures == {}


def test_alarm_boilerplate_count(census: Census):
    assert census.boilerplate == ALARM_BOILERPLATE_COUNT
    assert census.unmatched_severity == []


def test_no_initializer_dropped(census: Census):
    assert census.initializers > 0
    assert census.initializers_dropped == []
    assert census.declarers == census.initializers_in_declarer


def test_no_emitted_pv_carries_vtype_or_formula(converted: Converted):
    bad = [
        f"{rel}: {pv}"
        for rel, screen in converted.screens.items()
        for pv in _emitted_pvs(screen)
        if "<V" in pv or pv.strip().startswith("=")
    ]
    assert bad == []


def test_mapped_ratio(converted: Converted):
    total = unknown = 0
    for screen in converted.screens.values():
        for node in _nodes(screen.root):
            if node is screen.root or _is_declarer(node):
                continue
            total += 1
            unknown += node.type == "unknown-widget"
    assert total and (total - unknown) / total >= MIN_MAPPED_RATIO


def test_opi_action_targets(census: Census):
    assert census.opi_targets == OPI_ACTION_TARGETS


# --------------------------------------------------------------------------
# Coverage report
# --------------------------------------------------------------------------
def test_coverage_report(converted: Converted, census: Census):
    manifest = converted.manifest
    types: Counter = Counter()
    unknown_classes: Counter = Counter()
    categories: Counter = Counter()
    rules_emitted = 0
    largest = (0, "", "")
    gateway_pvs = 0
    for rel, screen in converted.screens.items():
        for node in _nodes(screen.root):
            if node is screen.root or _is_declarer(node):
                continue
            types[node.type] += 1
            if node.type == "unknown-widget":
                unknown_classes[str(node.props.get("originalClass"))] += 1
            rules_emitted += len(node.rules)
            for message in node.warnings:
                categories[_category(message)] += 1
            if node.meta is not None and node.meta.comment and len(node.meta.comment) > largest[0]:
                largest = (len(node.meta.comment), str(rel), node.id)
        gateway_pvs += sum(1 for pv in _emitted_pvs(screen) if is_gateway_channel(pv))
    total = sum(types.values())
    mapped = total - types["unknown-widget"]
    formulas = sum(len(screen.formulas) for screen in converted.screens.values())

    lines = [
        "",
        "=== Phoebus .bob corpus coverage report ===",
        f"root: {manifest.root}",
        f"files converted: {len(manifest.entries)} "
        f"({sum(e.rerooted for e in manifest.entries)} via the deployed-tree symlink rule); "
        f"excluded {len(manifest.excluded)}; dangling symlinks skipped {len(manifest.dangling)}",
        f"conversion time: {converted.seconds:.2f} s",
        f"widget instances: {total}, mapped {mapped} ({100.0 * mapped / total:.1f} %), "
        f"unknown-widget {types['unknown-widget']}",
        "unknown-widget by original class: "
        + ", ".join(f"{name} {count}" for name, count in unknown_classes.most_common(10)),
        "widgets by registry id: " + ", ".join(f"{name} {count}" for name, count in types.most_common()),
        f"rules emitted: {rules_emitted} (alarm boilerplate lowered {census.boilerplate}, "
        f"boilerplate skipped {census.boilerplate_skipped}, unmatched getSeverity scripts "
        f"{len(census.unmatched_severity)})",
        f"formula declarations: {formulas}",
        "formula PVs in the input: "
        + ", ".join(f"{name} {count}" for name, count in sorted(census.formula_pvs.items()))
        + f"; not lowered {categories['formula PV not lowered']}, tier-2 rule bindings "
        f"{categories['tier-2 rule formula binding']}, tier-2 trace bindings {categories['tier-2 trace formula binding']}",
        f"pvStr-on-gateway rule comparisons: {categories['pvStr-on-gateway']}",
        f".opi open_display targets: {census.opi_targets}",
        f"local-PV initializers: {census.initializers} (in channel {census.initializers_in_channel}, "
        f"in declarer {census.initializers_in_declarer}, warned unsupported {census.initializers_warned}, "
        f"dropped {len(census.initializers_dropped)}); declarers emitted {census.declarers}",
        f"gateway PV references emitted: {gateway_pvs}",
        f"largest meta.comment: {largest[0]} chars ({largest[1]} node {largest[2]})",
        "warnings by category:",
        *(f"  {count:6d}  {label}" for label, count in categories.most_common()),
    ]
    print("\n".join(lines))
    assert total > 0
