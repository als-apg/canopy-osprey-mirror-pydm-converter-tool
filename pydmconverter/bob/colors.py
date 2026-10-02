"""Named colours to scheme roles: the parity rule shared by every colour emitter.

A Phoebus colour name (``<color name="Text" .../>``) that the colour scheme imports
(``import.phoebus``) can be written as a scheme role, ``{"$role": role, "fallback": hex}``,
so a viewer re-colours it with the scheme and its light/dark mode. The converter does
that only when it changes nothing today: the role's light value must equal the hex
the converter would write anyway (the *fallback*). Otherwise the literal fallback is
kept and a ``parity:`` note is recorded, aggregated per document.

With no :class:`ColorContext` (no scheme) every call returns the fallback, so output
is identical to the converter's output before schemes existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydmconverter.scheme import canonical_hex

if TYPE_CHECKING:
    from pydmconverter.scheme import SchemeResult

__all__ = [
    "RGBA",
    "ColorContext",
    "ParityNotes",
    "named_color",
    "rgba_to_hex",
]

RGBA = tuple[int, int, int, int]

#: A colour value the IR stores: a literal hex, or a ``{"$role", "fallback"}`` role.
ColorValue = str | dict


def rgba_to_hex(rgba: tuple[int, ...]) -> str:
    """``(r, g, b[, a])`` -> ``"#rrggbb"``, or ``"#rrggbbaa"`` when alpha < 255 (components clamped)."""
    r, g, b, a = (max(0, min(255, int(c))) for c in (*rgba[:4], 255)[:4])
    return f"#{r:02x}{g:02x}{b:02x}" if a == 255 else f"#{r:02x}{g:02x}{b:02x}{a:02x}"


@dataclass
class _Mismatch:
    role: str
    fallback: str
    count: int = 0
    slots: list[str] = field(default_factory=list)


@dataclass
class ParityNotes:
    """Per-document aggregate of parity mismatches, keyed by ``(name, saved RGB, role light)``."""

    entries: dict[tuple[str, RGBA, str], _Mismatch] = field(default_factory=dict)

    def record(self, name: str, rgb: RGBA, light: str, role: str, fallback: str, slot: str) -> None:
        """Count one literal kept because ``role``'s light differs from ``fallback``."""
        entry = self.entries.setdefault((name, tuple(rgb), light), _Mismatch(role=role, fallback=fallback))
        entry.count += 1
        if slot not in entry.slots:
            entry.slots.append(slot)

    def notes(self) -> list[str]:
        """One ``parity: `` message per key, in first-seen order, with its count."""
        out: list[str] = []
        for (name, _rgb, light), entry in self.entries.items():
            uses = "use" if entry.count == 1 else "uses"
            out.append(
                f"parity: color '{name}' kept as {entry.fallback}, scheme role '{entry.role}' has light {light} "
                f"({entry.count} {uses}: {', '.join(entry.slots)})"
            )
        return out


@dataclass
class ColorContext:
    """What :func:`named_color` needs from one document's conversion.

    ``imports`` is the scheme's merged import maps (``{"phoebus": {...}, "edm": {...}}``);
    ``import_kind`` picks the one this front end uses. ``light`` maps each role to its
    light value. ``named`` is the colour-name table in force (built-ins or ``color.def``).
    ``parity`` aggregates the document's mismatches.
    """

    imports: dict[str, dict[str, str]]
    light: dict[str, str]
    named: dict[str, RGBA] | None = None
    import_kind: str = "phoebus"
    parity: ParityNotes = field(default_factory=ParityNotes)

    @classmethod
    def from_scheme(
        cls, scheme: SchemeResult, named: dict[str, RGBA] | None = None, *, import_kind: str = "phoebus"
    ) -> ColorContext:
        """Build the context of one document from a flattened scheme."""
        flat = scheme.flat
        light = dict(zip(flat.get("roles", []), flat.get("light", [])))
        imports = {kind: dict(table or {}) for kind, table in (scheme.imports or {}).items()}
        return cls(imports=imports, light=light, named=named, import_kind=import_kind)

    def role_for(self, name: str) -> str | None:
        """The role ``name`` is imported as, when that role exists in the scheme."""
        role = (self.imports.get(self.import_kind) or {}).get(name)
        return role if role is not None and role in self.light else None

    def parity_notes(self) -> list[str]:
        """The aggregated ``parity: `` notes of this document."""
        return self.parity.notes()


def named_color(name: str | None, rgb: RGBA, slot: str, ctx: ColorContext | None) -> ColorValue:
    """The IR value of a colour the converter would write as ``rgba_to_hex(rgb)``.

    ``name`` is the colour's Phoebus name (``None`` for an unnamed colour), ``rgb`` the
    RGBA the converter resolves today, ``slot`` the property being coloured (for the
    parity note). A name the scheme imports gives ``{"$role": role, "fallback": hex}``
    when the role's light value equals ``hex``; when it differs, ``hex`` is returned and
    a parity note is recorded on ``ctx``. Anything else returns ``hex``.
    """
    fallback = rgba_to_hex(rgb)
    if ctx is None or name is None:
        return fallback
    role = ctx.role_for(name)
    if role is None:
        return fallback
    light = canonical_hex(ctx.light[role])
    if light == canonical_hex(fallback):
        return {"$role": role, "fallback": fallback}
    ctx.parity.record(name, rgb, light, role, fallback, slot)
    return fallback
