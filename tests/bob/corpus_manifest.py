"""The curated Phoebus ``.bob`` corpus: the committed glob, exclusions and symlink rule.

The corpus itself (a site's panel tree) is never committed; its root comes from the
``PHOEBUS_CORPUS`` environment variable. This module fixes *which* files of that tree
the corpus tests convert, so the counts the tests assert are reproducible:

* every ``**/*.bob`` under the root, minus the top-level directories matched by
  :data:`EXCLUDE` (demo, generated and template panels);
* ``_``-prefixed files (embedded, "private" panels) are kept;
* a symlink whose target is missing is skipped, except that a symlink pointing into
  the deployed tree :data:`DEPLOYED_PREFIX` is resolved against the corpus root
  instead (``<PHOEBUS_CORPUS>/<suffix>``) and its output is written at the
  symlink's own path, so a parent embedding ``embedded/_bpm.screen.json`` finds it
  beside itself exactly as the deployed panels do.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

__all__ = [
    "CORPUS_ENV",
    "DEPLOYED_PREFIX",
    "EXCLUDE",
    "GLOB",
    "CorpusEntry",
    "Manifest",
    "corpus_root",
    "is_excluded",
    "load_manifest",
    "output_path",
]

CORPUS_ENV = "PHOEBUS_CORPUS"
GLOB = "**/*.bob"
# Matched against the corpus-relative POSIX path; ``*`` spans directories.
EXCLUDE: tuple[str, ...] = ("examples/*", "autogen/*", "templates/*", "synced_files*/*")
# Where the deployed panels live; links into it are re-rooted at the corpus root.
DEPLOYED_PREFIX = "/home/als/physbase/phoebus/accelerator/"


@dataclass(frozen=True)
class CorpusEntry:
    """One file to convert.

    ``rel`` is the corpus-relative path the output belongs at (the symlink's own
    path for a re-rooted link); ``source`` is the file actually read.
    """

    rel: PurePosixPath
    source: Path
    rerooted: bool = False


@dataclass(frozen=True)
class Manifest:
    """The curated entries plus the files the rules set aside, for the report."""

    root: Path
    entries: tuple[CorpusEntry, ...]
    excluded: tuple[PurePosixPath, ...]
    dangling: tuple[PurePosixPath, ...]

    def entry(self, rel: str) -> CorpusEntry:
        """The entry at corpus-relative path ``rel``; ``KeyError`` when not curated."""
        wanted = PurePosixPath(rel)
        for item in self.entries:
            if item.rel == wanted:
                return item
        raise KeyError(rel)


def corpus_root() -> Path | None:
    """The corpus root from ``PHOEBUS_CORPUS``, or ``None`` when unset or empty."""
    value = os.environ.get(CORPUS_ENV, "").strip()
    return Path(value).expanduser() if value else None


def is_excluded(rel: PurePosixPath) -> bool:
    """True when the corpus-relative path matches one of :data:`EXCLUDE`."""
    text = rel.as_posix()
    return any(fnmatch(text, pattern) for pattern in EXCLUDE)


def output_path(rel: PurePosixPath) -> PurePosixPath:
    """Where the converted screen of ``rel`` is written: ``x.bob`` -> ``x.screen.json``."""
    return rel.with_suffix(".screen.json")


def _rerooted_source(root: Path, link: Path) -> Path | None:
    target = os.readlink(link)
    if not target.startswith(DEPLOYED_PREFIX):
        return None
    candidate = root / target[len(DEPLOYED_PREFIX) :]
    return candidate if candidate.is_file() else None


def load_manifest(root: Path) -> Manifest:
    """Apply the glob, exclusions and symlink rule to ``root``, in sorted path order."""
    entries: list[CorpusEntry] = []
    excluded: list[PurePosixPath] = []
    dangling: list[PurePosixPath] = []
    for path in sorted(root.glob(GLOB)):
        rel = PurePosixPath(path.relative_to(root).as_posix())
        if is_excluded(rel):
            excluded.append(rel)
            continue
        if path.is_symlink() and not path.exists():
            source = _rerooted_source(root, path)
            if source is None:
                dangling.append(rel)
            else:
                entries.append(CorpusEntry(rel=rel, source=source, rerooted=True))
            continue
        if path.is_file():
            entries.append(CorpusEntry(rel=rel, source=path))
    return Manifest(root=root, entries=tuple(entries), excluded=tuple(excluded), dangling=tuple(dangling))
