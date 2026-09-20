"""sympy step verification: which step is the FIRST one that is actually wrong.

Implements docs/ERROR_TAXONOMY.md §4:

  Layer 1  - IS the step wrong? One invariant check against the ORIGINAL GIVEN DATA.
             Generic; works on errors that are nowhere in the taxonomy.
  Layer 2  - WHICH mistake was it? Signature match against the 19 entries. Buys a
             better scene and a better hint; never decides the verdict.

Non-negotiables encoded here:
  * charity (§4.7): a step is wrong only if EVERY candidate reading of it, against
    every candidate reading of the givens, is wrong;
  * "cannot parse" is never "wrong" (§4.6);
  * crossed-out work is never blamed (§4.5);
  * rounding amnesty (§4.4): 0.71 for 1/sqrt(2) is not a linear algebra mistake;
  * shape mismatches are caught HERE, so sympy never raises ShapeError inside a
    render job (LA03, a P0 correctness requirement).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

import sympy as sp

from .extract import Extraction, MathObject, Step

# --------------------------------------------------------------------------
# Performance guards (§4.8): simplify can hang and take the request with it.
# --------------------------------------------------------------------------

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sympy")
STEP_TIMEOUT = 2.0


def guarded(fn, default=None, seconds: float = STEP_TIMEOUT):
    try:
        return _POOL.submit(fn).result(timeout=seconds)
    except Exception:
        return default


ATOL, RTOL = 1e-6, 1e-4
AMNESTY_RTOL = 5e-3

LAM = sp.Symbol("lambda")


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------

@dataclass
class Val:
    """A canonicalized claimed/expected value plus the notation it was written in."""

    kind: str
    obj: Any                      # sp.Matrix | sp.Expr | list | str
    orientation: Optional[str] = None
    wrote_decimals: bool = False
    var: Optional[str] = None
    text: Optional[str] = None

    @property
    def is_matrix(self) -> bool:
        return isinstance(self.obj, sp.MatrixBase)

    def as_column(self) -> sp.Matrix:
        m = self.obj
        if not isinstance(m, sp.MatrixBase):
            raise TypeError("not a matrix")
        if m.rows == 1 and m.cols > 1:
            return m.T
        return m

    def shape(self):
        return (self.obj.rows, self.obj.cols) if self.is_matrix else None

    def json(self):
        return val_json(self)


def _sym(entry) -> sp.Expr:
    if isinstance(entry, str):
        return sp.sympify(entry.replace("^", "**"), locals={"lambda": LAM})
    if isinstance(entry, float) and entry.is_integer():
        return sp.Integer(int(entry))
    return sp.nsimplify(sp.sympify(entry), rational=True, tolerance=1e-9)


def to_sympy(obj: MathObject | None) -> Optional[Val]:
    """MathObject -> sympy. `exact` wins over `rows` whenever it is present (§2.1)."""
    if obj is None:
        return None
    kind = obj.kind
    try:
        if kind in ("matrix", "vector", "augmented", "vector_list"):
            src = obj.exact if obj.exact else obj.rows
            if not src:
                return None
            m = sp.Matrix([[_sym(e) for e in row] for row in src])
            return Val(kind, m, obj.orientation, obj.wrote_decimals)
        if kind == "scalar":
            src = obj.exact_scalars or obj.scalars
            if src is None or len(src) == 0:
                if obj.rows and obj.rows[0]:
                    return Val("scalar", _sym(obj.rows[0][0]), None, obj.wrote_decimals)
                return None
            return Val("scalar", _sym(src[0]), None, obj.wrote_decimals)
        if kind in ("scalar_list", "polynomial"):
            src = obj.exact_scalars or obj.scalars or []
            items = [_sym(s) for s in src]
            return Val(kind, items, None, obj.wrote_decimals, var=obj.var)
        if kind == "text":
            return Val("text", obj.text or "", text=obj.text or "")
    except Exception:
        return None
    return None


def val_json(v: Optional[Val]) -> Any:
    if v is None:
        return None
    if v.is_matrix:
        return {
            "kind": v.kind,
            "rows": [[_to_float(e) for e in v.obj.row(i)] for i in range(v.obj.rows)],
            "exact": [[sp.sstr(e) for e in v.obj.row(i)] for i in range(v.obj.rows)],
            "shape": [v.obj.rows, v.obj.cols],
        }
    if v.kind in ("scalar_list", "polynomial"):
        return {
            "kind": v.kind,
            "scalars": [_to_float(e) for e in v.obj],
            "exact_scalars": [sp.sstr(e) for e in v.obj],
            "var": v.var,
        }
    if v.kind == "text":
        return {"kind": "text", "text": v.text}
    return {"kind": v.kind, "scalar": _to_float(v.obj), "exact": sp.sstr(v.obj)}


def _to_float(e) -> Optional[float]:
    try:
        return float(sp.N(e))
    except Exception:
        return None


# --------------------------------------------------------------------------
# §4.3 / §4.4 comparison
# --------------------------------------------------------------------------

def _rationalize(e: sp.Expr) -> sp.Expr:
    """Pull Floats into exact rationals. Applied to BOTH sides or neither (§4.4 trap)."""
    e = sp.sympify(e)
    if e.atoms(sp.Float):
        try:
            return sp.nsimplify(e, rational=True, tolerance=1e-4)
        except Exception:
            return e
    return e


def _zero(expr: sp.Expr) -> bool:
    expr = sp.sympify(expr)
    if expr.is_number:
        try:
            return abs(complex(sp.N(expr))) <= ATOL
        except Exception:
            pass
    for fast in (sp.expand, sp.cancel, sp.together):
        try:
            if fast(expr) == 0:
                return True
        except Exception:
            continue
    return guarded(lambda: sp.simplify(expr) == 0, default=False) is True


def _num_close(a, b, rtol: float) -> bool:
    try:
        av, bv = complex(sp.N(a)), complex(sp.N(b))
    except Exception:
        return False
    return abs(av - bv) <= ATOL + rtol * max(1.0, abs(bv))


def _scalar_cmp(a, b, decimals: bool) -> str:
    """-> 'eq' | 'rounding' | 'neq'."""
    if decimals:
        a, b = _rationalize(a), _rationalize(b)
    try:
        if _zero(sp.sympify(a) - sp.sympify(b)):
            return "eq"
    except Exception:
        pass
    if _num_close(a, b, RTOL):
        return "eq"
    if _num_close(a, b, AMNESTY_RTOL):
        try:
            sa, sb = complex(sp.N(a)), complex(sp.N(b))
            if sa.real * sb.real >= 0:  # sign flips are never rounding
                return "rounding"
        except Exception:
            return "rounding"
    return "neq"


def compare(a: Val, b: Val) -> str:
    """Tolerance-aware, type-aware comparison. -> 'eq' | 'rounding' | 'neq' | 'unknown'."""
    decimals = bool(a.wrote_decimals or b.wrote_decimals)

    if a.kind == "text" or b.kind == "text":
        if a.kind == b.kind == "text":
            return "eq" if _norm_text(a.text) == _norm_text(b.text) else "neq"
        return "unknown"

    if a.is_matrix and b.is_matrix:
        A, B = a.obj, b.obj
        if A.shape != B.shape:
            # (1,n) vs (n,1) where the page never said which (§2.3 orientation leniency)
            lenient = "unspecified" in (a.orientation or "", b.orientation or "") or None in (
                a.orientation,
                b.orientation,
            )
            if lenient and A.shape == (B.cols, B.rows):
                B = B.T
            else:
                return "neq"
        worst = "eq"
        for i in range(A.rows):
            for j in range(A.cols):
                c = _scalar_cmp(A[i, j], B[i, j], decimals)
                if c == "neq":
                    return "neq"
                if c == "rounding":
                    worst = "rounding"
        return worst

    if a.kind in ("scalar_list", "polynomial") or b.kind in ("scalar_list", "polynomial"):
        la, lb = _as_list(a), _as_list(b)
        if la is None or lb is None:
            return "unknown"
        if a.kind == "polynomial" or b.kind == "polynomial":
            la, lb = _normalize_poly(la), _normalize_poly(lb)
        if len(la) != len(lb):
            return "neq"
        if a.kind == "scalar_list" and b.kind == "scalar_list":
            la, lb = _sorted_multiset(la), _sorted_multiset(lb)
        worst = "eq"
        for x, y in zip(la, lb):
            c = _scalar_cmp(x, y, decimals)
            if c == "neq":
                return "neq"
            if c == "rounding":
                worst = "rounding"
        return worst

    if a.is_matrix or b.is_matrix:
        # 1x1 matrix vs scalar is the same number written two ways.
        m, s = (a, b) if a.is_matrix else (b, a)
        if m.obj.shape == (1, 1):
            return _scalar_cmp(m.obj[0, 0], s.obj, decimals)
        return "neq"

    return _scalar_cmp(a.obj, b.obj, decimals)


def _norm_text(t: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _as_list(v: Val):
    if isinstance(v.obj, list):
        return list(v.obj)
    if v.is_matrix:
        return list(v.obj)
    if v.kind == "scalar":
        return [v.obj]
    return None


def _normalize_poly(coeffs: list) -> list:
    """Scale a coefficient list so the leading coefficient is 1 (p and 2p are one claim)."""
    for c in coeffs:
        if not _zero(c):
            return [sp.simplify(x / c) for x in coeffs]
    return coeffs


def _sorted_multiset(items: list) -> list:
    def key(e):
        try:
            z = complex(sp.N(e))
            return (round(z.real, 9), round(z.imag, 9))
        except Exception:
            return (0.0, 0.0)

    return sorted(items, key=key)


def eq(a: Val, b: Val) -> bool:
    return compare(a, b) in ("eq", "rounding")


# --------------------------------------------------------------------------
# §5 helper contract
# --------------------------------------------------------------------------

def is_eigvec(M: sp.Matrix, v: sp.Matrix) -> bool:
    v = v.T if v.rows == 1 else v
    if v.norm() == 0:
        return False
    try:
        return sp.Matrix.hstack(v, M * v).rank() <= 1
    except Exception:
        return False


def span_eq(V: list[sp.Matrix], W: list[sp.Matrix]) -> bool:
    MV, MW = sp.Matrix.hstack(*V), sp.Matrix.hstack(*W)
    return MV.rank() == MW.rank() == sp.Matrix.hstack(MV, MW).rank()


# --------------------------------------------------------------------------
# Expression evaluation: "AB", "det(M)", "M^-1", "proj_v(u)", "u x v", ...
# --------------------------------------------------------------------------

class ShapeMismatch(Exception):
    def __init__(self, left, right):
        super().__init__(f"{left} * {right} is not defined")
        self.left, self.right = left, right


_UNICODE = {
    "·": "*", "∙": "*", "•": "*",       # middle dots
    "×": " cross ", "✕": " cross ",           # times
    "ᵀ": "^T", "ₜ": "^T",
    "⁻¹": "^-1", "¹": "1",
    "−": "-", "–": "-",
    "λ": "lambda",
    "‖": "||",
    "√": "sqrt",
    "²": "^2", "³": "^3",
}

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<pow>\^-1|\^T|\^\d+|'|T\b)"
    r"|(?P<op>\|\||[()+\-*/.,|]))"
)


def _normalize_expr(text: str) -> str:
    for k, v in _UNICODE.items():
        text = text.replace(k, v)
    text = text.replace("→", "->")
    text = re.sub(r"\bproj_\{?([A-Za-z][A-Za-z_0-9]*)\}?\s*\(", r"proj(\1,", text)
    text = re.sub(r"\btranspose\s*\(", "transposefn(", text)
    # Bars are delimiters, not operators: rewrite them into calls before tokenizing,
    # so the parser never has to decide whether a "|" opens or closes a group.
    text = re.sub(r"\|\|\s*([^|]+?)\s*\|\|", r"norm(\1)", text)
    text = re.sub(r"\|\s*([^|]+?)\s*\|", r"bars(\1)", text)
    return text.strip()


class _Parser:
    """Tiny recursive-descent evaluator over the given objects. Fails closed: any
    symbol it does not know, or any construct it does not understand, yields None,
    which the caller reads as UNKNOWN - never as 'the student is wrong'."""

    FUNCS = {"det", "inv", "norm", "bars", "proj", "dot", "cross", "transposefn",
             "adj", "adjugate", "rref", "sqrt", "abs"}

    def __init__(self, text: str, env: dict[str, Val]):
        self.text = _normalize_expr(text)
        self.env = env
        self.toks: list[tuple[str, str]] = []
        i = 0
        while i < len(self.text):
            m = _TOKEN.match(self.text, i)
            if not m or m.end() == i:
                raise ValueError(f"cannot tokenize at {self.text[i:]!r}")
            i = m.end()
            for key in ("num", "name", "pow", "op"):
                if m.group(key):
                    self.toks.append((key, m.group(key)))
                    break
        self.pos = 0

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.pos += 1
        return t

    def parse(self):
        v = self.expr()
        if self.pos != len(self.toks):
            raise ValueError(f"trailing tokens {self.toks[self.pos:]!r}")
        return v

    def expr(self):
        left = self.term()
        while True:
            kind, tok = self.peek()
            if kind == "op" and tok in "+-":
                self.take()
                right = self.term()
                left = left + right if tok == "+" else left - right
            else:
                return left

    def term(self):
        left = self.factor()
        while True:
            kind, tok = self.peek()
            if kind == "op" and tok in ("*", "/", "."):
                self.take()
                right = self.factor()
                left = self._binary(left, right, tok)
            elif kind == "name" and tok in ("dot", "cross", "x") and self._starts_operand(self.pos + 1):
                self.take()
                right = self.factor()
                left = self._binary(left, right, "cross" if tok in ("cross", "x") else ".")
            elif kind in ("num", "name") or (kind == "op" and tok in ("(", "|", "||")):
                right = self.factor()
                left = self._binary(left, right, "*")
            else:
                return left

    def _starts_operand(self, idx: int) -> bool:
        if idx >= len(self.toks):
            return False
        kind, tok = self.toks[idx]
        return kind in ("num", "name") or (kind == "op" and tok in ("(", "|", "||"))

    def _binary(self, a, b, op: str):
        if op == "/":
            if isinstance(b, sp.MatrixBase):
                raise ValueError("division by a matrix")
            return a / b
        if op == ".":
            return _dot(a, b)
        if op == "cross":
            return _cross(a, b)
        if isinstance(a, sp.MatrixBase) and isinstance(b, sp.MatrixBase):
            if a.cols != b.rows:
                if a.shape == b.shape and a.cols == 1:      # two column vectors juxtaposed
                    raise ValueError("ambiguous vector product")
                raise ShapeMismatch(a.shape, b.shape)
            return a * b
        return a * b

    def factor(self):
        v = self.atom()
        while True:
            kind, tok = self.peek()
            if kind != "pow":
                return v
            self.take()
            if tok in ("^T", "'", "T"):
                v = v.T if isinstance(v, sp.MatrixBase) else v
            elif tok == "^-1":
                v = _inv(v)
            else:
                n = int(tok[1:])
                v = v ** n

    def atom(self):
        kind, tok = self.take()
        if kind == "num":
            return sp.nsimplify(sp.sympify(tok), rational=True, tolerance=1e-9)
        if kind == "op" and tok == "(":
            v = self.expr()
            self._expect(")")
            return v
        if kind == "op" and tok in ("|", "||"):
            v = self.expr()
            self._expect(tok)
            if isinstance(v, sp.MatrixBase):
                if tok == "||" or min(v.shape) == 1:
                    return v.norm()
                return v.det()
            return sp.Abs(v)
        if kind == "op" and tok == "-":
            return -self.atom()
        if kind == "name":
            return self.name(tok)
        raise ValueError(f"unexpected token {tok!r}")

    def _expect(self, tok: str):
        kind, got = self.take()
        if got != tok:
            raise ValueError(f"expected {tok!r}, got {got!r}")

    def name(self, tok: str):
        low = tok.lower()
        if low in self.FUNCS and self.peek() == ("op", "("):
            self.take()
            args = [self.expr()]
            while self.peek() == ("op", ","):
                self.take()
                args.append(self.expr())
            self._expect(")")
            return _apply_func(low, args)
        if tok in self.env:
            return self.env[tok].obj
        # Implicit juxtaposition of single-letter givens: "AB" -> A*B
        if len(tok) > 1 and all(ch in self.env for ch in tok):
            out = self.env[tok[0]].obj
            for ch in tok[1:]:
                out = self._binary(out, self.env[ch].obj, "*")
            return out
        raise ValueError(f"unknown symbol {tok!r}")


def _apply_func(name: str, args: list):
    a = args[0]
    if name == "det":
        return a.det()
    if name in ("inv",):
        return _inv(a)
    if name == "norm":
        return a.norm()
    if name == "bars":  # |x|: determinant of a square matrix, length of a vector
        if isinstance(a, sp.MatrixBase):
            return a.det() if (a.rows == a.cols and a.rows > 1) else a.norm()
        return sp.Abs(a)
    if name in ("adj", "adjugate"):
        return a.adjugate()
    if name == "transposefn":
        return a.T
    if name == "rref":
        return a.rref()[0]
    if name == "sqrt":
        return sp.sqrt(a)
    if name == "abs":
        return sp.Abs(a)
    if name == "dot":
        return _dot(args[0], args[1])
    if name == "cross":
        return _cross(args[0], args[1])
    if name == "proj":
        onto, vec = args[0], args[1]
        return _project(vec, onto)
    raise ValueError(f"unknown function {name!r}")


def _col(v):
    if isinstance(v, sp.MatrixBase) and v.rows == 1 and v.cols > 1:
        return v.T
    return v


def _dot(a, b):
    a, b = _col(a), _col(b)
    if isinstance(a, sp.MatrixBase) and isinstance(b, sp.MatrixBase):
        if a.shape != b.shape:
            raise ShapeMismatch(a.shape, b.shape)
        return a.dot(b)
    return a * b


def _cross(a, b):
    a, b = _col(a), _col(b)
    if a.shape != (3, 1) or b.shape != (3, 1):
        raise ShapeMismatch(a.shape, b.shape)
    return a.cross(b)


def _project(u, v):
    u, v = _col(u), _col(v)
    if v.norm() == 0:
        raise ValueError("projection onto the zero vector")
    return (u.dot(v) / v.dot(v)) * v


def _inv(m):
    if not isinstance(m, sp.MatrixBase):
        return 1 / m
    if m.rows != m.cols:
        raise ShapeMismatch(m.shape, m.shape)
    if m.det() == 0:
        raise ValueError("singular matrix has no inverse")
    return m.inv()


def eval_expr(text: str, env: dict[str, Val]) -> Optional[Any]:
    """-> sympy object, or None when we cannot be sure what the student meant."""
    if not text:
        return None
    stripped = text.split("=")[0].strip() if "=" in text else text.strip()
    try:
        return _Parser(stripped, env).parse()
    except ShapeMismatch:
        raise
    except Exception:
        return None


def wrap(obj: Any, *, kind: Optional[str] = None, orientation: Optional[str] = None) -> Optional[Val]:
    if obj is None:
        return None
    if isinstance(obj, sp.MatrixBase):
        k = kind or ("vector" if min(obj.shape) == 1 and max(obj.shape) > 1 else "matrix")
        return Val(k, obj, orientation)
    if isinstance(obj, (list, tuple)):
        return Val(kind or "scalar_list", list(obj))
    return Val(kind or "scalar", sp.sympify(obj))


# --------------------------------------------------------------------------
# What SHOULD this step have produced?
# --------------------------------------------------------------------------

# Candidate names for an operation's operands, tried in order. Students call a
# matrix "A" far more often than "M"; when these listed only "M", every one of
# determinant / inverse / char_poly / eigenvector_solve found no symbol, `syms`
# came back empty, the `and syms` guard skipped the check, and a wrong answer
# passed SILENTLY. "det A = 22" for a matrix whose determinant is 2 was reported
# as "nothing in this work disagrees with the problem".
_OP_SYMBOL_DEFAULTS = {
    "multiply": ["A", "B"],
    "dot": ["u", "v"],
    "cross": ["u", "v"],
    "project": ["u", "v"],
    "normalize": ["v", "u"],
    "transpose": ["A", "M"],
    "inverse_formula": ["A", "M"],
    "determinant_expand": ["A", "M"],
    "cofactor": ["A", "M"],
    "char_poly": ["A", "M"],
    "solve_char_poly": ["A", "M"],
    "eigenvector_solve": ["A", "M"],
}

# Operations that act on exactly ONE matrix. For these, if no name matched, a
# single matrix in scope is unambiguously the operand whatever it is called.
_SINGLE_MATRIX_OPS = frozenset({
    "transpose", "inverse_formula", "determinant_expand", "cofactor",
    "char_poly", "solve_char_poly", "eigenvector_solve",
})

# The extractor is a language model choosing from an enum, and it emits
# near-misses. Every one of these used to fall through to "no handler", which
# reads as "this step is fine" -- the single most damaging way to be wrong.
_OP_ALIASES = {
    "determinant": "determinant_expand",
    "det": "determinant_expand",
    "inverse": "inverse_formula",
    "invert": "inverse_formula",
    "matrix_inverse": "inverse_formula",
    "eigenvector": "eigenvector_solve",
    "eigenvectors": "eigenvector_solve",
    "eigenvalue": "solve_char_poly",
    "eigenvalues": "solve_char_poly",
    "matrix_multiply": "multiply",
    "matmul": "multiply",
    "product": "multiply",
    "dot_product": "dot",
    "inner_product": "dot",
    "cross_product": "cross",
    "projection": "project",
    "norm": "normalize",
    "unit_vector": "normalize",
    "characteristic_polynomial": "char_poly",
}


def canonical_op(op: str) -> str:
    """Fold a near-miss operation name onto the enum verify.py dispatches on."""
    op = (op or "").strip().lower()
    return _OP_ALIASES.get(op, op)


def _syms(step: Step, env: dict[str, Val]) -> list[str]:
    given = [s for s in (step.op_args.source_symbols or []) if s in env]
    if given:
        return given
    op = canonical_op(step.claimed_operation)
    named = [s for s in _OP_SYMBOL_DEFAULTS.get(op, []) if s in env]
    if named:
        return named
    if op in _SINGLE_MATRIX_OPS:
        matrices = [k for k, v in env.items()
                    if isinstance(getattr(v, "obj", None), sp.MatrixBase)
                    and getattr(v, "obj").shape[0] > 1]
        if len(matrices) == 1:
            return matrices
    return []


def expected_for(step: Step, env: dict[str, Val], topic: str) -> tuple[Optional[Val], str]:
    """Layer 1. -> (expected value, how we got it). (None, reason) means UNKNOWN."""
    # 1. The student restated an expression: evaluate it from the givens.
    if step.claimed_expression:
        obj = eval_expr(step.claimed_expression, env)
        if obj is not None:
            return wrap(obj), f"evaluated {step.claimed_expression!r} from the givens"

    op = canonical_op(step.claimed_operation)
    syms = _syms(step, env)

    # 2. The labelled operation, applied to the givens.
    try:
        if op == "copy_given" and syms:
            return env[syms[0]], f"the given {syms[0]}"
        if op == "multiply" and len(syms) >= 2:
            out = env[syms[0]].obj
            for s in syms[1:]:
                a, b = out, env[s].obj
                if isinstance(a, sp.MatrixBase) and isinstance(b, sp.MatrixBase) and a.cols != b.rows:
                    raise ShapeMismatch(a.shape, b.shape)
                out = a * b
            return wrap(out), f"the product {' '.join(syms)}"
        if op in ("add", "subtract") and len(syms) >= 2:
            a, b = env[syms[0]].obj, env[syms[1]].obj
            return wrap(a + b if op == "add" else a - b), f"{syms[0]} {'+' if op == 'add' else '-'} {syms[1]}"
        if op == "scalar_multiply" and syms:
            k = sp.sympify(step.op_args.scalar or "1")
            return wrap(k * env[syms[0]].obj), f"{step.op_args.scalar} times {syms[0]}"
        if op == "transpose" and syms:
            return wrap(env[syms[0]].obj.T), f"the transpose of {syms[0]}"
        if op == "inverse_formula" and syms:
            return wrap(_inv(env[syms[0]].obj)), f"the inverse of {syms[0]}"
        if op in ("determinant_expand", "cofactor") and syms:
            return wrap(env[syms[0]].obj.det(), kind="scalar"), f"the determinant of {syms[0]}"
        if op == "dot" and len(syms) >= 2:
            return wrap(_dot(env[syms[0]].obj, env[syms[1]].obj), kind="scalar"), "the dot product"
        if op == "cross" and len(syms) >= 2:
            return wrap(_cross(env[syms[0]].obj, env[syms[1]].obj)), "the cross product"
        if op == "project" and len(syms) >= 2:
            return wrap(_project(env[syms[0]].obj, env[syms[1]].obj)), "the projection"
        if op == "normalize" and syms:
            v = _col(env[syms[0]].obj)
            if v.norm() != 0:
                return wrap(v / v.norm()), f"the unit vector along {syms[0]}"
        if op == "char_poly" and syms:
            coeffs = list(sp.Poly(env[syms[0]].obj.charpoly(LAM).as_expr(), LAM).all_coeffs())
            return Val("polynomial", coeffs, var="lambda"), "the characteristic polynomial"
        if op == "solve_char_poly" and syms:
            eigs = _eigenvalues(env[syms[0]].obj)
            return Val("scalar_list", eigs), "the eigenvalues"
        if op == "state_answer":
            return topic_target(topic, env)
    except ShapeMismatch:
        raise
    except Exception:
        return None, "could not evaluate the labelled operation"

    # 3. It is the final answer and the problem says what the answer is.
    if step.is_final_answer:
        return topic_target(topic, env)

    return None, "no checkable claim against the givens"


def topic_target(topic: str, env: dict[str, Val]) -> tuple[Optional[Val], str]:
    """The canonical correct answer to the WHOLE problem. Drives the final-answer
    fallback (§4.6.5), which is the path that guarantees the demo shows something."""
    try:
        if topic == "matrix_multiply" and "A" in env and "B" in env:
            A, B = env["A"].obj, env["B"].obj
            if A.cols != B.rows:
                raise ShapeMismatch(A.shape, B.shape)
            return wrap(A * B), "the product AB"
        if topic == "matrix_add" and "A" in env and "B" in env:
            return wrap(env["A"].obj + env["B"].obj), "the sum A+B"
        # These resolve the subject matrix by convention-then-uniqueness rather
        # than demanding it be called "M": a student who wrote A got no target
        # at all, and so was never contradicted.
        subject = _subject_matrix(env)
        if topic == "determinant" and subject is not None:
            return wrap(subject.det(), kind="scalar"), "the determinant"
        if topic == "inverse" and subject is not None:
            return wrap(_inv(subject)), "the inverse"
        if topic == "transpose":
            if "A" in env and "B" in env:
                return wrap((env["A"].obj * env["B"].obj).T), "the transpose of AB"
            if subject is not None:
                return wrap(subject.T), "the transpose"
        if topic == "dot_product" and "u" in env and "v" in env:
            return wrap(_dot(env["u"].obj, env["v"].obj), kind="scalar"), "the dot product"
        if topic == "cross_product" and "u" in env and "v" in env:
            return wrap(_cross(env["u"].obj, env["v"].obj)), "the cross product"
        if topic == "projection" and "u" in env and "v" in env:
            return wrap(_project(env["u"].obj, env["v"].obj)), "the projection of u onto v"
        if topic == "norm" and "v" in env:
            return wrap(_col(env["v"].obj).norm(), kind="scalar"), "the norm of v"
        if topic == "solve_system" and "A" in env and "b" in env:
            A, b = env["A"].obj, _col(env["b"].obj)
            return wrap(A.solve(b)), "the solution of Ax=b"
    except ShapeMismatch:
        raise
    except Exception:
        return None, "could not compute the target answer"
    return None, "no target answer for this topic"


def _eigenvalues(M: sp.Matrix) -> list[sp.Expr]:
    out: list[sp.Expr] = []
    for val, mult in M.eigenvals().items():
        out.extend([val] * int(mult))
    return _sorted_multiset(out)


def _eigenvectors(M: sp.Matrix) -> list[tuple[sp.Expr, sp.Matrix]]:
    out = []
    try:
        for val, _mult, vecs in M.eigenvects():
            for v in vecs:
                out.append((sp.simplify(val), sp.Matrix(v)))
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------
# Structural claims (§4: independence, span dimension, "is an eigenvector")
# --------------------------------------------------------------------------

def _subject_matrix(env: dict[str, Val]) -> Optional[sp.Matrix]:
    """The square matrix a single-matrix question is about, or None.

    Prefers the conventional names, then falls back to the only square matrix in
    scope. Sites used to test `"M" in env` directly, so a student who called
    their matrix A -- which is most of them -- skipped the check entirely and
    was told their work was fine.
    """
    for name in ("A", "M"):
        val = env.get(name)
        obj = getattr(val, "obj", None)
        if isinstance(obj, sp.MatrixBase) and obj.shape[0] == obj.shape[1] > 1:
            return obj
    square = [v.obj for v in env.values()
              if isinstance(getattr(v, "obj", None), sp.MatrixBase)
              and v.obj.shape[0] == v.obj.shape[1] > 1]
    return square[0] if len(square) == 1 else None


def _claims_eigenvector(step: Step, topic: str, v: Optional[Val]) -> bool:
    if v is None or not v.is_matrix or min(v.obj.shape) != 1:
        return False
    if canonical_op(step.claimed_operation) == "eigenvector_solve":
        return True
    text = f"{step.claimed_expression or ''} {step.raw_text}".lower()
    return topic == "eigen" and ("eigenvector" in text or "eigenvec" in text or bool(re.search(r"\bv\s*=", text)))


_INDEP = re.compile(r"\b(linearly\s+)?independent\b")
_DEP = re.compile(r"\b(linearly\s+)?dependent\b")
_DIM = re.compile(r"\bdim(?:ension)?\D{0,12}(\d+)")


def _structural(step: Step, env: dict[str, Val], topic: str, claimed: Optional[Val]):
    """-> (ok: bool|None, correct: Val|None, error_id: str|None, note: str)"""
    text = f"{step.claimed_expression or ''} {step.raw_text} {(claimed.text if claimed and claimed.kind == 'text' else '')}".lower()
    V = _vector_set(env)

    if topic == "span" or _INDEP.search(text) or _DIM.search(text):
        if not V:
            return None, None, None, "no vector set to test"
        M = sp.Matrix.hstack(*V)
        rank = M.rank()
        if _INDEP.search(text) and not _DEP.search(text):
            ok = rank == len(V)
            return ok, wrap(sp.Integer(rank), kind="scalar"), (None if ok else "LA14"), f"rank is {rank} for {len(V)} vectors"
        m = _DIM.search(text)
        claimed_dim = None
        if m:
            claimed_dim = int(m.group(1))
        elif claimed is not None and claimed.kind == "scalar":
            claimed_dim = _to_float(claimed.obj)
            claimed_dim = int(claimed_dim) if claimed_dim is not None and float(claimed_dim).is_integer() else None
        if claimed_dim is not None:
            ok = claimed_dim == rank
            return ok, wrap(sp.Integer(rank), kind="scalar"), (None if ok else "LA15"), f"the span has dimension {rank}"

    subject = _subject_matrix(env)
    if _claims_eigenvector(step, topic, claimed) and subject is not None:
        M = subject
        v = claimed.as_column()
        ok = is_eigvec(M, v)
        best = _closest_eigenvector(M, v)
        return ok, (wrap(best) if best is not None else None), (None if ok else "LA09"), "eigenvector test"

    return None, None, None, ""


def _vector_set(env: dict[str, Val]) -> list[sp.Matrix]:
    if "V" in env and env["V"].is_matrix:
        M = env["V"].obj
        if env["V"].kind == "vector_list":
            return [M.row(i).T for i in range(M.rows)]
        return [M.col(j) for j in range(M.cols)]
    vs = [env[k] for k in ("v1", "v2", "v3", "u", "v", "w") if k in env and env[k].is_matrix]
    return [_col(x.obj) for x in vs] if len(vs) >= 2 else []


def _closest_eigenvector(M: sp.Matrix, v: sp.Matrix) -> Optional[sp.Matrix]:
    """The real eigenvector a student is most plausibly reaching for: closest in
    direction, ties broken by the larger eigenvalue (which is the one demos want)."""
    best, best_key = None, None
    for val, vec in _eigenvectors(M):
        if not _is_real(val) or vec.shape != v.shape:
            continue
        try:
            cos = abs(float(sp.N(vec.dot(v) / (vec.norm() * v.norm()))))
        except Exception:
            cos = 0.0
        key = (round(cos, 6), float(sp.N(sp.re(val))))
        if best_key is None or key > best_key:
            best, best_key = sp.Matrix(vec), key
    return best


def _is_real(x) -> bool:
    try:
        return abs(complex(sp.N(x)).imag) < 1e-9
    except Exception:
        return False


# --------------------------------------------------------------------------
# Layer 2: signatures
# --------------------------------------------------------------------------

def _M(env, k):
    v = env.get(k)
    return v.obj if v is not None and v.is_matrix else None


def match_signature(S: Val, env: dict[str, Val], expected: Optional[Val], step: Step, topic: str) -> Optional[str]:
    """Which of the 19 taxonomy errors is this? None = Layer 1 only (still renders)."""
    A, B, M = _M(env, "A"), _M(env, "B"), _M(env, "M")
    # The single-matrix signatures (determinant, inverse, eigen) all keyed off a
    # matrix literally named "M". A student who wrote "A" matched none of them,
    # so error_id stayed None and the planner fell back to a static slide
    # instead of the determinant or eigen animation. Only adopt A as the subject
    # when there is no second matrix, so AB problems are untouched.
    if M is None and B is None and A is not None and A.rows == A.cols > 1:
        M = A
    u, v = _M(env, "u"), _M(env, "v")
    if u is not None:
        u = _col(u)
    if v is not None:
        v = _col(v)
    s = S.obj

    def same(x, y) -> bool:
        try:
            return compare(wrap(x), wrap(y)) in ("eq", "rounding")
        except Exception:
            return False

    checks: list[tuple[str, Any]] = []
    if A is not None and B is not None and S.is_matrix:
        checks += [
            ("LA02", lambda: A.cols == B.rows and B.cols == A.rows and same(s, B * A) and not same(s, A * B)),
            ("LA01", lambda: A.cols == B.rows and same(s, A * B.T) and not same(s, A * B)),
            ("LA16", lambda: topic == "transpose" and same(s, A.T * B.T) and not same(s, (A * B).T)),
        ]
    if M is not None and M.rows == M.cols:
        # LA06 only when the page shows a row swap. Without that evidence a claim of
        # +6 where the determinant is -6 is indistinguishable from LA04 on many
        # matrices (ad+bc == -det whenever ad == 0), and LA04 is the commoner slip.
        if _swap_evidence(step):
            checks.append(
                ("LA06", lambda: not S.is_matrix and same(s, -M.det()) and not same(s, M.det()))
            )
        checks += [
            ("LA07", lambda: S.is_matrix and same(s, M.adjugate()) and not same(s, _inv(M))),
            ("LA08", lambda: S.is_matrix and M.rows == 2
                and same(s, sp.Matrix([[M[0, 0], -M[0, 1]], [-M[1, 0], M[1, 1]]]) / M.det())
                and not same(s * M, sp.eye(2))),
            ("LA04", lambda: not S.is_matrix and M.rows == 2
                and same(s, M[0, 0] * M[1, 1] + M[0, 1] * M[1, 0]) and not same(s, M.det())),
            ("LA05", lambda: not S.is_matrix and M.rows == 3
                and same(s, sum(M[0, j] * M.minor(0, j) for j in range(3))) and not same(s, M.det())),
            ("LA06", lambda: not S.is_matrix and _swap_evidence(step)
                and same(s, -M.det()) and not same(s, M.det())),
            ("LA10", lambda: topic == "eigen" and S.kind in ("scalar", "scalar_list")
                and not _is_charpoly_root(M, S)),
        ]
    if u is not None and v is not None and S.is_matrix:
        sv = _col(s)
        checks += [
            ("LA19", lambda: topic == "projection" and sv.shape == v.shape and not same((u - sv).dot(v), 0)),
            ("LA17", lambda: topic == "cross_product" and sv.shape == (3, 1)
                and (not same(u.dot(sv), 0) or not same(v.dot(sv), 0))),
            ("LA18", lambda: topic == "dot_product" and sv.shape == u.shape
                and same(sv, u.multiply_elementwise(v))),
        ]
    # LA11 is "normalized by the wrong divisor", so it only applies where a unit
    # vector was the goal. Without this gate it also matches any scalar multiple of
    # v - e.g. a wrong projection, which is LA19's story and a much better animation.
    if v is not None and S.is_matrix and (
        canonical_op(step.claimed_operation) == "normalize" or topic in ("eigen", "norm")
    ):
        sv = _col(s)
        checks += [
            ("LA11", lambda: sv.shape == v.shape and sp.Matrix.hstack(sv, v).rank() == 1
                and not same(sv.norm(), 1)),
        ]
    if topic == "rref" or topic == "solve_system":
        checks += [
            ("LA13", lambda: _row_scale_signature(S, env)),
            ("LA12", lambda: _solution_signature(S, env)),
        ]

    for error_id, fn in checks:
        hit = guarded(fn, default=False, seconds=1.5)
        if hit:
            return error_id
    return None


_SWAP = re.compile(r"(swap|interchang|<->|<=>|R1\s*<|R2\s*<|↔)", re.I)


def _swap_evidence(step: Step) -> bool:
    if canonical_op(step.claimed_operation) == "row_swap":
        return True
    blob = " ".join(filter(None, [step.raw_text, step.claimed_expression, step.op_args.note]))
    return bool(_SWAP.search(blob))


def _is_charpoly_root(M: sp.Matrix, S: Val) -> bool:
    claims = S.obj if isinstance(S.obj, list) else [S.obj]
    poly = M.charpoly(LAM).as_expr()
    return all(_zero(poly.subs(LAM, c)) for c in claims)


def _row_scale_signature(S: Val, env: dict[str, Val]) -> bool:
    Aug = _M(env, "Aug") or _M(env, "A")
    if Aug is None or not S.is_matrix or S.obj.cols < 2:
        return False
    coeff_ok = S.obj[:, :-1].rref() == Aug[:, :-1].rref()
    return bool(coeff_ok and S.obj.rref() != Aug.rref())


def _solution_signature(S: Val, env: dict[str, Val]) -> bool:
    A, b = _M(env, "A"), _M(env, "b")
    if A is None or b is None or not S.is_matrix:
        return False
    x = _col(S.obj)
    if A.cols != x.rows:
        return False
    return not _zero((A * x - _col(b)).norm())


# --------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------

OK, WRONG, UNPARSED, UNCHECKED, CROSSED = "OK", "WRONG", "SKIPPED_UNPARSED", "UNCHECKED", "CROSSED_OUT"


@dataclass
class StepResult:
    index: int
    step_id: str
    student_label: Optional[str]
    status: str
    reason: str = ""
    expected: Optional[Val] = None
    claimed: Optional[Val] = None
    plausible_rounding: bool = False
    error_id: Optional[str] = None
    adopted_alternate: Optional[int] = None


@dataclass
class Verdict:
    first_error_index: Optional[int]
    step_results: list[StepResult] = field(default_factory=list)
    confidence: str = "high"
    error_id: Optional[str] = None
    student_value: Optional[Val] = None
    correct_value: Optional[Val] = None
    topic: str = "other"
    step_id: Optional[str] = None
    student_label: Optional[str] = None
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    givens: dict[str, Val] = field(default_factory=dict)

    @property
    def found_error(self) -> bool:
        return self.first_error_index is not None

    def json(self) -> dict:
        return {
            "first_error_index": self.first_error_index,
            "step_id": self.step_id,
            "student_label": self.student_label,
            "confidence": self.confidence,
            "error_id": self.error_id,
            "student_value": val_json(self.student_value),
            "correct_value": val_json(self.correct_value),
            "flags": self.flags,
            "notes": self.notes,
            "steps": [
                {
                    "index": r.index,
                    "id": r.step_id,
                    "label": r.student_label,
                    "status": r.status,
                    "reason": r.reason,
                    "plausible_rounding": r.plausible_rounding,
                }
                for r in self.step_results
            ],
        }


def _given_envs(ext: Extraction, cap: int = 4) -> list[dict[str, Val]]:
    """Primary reading of the givens first, then one-at-a-time alternate readings
    (§4.7 charity applied to the givens, where a misread poisons every check)."""
    base: dict[str, Val] = {}
    for g in ext.problem.givens:
        v = to_sympy(g.object)
        if v is not None:
            base[g.symbol] = v
    envs = [base]
    for g in ext.problem.givens:
        for alt in g.alternates[:1]:
            av = to_sympy(alt)
            if av is None:
                continue
            clone = dict(base)
            clone[g.symbol] = av
            envs.append(clone)
            if len(envs) >= cap:
                return envs
    return envs


def _candidates(step: Step) -> list[Val]:
    out = []
    for obj in [step.value] + list(step.alternates):
        v = to_sympy(obj)
        if v is not None:
            out.append(v)
    return out


def _check_one(step: Step, env: dict[str, Val], topic: str, cand: Val):
    """-> (status, reason, expected, rounding, error_id)"""
    ok, correct, error_id, note = _structural(step, env, topic, cand)
    if ok is not None:
        if ok:
            return OK, note, correct, False, None
        return WRONG, note, correct, False, error_id

    try:
        expected, how = expected_for(step, env, topic)
    except ShapeMismatch as exc:
        return WRONG, f"the shapes do not line up: {exc}", None, False, "LA03"
    if expected is None:
        return UNCHECKED, how, None, False, None

    verdict = compare(expected, cand)
    if verdict == "unknown":
        return UNCHECKED, f"cannot compare a {cand.kind} against {how}", expected, False, None
    if verdict == "neq":
        return WRONG, f"does not match {how}", expected, False, None

    # The step evaluates its own expression correctly - but if it is the final answer,
    # it also has to be the answer to the PROBLEM. This is what catches a student who
    # rewrote (AB)^T as A^T B^T and then multiplied those two perfectly: the arithmetic
    # is clean, the expression is not the one they were asked for.
    if step.is_final_answer and step.claimed_expression:
        target, thow = _target_quiet(topic, env)
        if target is not None and compare(target, cand) == "neq" and compare(target, expected) == "neq":
            return WRONG, f"does not match {thow}", target, False, None

    if verdict == "rounding":
        return OK, f"matches {how} to rounding", expected, True, None
    return OK, f"matches {how}", expected, False, None


def _target_quiet(topic: str, env: dict[str, Val]):
    try:
        return topic_target(topic, env)
    except Exception:
        return None, ""


def verify(ext: Extraction) -> Verdict:
    topic = ext.problem.topic
    envs = _given_envs(ext)
    steps = sorted(ext.steps, key=lambda s: (s.page, s.reading_order))
    results: list[StepResult] = []
    notes: list[str] = []

    for i, step in enumerate(steps):
        base = StepResult(i, step.id, step.student_label, UNCHECKED)
        if step.crossed_out:
            base.status = CROSSED
            base.reason = "abandoned by the student; never blamed (taxonomy 4.5)"
            results.append(base)
            continue
        cands = _candidates(step)
        if not step.parse_ok or not cands:
            base.status = UNPARSED
            base.reason = "could not be read; carried forward, never counted as wrong"
            results.append(base)
            continue

        best: Optional[tuple] = None
        for env in envs:
            for ci, cand in enumerate(cands):
                status, reason, expected, rounding, error_id = _check_one(step, env, topic, cand)
                score = {OK: 0, UNCHECKED: 1, WRONG: 2}[status]
                if best is None or score < best[0]:
                    best = (score, status, reason, expected, rounding, error_id, cand, ci)
                if status == OK:
                    break
            if best and best[1] == OK:
                break

        _score, status, reason, expected, rounding, error_id, cand, ci = best
        base.status = status
        base.reason = reason
        base.expected = expected
        base.claimed = cand
        base.plausible_rounding = rounding
        base.error_id = error_id
        base.adopted_alternate = ci if ci > 0 else None
        if ci > 0:
            notes.append(f"step {step.id}: adopted an alternate reading that makes the step work (charity)")
        results.append(base)

    verdict = Verdict(first_error_index=None, step_results=results, topic=topic, notes=notes)
    verdict.givens = envs[0]

    wrongs = [r for r in results if r.status == WRONG and not r.plausible_rounding]
    if not wrongs:
        verdict.confidence = "high"
        verdict.flags = ["no_error_found"]
        _fill_no_error(verdict, ext, envs[0], topic)
        return verdict

    first = wrongs[0]
    # §4.5 load-bearing: never blame a line the student abandoned.
    if not _load_bearing(first, results, steps, ext):
        later = [r for r in wrongs[1:] if _load_bearing(r, results, steps, ext)]
        if later:
            verdict.notes.append(
                f"step {first.step_id} is wrong but does not reach the final answer; "
                "treated as scratch work"
            )
            first = later[0]

    step = steps[first.index]
    verdict.first_error_index = first.index
    verdict.step_id = first.step_id
    verdict.student_label = first.student_label
    verdict.student_value = first.claimed
    verdict.correct_value = first.expected
    verdict.flags = ["load_bearing"] if _load_bearing(first, results, steps, ext) else []

    # Layer 2.
    error_id = first.error_id
    if error_id is None and first.claimed is not None:
        error_id = match_signature(first.claimed, envs[0], first.expected, step, topic)
    verdict.error_id = error_id

    # §4.5 forward propagation: is this the only error, or the first of several?
    later_wrong = [r for r in wrongs if r.index > first.index]
    verdict.flags.append("multiple_errors" if later_wrong else "single_error")

    # §4.6.3 bracketing: an unreadable line immediately before the error.
    prev_unparsed = [r for r in results if r.index == first.index - 1 and r.status == UNPARSED]
    bracketed = bool(prev_unparsed) and first.expected is None

    conf = step.confidence
    if bracketed or first.expected is None:
        verdict.confidence = "low"
        verdict.flags.append("bracketed")
    elif conf < 0.55 or step.alternates or step.ambiguities:
        verdict.confidence = "medium"
    else:
        verdict.confidence = "high"

    if first.expected is None and verdict.correct_value is None:
        target, _how = _safe_target(topic, envs[0])
        verdict.correct_value = target
    return verdict


def _safe_target(topic: str, env: dict[str, Val]):
    try:
        return topic_target(topic, env)
    except ShapeMismatch:
        return None, "shapes do not line up"


def _fill_no_error(verdict: Verdict, ext: Extraction, env: dict[str, Val], topic: str) -> None:
    """Even with no per-step error, check the final answer against the problem
    (§4.6.5). This is the safety net that always produces something to show."""
    final = to_sympy(ext.final_answer.object)
    if final is None:
        return
    target, _how = _safe_target(topic, env)
    if target is None:
        return
    if compare(target, final) == "neq":
        idx = next(
            (r.index for r in verdict.step_results if r.step_id == ext.final_answer.step_id),
            None,
        )
        verdict.first_error_index = idx
        verdict.step_id = ext.final_answer.step_id
        verdict.student_label = next(
            (r.student_label for r in verdict.step_results if r.step_id == ext.final_answer.step_id), None
        )
        verdict.student_value = final
        verdict.correct_value = target
        verdict.confidence = "low"
        verdict.flags = ["final_answer_fallback", "load_bearing"]
        verdict.error_id = match_signature(final, env, target, ext.steps[-1] if ext.steps else Step(id="final"), topic)


def _load_bearing(result: StepResult, results: list[StepResult], steps: list[Step], ext: Extraction) -> bool:
    """Does this step actually reach the student's final answer? (§4.5)"""
    step = steps[result.index]
    if step.crossed_out:
        return False
    if step.is_final_answer or ext.final_answer.step_id == step.id:
        return True
    final = to_sympy(ext.final_answer.object)
    if final is None:
        # No stated final answer: the last non-crossed-out parseable step carries the work.
        live = [r for r in results if r.status in (OK, WRONG, UNCHECKED)]
        return bool(live) and live[-1].index == result.index
    if result.claimed is not None and compare(result.claimed, final) in ("eq", "rounding"):
        return True
    # Everything after it either passed (i.e. was derived from it) or was unreadable.
    later = [r for r in results if r.index > result.index and r.status in (OK, WRONG)]
    return bool(later)
