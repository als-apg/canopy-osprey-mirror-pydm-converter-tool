"""screen_ref rewrites for Phoebus .bob/.opi display references.

The bob adapter relies on ``screen_ref`` to turn embedded-display and
open-display action targets into the converted ``.screen.json`` artifact.
No existence check happens here: the corpus test owns that.
"""

from __future__ import annotations

import pytest

from pydmconverter.ir.transforms import DROP, screen_ref


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("../common/KnobPanel.bob", "../common/KnobPanel.screen.json"),
        ("foo.OPI", "foo.screen.json"),
        ("foo.opi", "foo.screen.json"),
        ("Foo.BOB", "Foo.screen.json"),
        # a macro default value is a plain filename and is rewritten too
        ("Mod1EPS.bob", "Mod1EPS.screen.json"),
        # the existing front-ends, now case-insensitive
        ("panel.ui", "panel.screen.json"),
        ("panel.EDL", "panel.screen.json"),
        ("panel.adl", "panel.screen.json"),
        ("sub\\dir\\panel.bob", "sub/dir/panel.screen.json"),
    ],
)
def test_screen_ref_rewrites_display_extensions(ref, expected):
    assert screen_ref(ref) == expected


@pytest.mark.parametrize("ref", ["${WG_file}", "$(FILE)", "${FILE}", "x.screen.json"])
def test_screen_ref_leaves_macros_and_converted_names(ref):
    assert screen_ref(ref) == ref


def test_screen_ref_does_not_check_existence(tmp_path):
    missing = tmp_path / "nope" / "Missing.bob"
    assert screen_ref(str(missing)) == str(missing)[: -len(".bob")] + ".screen.json"


def test_screen_ref_takes_first_of_list_and_drops_empty():
    assert screen_ref(["a.bob", "b.opi"]) == "a.screen.json"
    assert screen_ref([]) is DROP
