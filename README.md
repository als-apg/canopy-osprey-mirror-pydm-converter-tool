# PyDM Converter

PyDM Converter is an PyDM-based tool developed at SLAC National Accelerator Laboratory. PyDM Converter is an open-source project.

For more information and a how to guide on PyDM Converter see [the project's website](https://slaclab.github.io/pydm-converter-tool/)
<p align="center">
  <a href="https://github.com/slaclab/pydm-converter-tool/issues/new?labels=bug&projects=&template=bug-report.yml&title=%5BBUG%5D+-+">Report bug</a>
  ·
  <a href="https://github.com/slaclab/pydm-converter-tool/issues/new?labels=enhancement&projects=&template=feature-request.yml&title=%5BFEATURE%5D+-+">Request feature</a>

</p>

## Phoebus .bob

The `--target react` path (the Canopy Screen IR pipeline) accepts Phoebus Display
Builder `.bob` XML files as a third input format alongside EDM `.edl` and Qt Designer
`.ui`. The front-end lives in `pydmconverter/bob/`; see
[`pydmconverter/bob/README.md`](pydmconverter/bob/README.md) for its module layout and
the tables it is built from.

### Public API

- `pydmconverter.bob.ir_adapter.bob_file_to_ir(path, *, registry=None, color_def_path=None) -> ScreenIR`
  — parses a `.bob` file from disk and returns its Screen IR. The screen id and title
  are the file stem. Raises `BobParseError` on malformed XML; every other problem in
  the input becomes a warning on the widget node it concerns rather than an exception.
- `pydmconverter.bob.ir_adapter.bob_bytes_to_ir(data, *, registry=None, color_def_path=None) -> ScreenIR`
  — the same lowering over raw bytes with no path on disk (used for uploads). The
  screen id is the fixed string `"screen"`, so identical bytes always produce
  byte-identical output.
- `pydmconverter.react.convert_bytes(data, *, kind="bob", registry=None, color_def_path=None, ...) -> ScreenIR`
  — the format-agnostic entry point shared with `.edl`/`.ui`; pass `kind="bob"` to
  route through the Phoebus front-end. `convert_to_ir`/`convert_file`/`convert_folder`
  dispatch by file suffix (`.bob`) automatically and need no `kind` argument.

### `--color-def`

The CLI's `--target react` path accepts `--color-def PATH`, a Phoebus `color.def` file
whose named-colour entries overlay the built-in Phoebus palette before `.bob` inputs
are converted (`<color name="STOP">` resolves to whatever `.def` entry names it, falling
back to the built-in table). It affects `.bob` inputs only; `.edl`/`.ui` conversions
ignore it. Programmatically the same file is `color_def_path=` on `bob_file_to_ir`,
`bob_bytes_to_ir`, `convert_to_ir` and `convert_bytes`.

### What lowers and what warns

Nothing in a `.bob` file raises past a `BobParseError` on malformed XML. Everything
else the adapter cannot express in the Screen IR becomes a warning on the widget node
it concerns, and — for unlowered scripts and Jython/JavaScript actions — the original
text is also carried verbatim on the node (`meta.comment`) so it is one click away in
the Screen Builder's Source inspector.

Widgets, properties, rules, actions and local-PV URLs map declaratively through the six
tables in `pydmconverter/bob/bob_qt.py`. Rule conditions (`bool_exp`) are rewritten
through a Python port of Phoebus's own `RuleToScript.javascriptToPythonLogic`, so a
converted condition evaluates exactly as it did in Phoebus. PV names beginning with `=`
("formula PVs") are rewritten into Fox formula expressions when they use only
arithmetic, `abs`, comparisons and the JavaScript-style boolean operators; anything
else (`concat`, `elementAt`, other functions, a bare unparenthesized name) is declined
with a warning and the widget becomes `unknown-widget`.

### Tier vocabulary

The adapter buckets everything it converts into three tiers, used throughout its
docstrings, warnings and the corpus coverage report:

- **Tier 0** — scripts lowered declaratively. Two exact-match idioms: the
  EDM-to-Phoebus alarm-colour boilerplate (a fixed `PVUtil.getSeverity(...)` read,
  indexed into a palette) becomes a severity rule on `<pv>.SEVR`; and a script that
  reads PVs, does arithmetic, and writes the result to exactly one `loc://` PV it is
  the sole writer of becomes a `FormulaDeclaration`, with every in-file reader of that
  PV retargeted to `fox://<name>`.
- **Tier 1** — actions. A widget's `<actions>` list (`open_display`, `write_pv`,
  `command`, `open_webpage`, `open_file`, `close_display`) becomes the Screen
  Builder's `props.actions`, one entry per action in document order. `command`
  actions carry the shell command line but also warn, since the web runtime does not
  execute shell commands.
- **Tier 2** — needs the script runtime. Any script or action Canopy cannot express
  declaratively (anything outside the two tier-0 idioms, any Jython/JavaScript
  `execute` action) is out of scope for this adapter: it warns and its full source
  text is carried in `meta.comment` instead of being converted.

### Corpus tests

`tests/bob/test_corpus.py` exercises the adapter against a real site's Phoebus panel
tree rather than the committed synthetic fixtures. It reads its root from the
`PHOEBUS_CORPUS` environment variable:

```bash
PHOEBUS_CORPUS=/path/to/phoebus/panels pytest tests/bob/test_corpus.py -q -s
```

Every test in that module skips, with a reason, when `PHOEBUS_CORPUS` is unset, so
`pytest tests/bob` (and the whole suite) passes on a machine with no corpus checked
out. The corpus tree is never committed to this repository; which files count (glob,
exclusions, symlink handling) is fixed by `tests/bob/corpus_manifest.py`. The suite
covers milestone panels (byte-stable, schema-valid, golden-pinned conversions),
whole-corpus statistics (alarm-boilerplate count, local-PV initializer accounting,
mapped-widget ratio, `.opi` action-target count, timing budget), and a coverage report
printed with `-s`.

## Contributing to PyDM Converter

Thank you for your interest in contributing to **PyDM Converter**! Your contributions help make the project better for everyone. Below are the guidelines to ensure a smooth and efficient collaboration.

### How to Contribute

1. **Fork and Clone the Repository**
   - Fork the [PyDM Converter repository](https://github.com/slaclab/pydm-converter-tool) on GitHub.
   - Clone your fork to your local machine:
     ```bash
     git clone https://github.com/your-username/pydm-converter-tool.git
     cd pydm-converter-tool
     ```

2. **Set Up Your Development Environment**
   - Install the necessary dependencies:
     ```bash
     pip install -r requirements.txt
     ```

3. **Implement Your Changes**
   - **Code Style:** Follow the [PEP8](https://peps.python.org/pep-0008/) style guide for Python code.
   - **Documentation:** Add docstrings to all new methods and classes using the [NumPy style guide](https://numpydoc.readthedocs.io/en/latest/format.html).
   - **Unit Tests:** Write unit tests for your changes using [Pytest](https://docs.pytest.org/).

4. **Run Tests Locally**
   - Ensure all tests pass before submitting:
     ```bash
     pytest
     ```

5. **Create a Pull Request (PR)**
   - When you feel like your feature is ready to be merged into the pydm converter make a PR and request feedback from the Maintainers.
   - Provide a descriptive title and detailed description of your changes.

### Pull Request Requirements

To ensure your PR is reviewed efficiently, please adhere to the following:

- **Unit Tests:**
  - Include tests for all new functionality.
  - Ensure tests cover different scenarios and edge cases.

- **Documentation:**
  - All new methods and classes must have comprehensive docstrings.
  - Follow the [NumPy style guide](https://numpydoc.readthedocs.io/en/latest/format.html) for consistency.

- **Code Quality:**
  - Adhere to the [PEP8](https://peps.python.org/pep-0008/) style guide.
  - Ensure your code is clean, well-organized, and free of unnecessary complexity.

### Additional Guidelines
- **Communication:**
  - For significant changes, consider opening an issue to discuss your approach before starting.

### Resources

- [NumPy Docstring Guide](https://numpydoc.readthedocs.io/en/latest/format.html)
- [PEP8 Style Guide](https://peps.python.org/pep-0008/)
- [Pytest Documentation](https://docs.pytest.org/)

### Notes on Contributing to the Documentation

1. **Set Up Your Development Environment**
   - Ensure you are working on your development environment.

2. **Navigate to the Project Directory**
   - Go to the top-level `pydm-converter-tool` project directory, which contains the `mkdocs.yml` file.

3. **Make and Test Your Changes Locally**
   - Edit the documentation files as needed.
   - Test your changes locally using MkDocs before submitting a pull request.

---

#### Detailed Steps

1. **Set Up Your Development Environment**
   - Make sure you have all the necessary tools installed (e.g., Python, MkDocs).

2. **Navigate to the Project Directory**
   ```bash
   cd path/to/pydm-converter-tool

3. **Install Dependencies**
   ```bash
    pip install -r requirements.txt

4. **Serve the Documentation Locally**
   ```bash
    mkdocs serve

-  Open your browser and go to http://localhost:8000 to preview your changes.

5. **Submit Your Changes**

- After verifying your changes, commit and push them to your forked repository.
-  Create a pull request to submit your updates.

---

If you have any questions or need further assistance, feel free to open an [issue](https://github.com/slaclab/pydm-converter-tool/issues) or reach out to the maintainers.
