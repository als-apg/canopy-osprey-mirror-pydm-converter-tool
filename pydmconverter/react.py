"""React/Canopy target entry point: dispatch ``.edl``/``.ui``/``.bob`` -> Screen IR JSON.

This is the ``--target react`` half of the converter. It picks the front-end adapter
by file suffix and writes ``*.screen.json``. The legacy ``--target pydm`` path
(``edm/converter.py``, which writes ``.ui``) is untouched.

TSX is intentionally not produced here — that is the Screen Builder's eject path
(``@canopy/emitters``); this side stops at the runtime-renderable IR JSON.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from pydmconverter.bob.ir_adapter import bob_file_to_ir
from pydmconverter.edm.ir_adapter import edm_file_to_ir
from pydmconverter.ir.emit import to_wire_dict, write_screen_json
from pydmconverter.ir.model import ScreenIR
from pydmconverter.ir.registry import RegistryClient
from pydmconverter.scheme import SchemeResult, stamp_schema_version
from pydmconverter.ui.ir_adapter import ui_file_to_ir

logger = logging.getLogger(__name__)

_ADAPTERS = {".edl": edm_file_to_ir, ".ui": ui_file_to_ir, ".bob": bob_file_to_ir}
SUPPORTED_SUFFIXES = tuple(_ADAPTERS)


def convert_to_ir(
    input_path: str | Path,
    *,
    registry: RegistryClient | None = None,
    color_list_path: str | Path | None = None,
    calc_list_path: str | Path | None = None,
    site: str | None = None,
    color_def_path: str | Path | None = None,
    scheme: SchemeResult | None = None,
) -> ScreenIR:
    """Parse an ``.edl``, ``.ui`` or ``.bob`` file into a Screen IR, dispatching by suffix.

    ``color_list_path`` (``.edl`` inputs only) points at an EDM ``colors.list`` palette
    used to resolve "index N" color props; when omitted it is located via (in order)
    the ``EDMCOLORFILE`` env var, ``$EDMFILES/colors.list``, then ``/etc/edm/colors.list``.
    ``color_def_path`` (``.bob`` inputs only) names a Phoebus ``color.def`` whose entries
    overlay the built-in named colours; when omitted only the built-in names resolve.
    ``scheme`` (``.bob`` inputs only, for now) is a flattened colour scheme whose imported names
    become colour roles. The result is stamped ``schema_version`` ``"1.1"`` iff it carries a
    role (:func:`pydmconverter.scheme.stamp_schema_version`); it is never validated here.
    """
    suffix = Path(input_path).suffix.lower()
    adapter = _ADAPTERS.get(suffix)
    if adapter is None:
        raise ValueError(f"--target react supports {', '.join(SUPPORTED_SUFFIXES)} inputs, not {suffix!r}")
    if suffix == ".edl":
        ir = edm_file_to_ir(
            input_path,
            registry=registry,
            color_list_path=color_list_path,
            calc_list_path=calc_list_path,
            site=site,
        )
    elif suffix == ".bob":
        ir = bob_file_to_ir(input_path, registry=registry, color_def_path=color_def_path, scheme=scheme)
    else:
        ir = ui_file_to_ir(input_path, registry=registry)
    # Stamp here, the one point every entry point flows through, so callers that take the ScreenIR (not the
    # written JSON) see the right version. Role-free screens keep "1.0" and are byte-identical to before.
    ir.schema_version = stamp_schema_version(to_wire_dict(ir))
    return ir


def convert_bytes(
    data: bytes,
    *,
    kind: Literal["edl", "ui", "bob"],
    registry: RegistryClient | None = None,
    color_list_path: str | Path | None = None,
    calc_list_path: str | Path | None = None,
    site: str | None = None,
    color_def_path: str | Path | None = None,
    scheme: SchemeResult | None = None,
) -> ScreenIR:
    """Parse raw ``.edl``/``.ui``/``.bob`` bytes into a Screen IR, keyed on ``kind``.

    For HTTP callers (the Screen Builder uploads screens as bytes, a browser cannot
    hand the backend a server path), so callers need not spill uploads to disk. The
    EDM parser reads from a path, so the bytes are staged in a temp file scoped to
    this call rather than in every caller.

    ``color_list_path`` (``kind="edl"`` only) points at an EDM ``colors.list`` palette
    used to resolve "index N" color props; when omitted it falls back to the
    ``EDMCOLORFILE`` env var, then ``$EDMFILES/colors.list``, then ``/etc/edm/colors.list``.
    ``color_def_path`` (``kind="bob"`` only) names a Phoebus ``color.def`` whose entries
    overlay the built-in named colours; when omitted only the built-in names resolve.
    ``scheme`` is a flattened colour scheme; see :func:`convert_to_ir`.
    """
    if kind not in ("edl", "ui", "bob"):
        raise ValueError(f"convert_bytes kind must be 'edl', 'ui' or 'bob', not {kind!r}")
    # Fixed basename in a private temp dir -> a deterministic screen id (not a random
    # temp stem), and conversion of identical bytes is byte-stable.
    tmp_dir = Path(tempfile.mkdtemp(prefix="pydmconv-"))
    try:
        staged = tmp_dir / f"screen.{kind}"
        staged.write_bytes(data)
        return convert_to_ir(
            staged,
            registry=registry,
            color_list_path=color_list_path,
            calc_list_path=calc_list_path,
            site=site,
            color_def_path=color_def_path,
            scheme=scheme,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _screen_json_path(input_path: Path, output_path: Path) -> Path:
    """Normalize the output to a ``*.screen.json`` path."""
    if output_path.suffix.lower() == ".json":
        return output_path
    return output_path.parent / f"{output_path.stem or input_path.stem}.screen.json"


def convert_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    override: bool = False,
    registry: RegistryClient | None = None,
    color_list_path: str | Path | None = None,
    calc_list_path: str | Path | None = None,
    site: str | None = None,
    color_def_path: str | Path | None = None,
    scheme: SchemeResult | None = None,
) -> Path:
    """Convert one ``.edl``/``.ui``/``.bob`` file to ``*.screen.json``; return the output path.

    ``color_list_path`` (``.edl`` inputs only) points at an EDM ``colors.list`` palette
    used to resolve "index N" color props; when omitted it falls back to the
    ``EDMCOLORFILE`` env var, then ``$EDMFILES/colors.list``, then ``/etc/edm/colors.list``.
    ``color_def_path`` (``.bob`` inputs only) names a Phoebus ``color.def`` whose entries
    overlay the built-in named colours; when omitted only the built-in names resolve.
    ``scheme`` is a flattened colour scheme; see :func:`convert_to_ir`.
    """
    inp = Path(input_path)
    out = _screen_json_path(inp, Path(output_path))
    if out.is_file() and not override:
        raise FileExistsError(f"Output file '{out}' already exists. Use --override or -o to overwrite it.")
    return write_screen_json(
        convert_to_ir(
            inp,
            registry=registry,
            color_list_path=color_list_path,
            calc_list_path=calc_list_path,
            site=site,
            color_def_path=color_def_path,
            scheme=scheme,
        ),
        out,
    )


def convert_folder(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    override: bool = False,
    registry: RegistryClient | None = None,
    color_list_path: str | Path | None = None,
    calc_list_path: str | Path | None = None,
    site: str | None = None,
    color_def_path: str | Path | None = None,
    scheme: SchemeResult | None = None,
) -> tuple[int, list[str]]:
    """Recursively convert every ``.edl``/``.ui``/``.bob`` under ``input_dir``.

    Returns ``(files_found, files_failed)``.

    ``color_list_path`` (``.edl`` inputs only) points at an EDM ``colors.list`` palette
    used to resolve "index N" color props; when omitted it falls back to the
    ``EDMCOLORFILE`` env var, then ``$EDMFILES/colors.list``, then ``/etc/edm/colors.list``.
    ``color_def_path`` (``.bob`` inputs only) names a Phoebus ``color.def`` whose entries
    overlay the built-in named colours; when omitted only the built-in names resolve.
    ``scheme`` is a flattened colour scheme; see :func:`convert_to_ir`.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    found = 0
    failed: list[str] = []
    for source in sorted(input_dir.rglob("*")):
        if not source.is_file() or source.suffix.lower() not in _ADAPTERS:
            continue
        found += 1
        relative = source.relative_to(input_dir)
        out = (output_dir / relative).parent / f"{source.stem}.screen.json"
        if out.is_file() and not override:
            failed.append(str(source))
            logger.warning("Skipped: %s already exists. Use --override or -o to overwrite it.", out)
            continue
        try:
            write_screen_json(
                convert_to_ir(
                    source,
                    registry=registry,
                    color_list_path=color_list_path,
                    calc_list_path=calc_list_path,
                    site=site,
                    color_def_path=color_def_path,
                    scheme=scheme,
                ),
                out,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue the walk
            failed.append(str(source))
            logger.warning("Failed to convert %s: %s", source, exc)
    return found, failed
