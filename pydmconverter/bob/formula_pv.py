"""Formula-PV lowering for the Phoebus ``.bob`` front-end.

A Phoebus PV name starting with ``=`` is a *formula PV*: the rest of the text is an
expression over other PVs, evaluated client-side by Phoebus' ``FormulaPV``. PVs are
referenced as backticked names (```SR:PV```), single-quoted names (``'SR:PV'``) or
``pv("SR:PV")`` calls. The corpus forms are arithmetic, ``abs``, comparisons and the
JavaScript-style boolean operators, e.g. ``=(pv("X")*60)``, ``=abs(`A`-`B`) <= 0.25`` and
``=`A`&&`B```.

:func:`lower_formula_pv` rewrites such a text into a Fox formula: every distinct PV name
(macro syntax normalised to ``${VAR}``) becomes a positional binding ``{0}``, ``{1}``, ...,
``&&``/``||``/``!`` become ``and``/``or``/``not``, and the result is interned in the
screen's formula pool, the caller retargeting the prop to ``fox://<name>``. Anything
outside that subset (``concat``, ``elementAt``, other functions, conditionals, bare
names, a rewrite that fails ``ast.parse``) is declined with a warning and ``None``; the
caller carries the text in ``meta.comment`` instead.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from pydmconverter.ir.macros import normalize_macro_syntax

__all__ = ["FORMULA_NOT_LOWERED_WARNING", "lower_formula_pv"]

FORMULA_NOT_LOWERED_WARNING = "{widget}: formula PV not lowered: {text}"

# PV references, in precedence order: pv("x") / pv('x') calls, `x`, 'x'.
_PV_REF_RE = re.compile(
    r"""pv\(\s*"(?P<dq>[^"]*)"\s*\)"""
    r"""|pv\(\s*'(?P<sq>[^']*)'\s*\)"""
    r"""|`(?P<bt>[^`]*)`"""
    r"""|'(?P<q>[^']*)'"""
)
_BINDING_RE = re.compile(r"\{(\d+)\}")
_PLACEHOLDER = "_pv{}"

_ALLOWED_NODES: tuple[type, ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)
_ALLOWED_FUNCTIONS = frozenset({"abs"})


def _tokenise(body: str) -> tuple[str, dict[str, str]]:
    """Replace PV references with ``{N}`` tokens; identical names share one index."""
    index_of: dict[str, int] = {}

    def token(m: re.Match) -> str:
        name = next(g for g in m.groups() if g is not None)
        name = normalize_macro_syntax(name.strip())
        n = index_of.setdefault(name, len(index_of))
        return f"{{{n}}}"

    text = _PV_REF_RE.sub(token, body)
    return text, {str(n): name for name, n in index_of.items()}


def _rewrite_operators(text: str) -> str:
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text)
    return " ".join(text.split())


def _supported(expression: str, bindings: dict[str, str]) -> bool:
    """Syntax check with tokens replaced by names, then the allowed-subset walk."""
    placeholders = {_PLACEHOLDER.format(n) for n in bindings}
    try:
        tree = ast.parse(_BINDING_RE.sub(lambda m: _PLACEHOLDER.format(m.group(1)), expression), mode="eval")
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return False
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_FUNCTIONS) or node.keywords:
                return False
        elif isinstance(node, ast.Name) and node.id not in placeholders and node.id not in _ALLOWED_FUNCTIONS:
            return False
    # Function names may only appear as the callee.
    callees = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return not any(
        isinstance(n, ast.Name) and n.id in _ALLOWED_FUNCTIONS and id(n) not in callees for n in ast.walk(tree)
    )


def _warn(ctx: Any, message: str) -> None:
    warn = getattr(ctx, "warn", None)
    if callable(warn):
        warn(message)
    else:
        ctx.warnings.append(message)


def lower_formula_pv(text: str, ctx: Any, *, widget: str | None = None) -> str | None:
    """Lower a Phoebus ``=`` formula PV to ``fox://<name>``, or return ``None``.

    ``ctx`` needs ``builder.formulas`` (a :class:`~pydmconverter.ir.ids.FormulaPool`,
    normally ``IRBuilder.formulas``) and either a ``warn(str)`` callable or a
    ``warnings`` list. ``widget`` prefixes the warning. On ``None`` exactly one
    warning, ``"<widget>: formula PV not lowered: <text>"``, has been recorded.
    """
    stripped = text.strip()
    if stripped.startswith("="):
        expression, bindings = _tokenise(stripped[1:])
        expression = _rewrite_operators(expression)
        if bindings and _supported(expression, bindings):
            return f"fox://{ctx.builder.formulas.intern(expression, bindings)}"
    message = f"formula PV not lowered: {text}"
    _warn(ctx, FORMULA_NOT_LOWERED_WARNING.format(widget=widget, text=text) if widget else message)
    return None
