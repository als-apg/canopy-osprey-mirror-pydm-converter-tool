"""``canopy-scheme``: check a color scheme file, and survey the named colors a panel corpus uses.

``check <file>`` flattens the scheme the way the converter does and prints every validation error and every role
that has no dark value; it exits 1 when there is any.

``survey <dir>... [--scheme <file>] [--corpus-root <dir>]`` counts the ``<color>`` elements of the ``.bob`` files
under the directories, per ``(name, slot, saved RGB)``, and says what each would become under the scheme.

The corpus rule (which files count) is a copy of ``tests/bob/corpus_manifest.py``; a test pins the two together.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from pydmconverter.bob.colors import ColorContext, rgba_to_hex
from pydmconverter.scheme import SchemeResult, canonical_hex, load_scheme

GLOB = "**/*.bob"
EXCLUDE: tuple[str, ...] = ("examples/*", "autogen/*", "templates/*", "synced_files*/*")
DEPLOYED_PREFIX = "/home/als/physbase/phoebus/accelerator/"

NO_SCHEME_FATE = "n/a (no scheme)"
UNNAMED = "(unnamed)"

RGBA = tuple[int, int, int, int]
Key = tuple[str, str, RGBA]


@dataclass(frozen=True)
class CorpusFile:
    """One file to survey: ``rel`` is the re-rooted corpus-relative path, ``source`` the file read."""

    rel: PurePosixPath
    source: Path


def is_excluded(rel: PurePosixPath) -> bool:
    text = rel.as_posix()
    return any(fnmatch(text, pattern) for pattern in EXCLUDE)


def _rerooted(root: Path, link: Path) -> tuple[PurePosixPath, Path] | None:
    target = os.readlink(link)
    if not target.startswith(DEPLOYED_PREFIX):
        return None
    suffix = target[len(DEPLOYED_PREFIX) :]
    candidate = root / suffix
    return (PurePosixPath(suffix), candidate) if candidate.is_file() else None


def scan_dir(directory: Path, root: Path) -> list[CorpusFile]:
    """The corpus files under ``directory``, with paths relative to ``root``, in sorted path order.

    Exclusions match the path relative to ``root``. A dangling symlink is skipped unless it points into the deployed
    tree, in which case it is read from ``root`` and keeps the re-rooted path.
    """
    out: list[CorpusFile] = []
    for path in sorted(directory.glob(GLOB)):
        try:
            rel = PurePosixPath(path.relative_to(root).as_posix())
        except ValueError:
            rel = PurePosixPath(path.relative_to(directory).as_posix())
        if is_excluded(rel):
            continue
        if path.is_symlink():
            if path.exists():
                resolved = path.resolve()
                if resolved.is_relative_to(root.resolve()):
                    rel = PurePosixPath(resolved.relative_to(root.resolve()).as_posix())
                out.append(CorpusFile(rel, path))
                continue
            rerooted = _rerooted(root, path)
            if rerooted is not None:
                out.append(CorpusFile(rerooted[0], rerooted[1]))
            continue
        if path.is_file():
            out.append(CorpusFile(rel, path))
    return out


def _default_root(dirs: list[Path]) -> Path:
    if len(dirs) == 1:
        return dirs[0]
    return Path(os.path.commonpath([str(d.resolve()) for d in dirs]))


def _file_colors(source: Path) -> dict[Key, int]:
    """Counts of ``<color>`` elements in one ``.bob`` file, keyed ``(name, slot, saved RGBA)``."""
    counts: dict[Key, int] = {}
    try:
        tree = ET.parse(source)
    except (ET.ParseError, OSError):
        return counts
    for parent in tree.iter():
        for child in parent:
            if child.tag != "color":
                continue
            try:
                rgb = tuple(int(float(child.get(c, "0"))) for c in ("red", "green", "blue"))
                alpha = int(float(child.get("alpha", "255")))
            except ValueError:
                continue
            key = (child.get("name") or UNNAMED, parent.tag, (*rgb, alpha))
            counts[key] = counts.get(key, 0) + 1
    return counts


def fate(name: str, rgba: RGBA, ctx: ColorContext | None) -> str:
    """What a color becomes under the scheme: ``role <name>`` or ``literal`` (with the reason)."""
    if ctx is None:
        return NO_SCHEME_FATE
    role = None if name == UNNAMED else ctx.role_for(name)
    if role is None:
        return "literal (not imported)"
    light = canonical_hex(ctx.light[role])
    if light == canonical_hex(rgba_to_hex(rgba)):
        return f"role {role}"
    return f"literal (role {role} light {light} differs)"


def _row(key: Key, count: int, ctx: ColorContext | None) -> str:
    name, slot, rgba = key
    return f"{name}\t{slot}\t{rgba_to_hex(rgba)}\t{count}\t{fate(name, rgba, ctx)}"


def survey(dirs: list[Path], scheme: SchemeResult | None, root: Path | None, out) -> None:
    root = root if root is not None else _default_root(dirs)
    ctx = ColorContext.from_scheme(scheme) if scheme is not None else None
    seen: set[PurePosixPath] = set()
    total: dict[Key, int] = {}
    print("# name\tslot\tsaved RGB\tcount\tfate", file=out)
    for directory in dirs:
        for item in scan_dir(directory, root):
            if item.rel in seen:
                continue
            seen.add(item.rel)
            counts = _file_colors(item.source)
            print(f"# file: {item.rel.as_posix()}", file=out)
            for key in sorted(counts):
                print(_row(key, counts[key], ctx), file=out)
                total[key] = total.get(key, 0) + counts[key]
    print(f"# total: {len(seen)} file(s)", file=out)
    for key in sorted(total):
        print(_row(key, total[key], ctx), file=out)


def check(path: Path, out) -> int:
    result = load_scheme(path)
    errors = result.meta["errors"]
    no_dark = sorted(
        {e["path"].split("/")[-2] for e in errors if e["path"].endswith("/dark") and "no dark value" in e["message"]}
    )
    for err in errors:
        print(f"error: {err['path'] or '<file>'}: {err['message']}", file=out)
    for name in no_dark:
        print(f"no dark value: {name}", file=out)
    if errors:
        print(f"{path}: {len(errors)} error(s)", file=out)
        return 1
    print(f"{path}: ok ({len(result.flat['roles'])} roles)", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canopy-scheme", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="validate a scheme file")
    p_check.add_argument("file", type=Path)
    p_survey = sub.add_parser("survey", help="count the named colors a corpus uses")
    p_survey.add_argument("dirs", nargs="+", type=Path)
    p_survey.add_argument("--scheme", type=Path, default=None)
    p_survey.add_argument("--corpus-root", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "check":
        return check(args.file, sys.stdout)
    scheme = load_scheme(args.scheme) if args.scheme is not None else None
    if scheme is not None and scheme.meta["errors"]:
        print(f"{args.scheme}: scheme has errors; run 'canopy-scheme check'", file=sys.stderr)
        return 1
    survey(args.dirs, scheme, args.corpus_root, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
