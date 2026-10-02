# Vendored Canopy contracts

Everything in this directory except `VENDORED_SCHEMA.md` and `.gitignore` is
**vendored**, not generated here. `@slaclab/canopy-screen-ir` owns the Canopy
screen contract and the colour-scheme contract; canopy owns the widget registry
and the default colour scheme. This converter is a disposable consumer that must
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
- Widget registry: snapshot of canopy at the commit named in
  `widget-registry/.beaver-snapshot-sha`.

## Vendored files

Each file is a byte copy of its source, taken from the committed file in the
source repo. Sources are repo-relative (`<repo>: <path>`).

| Vendored file | Source | sha256 |
|---|---|---|
| `screen-ir.schema.json` | `canopy-sdk-js: packages/screen-ir/schema/screen-ir.schema.json` | `e9a2cbd3bf620b12c97da9941af4dd9db061bf088d25ed1c1bcdfcffd7c10e4c` |
| `canopy-color-scheme-1.schema.json` | `canopy-sdk-js: packages/screen-ir/schema/canopy-color-scheme-1.schema.json` | `be4f4b9a14714cab955173546dc868f078da4f7b1867a7482a6f582456d8c2c3` |
| `schemes/canopy-default.json` | `canopy: src/canopy/converter/data/schemes/canopy-default.json` | `36e765dc007f378c468baa41173cee4973a123c16e936e30b5becf9e187b4683` |
| `widget-registry/*.json` | `canopy: widget-registry-data/widgets` | `5a721981b55042091a3329626a5fb62f327685a8e91989dd164c3c816983147b` |

The widget-registry digest covers the whole directory: it is the sha256 of the
`shasum -a 256 *.json` listing taken inside `widget-registry/` (one
`<sha256>  <name>` line per file, sorted by name):

```sh
cd pydmconverter/ir/data/widget-registry && shasum -a 256 *.json | shasum -a 256
```

`tests/ir/test_vendored_data.py` pins these values and checks that the files ship
as package data.

## Re-vendoring

Because this tool is short-lived there is no live sync. To refresh, byte-copy
each file from its source above (`git show <commit>:<path>`, never an
uncommitted working tree), update the sha256 values here and in
`tests/ir/test_vendored_data.py`, point `.beaver-snapshot-sha` at the canopy
commit the registry came from, then run `python -m pytest tests/ir` to confirm
converter output still validates. If validation fails, reconcile: fix converter
output, or file a change against the owning package — do NOT widen only the
converter's copy.
