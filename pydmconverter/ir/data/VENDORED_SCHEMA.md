# Vendored Canopy contracts

Everything in this directory except `VENDORED_SCHEMA.md`, `.gitignore` and
`widget-registry/` is **vendored**, not generated here. `@slaclab/canopy-screen-ir`
owns the Canopy screen contract and the colour-scheme contract; canopy owns the
default colour scheme. This converter is a disposable consumer that must
produce IR the editor accepts. It validates its output against the vendored
screen schema (`validate_screen_json`); it does not mint any of these contracts.

## Pinned source

- Package: `@slaclab/canopy-screen-ir` (the shared SDK contract package;
  canopy-sdk-js issue #2). This is the single canonical home — the previous
  `@canopy/screen-ir` copy in `canopy-screen-builder` and the workspace copy in
  `canopy-screen-runtime` are being retired in favor of it.
- Screen IR schema version: `1.1` (accepts documents declaring `1.0` or `1.1`).
- Canonical macro-name pattern: `^[A-Za-z][A-Za-z0-9_]*$` (accepts lowercase —
  PyDM/EDM sources author `${dev}`/`${signal}`).
- Widget registry: **not vendored**. `widget-registry/*.json` holds only each
  type's `id`, `qtMapping` and `qtPropMap`; these files are the source of truth
  for the Qt mappings and are edited here (see `pydmconverter/ir/registry.py`).

## Vendored files

Each file is a byte copy of its source, taken from the committed file in the
source repo. Sources are repo-relative (`<repo>: <path>`).

| Vendored file | Source | sha256 |
|---|---|---|
| `screen-ir.schema.json` | `canopy-sdk-js: packages/screen-ir/schema/screen-ir.schema.json` | `f672ff1800881ddaa788744448a3972ed0c89ef5aab032d7b7dfcf8f9014a7de` |
| `canopy-color-scheme-1.schema.json` | `canopy-sdk-js: packages/screen-ir/schema/canopy-color-scheme-1.schema.json` | `94b2e2cb5c0ee1854ebe2b806ba2c52213f9ef2d218cb11a1be49bde3562c2b2` |
| `schemes/canopy-default.json` | `canopy: src/canopy/converter/data/schemes/canopy-default.json` | `0a8f403e70f0b9a5dc2eb9679da24f72f54209e19a8a9043d3de636e49ce810d` |

`tests/ir/test_vendored_data.py` pins these values and checks that the files ship
as package data.

## Re-vendoring

Because this tool is short-lived there is no live sync. To refresh, byte-copy
each file from its source above (`git show <commit>:<path>`, never an
uncommitted working tree), update the sha256 values here and in
`tests/ir/test_vendored_data.py`, then run `python -m pytest tests/ir` to confirm
converter output still validates. If validation fails, reconcile: fix converter
output, or file a change against the owning package — do NOT widen only the
converter's copy.
