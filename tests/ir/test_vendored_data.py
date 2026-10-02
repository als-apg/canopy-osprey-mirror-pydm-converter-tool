"""Pins the vendored Canopy contracts and checks they ship as package data.

The values here must match the table in ``pydmconverter/ir/data/VENDORED_SCHEMA.md``.
Everything is read through ``importlib.resources`` on the installed package, so a
missing ``package-data`` glob fails here rather than at a user's import.
"""

import hashlib
import json
import re
from importlib.resources import files
from typing import get_args

import jsonschema
import pytest

from pydmconverter.ir.model import SchemaVersion, ScreenIR

PINNED = {
    "screen-ir.schema.json": "e9a2cbd3bf620b12c97da9941af4dd9db061bf088d25ed1c1bcdfcffd7c10e4c",
    "canopy-color-scheme-1.schema.json": "be4f4b9a14714cab955173546dc868f078da4f7b1867a7482a6f582456d8c2c3",
    "schemes/canopy-default.json": "36e765dc007f378c468baa41173cee4973a123c16e936e30b5becf9e187b4683",
}
REGISTRY_DIGEST = "5a721981b55042091a3329626a5fb62f327685a8e91989dd164c3c816983147b"


def data_dir():
    return files("pydmconverter") / "ir" / "data"


def resource(rel):
    node = data_dir()
    for part in rel.split("/"):
        node = node / part
    return node


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def registry_digest() -> str:
    """sha256 of the ``shasum -a 256 *.json`` listing of widget-registry/, sorted by name."""
    entries = sorted(
        (entry for entry in (data_dir() / "widget-registry").iterdir() if entry.name.endswith(".json")),
        key=lambda entry: entry.name,
    )
    listing = "".join(f"{sha256(entry.read_bytes())}  {entry.name}\n" for entry in entries)
    return sha256(listing.encode())


@pytest.mark.parametrize("rel", sorted(PINNED))
def test_vendored_file_matches_pinned_sha256(rel):
    """Each vendored file is the exact byte copy recorded in VENDORED_SCHEMA.md."""
    node = resource(rel)
    assert node.is_file(), f"{rel} is not shipped as package data"
    assert sha256(node.read_bytes()) == PINNED[rel]


def test_widget_registry_matches_pinned_digest():
    """The registry snapshot is the byte copy recorded in VENDORED_SCHEMA.md."""
    assert registry_digest() == REGISTRY_DIGEST


def test_registry_files_end_in_one_newline():
    """The byte copy keeps canopy's normalisation: exactly one final newline per file."""
    for entry in (data_dir() / "widget-registry").iterdir():
        if entry.name.endswith(".json"):
            data = entry.read_bytes()
            assert data.endswith(b"}\n") and not data.endswith(b"\n\n"), entry.name


def test_vendored_schema_md_records_the_pinned_values():
    """VENDORED_SCHEMA.md and this test pin the same sha256 values."""
    text = (data_dir() / "VENDORED_SCHEMA.md").read_text(encoding="utf-8")
    for rel, digest in PINNED.items():
        assert re.search(rf"`{re.escape(rel)}` \| `[^`]+` \| `{digest}`", text), rel
    assert re.search(rf"`widget-registry/\*\.json` \| `[^`]+` \| `{REGISTRY_DIGEST}`", text)


def test_vendored_schema_md_sources_are_repo_relative():
    """Sources are recorded as ``<repo>: <path>``, never an absolute or tool-local path."""
    text = (data_dir() / "VENDORED_SCHEMA.md").read_text(encoding="utf-8")
    sources = re.findall(r"\| `[^`]+` \| `([^`]+)` \| `[0-9a-f]{64}` \|", text)
    assert len(sources) == len(PINNED) + 1
    for source in sources:
        repo, _, path = source.partition(": ")
        assert repo in {"canopy", "canopy-sdk-js"}, source
        assert path and not path.startswith(("/", "~")) and ".claude" not in path, source


def test_beaver_snapshot_sha_is_one_commit_id():
    """The registry pin names a single full commit id."""
    text = (data_dir() / "widget-registry" / ".beaver-snapshot-sha").read_text(encoding="utf-8")
    assert re.fullmatch(r"[0-9a-f]{40}\n", text)


def test_schema_and_model_accept_1_0_and_1_1():
    """The vendored 1.1 schema and the model both accept 1.0 and 1.1 documents."""
    schema = json.loads(resource("screen-ir.schema.json").read_text(encoding="utf-8"))
    assert sorted(schema["properties"]["schemaVersion"]["enum"]) == ["1.0", "1.1"]
    assert get_args(SchemaVersion) == ("1.0", "1.1")
    assert ScreenIR.model_fields["schema_version"].default == "1.0"


def test_color_scheme_schema_validates_the_default_scheme():
    """The vendored default scheme conforms to the vendored colour-scheme schema."""
    schema = json.loads(resource("canopy-color-scheme-1.schema.json").read_text(encoding="utf-8"))
    scheme = json.loads(resource("schemes/canopy-default.json").read_text(encoding="utf-8"))
    jsonschema.validate(scheme, schema)
    assert scheme["id"] == "canopy-default"
