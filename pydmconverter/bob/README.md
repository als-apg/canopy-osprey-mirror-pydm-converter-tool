# pydmconverter/bob

Phoebus Display Builder (`.bob`) front-end for the Screen IR. It mirrors the structure
of `pydmconverter/edm/`: a thin parser, data tables mapping Phoebus vocabulary onto the
Qt/registry vocabulary the shared `IRBuilder` understands, a handful of
single-purpose lowering modules, and one orchestrator that wires them together. See
the top-level [README's "Phoebus .bob" section](../../README.md#phoebus-bob) for the
public API, the tier vocabulary, and how to run the corpus tests.

## Module layout

- **`parser.py`** — `parse_bob(path_or_bytes) -> BobDisplay`. Turns the `.bob` XML
  into a neutral tree of `BobWidget`/`BobRule`/`BobScript`/`BobAction` dataclasses;
  leaf properties are kept as text, structured properties (fonts, colours, points,
  ...) as the raw `ET.Element` for later stages to interpret. Also does the two things
  every consumer needs done first: substituting widget-scope `$(pv_name)`/`${pv_name}`
  macros in a widget's own action/rule/script PV references, and reading `<script
  file=...>` script bodies from beside the input file.
- **`bob_qt.py`** — data only: the six tables described below, translating Phoebus
  vocabulary into the Qt/registry vocabulary.
- **`coercion.py`** — turns raw parsed values into the plain Python values the IR
  stores: colours as `#rrggbb`, font sizes, alignment flags, polygon points, and
  rule-arm values coerced per target kind. Also owns the built-in named-colour table
  (`BUILTIN_NAMED_COLORS`, following Phoebus's `NamedWidgetColors`) and
  `load_color_def`, which overlays a site `color.def` file onto it.
- **`groups.py`** — Phoebus `group` widget geometry: child-origin accumulation plus
  the style- and font-dependent inset ported from Phoebus's
  `GroupRepresentation.updateChanges`, and the style -> `group-box`/`group` target
  choice.
- **`local_pv.py`** — Phoebus local-PV URL handling: `loc://name<VType>(v)` ->
  `loc://name?type=<t>&init=<v>`; `local_pv_key`, the identity every writer/reader
  comparison uses; gateway-vs-local/simulated/computed scheme detection
  (`is_gateway_channel`, `NON_GATEWAY_SCHEMES`); and `plan_declarers`, which emits the
  hidden `<widget>.init` declarer nodes for initializers that have no channel slot of
  their own on their widget (e.g. an `action_button`'s `pv_name`).
- **`formula_pv.py`** — lowers Phoebus formula PVs (a `pv_name`, rule PV, or trace PV
  starting with `=`) into Fox formula expressions, when the expression is
  arithmetic/`abs`/comparisons/boolean operators over PV references; otherwise
  declines with a warning and leaves the text for `meta.py` to carry.
- **`rules.py`** — `RuleContext` and `lower_rule`: turns a Phoebus `<rule>` into an IR
  `RuleSpec`, after rewriting its `bool_exp` through `js_to_python`, a faithful port of
  Phoebus's own `RuleToScript.javascriptToPythonLogic`.
- **`scripts.py`** — the two tier-0 script matchers: `match_alarm_boilerplate` (the
  fixed EDM-to-Phoebus alarm-colour Jython idiom) and `match_loc_formula` (a script
  that is exactly a formula over `loc://` PVs), plus `mentions_severity` (used by the
  corpus report to account for every script that reads a severity) and
  `build_writer_census`, the file-wide sole-writer check the loc-formula matcher needs.
- **`actions.py`** — lowers a widget's `<actions>` list into the Screen Builder's
  `props.actions` shape (`open_display`, `write_pv`, `command`/`execute`,
  `open_webpage`, `open_file`, `close_display`).
- **`meta.py`** — `build_meta`: assembles the `meta.comment` carry-over for whatever a
  widget could not lower (an unmatched script, a Jython `execute` action, a declined
  formula PV), one block per item in document order, each headed by a one-line
  description of what it is.
- **`ir_adapter.py`** — the orchestrator. `bob_file_to_ir`/`bob_bytes_to_ir` wire every
  module above together: parse and construct the `IRBuilder`, a file-wide census
  (writer census, hidden local-PV declarers), per-widget lowering in document order,
  formula-reader retargeting, and `build_screen`. Nothing here raises on unmapped
  input — see the module docstring for the exact five-step pipeline.

## The six tables (`bob_qt.py`)

1. **`BOB_TO_QT_CLASS`** — Phoebus widget `type` -> `(Qt class, registry id)`, e.g.
   `action_button` -> `("QPushButton", "regular-button")`, `led` -> `("PyDMSymbol",
   "pv-led")`. `tabs` is deliberately absent (no registry `qtPropMap` for `tabs[]` in
   either registry copy) and stays `unknown-widget`.
2. **`BOB_TO_QT_PROP`** / **`BOB_TO_QT_PROP_BY_TYPE`** — Phoebus property name -> Qt
   property name. The by-type table overrides the generic table per widget type,
   including `None` entries that mean "deliberately not mapped" (e.g.
   `action_button.pv_name`, `led.line_color`).
3. **`BOB_DEFAULTS`** / **`DISPLAY_BACKGROUND_DEFAULT`** — per-type values Phoebus does
   not serialise because they equal its own widget constructor defaults (a bare
   `rectangle` is `transparent: false, line_width: 3, line_color: #0000ff,
   background_color: #1e90ff`; a bare `bool_button` carries On/Off labels and colours;
   and so on). The adapter fills these in whenever the corresponding element is
   absent, before the prop table runs.
4. **`DEFAULT_SIZES`** — `(width, height)` used when a widget's `<width>`/`<height>`
   are absent (`label`/`textupdate`/`textentry`/`rectangle` 100x20, `led` 20x20,
   `group` 300x200, ...). `polyline`/`polygon` instead derive their box from the
   points' bounding box in the adapter.
5. **`GROUP_INSET`** — child-origin inset per Phoebus group `<style>` (0 GROUP_BOX, 1
   TITLE, 2 LINE, 3 NONE), a direct port of Phoebus's
   `GroupRepresentation.updateChanges`.
6. **`RULE_DIRECT_TARGETS`** / **`RULE_TARGET_COERCION`** — which rule targets
   (`visible`, `x`, `y`, `width`, `height`) land on the IR rule target as-is versus
   going through the prop table, and which coercion kind (`bool`/`number`/`color`/
   `str`) each target's arm values need.

## Tests

`tests/bob/` mirrors this layout: one test module per table or lowering module,
synthetic fixtures under `tests/bob/fixtures/` for each construct, and
`tests/bob/test_corpus.py` for whole-corpus statistics and milestone goldens, gated on
the `PHOEBUS_CORPUS` environment variable.
