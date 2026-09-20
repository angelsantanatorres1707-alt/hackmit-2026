"""Extracted student work -> StepReplay scene parameters.

This is the piece that makes the video *replay the student's reasoning* instead
of picking one of seven canned comparisons. Everything it emits is a function of

  * ``problem.givens``            -- the printed problem, which is public, and
  * ``step.value`` / ``raw_text`` -- the numbers the student actually wrote.

``verdict.correct_value`` is never read and never emitted. A scene that is not
handed the right answer cannot leak it; that is the whole point of the
:mod:`docs/STEP_REPLAY.md` design and it is enforced here, at the source.

Entry points
------------

``compile_step_replay(ext, verdict) -> dict``
    The params block the ``StepReplay`` scene consumes. **Never raises.** A step
    it cannot make sense of degrades to ``kind="literal"`` -- the written line
    docks into the ledger and the canvas holds. A partial replay beats no replay.

``viable(params) -> (bool, reason)``
    The planner's gate, implementing STEP_REPLAY.md §3 validation cases 1, 2
    and 7. ``False`` means "fall through to the old template ladder", not
    "error".

``compile_replay(ext, verdict) -> CompileResult``
    Both of the above plus the warnings, for debugging and for tests.

Classification (STEP_REPLAY.md §2) is driven by ``claimed_operation`` first,
then by the *shape of the value the student wrote*, then -- for the case that
matters most -- by arithmetic on their own numbers. A line the extractor
labelled ``project`` but which is written ``5(1,2) = (5,10)``, where ``5`` is
the scalar a previous step bound, is a ``scale_vector``: we can check that
5 * (1,2) really is (5,10) and say so. That check is what "it read my work"
means in code.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Iterable, Optional

__all__ = [
    "compile_step_replay",
    "compile_replay",
    "viable",
    "CompileResult",
    "STEP_KINDS",
    "MOTION_KINDS",
]

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

STEP_KINDS = (
    "define_vector", "define_matrix", "dot_product", "scale_vector",
    "add_vectors", "matrix_apply", "matrix_product", "row_op",
    "normalize", "project", "scalar_value", "literal",
)

#: Kinds that actually move something on the canvas. ``define_matrix`` only
#: pulses the grid and ``scalar_value``/``literal`` are ledger-only, so they do
#: not count as motion when the planner asks whether a replay is worth playing.
MOTION_KINDS = frozenset({
    "define_vector", "dot_product", "scale_vector", "add_vectors",
    "matrix_apply", "matrix_product", "row_op", "normalize", "project",
})

#: Ledger-only kinds. STEP_REPLAY.md §2.11: a replay that invents a picture for
#: an arithmetic line is the exact failure mode being fixed.
LEDGER_KINDS = frozenset({"scalar_value", "literal"})

#: Kinds whose textbook construction would give away a LATER step's answer, so
#: an earlier step must be told not to draw it (STEP_REPLAY.md §2.3, the trap).
LEAKY_KINDS = frozenset({"project", "normalize"})

MAX_MAGNITUDE = 50.0       # validation case 6 -- past this nothing frames
MAX_ZOOM_RATIO = 40.0      # validation case 7 -- no framing holds both ends
EXPR_CHARS = 34            # ledger line width, STEP_REPLAY.md §3

# Canvas constants, verified at -qm (STEP_REPLAY.md §5)
BOX_W, BOX_H = 9.5, 6.05
BOX_CENTER = (-1.85, -0.30)
LEDGER_X = 4.95
ZOOM_MAX = 2.6
MAX_UNIT = 2.0           # BOX_W/2.0 = 4.75 cells, the legibility floor
GROW_MAX_UNIT = 4.0      # normalize: the unit circle carries the frame
PAD = 0.9                  # math units of air around the bbox
MARGIN = 0.55              # scene units kept clear inside the box (arrowheads)

VECTOR_COLORS = ("i_hat", "j_hat", "probe")

# Per-kind run times, STEP_REPLAY.md §4.1
BASE_RUN_TIME = {
    "define_vector": 0.6, "define_matrix": 0.7, "dot_product": 2.4,
    "add_vectors": 1.8, "matrix_apply": 2.2, "matrix_product": 2.0,
    "row_op": 2.0, "normalize": 1.6, "project": 2.2,
    "scalar_value": 0.5, "literal": 0.5, "scale_vector": 2.6,
}
RUN_TIME_FLOOR = 0.4
BUDGET = 18.0              # target; hard ceiling 20

FIXED_TITLE = 1.6          # title + givens beat
FIXED_INVARIANT = 1.0
FIXED_DIVERGENCE = 1.2
FIXED_HINT = 1.2
FIXED_HOLD = 1.8

# verify.py status -> our status vocabulary
STATUS_MAP = {
    "OK": "ok",
    "WRONG": "wrong",
    "UNCHECKED": "unchecked",
    "CROSSED_OUT": "crossed_out",
    "SKIPPED_UNPARSED": "unchecked",
}


# --------------------------------------------------------------------------
# Formatting and coercion
# --------------------------------------------------------------------------

def fmt_num(x: Any, max_den: int = 20) -> str:
    """``3`` -> ``'3'``; a nice rational -> ``'2/5'``; else ``'0.71'``.

    Mirrors ``helpers.fmt_num`` without importing manim -- this module has to be
    importable from the API process, which must not pull in a renderer.
    """
    if isinstance(x, str):
        return x
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not math.isfinite(f):
        return "?"
    if abs(f) < 5e-9:
        return "0"
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    fr = Fraction(f).limit_denominator(max_den)
    if abs(float(fr) - f) < 1e-9:
        return f"{fr.numerator}/{fr.denominator}"
    s = f"{f:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def _finite(x: Any) -> Optional[float]:
    """A number we are willing to put on a plane, or None. Never raises."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or abs(f) > MAX_MAGNITUDE:
        return None
    return f


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field off a pydantic model or a plain dict, indifferently.

    The compiler is fed ``backend.extract.Extraction`` in production and plain
    dicts in tests and from cached JSON; both must work.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        v = obj.get(name, default)
    else:
        v = getattr(obj, name, default)
    return default if v is None else v


def _obj_kind(obj: Any) -> str:
    return str(_get(obj, "kind", "unknown") or "unknown")


def as_vector(obj: Any) -> Optional[list[float]]:
    """A MathObject -> a flat list of finite floats, or None.

    Accepts a row vector (``rows=[[3,4]]``), a column vector
    (``rows=[[3],[4]]``) and a ``scalars`` list used as coordinates.
    """
    if obj is None:
        return None
    rows = _get(obj, "rows")
    flat: list[Any] = []
    if isinstance(rows, list) and rows:
        if all(isinstance(r, (list, tuple)) for r in rows):
            nrow, ncol = len(rows), max(len(r) for r in rows)
            if nrow != 1 and ncol != 1:
                return None                      # a genuine matrix, not a vector
            flat = [c for r in rows for c in r]
        else:
            flat = list(rows)
    elif _obj_kind(obj) == "vector":
        # A list of eigenvalues is NOT a point. Only an object the extractor
        # actually called a vector may fall back to `scalars` for coordinates.
        sc = _get(obj, "scalars")
        if isinstance(sc, list):
            flat = list(sc)
    if not 2 <= len(flat) <= 3:
        return None
    out = [_finite(c) for c in flat]
    if any(c is None for c in out):
        return None
    return [float(c) for c in out]              # type: ignore[arg-type]


def as_matrix(obj: Any) -> Optional[list[list[float]]]:
    """A MathObject -> a rectangular list of lists of finite floats, or None."""
    if obj is None:
        return None
    rows = _get(obj, "rows")
    if not isinstance(rows, list) or not rows:
        return None
    if not all(isinstance(r, (list, tuple)) and r for r in rows):
        return None
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        return None
    if len(rows) == 1 or width == 1:
        return None                              # that is a vector
    out: list[list[float]] = []
    for r in rows:
        vals = [_finite(c) for c in r]
        if any(v is None for v in vals):
            return None
        out.append([float(v) for v in vals])     # type: ignore[arg-type]
    return out


def as_scalar(obj: Any) -> Optional[float]:
    """A MathObject -> one finite float, or None."""
    if obj is None:
        return None
    sc = _get(obj, "scalars")
    if isinstance(sc, list) and len(sc) == 1:
        return _finite(sc[0])
    rows = _get(obj, "rows")
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], list) \
            and len(rows[0]) == 1:
        return _finite(rows[0][0])
    return None


def _exact_scalar_display(obj: Any) -> Optional[str]:
    ex = _get(obj, "exact_scalars")
    if isinstance(ex, list) and len(ex) == 1 and isinstance(ex[0], str):
        return ex[0]
    return None


def vec_display(v: Iterable[float]) -> str:
    return "(" + ", ".join(fmt_num(c) for c in v) + ")"


def mat_display(M: Iterable[Iterable[float]]) -> list[list[str]]:
    return [[fmt_num(c) for c in row] for row in M]


def normalise_expr(text: str, limit: int = EXPR_CHARS) -> str:
    """The student's own line, whitespace-normalised and clipped to the rail."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= limit:
        return s
    return s[: max(1, limit - 1)].rstrip() + "…"


# --------------------------------------------------------------------------
# The register file (STEP_REPLAY.md §1)
# --------------------------------------------------------------------------

@dataclass
class Reg:
    """symbol -> the student's current value for it, and how to draw it."""
    symbol: str
    kind: str                       # "vector" | "matrix" | "scalar"
    value: Any                      # list | list[list] | float
    display: Any                    # str | list[list[str]]
    color: str = "correct"
    label: str = ""
    source: str = "given"           # "given" or a step id


class Env:
    """Ordered register file. Symbols only ever resolve *backwards* in time,
    which is what makes validation case 3 (forward reference) impossible."""

    def __init__(self) -> None:
        self._regs: dict[str, Reg] = {}
        self._vec_colors = 0

    def __contains__(self, sym: object) -> bool:
        return sym in self._regs

    def get(self, sym: Optional[str]) -> Optional[Reg]:
        if not sym:
            return None
        return self._regs.get(sym)

    def put(self, reg: Reg) -> Reg:
        self._regs[reg.symbol] = reg
        return reg

    def next_vector_color(self) -> str:
        c = VECTOR_COLORS[self._vec_colors % len(VECTOR_COLORS)]
        self._vec_colors += 1
        return c

    def of_kind(self, kind: str) -> list[Reg]:
        return [r for r in self._regs.values() if r.kind == kind]

    def symbols(self) -> list[str]:
        return list(self._regs)

    def fresh(self, preferred: Iterable[str]) -> str:
        names = [str(n) for n in preferred if n]
        for name in names:
            if name not in self._regs:
                return name
        base = names[-1] if names else "t"   # "c2", never "2"
        i = 2
        while f"{base}{i}" in self._regs:
            i += 1
        return f"{base}{i}"


_SCALAR_BIND_NAMES = ("k", "m", "n", "c")
_VECTOR_BIND_NAMES = ("p", "q", "r", "w")
_MATRIX_BIND_NAMES = ("P", "Q", "R", "S")

#: ``AB = [...]`` and ``eigenvector v = (1,0)`` both name their result; but
#: ``b.a = 5`` does NOT name it ``a``, and binding there would clobber the given
#: ``a`` mid-replay. Hence the prefix may only be words: letters and spaces.
_LHS_RE = re.compile(r"^[A-Za-z ]{0,20}?\b([A-Za-z][A-Za-z0-9_^']{0,3})\s*=(?!=)")
_NOT_A_NAME = {"proj", "det", "so", "then", "and", "if", "let", "sum",
               "norm", "unit", "row", "eq", "ans", "thus"}


def _lhs_symbol(step: Any) -> Optional[str]:
    """``'AB = [6 -5 ; 2 5]'`` -> ``'AB'``. The student's own name for the thing
    they just produced is a better register name than anything we invent."""
    for text in (_get(step, "claimed_expression", ""), _get(step, "raw_text", "")):
        m = _LHS_RE.match(str(text or ""))
        if m and m.group(1).lower() not in _NOT_A_NAME:
            return m.group(1)
    expr = str(_get(step, "claimed_expression", "") or "").strip()
    if expr and re.fullmatch(r"[A-Za-z][A-Za-z0-9_^']{0,3}", expr) \
            and expr.lower() not in _NOT_A_NAME:
        return expr
    return None


# --------------------------------------------------------------------------
# Reading the student's arithmetic out of what they wrote
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?")
_DOT_EXPR_RE = re.compile(
    r"([A-Za-z]\w*)\s*(?:·|⋅|\bdot\b|\.)\s*([A-Za-z]\w*)", re.I)
_PROJ_EXPR_RE = re.compile(r"\bproj", re.I)
_NORM_EXPR_RE = re.compile(r"(/\s*\|\||\|\|[^|]{1,12}\|\|\s*\^?\s*\(?\s*-\s*1|"
                           r"\bunit\b|\bnormali[sz]e)", re.I)
_SCALE_TEXT_RE = re.compile(
    r"(-?\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\s*\*?\s*(?:\(\s*|)([A-Za-z]\w*)\b")


def _num(text: Any) -> Optional[float]:
    """``'5'``, ``'-1/10'``, ``'2.5'`` -> a float. Never raises."""
    if isinstance(text, (int, float)):
        return _finite(text)
    s = str(text or "").strip().replace(" ", "")
    if not s:
        return None
    try:
        if "/" in s:
            return _finite(float(Fraction(s)))
        return _finite(float(s))
    except (ValueError, ZeroDivisionError):
        return None


def _scaled(k: float, v: list[float]) -> list[float]:
    return [k * c for c in v]


def _close(a: Iterable[float], b: Iterable[float], tol: float = 1e-6) -> bool:
    a, b = list(a), list(b)
    if len(a) != len(b):
        return False
    scale = max(1.0, max((abs(x) for x in a + b), default=1.0))
    return all(abs(x - y) <= tol * scale for x, y in zip(a, b))


def _source_symbols(step: Any) -> list[str]:
    op = _get(step, "op_args")
    syms = _get(op, "source_symbols", []) or []
    return [str(s) for s in syms if s]


def _op_scalar(step: Any) -> Optional[str]:
    op = _get(step, "op_args")
    s = _get(op, "scalar")
    return str(s) if s is not None else None


def _op_rows(step: Any) -> list[int]:
    op = _get(step, "op_args")
    rows = _get(op, "rows", []) or []
    out = []
    for r in rows:
        try:
            out.append(int(r))
        except (TypeError, ValueError):
            pass
    return out


def _resolve(env: Env, syms: Iterable[str], kind: str) -> list[Reg]:
    """Named symbols that are in scope *and* of the right kind, in order."""
    out = []
    for s in syms:
        reg = env.get(s)
        if reg is not None and reg.kind == kind and reg not in out:
            out.append(reg)
    return out


def _pick_vectors(env: Env, step: Any, want: int = 2) -> list[Reg]:
    """The vector registers this step is talking about.

    Named source symbols first (that is the student's own attribution); then the
    symbols appearing in the written line; then, as a last resort, the most
    recently bound vectors, which is what a student means by "the two vectors"
    when they did not name them.
    """
    declared = _source_symbols(step)
    named = _resolve(env, declared, "vector")
    if len(named) >= want:
        return named[:want]
    if declared and not named:
        return []          # they named their operands and we do not have them
    text = f"{_get(step, 'claimed_expression', '')} {_get(step, 'raw_text', '')}"
    for tok in re.findall(r"[A-Za-z]\w*", text):
        reg = env.get(tok)
        if reg is not None and reg.kind == "vector" and reg not in named:
            named.append(reg)
        if len(named) >= want:
            return named[:want]
    for reg in reversed(env.of_kind("vector")):
        if reg not in named:
            named.append(reg)
        if len(named) >= want:
            break
    return named[:want]


def _written_terms(raw: str) -> Optional[list[str]]:
    """``'u . v = (3)(2) + (4)(1) = 10'`` -> ``['(3)(2)', '(4)(1)']``.

    The student's own products, in their own notation, lifted verbatim. Falls
    back to None so the caller can synthesise them from the numbers.
    """
    s = re.sub(r"\s+", " ", str(raw or ""))
    parts = [p.strip() for p in s.split("=")]
    for part in parts:
        if "+" not in part and "-" not in part[1:]:
            continue
        chunks = [c.strip() for c in re.split(r"(?<![(*/^-])\+", part) if c.strip()]
        if len(chunks) < 2:
            continue
        if all(_NUM_RE.search(c) and len(c) <= 12 and not re.search(r"[A-Za-z]", c)
               for c in chunks):
            return chunks
    return None


def _infer_scale(env: Env, step: Any, result: Optional[list[float]]):
    """Is this line "a scalar times a vector"? -> (k, k_symbol, v_reg) or None.

    Checked *numerically against the student's own claim* wherever possible: if
    k*v really is the vector they wrote, the classification is not a guess.
    """
    text = f"{_get(step, 'claimed_expression', '')} {_get(step, 'raw_text', '')}"
    declared = _source_symbols(step)
    vec_regs = _resolve(env, declared, "vector")
    if not vec_regs:
        if declared:
            return None    # see _pick_vectors: no substituting for a named symbol
        vec_regs = env.of_kind("vector")

    # Candidate multipliers, most trustworthy first.
    cands: list[tuple[float, Optional[str]]] = []
    k_op = _num(_op_scalar(step))
    if k_op is not None:
        cands.append((k_op, None))
    for reg in env.of_kind("scalar"):
        k = _finite(reg.value)
        if k is not None:
            cands.append((k, reg.symbol))
    for m in _SCALE_TEXT_RE.finditer(text):
        k = _num(m.group(1))
        if k is not None:
            cands.append((k, None))
    for m in _NUM_RE.finditer(text):
        k = _num(m.group(0))
        if k is not None:
            cands.append((k, None))

    # Prefer a scalar that a previous step BOUND: the 5 in "5(1,2)" is the 5
    # from "b.a = 5", and saying so is the difference between replaying the
    # student's reasoning and re-deriving it.
    def rank(item: tuple[float, Optional[str]]) -> tuple[int, int]:
        k, sym = item
        return (0 if sym else 1, 0 if abs(k) > 1e-9 else 1)

    if result is not None:
        for k, sym in sorted(cands, key=rank):
            for reg in vec_regs:
                if _close(_scaled(k, reg.value), result):
                    match = sym
                    if match is None:
                        for s_reg in env.of_kind("scalar"):
                            if _finite(s_reg.value) is not None and \
                                    abs(float(s_reg.value) - k) < 1e-9:
                                match = s_reg.symbol
                                break
                    return k, match, reg
    # No numeric confirmation: accept an explicitly labelled scalar_multiply.
    if k_op is not None and vec_regs:
        return k_op, None, vec_regs[0]
    return None


# --------------------------------------------------------------------------
# Classification (STEP_REPLAY.md §2)
# --------------------------------------------------------------------------

#: Operations that are honest arithmetic but have no motion of their own.
SCALARISH_OPS = frozenset({
    "determinant_expand", "cofactor", "char_poly", "solve_char_poly",
    "back_substitute", "state_answer", "transpose", "inverse_formula",
    "augment", "eigenvector_solve",
})


@dataclass
class Classified:
    kind: str
    args: dict[str, Any] = field(default_factory=dict)      # role -> symbol
    extras: dict[str, Any] = field(default_factory=dict)    # kind-specific
    why: str = ""
    bind_kind: Optional[str] = None                         # vector|matrix|scalar


def _classify(step: Any, env: Env, ctx: dict[str, Any]) -> Classified:
    """One extracted step -> one step kind, from what the student wrote.

    Never raises and never returns an unresolvable symbol: anything it cannot
    stand behind comes back as ``literal``, which the ledger shows verbatim.
    """
    op = str(_get(step, "claimed_operation", "unknown") or "unknown")
    expr = str(_get(step, "claimed_expression", "") or "")
    raw = str(_get(step, "raw_text", "") or "")
    text = f"{expr} {raw}"
    value = _get(step, "value")
    vkind = _obj_kind(value)

    vec = as_vector(value) if vkind in ("vector", "unknown") else None
    mat = as_matrix(value) if vkind in ("matrix", "augmented", "unknown") else None
    sca = as_scalar(value) if vkind in ("scalar", "unknown") else None

    if _get(step, "crossed_out", False):
        return Classified("literal", why="crossed out by the student")
    if _get(step, "parse_ok", True) is False:
        return Classified("literal", why="the line did not parse")

    # -- 2.1 / 2.2  a copied given ---------------------------------------
    if op == "copy_given":
        syms = _source_symbols(step)
        if mat is not None:
            sym = next((s for s in syms if s), None) or "M"
            return Classified("define_matrix", extras={"rows": mat, "label": sym},
                              why="copy_given with a matrix value",
                              bind_kind="matrix")
        if vec is not None:
            sym = next((s for s in syms if s), None) or "v"
            return Classified("define_vector", extras={"value": vec, "label": sym},
                              why="copy_given with a vector value",
                              bind_kind="vector")
        return Classified("literal", why="copy_given with nothing drawable")

    # -- 2.8  row operations ---------------------------------------------
    if op in ("row_swap", "row_scale", "row_add_multiple"):
        rows = _op_rows(step)
        scalar = _op_scalar(step)
        label = {"row_swap": "swap", "row_scale": "scale",
                 "row_add_multiple": "combine"}[op]
        op_label = normalise_expr(raw, 18) or label
        if rows:
            op_label = _row_label(op, rows, scalar) or op_label
        return Classified(
            "row_op",
            extras={"rows": rows, "scalar": scalar, "op": op,
                    "op_label": op_label,
                    "result_rows": mat if mat is not None else None},
            why=f"claimed_operation={op!r}",
        )

    # -- 2.9  normalize ---------------------------------------------------
    if op == "normalize" or (vec is not None and _NORM_EXPR_RE.search(text)):
        srcs = _pick_vectors(env, step, 1)
        if vec is not None and srcs:
            return Classified(
                "normalize", args={"v": srcs[0].symbol},
                extras={"divisor_display": _divisor_display(raw, srcs[0]),
                        "result": vec},
                why="claimed_operation='normalize'" if op == "normalize"
                    else "the line is written v/||v||",
                bind_kind="vector")

    # -- 2.4 / 2.10  a projection the student assembled, or wrote in one line
    scale = _infer_scale(env, step, vec) if vec is not None else None
    proj_written = op == "project" or bool(_PROJ_EXPR_RE.search(text))

    if op == "scalar_multiply" or (scale is not None and
                                   (op in ("unknown", "state_answer", "multiply")
                                    or proj_written)):
        if scale is not None:
            k, k_sym, v_reg = scale
            args = {"v": v_reg.symbol}
            if k_sym:
                args["k"] = k_sym
            why = ("the scalar %s a previous step bound, times %s -- checked: "
                   "%s x %s = %s" % (k_sym or fmt_num(k), v_reg.symbol,
                                     fmt_num(k), vec_display(v_reg.value),
                                     vec_display(vec or [])))
            if not k_sym:
                why = "scalar %s times %s, checked against the written result" % (
                    fmt_num(k), v_reg.symbol)
            return Classified(
                "scale_vector", args=args,
                extras={"k": k, "k_display": _k_display(step, k, k_sym),
                        "result": vec},
                why=why, bind_kind="vector")

    if proj_written and vec is not None:
        srcs = _pick_vectors(env, step, 2)
        if len(srcs) >= 2:
            u, v = _projection_roles(step, srcs, expr, raw)
            return Classified("project", args={"u": u.symbol, "v": v.symbol},
                              extras={"result": vec},
                              why="claimed_operation='project'" if op == "project"
                                  else "the line names proj_v(u)",
                              bind_kind="vector")

    # -- 2.3  dot product -------------------------------------------------
    if op == "dot" or (sca is not None and _DOT_EXPR_RE.search(expr or raw)):
        srcs = _pick_vectors(env, step, 2)
        if sca is not None and len(srcs) >= 2:
            u, v = srcs[0], srcs[1]
            terms = _written_terms(raw) or [
                "%s(%s)" % (fmt_num(a), fmt_num(b))
                for a, b in zip(u.value, v.value)]
            return Classified(
                "dot_product", args={"u": u.symbol, "v": v.symbol},
                extras={"result": sca, "terms": terms,
                        "result_display": _exact_scalar_display(value)
                                          or fmt_num(sca)},
                why="claimed_operation='dot'" if op == "dot"
                    else "the line is written u . v with a scalar value",
                bind_kind="scalar")

    # -- 2.5  vector addition ---------------------------------------------
    if op in ("add", "subtract") and vec is not None:
        srcs = _pick_vectors(env, step, 2)
        if len(srcs) >= 2:
            return Classified(
                "add_vectors", args={"u": srcs[0].symbol, "v": srcs[1].symbol},
                extras={"sign": "+" if op == "add" else "-", "result": vec},
                why=f"claimed_operation={op!r} with two vectors in scope",
                bind_kind="vector")

    # -- 2.6 / 2.7  multiplication ----------------------------------------
    if op == "multiply" or (mat is not None and re.search(r"[A-Z]\s*[A-Z]", expr)):
        named = _source_symbols(step)
        mats = _resolve(env, named, "matrix") or env.of_kind("matrix")
        vecs = _resolve(env, named, "vector")
        if vec is not None and mats and vecs:
            return Classified(
                "matrix_apply", args={"M": mats[0].symbol, "v": vecs[0].symbol},
                extras={"result": vec},
                why="a matrix register times a vector register",
                bind_kind="vector")
        if mat is not None and len(mats) >= 2:
            order = _product_order(expr or raw, mats)
            return Classified(
                "matrix_product",
                args={"factors": [r.symbol for r in mats[:2]]},
                extras={"factors": [r.symbol for r in mats[:2]],
                        "order": order, "result": mat},
                why="claimed_operation='multiply' with two matrix registers",
                bind_kind="matrix")
        if mat is not None:
            return Classified("define_matrix",
                              extras={"rows": mat, "label": _lhs_symbol(step) or "M"},
                              why="a matrix result with no two factors in scope",
                              bind_kind="matrix")

    # -- 2.11  ledger-only lines ------------------------------------------
    if sca is not None:
        return Classified(
            "scalar_value",
            extras={"display": normalise_expr(raw or expr),
                    "result": sca,
                    "result_display": _exact_scalar_display(value) or fmt_num(sca),
                    "area_of": _det_symbol(step, env) if op in
                               ("determinant_expand", "cofactor") else None},
            why=f"claimed_operation={op!r} with a scalar value and no vector args",
            bind_kind="scalar")

    # A vector claim we could not attribute to an operation is still a vector
    # the student wrote down, and drawing it is honest.
    if vec is not None and op in ("state_answer", "unknown", "eigenvector_solve",
                                  "back_substitute", "cross"):
        same = next((r for r in env.of_kind("vector") if _close(r.value, vec)), None)
        if same is not None and op == "state_answer":
            return Classified(
                "scalar_value",
                extras={"display": normalise_expr(raw or expr), "restates": same.symbol},
                why=f"state_answer restating {same.symbol}; no new geometry")
        return Classified(
            "define_vector",
            extras={"value": vec, "label": _lhs_symbol(step) or "claim",
                    "claimed": True},
            why=f"claimed_operation={op!r} with a vector value",
            bind_kind="vector")

    if mat is not None:
        return Classified("define_matrix",
                          extras={"rows": mat, "label": _lhs_symbol(step) or "M",
                                  "claimed": True},
                          why=f"claimed_operation={op!r} with a matrix value",
                          bind_kind="matrix")

    # A determinant, a characteristic polynomial, a back-substitution: real
    # arithmetic with no geometry of its own. It says so rather than inventing
    # a picture (STEP_REPLAY.md §2.11, ERROR_TAXONOMY.md §3).
    if op in SCALARISH_OPS:
        return Classified(
            "scalar_value",
            extras={"display": normalise_expr(raw or expr)},
            why=f"claimed_operation={op!r} -- an arithmetic line with no "
                f"geometry of its own")

    return Classified("literal", why=f"claimed_operation={op!r} with no drawable value")


def _row_label(op: str, rows: list[int], scalar: Optional[str]) -> Optional[str]:
    if op == "row_swap" and len(rows) >= 2:
        return f"R{rows[0]} <-> R{rows[1]}"
    if op == "row_scale" and rows:
        return f"R{rows[0]} -> {scalar or 'k'} R{rows[0]}"
    if op == "row_add_multiple" and len(rows) >= 2:
        k = (scalar or "k").strip()
        sign = "-" if k.startswith("-") else "+"
        return f"R{rows[0]} {sign} {k.lstrip('+-')} R{rows[1]}"
    return None


def _divisor_display(raw: str, reg: Reg) -> str:
    m = re.search(r"/\s*(sqrt\s*\(?\s*\d+\s*\)?|\d+(?:\.\d+)?)", raw or "")
    if m:
        return m.group(1).replace(" ", "")
    n = math.sqrt(sum(c * c for c in reg.value))
    return fmt_num(n)


def _k_display(step: Any, k: float, k_sym: Optional[str]) -> str:
    written = _op_scalar(step)
    if written and _num(written) is not None and abs((_num(written) or 0) - k) < 1e-9:
        return str(written).strip()
    return fmt_num(k)


def _projection_roles(step: Any, srcs: list[Reg], expr: str, raw: str):
    """``proj_v(u)`` -> (u = the thing being projected, v = the thing onto)."""
    m = re.search(r"proj[_ ]*\{?([A-Za-z]\w*)\}?\s*\(\s*([A-Za-z]\w*)\s*\)",
                  f"{expr} {raw}", re.I)
    if m:
        onto, of = m.group(1), m.group(2)
        u = next((r for r in srcs if r.symbol == of), None)
        v = next((r for r in srcs if r.symbol == onto), None)
        if u is not None and v is not None:
            return u, v
    return srcs[0], srcs[1]


def _product_order(text: str, mats: list[Reg]) -> list[str]:
    """The order the factors actually compose in: right factor acts first."""
    syms = [r.symbol for r in mats[:2]]
    written = re.findall(r"[A-Za-z]\w*", text or "")
    seq = [s for s in written if s in syms]
    seen: list[str] = []
    for s in seq:
        if s not in seen:
            seen.append(s)
    if len(seen) == 2:
        return [seen[1], seen[0]]        # right factor first
    return [syms[1], syms[0]]


def _det_symbol(step: Any, env: Env) -> Optional[str]:
    for s in _source_symbols(step):
        reg = env.get(s)
        if reg is not None and reg.kind == "matrix":
            return reg.symbol
    mats = env.of_kind("matrix")
    return mats[-1].symbol if mats else None


# --------------------------------------------------------------------------
# Invariants and divergence (STEP_REPLAY.md §6)
# --------------------------------------------------------------------------

def _invariant_and_divergence(kind: str, args: dict, extras: dict, env: Env,
                              ctx: dict) -> tuple[Optional[dict], Optional[dict]]:
    """The region the result had to land in, and how the claim misses it.

    Every ``*_of`` field names a SYMBOL already in scope -- never a literal and
    never a correct value (validation case 5). If no such symbol exists the
    invariant is dropped rather than faked.
    """
    def sym(name: Optional[str]) -> Optional[str]:
        return name if name and name in env else None

    if kind == "project":
        u, v = sym(args.get("u")), sym(args.get("v"))
        if u:
            return ({"kind": "disc", "radius_of": u,
                     "caption": f"every shadow of {u} lands in here"},
                    {"absurdity": "length", "compare_to": u,
                     "residual_from": u, "right_angle_at": "result"})
        if v:
            return ({"kind": "line", "along_of": v,
                     "caption": f"the answer has to sit on {v}'s line"}, None)
        return None, None

    if kind == "scale_vector":
        v = sym(args.get("v"))
        obj = sym(ctx.get("projected_of"))
        if obj:
            # A projection assembled as dot -> scale inherits the projection's
            # invariant: the shadow of `obj` cannot be longer than `obj`.
            return ({"kind": "disc", "radius_of": obj,
                     "caption": f"every shadow of {obj} lands in here"},
                    {"absurdity": "length", "compare_to": obj,
                     "residual_from": obj, "right_angle_at": "result"})
        if v:
            return ({"kind": "line", "along_of": v,
                     "caption": f"scaling keeps you on {v}'s line"},
                    {"absurdity": "length", "compare_to": v,
                     "residual_from": None, "right_angle_at": None})
        return None, None

    if kind == "normalize":
        return ({"kind": "unit_circle", "caption": "a unit vector ends here"},
                {"absurdity": "none", "compare_to": sym(args.get("v")),
                 "residual_from": None, "right_angle_at": None})

    if kind == "dot_product":
        u, v = sym(args.get("u")), sym(args.get("v"))
        if u and v:
            return ({"kind": "band", "cap_of": u, "against_of": v,
                     "caption": f"|{u}||{v}| is as far as any dot product reaches"},
                    {"absurdity": "length", "compare_to": u,
                     "residual_from": None, "right_angle_at": None})
        return None, None

    if kind == "add_vectors":
        u, v = sym(args.get("u")), sym(args.get("v"))
        if u and v:
            return ({"kind": "parallelogram", "from_of": u, "to_of": v,
                     "caption": "the sum is the far corner"},
                    {"absurdity": "offcorner", "compare_to": u,
                     "residual_from": None, "right_angle_at": None})
        return None, None

    if kind == "matrix_apply":
        M, v = sym(args.get("M")), sym(args.get("v"))
        if M and v:
            return ({"kind": "point", "lattice_of": M, "carried_of": v,
                     "caption": f"{v} rides the grid {M} makes"},
                    {"absurdity": "offlattice", "compare_to": v,
                     "residual_from": None, "right_angle_at": None})
        return None, None

    if kind == "matrix_product":
        factors = [s for s in (extras.get("factors") or []) if s in env]
        if len(factors) >= 2:
            return ({"kind": "composite", "left_of": factors[0],
                     "right_of": factors[1],
                     "caption": "apply them one after the other"},
                    {"absurdity": "none", "compare_to": None,
                     "residual_from": None, "right_angle_at": None})
        return None, None

    if kind == "row_op":
        pivot = sym(ctx.get("system_of"))
        if pivot:
            return ({"kind": "point", "pivot_of": pivot,
                     "caption": "a legal row operation turns about this point"},
                    {"absurdity": "offpivot", "compare_to": pivot,
                     "residual_from": None, "right_angle_at": None})
        return None, None

    if kind in ("define_vector", "define_matrix"):
        # The ONE case that may draw a second object: a mis-copied given. The
        # problem statement is public, so holding a ghost at the printed value
        # discloses nothing. A DERIVED claim gets no ghost -- there is nothing
        # public to compare it with, and inventing one would be the leak.
        label = extras.get("label")
        if not extras.get("claimed") and label in (ctx.get("given_symbols") or ()):
            return None, {"absurdity": "none", "compare_to": None,
                          "residual_from": None, "right_angle_at": None,
                          "ghost_given": label}
        return None, None

    return None, None


# --------------------------------------------------------------------------
# Framing (STEP_REPLAY.md §5)
# --------------------------------------------------------------------------

def frame_for(points: list[Iterable[float]], box=(BOX_W, BOX_H),
              box_center=BOX_CENTER, pad: float = PAD,
              margin: float = MARGIN) -> tuple[float, list[float]]:
    """Points -> (scene units per math unit, the plane's origin in scene units).

    Two things plain ``fit_unit`` does not do, both necessary: the ORIGIN is in
    the bounding box (every arrow starts there) and the origin is anchored
    OFF-CENTRE, so a first-quadrant story does not waste three quadrants.
    """
    pts = [[0.0, 0.0]] + [[float(p[0]), float(p[1])] for p in points if p is not None]
    lo = [min(p[i] for p in pts) - pad for i in (0, 1)]
    hi = [max(p[i] for p in pts) + pad for i in (0, 1)]
    span = [max(hi[i] - lo[i], 1e-6) for i in (0, 1)]
    unit = min((box[0] - 2 * margin) / span[0], (box[1] - 2 * margin) / span[1])
    mid = [(lo[i] + hi[i]) / 2 for i in (0, 1)]
    origin = [box_center[0] - unit * mid[0], box_center[1] - unit * mid[1], 0.0]
    return unit, origin


def _matrix_points(M: list[list[float]]) -> list[list[float]]:
    """A 2x2 map's columns -- the images of the basis, which is what has to fit."""
    if len(M) >= 2 and len(M[0]) >= 2:
        return [[M[0][0], M[1][0]], [M[0][1], M[1][1]]]
    return []


def _origin_at(unit: float, points: list[list[float]], pad: float = PAD) -> list[float]:
    """The plane origin that puts ``points`` in the box at a GIVEN unit.

    Needed because the opening unit gets clamped to ``zoom_max`` and the origin
    has to follow the clamp, or the opening frame is centred on nothing.
    """
    pts = [[0.0, 0.0]] + [[float(p[0]), float(p[1])] for p in points if p is not None]
    mid = [(min(p[i] for p in pts) - pad + max(p[i] for p in pts) + pad) / 2
           for i in (0, 1)]
    return [BOX_CENTER[0] - unit * mid[0], BOX_CENTER[1] - unit * mid[1], 0.0]


def _solve_canvas(opening: list[list[float]], every: list[list[float]],
                  grow: bool) -> dict:
    u_end, org_end = frame_for(every)
    u_start, _ = frame_for(opening or every)
    # Without `grow`, a story that lives inside one math unit of the origin must
    # not blow the unit up: below ~4 cells across the box the lattice stops
    # reading as a grid at all (STEP_REPLAY.md §5.3), so BOX_W/unit >= 4.75.
    cap = GROW_MAX_UNIT if grow else MAX_UNIT
    u_end = min(u_end, cap)
    u_start = min(u_start, ZOOM_MAX * u_end, cap)
    org_end = _origin_at(u_end, every)
    org_start = _origin_at(u_start, opening or every)
    cells = BOX_W / u_end if u_end > 0 else 0.0
    grid_step = 1 if cells <= 24 else 2
    radius = int(min(26, math.ceil((max(BOX_W, BOX_H) / 2 + 1.6) / max(u_end, 1e-6))))
    return {
        "box": [BOX_W, BOX_H],
        "box_center": list(BOX_CENTER),
        "ledger_x": LEDGER_X,
        "zoom_max": ZOOM_MAX,
        "pad": PAD,
        "margin": MARGIN,
        "grow": bool(grow),
        "unit_start": round(u_start, 4),
        "unit_end": round(u_end, 4),
        "origin_start": [round(c, 4) for c in org_start],
        "origin_end": [round(c, 4) for c in org_end],
        "zoom_ratio": round(u_start / u_end, 4) if u_end > 0 else 1.0,
        "grid_step": grid_step,
        "radius": max(radius, 4),
        "cells_end": round(cells, 2),
    }


# --------------------------------------------------------------------------
# Timing (STEP_REPLAY.md §4)
# --------------------------------------------------------------------------

def _base_run_time(kind: str, extras: dict) -> float:
    if kind == "scale_vector":
        k = abs(float(extras.get("k") or 1.0))
        return round(0.28 * min(k, 5.0) + 1.2, 2)
    if kind == "matrix_product":
        return round(2.0 * max(1, len(extras.get("factors") or [])) + 0.6, 2)
    return BASE_RUN_TIME.get(kind, 1.0)


def _fit_budget(steps: list[dict], has_wrong: bool, budget: float = BUDGET) -> None:
    """Scale the non-first_wrong beats down to fit. The wrong step's beat is
    never compressed -- it is the only beat the video exists for."""
    fixed = FIXED_TITLE + FIXED_HINT + FIXED_HOLD
    if has_wrong:
        fixed += FIXED_INVARIANT + FIXED_DIVERGENCE
    wrong_rt = sum(s["run_time"] for s in steps if s.get("first_wrong"))
    rest = [s for s in steps if not s.get("first_wrong")]
    rest_rt = sum(s["run_time"] for s in rest)
    avail = budget - fixed - wrong_rt
    if rest_rt <= avail or rest_rt <= 0:
        return
    scale = max(avail, 0.0) / rest_rt
    for s in rest:
        s["run_time"] = round(max(RUN_TIME_FLOOR, s["run_time"] * scale), 2)

    # Still over at the floor: drop the ledger-only lines to instant.
    if sum(s["run_time"] for s in rest) <= avail:
        return
    for s in rest:
        if s["kind"] in LEDGER_KINDS:
            s["run_time"] = 0.0
    if sum(s["run_time"] for s in rest) <= avail:
        return

    # Still over: elide the middle of a long run of ok steps behind one line.
    live = [s for s in rest if s["run_time"] > 0 and s.get("status") == "ok"]
    if len(live) > 4:
        for s in live[2:-1]:
            s["run_time"] = 0.0
            s["elided"] = True


# --------------------------------------------------------------------------
# Titles and hints (positional only -- never a value)
# --------------------------------------------------------------------------

_HINTS = {
    "scale_vector": "a shadow can't be longer than the thing casting it",
    "project": "a shadow can't be longer than the thing casting it",
    "normalize": "check where your arrow stops against the unit circle",
    "dot_product": "check the pieces against the total",
    "add_vectors": "check your arrow against the corner of the parallelogram",
    "matrix_apply": "watch where the grid actually carries that point",
    "matrix_product": "watch which map gets applied first",
    "row_op": "watch the crossing point while the line sweeps",
    "define_vector": "check this against the vector printed in the question",
    "define_matrix": "check this against the matrix printed in the question",
    "define_vector.claimed": "watch whether this arrow stays on its own line",
    "define_matrix.claimed": "watch what this map does to the grid",
    "scalar_value": "look again at the line the caret marks",
    "literal": "look again at the line the caret marks",
}
DEFAULT_HINT = "watch the step the caret marks"


def _default_hint(steps: list[dict]) -> str:
    for s in steps:
        if not s.get("first_wrong"):
            continue
        key = s["kind"] + (".claimed" if s.get("claimed") else "")
        return _HINTS.get(key) or _HINTS.get(s["kind"], DEFAULT_HINT)
    return DEFAULT_HINT


# --------------------------------------------------------------------------
# The compiler
# --------------------------------------------------------------------------

@dataclass
class CompileResult:
    params: dict
    ok: bool
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    motion_steps: int = 0


def _status_for(step: Any, index: int, verdict: Any) -> tuple[str, bool]:
    """(status, first_wrong) for one step, matched by id then by index."""
    if verdict is None:
        return ("crossed_out" if _get(step, "crossed_out", False) else "unchecked"), False
    results = _get(verdict, "step_results", None)
    if results is None:
        results = _get(verdict, "steps", []) or []
    sid = _get(step, "id", None)
    found = None
    for r in results:
        rid = _get(r, "step_id", None) or _get(r, "id", None)
        if sid is not None and rid == sid:
            found = r
            break
    if found is None:
        for r in results:
            if _get(r, "index", -1) == index:
                found = r
                break
    raw_status = str(_get(found, "status", "UNCHECKED") or "UNCHECKED") if found else "UNCHECKED"
    status = STATUS_MAP.get(raw_status, "unchecked")
    if _get(step, "crossed_out", False):
        status = "crossed_out"
    fwi = _get(verdict, "first_error_index", None)
    first_wrong = False
    if fwi is not None and found is not None:
        first_wrong = _get(found, "index", -1) == fwi
    elif fwi is not None:
        first_wrong = index == fwi
    if first_wrong and status not in ("wrong",):
        status = "wrong"
    return status, bool(first_wrong)


def _seed_givens(ext: Any, env: Env) -> dict:
    """``problem.givens`` -> the opening register file and the ``givens`` block."""
    out: dict[str, dict] = {}
    problem = _get(ext, "problem")
    for g in (_get(problem, "givens", []) or []):
        sym = str(_get(g, "symbol", "") or "").strip()
        obj = _get(g, "object")
        if not sym or sym in env:
            continue
        vec, mat, sca = as_vector(obj), as_matrix(obj), as_scalar(obj)
        kind = _obj_kind(obj)
        if mat is not None and kind in ("matrix", "augmented"):
            env.put(Reg(sym, "matrix", mat, mat_display(mat), "correct", sym))
            out[sym] = {"kind": "matrix", "value": mat, "display": mat_display(mat)}
        elif vec is not None and kind in ("vector", "unknown"):
            color = env.next_vector_color()
            env.put(Reg(sym, "vector", vec, vec_display(vec), color, sym))
            out[sym] = {"kind": "vector", "value": vec,
                        "display": vec_display(vec), "color": color}
        elif sca is not None:
            env.put(Reg(sym, "scalar", sca, fmt_num(sca), "correct", sym))
            out[sym] = {"kind": "scalar", "value": sca, "display": fmt_num(sca)}
    return out


def _context(ext: Any) -> dict:
    problem = _get(ext, "problem", {})
    topic = str(_get(problem, "topic", "other") or "other")
    asks = str(_get(problem, "asks_for", "") or "")
    statement = str(_get(problem, "statement", "") or "")
    projection = (topic == "projection"
                  or bool(_PROJ_EXPR_RE.search(f"{asks} {statement}")))
    return {"topic": topic, "projection": projection, "asks_for": asks}


def compile_step_replay(ext: Any, verdict: Any = None, *, title: Optional[str] = None,
                        hint: Optional[str] = None, student_label: str = "YOUR WORK",
                        budget: float = BUDGET) -> dict:
    """The params block ``StepReplay`` consumes. Never raises."""
    return compile_replay(ext, verdict, title=title, hint=hint,
                          student_label=student_label, budget=budget).params


def compile_replay(ext: Any, verdict: Any = None, *, title: Optional[str] = None,
                   hint: Optional[str] = None, student_label: str = "YOUR WORK",
                   budget: float = BUDGET) -> CompileResult:
    """Full result: params, the planner's gate, and why."""
    warnings: list[str] = []
    env = Env()
    givens = _seed_givens(ext, env)

    # verify.py sorts by (page, reading_order) before indexing its results, so
    # the same order here makes `index` line up when a step id does not match.
    raw_steps = sorted(
        _get(ext, "steps", []) or [],
        key=lambda st: (int(_get(st, "page", 1) or 1),
                        int(_get(st, "reading_order", 0) or 0)),
    )

    ctx = _context(ext)
    ctx["given_symbols"] = tuple(givens)
    ctx["system_of"] = next((r.symbol for r in env.of_kind("matrix")), None)

    steps: list[dict] = []
    motion = 0
    leaky: set[str] = set()

    for index, step in enumerate(raw_steps):
        cls = _classify(step, env, ctx)
        status, first_wrong = _status_for(step, index, verdict)

        # Never emit a symbol that is not already in scope (validation case 3).
        bad = [k for k, v in cls.args.items()
               if isinstance(v, str) and v not in env]
        if bad:
            warnings.append(
                f"{_get(step, 'id', index)}: {cls.kind} dropped to literal "
                f"(unresolved {', '.join(sorted(bad))})")
            cls = Classified("literal", why="an operand it names is not in scope")

        entry: dict[str, Any] = {
            "id": str(_get(step, "id", f"s{index + 1}")),
            "student_label": _get(step, "student_label", None) or "",
            "kind": cls.kind,
            "expr": normalise_expr(_get(step, "raw_text", "")
                                   or _get(step, "claimed_expression", "")),
            "raw_text": str(_get(step, "raw_text", "") or ""),
            "args": dict(cls.args),
            "status": status,
            "first_wrong": bool(first_wrong),
            "why": cls.why,
        }
        entry.update(cls.extras)

        # -- the claimed result, as numbers -------------------------------
        result = _result_block(step, cls)
        entry["result"] = result

        # -- operands, fully resolved to numbers --------------------------
        operands = {}
        for role, sym in cls.args.items():
            if isinstance(sym, str):
                reg = env.get(sym)
                if reg is not None:
                    operands[role] = {"symbol": reg.symbol, "kind": reg.kind,
                                      "value": reg.value, "display": reg.display}
        if operands:
            entry["operands"] = operands

        # -- write the register this step binds ---------------------------
        bind = _bind(env, step, cls, result)
        if bind:
            entry["bind"] = bind

        entry["run_time"] = _base_run_time(cls.kind, cls.extras)
        steps.append(entry)
        if cls.kind in MOTION_KINDS:
            motion += 1
        if cls.kind in LEAKY_KINDS:
            leaky.add(cls.kind)

        # A projection assembled as dot -> scale: remember what is being
        # projected, so the scale step can inherit the projection's invariant.
        if cls.kind == "dot_product" and ctx.get("projection"):
            ctx["dot_pair"] = [cls.args.get("u"), cls.args.get("v")]

    # -- leak guard -------------------------------------------------------
    leak_guard = sorted(leaky | ({"project"} if ctx["projection"] else set()))

    # -- the one wrong step gets its invariant and its divergence ---------
    _mark_first_wrong(steps, env, ctx, warnings)

    # -- framing ----------------------------------------------------------
    grow = any(s["kind"] == "normalize" for s in steps)
    opening = [g["value"] for g in givens.values() if g["kind"] == "vector"]
    for g in givens.values():
        if g["kind"] == "matrix":
            opening.extend(_matrix_points(g["value"]))
    if not opening:
        opening = [[1.0, 0.0], [0.0, 1.0]]
    every = list(opening)
    for s in steps:
        r = s.get("result") or {}
        if r.get("kind") == "vector":
            every.append(r["value"])
        elif r.get("kind") == "matrix":
            every.extend(_matrix_points(r["value"]))
    canvas = _solve_canvas(opening, every, grow)

    has_wrong = any(s.get("first_wrong") for s in steps)
    _fit_budget(steps, has_wrong, budget)

    params = {
        "title": title or "Your steps, replayed",
        "hint": hint or _default_hint(steps),
        "student_label": student_label,
        "canvas": canvas,
        "givens": givens,
        "leak_guard": leak_guard,
        "steps": steps,
    }

    ok, reason = viable(params)
    return CompileResult(params=params, ok=ok, reason=reason,
                         warnings=warnings, motion_steps=motion)


def _result_block(step: Any, cls: Classified) -> dict:
    """The student's claim, verbatim, as numbers plus a display string."""
    value = _get(step, "value")
    if "result" in cls.extras and cls.extras["result"] is not None:
        r = cls.extras["result"]
        if isinstance(r, (int, float)):
            return {"kind": "scalar", "value": float(r),
                    "display": cls.extras.get("result_display")
                               or _exact_scalar_display(value) or fmt_num(r)}
        if isinstance(r, list) and r and isinstance(r[0], (list, tuple)):
            return {"kind": "matrix", "value": r, "display": mat_display(r)}
        if isinstance(r, list):
            return {"kind": "vector", "value": list(r), "display": vec_display(r)}
    if cls.kind == "define_vector" and cls.extras.get("value") is not None:
        v = cls.extras["value"]
        return {"kind": "vector", "value": v, "display": vec_display(v)}
    if cls.kind in ("define_matrix", "matrix_product") and cls.extras.get("rows"):
        M = cls.extras["rows"]
        return {"kind": "matrix", "value": M, "display": mat_display(M)}
    sca = as_scalar(value)
    if sca is not None:
        return {"kind": "scalar", "value": sca,
                "display": _exact_scalar_display(value) or fmt_num(sca)}
    # StepReplay.validate parses every step's result as a number, so a line
    # with no numeric claim of its own still needs one. The placeholder never
    # reaches the screen: these kinds are ledger-only and `display` -- the
    # student's own words -- is what gets drawn. `no_value` says so out loud.
    return {"kind": "scalar", "value": 0.0, "no_value": True,
            "display": normalise_expr(_get(step, "raw_text", ""))}


def _bind(env: Env, step: Any, cls: Classified, result: dict) -> Optional[str]:
    """Write the result into a register and return its name."""
    kind = result.get("kind")
    if kind not in ("vector", "matrix", "scalar") or cls.bind_kind is None:
        return None
    label = cls.extras.get("label")
    # A copied given writes the symbol it copies -- the student's transcription
    # REPLACES the printed value in the register file, which is what makes a
    # mis-copy show up downstream. A derived claim gets a fresh name instead.
    if cls.kind in ("define_vector", "define_matrix") and label \
            and not cls.extras.get("claimed"):
        sym = str(label)
    else:
        preferred = [_lhs_symbol(step) or ""]
        preferred += list({"scalar": _SCALAR_BIND_NAMES,
                           "vector": _VECTOR_BIND_NAMES,
                           "matrix": _MATRIX_BIND_NAMES}[kind])
        sym = env.fresh(preferred)
    color = "correct"
    if kind == "vector":
        src = cls.args.get("v") or cls.args.get("u")
        src_reg = env.get(src) if isinstance(src, str) else None
        color = src_reg.color if src_reg else env.next_vector_color()
    env.put(Reg(sym, kind, result["value"], result["display"], color, sym,
                source=str(_get(step, "id", "step"))))
    return sym


def _mark_first_wrong(steps: list[dict], env: Env, ctx: dict,
                      warnings: list[str]) -> None:
    """Attach the invariant and the divergence cues to the one wrong step.

    Everything named is a symbol already on the canvas. Nothing correct is
    computed here, because nothing correct is available here.
    """
    wrong = [s for s in steps if s.get("first_wrong")]
    if len(wrong) > 1:                          # validation case 4
        for s in wrong[1:]:
            s["first_wrong"] = False
        warnings.append("more than one first_wrong; kept the earliest")
        wrong = wrong[:1]
    for s in steps:
        s.setdefault("invariant", None)
        s.setdefault("divergence", None)
    if not wrong:
        return
    s = wrong[0]
    local = dict(ctx)
    if s["kind"] == "scale_vector" and ctx.get("projection"):
        pair = ctx.get("dot_pair") or []
        v = s["args"].get("v")
        other = next((p for p in pair if p and p != v), None)
        local["projected_of"] = other
    inv, div = _invariant_and_divergence(s["kind"], s["args"], s, env, local)
    if inv is not None and _invariant_ok(inv, env):
        s["invariant"] = inv
    elif inv is not None:
        warnings.append(f"{s['id']}: invariant dropped (a field was not a symbol)")
    s["divergence"] = div


def _invariant_ok(inv: dict, env: Env) -> bool:
    """Validation case 5: every ``*_of`` names a symbol in scope, never a
    literal. A caption is prose and is exempt; it is linted by the planner."""
    for key, val in inv.items():
        if not key.endswith("_of"):
            continue
        # A list here would be rejected downstream, and a number would be a
        # literal smuggled in as a region. Exactly one in-scope symbol.
        if not isinstance(val, str) or val not in env or _num(val) is not None:
            return False
    return True


# --------------------------------------------------------------------------
# The planner's gate (STEP_REPLAY.md §3 validation 1, 2, 7)
# --------------------------------------------------------------------------

def viable(params: dict, *, min_motion: int = 0) -> tuple[bool, str]:
    """Is this replay worth playing? ``(False, reason)`` means fall through to
    the old template ladder -- it is never an error."""
    steps = params.get("steps") or []
    if len(steps) < 2:
        return False, "fewer than two steps -- that is not a replay"
    if all(s["kind"] in LEDGER_KINDS for s in steps):
        return False, "every step is ledger-only -- there is no geometry to play"
    ratio = (params.get("canvas") or {}).get("zoom_ratio", 1.0)
    if ratio and ratio > MAX_ZOOM_RATIO:
        return False, f"zoom ratio {ratio:.1f} -- no framing holds both ends"
    motion = sum(1 for s in steps if s["kind"] in MOTION_KINDS)
    if motion < min_motion:
        return False, f"only {motion} step(s) move anything on the canvas"
    return True, ""
