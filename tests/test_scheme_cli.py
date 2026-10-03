"""``canopy-scheme``: the check and survey subcommands, on synthetic fixtures only."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path, PurePosixPath

from pydmconverter import scheme_cli
from pydmconverter.scheme import DEFAULT_SCHEME_PATH
from tests.bob import corpus_manifest

FIXTURES = Path(__file__).parent / "bob" / "fixtures" / "theming"


def _run(capsys, *argv: str) -> tuple[int, str]:
    code = scheme_cli.main(list(argv))
    return code, capsys.readouterr().out


def _rows(out: str) -> list[list[str]]:
    return [line.split("\t") for line in out.splitlines() if not line.startswith("#")]


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    for sub in ("bts", "gun"):
        (root / sub).mkdir(parents=True)
    (root / "common" / "embedded").mkdir(parents=True)
    shutil.copy(FIXTURES / "survey_a.bob", root / "bts" / "a.bob")
    shutil.copy(FIXTURES / "survey_b.bob", root / "gun" / "b.bob")
    return root


def test_check_default_is_clean(capsys):
    code, out = _run(capsys, "check", str(DEFAULT_SCHEME_PATH))
    assert code == 0
    assert "ok" in out


def test_check_reports_dangling_alias(tmp_path, capsys):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"id": "x", "roles": {"Text": {"light": "@Nope", "dark": "#ffffff"}}}))
    code, out = _run(capsys, "check", str(path))
    assert code == 1
    assert "@Nope" in out


def test_check_reports_role_without_dark(tmp_path, capsys):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"id": "x", "roles": {"Brand": {"light": "#123456"}}}))
    code, out = _run(capsys, "check", str(path))
    assert code == 1
    assert "no dark value: Brand" in out


def test_check_unreadable_file_fails(tmp_path, capsys):
    code, _ = _run(capsys, "check", str(tmp_path / "missing.json"))
    assert code == 1


def test_survey_aggregates_across_dirs(tmp_path, capsys):
    root = _corpus(tmp_path)
    code, out = _run(capsys, "survey", str(root / "bts"), str(root / "gun"), "--corpus-root", str(root))
    assert code == 0
    total = out.split("# total")[1]
    text = [r for r in _rows("#x\n" + total.split("\n", 1)[1]) if r[0] == "Text" and r[2] == "#161616"]
    assert [r[3] for r in text] == ["2"]  # one in a.bob, one in b.bob
    assert all(r[4] == scheme_cli.NO_SCHEME_FATE for r in _rows(out))


def test_survey_counts_a_symlinked_file_once(tmp_path, capsys):
    root = _corpus(tmp_path)
    (root / "gun" / "linka.bob").symlink_to(root / "bts" / "a.bob")
    code, out = _run(capsys, "survey", str(root / "bts"), str(root / "gun"), "--corpus-root", str(root))
    assert code == 0
    assert out.count("# file: bts/a.bob") == 1
    assert "linka.bob" not in out


def test_survey_prints_rerooted_header(tmp_path, capsys):
    root = _corpus(tmp_path)
    shutil.copy(FIXTURES / "survey_b.bob", root / "common" / "embedded" / "_KnobDevice.bob")
    link = root / "bts" / "embedded" / "_KnobDevice.bob"
    link.parent.mkdir()
    link.symlink_to(scheme_cli.DEPLOYED_PREFIX + "common/embedded/_KnobDevice.bob")
    _, out = _run(capsys, "survey", str(root / "bts"), "--corpus-root", str(root))
    assert "# file: common/embedded/_KnobDevice.bob" in out
    assert "bts/embedded" not in out


def test_survey_skips_dangling_symlink(tmp_path, capsys):
    root = _corpus(tmp_path)
    (root / "bts" / "gone.bob").symlink_to("/nowhere/at/all/gone.bob")
    _, out = _run(capsys, "survey", str(root / "bts"), "--corpus-root", str(root))
    assert "gone.bob" not in out
    assert "# file: bts/a.bob" in out


def test_survey_applies_exclude(tmp_path, capsys):
    root = _corpus(tmp_path)
    (root / "examples").mkdir()
    shutil.copy(FIXTURES / "survey_b.bob", root / "examples" / "e.bob")
    _, out = _run(capsys, "survey", str(root), "--corpus-root", str(root))
    assert "examples" not in out


def test_survey_fates_with_scheme(tmp_path, capsys):
    root = _corpus(tmp_path)
    scheme = tmp_path / "s.json"
    scheme.write_text(json.dumps({"id": "x", "roles": {}}))
    code, out = _run(capsys, "survey", str(root / "bts"), "--scheme", str(scheme), "--corpus-root", str(root))
    assert code == 0
    fates = {(r[0], r[2]): r[4] for r in _rows(out)}
    assert fates[("Text", "#161616")] == "role Text"
    assert fates[("Text", "#000000")].startswith("literal (role Text light #161616")
    assert fates[("Brand_Blue", "#0a141e")] == "literal (not imported)"
    assert fates[(scheme_cli.UNNAMED, "#010203")].startswith("literal")


def test_survey_bad_scheme_exits_nonzero(tmp_path, capsys):
    root = _corpus(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    code = scheme_cli.main(["survey", str(root), "--scheme", str(bad)])
    assert code == 1


def test_corpus_rule_equals_manifest_copy(tmp_path):
    assert scheme_cli.GLOB == corpus_manifest.GLOB
    assert scheme_cli.EXCLUDE == corpus_manifest.EXCLUDE
    assert scheme_cli.DEPLOYED_PREFIX == corpus_manifest.DEPLOYED_PREFIX
    root = _corpus(tmp_path)
    (root / "examples").mkdir()
    shutil.copy(FIXTURES / "survey_b.bob", root / "examples" / "e.bob")
    shutil.copy(FIXTURES / "survey_b.bob", root / "common" / "embedded" / "_K.bob")
    (root / "bts" / "embedded").mkdir()
    (root / "bts" / "embedded" / "_K.bob").symlink_to(corpus_manifest.DEPLOYED_PREFIX + "common/embedded/_K.bob")
    (root / "bts" / "gone.bob").symlink_to("/nowhere/gone.bob")
    # The manifest writes a re-rooted link's output at the link's own path; the survey names it by its
    # re-rooted path. The set of files read must be identical.
    expected = sorted(e.source for e in corpus_manifest.load_manifest(root).entries)
    items = scheme_cli.scan_dir(root, root)
    assert sorted(f.source for f in items) == expected
    assert PurePosixPath("common/embedded/_K.bob") in [f.rel for f in items]
    assert os.readlink(root / "bts" / "embedded" / "_K.bob").startswith(corpus_manifest.DEPLOYED_PREFIX)


# --- fate: slot imports and declared sources ------------------------------------------------------


def _fate_ctx():
    from pydmconverter.bob.colors import ColorContext
    from pydmconverter.scheme import SchemeResult

    flat = {"roles": ["Grid", "Grid_Fill", "OK"], "light": ["#808080", "#c6c6c6", "#006e00"], "dark": ["#000000"] * 3}
    imports = {"phoebus": {"Grid": {"role": "Grid", "background_color": "Grid_Fill"}, "OK": "OK"}}
    return ColorContext.from_scheme(SchemeResult(flat=flat, imports=imports, meta={}, sources={"OK": "#00ff00"}))


def test_fate_reports_the_default_role_of_a_slot_import():
    assert scheme_cli.fate("Grid", (128, 128, 128, 255), _fate_ctx()) == "role Grid"


def test_fate_matches_a_declared_source():
    ctx = _fate_ctx()
    assert scheme_cli.fate("OK", (0, 255, 0, 255), ctx) == "role OK"
    assert scheme_cli.fate("OK", (0, 254, 0, 255), ctx) == "literal (role OK phoebus #00ff00 differs)"


def test_fate_without_source_compares_light():
    assert scheme_cli.fate("Grid", (1, 2, 3, 255), _fate_ctx()) == "literal (role Grid light #808080 differs)"


def test_survey_with_default_scheme_handles_slot_imports(tmp_path, capsys):
    root = _corpus(tmp_path)
    code, out = _run(
        capsys, "survey", str(root / "bts"), "--corpus-root", str(root), "--scheme", str(DEFAULT_SCHEME_PATH)
    )
    assert code == 0
    assert all(len(r) == 5 for r in _rows(out))
