import json
from pathlib import Path

import pytest

from pydmconverter import react

EDM_FIXTURE = Path(__file__).parent / "edm" / "fixtures" / "basic_widgets.edl"
UI_FIXTURE = Path(__file__).parent / "ui" / "fixtures" / "basic_widgets.ui"


def test_convert_to_ir_dispatches_by_suffix():
    assert react.convert_to_ir(EDM_FIXTURE).metadata.source.type == "edl-converter"
    assert react.convert_to_ir(UI_FIXTURE).metadata.source.type == "ui-converter"


def test_convert_bytes_edl_and_ui():
    """convert_bytes runs the same pipeline as convert_to_ir but is keyed on kind (#146)."""
    edm = react.convert_bytes(EDM_FIXTURE.read_bytes(), kind="edl")
    ui = react.convert_bytes(UI_FIXTURE.read_bytes(), kind="ui")
    assert edm.metadata.source.type == "edl-converter"
    assert ui.metadata.source.type == "ui-converter"
    assert edm.root.children  # produced widgets through the shared builder


def test_convert_bytes_is_deterministic():
    data = EDM_FIXTURE.read_bytes()
    assert react.convert_bytes(data, kind="edl") == react.convert_bytes(data, kind="edl")


def test_convert_bytes_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        react.convert_bytes(b"<x/>", kind="txt")


def test_convert_to_ir_rejects_unknown_suffix(tmp_path):
    bogus = tmp_path / "x.txt"
    bogus.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="supports"):
        react.convert_to_ir(bogus)


def test_convert_file_writes_screen_json(tmp_path):
    out = react.convert_file(EDM_FIXTURE, tmp_path / "vac", override=True)
    assert out.name == "vac.screen.json"
    assert json.loads(out.read_text(encoding="utf-8"))["kind"] == "screen"


def test_convert_file_honors_explicit_json_name(tmp_path):
    out = react.convert_file(UI_FIXTURE, tmp_path / "custom.json", override=True)
    assert out.name == "custom.json"


def test_convert_file_refuses_overwrite_without_override(tmp_path):
    target = tmp_path / "out.screen.json"
    react.convert_file(EDM_FIXTURE, target, override=True)
    with pytest.raises(FileExistsError):
        react.convert_file(EDM_FIXTURE, target, override=False)


def test_convert_folder(tmp_path):
    src = tmp_path / "in"
    (src / "nested").mkdir(parents=True)
    (src / "a.edl").write_text(EDM_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    (src / "nested" / "b.ui").write_text(UI_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    (src / "ignore.txt").write_text("x", encoding="utf-8")

    found, failed = react.convert_folder(src, tmp_path / "out", override=True)
    assert found == 2
    assert failed == []
    assert (tmp_path / "out" / "a.screen.json").is_file()
    assert (tmp_path / "out" / "nested" / "b.screen.json").is_file()


BOB_FIXTURES = Path(__file__).parent / "bob" / "fixtures"
BOB_FIXTURE = BOB_FIXTURES / "defaults.bob"


def _assert_valid(ir):
    from pydmconverter.ir.emit import to_wire_dict
    from pydmconverter.ir.schema import validate_screen_json

    assert validate_screen_json(to_wire_dict(ir)) == []


def test_convert_bytes_bob_inline_display():
    ir = react.convert_bytes(b"<display><name>t</name></display>", kind="bob")
    assert ir.metadata.source.type == "bob-converter"
    assert ir.id == "screen"
    _assert_valid(ir)


def test_convert_bytes_bob_fixture_matches_adapter():
    from pydmconverter.bob.ir_adapter import bob_bytes_to_ir

    data = BOB_FIXTURE.read_bytes()
    ir = react.convert_bytes(data, kind="bob")
    _assert_valid(ir)
    assert ir == bob_bytes_to_ir(data)
    assert ir == react.convert_bytes(data, kind="bob")  # deterministic


def test_convert_bytes_bob_passes_color_def_path():
    from pydmconverter.bob.ir_adapter import bob_bytes_to_ir

    data = (BOB_FIXTURES / "color_def.bob").read_bytes()
    color_def = BOB_FIXTURES / "color.def"
    ir = react.convert_bytes(data, kind="bob", color_def_path=color_def)
    assert ir == bob_bytes_to_ir(data, color_def_path=color_def)
    _assert_valid(ir)


def test_convert_bytes_bad_kind_message_lists_bob():
    with pytest.raises(ValueError, match="kind") as info:
        react.convert_bytes(b"<display/>", kind="opi")
    assert "bob" in str(info.value)


def test_convert_to_ir_dispatches_bob():
    ir = react.convert_to_ir(BOB_FIXTURE)
    assert ir.metadata.source.type == "bob-converter"
    assert ir.id == "defaults"
    assert ".bob" in react.SUPPORTED_SUFFIXES


def test_convert_file_bob(tmp_path):
    out = react.convert_file(BOB_FIXTURE, tmp_path / "x", override=True)
    assert out.name == "x.screen.json"
    assert json.loads(out.read_text(encoding="utf-8"))["kind"] == "screen"


def test_convert_folder_includes_bob(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "a.bob").write_bytes(BOB_FIXTURE.read_bytes())
    found, failed = react.convert_folder(src, tmp_path / "out", override=True)
    assert (found, failed) == (1, [])
    assert (tmp_path / "out" / "a.screen.json").is_file()


# -- scheme keyword ------------------------------------------------------------------------------------------------

_NAMED_BG = (
    b'<display version="2.0.0"><name>t</name><background_color>'
    b'<color name="Display_Background" red="255" green="255" blue="255"/></background_color></display>'
)


def test_convert_bytes_bob_passes_scheme():
    from pydmconverter.bob.ir_adapter import bob_bytes_to_ir
    from pydmconverter.scheme import load_scheme

    scheme = load_scheme(None)
    ir = react.convert_bytes(_NAMED_BG, kind="bob", scheme=scheme)
    expected = bob_bytes_to_ir(_NAMED_BG, scheme=scheme).model_copy(update={"schema_version": "1.1"})
    assert ir == expected
    _assert_valid(ir)


def test_convert_bytes_edl_and_ui_accept_scheme():
    from pydmconverter.scheme import load_scheme

    scheme = load_scheme(None)
    assert react.convert_bytes(EDM_FIXTURE.read_bytes(), kind="edl", scheme=scheme) == react.convert_bytes(
        EDM_FIXTURE.read_bytes(), kind="edl"
    )
    assert react.convert_bytes(UI_FIXTURE.read_bytes(), kind="ui", scheme=scheme) == react.convert_bytes(
        UI_FIXTURE.read_bytes(), kind="ui"
    )


def test_convert_file_and_folder_pass_scheme(tmp_path):
    from pydmconverter.scheme import load_scheme

    scheme = load_scheme(None)
    src = tmp_path / "in"
    src.mkdir()
    (src / "a.bob").write_bytes(_NAMED_BG)
    out = react.convert_file(src / "a.bob", tmp_path / "one", scheme=scheme)
    assert json.loads(out.read_text(encoding="utf-8"))["schemaVersion"] == "1.1"
    found, failed = react.convert_folder(src, tmp_path / "out", scheme=scheme)
    assert (found, failed) == (1, [])
    assert json.loads((tmp_path / "out" / "a.screen.json").read_text(encoding="utf-8"))["schemaVersion"] == "1.1"
    found, failed = react.convert_folder(src, tmp_path / "plain")
    assert json.loads((tmp_path / "plain" / "a.screen.json").read_text(encoding="utf-8"))["schemaVersion"] == "1.0"
