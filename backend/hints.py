"""A located error -> (a) a scene template plus its filled parameters, and
(b) a POSITIONAL hint that points at the step without ever stating the correction.

Two rules govern this whole module.

1. Who fills what (SCENE_CATALOG.md §1.2). Every number in `params` is computed
   here from sympy values and formatted with `fmt_num`. No LLM retypes a matrix.
2. Hint discipline (SCENE_CATALOG.md §1.4). A hint names a LOCATION and a THING TO
   WATCH. It never contains the corrected value, in any form. `lint_hint` is the
   enforcement, and `plan()` runs it on itself before returning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Optional

import sympy as sp

from .extract import Extraction
from .verify import Val, Verdict, _col, val_json

MAX_ENTRY = 50.0
MIN_DET = 0.05


# --------------------------------------------------------------------------
# Formatting (SCENE_CATALOG.md §2.2) - there is no \frac without LaTeX
# --------------------------------------------------------------------------

def fmt_num(x: Any, max_den: int = 20) -> str:
    """int -> '3', nice rational -> '2/5', else '0.71'. Never str(float)."""
    try:
        val = float(sp.N(x))
    except Exception:
        return str(x)
    if abs(val) < 1e-12:
        return "0"
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    frac = Fraction(val).limit_denominator(max_den)
    if abs(float(frac) - val) < 1e-9:
        return f"{frac.numerator}/{frac.denominator}"
    return f"{val:.2f}".rstrip("0").rstrip(".")


def _rows(v: Optional[Val]) -> Optional[list[list[float]]]:
    if v is None or not v.is_matrix:
        return None
    return [[float(sp.N(e)) for e in v.obj.row(i)] for i in range(v.obj.rows)]


def _display(v: Optional[Val]) -> Optional[list[list[str]]]:
    if v is None or not v.is_matrix:
        return None
    return [[fmt_num(e) for e in v.obj.row(i)] for i in range(v.obj.rows)]


def _flat(v: Optional[Val]) -> Optional[list[float]]:
    if v is None or not v.is_matrix:
        return None
    return [float(sp.N(e)) for e in _col(v.obj)]


def _is_2x2(v: Optional[Val]) -> bool:
    return bool(v is not None and v.is_matrix and v.obj.shape == (2, 2))


def _finite(rows: Optional[list[list[float]]]) -> bool:
    if not rows:
        return False
    for row in rows:
        for e in row:
            if e != e or abs(e) == float("inf") or abs(e) > MAX_ENTRY:
                return False
    return True


def _det_ok(rows: list[list[float]]) -> bool:
    try:
        return abs(rows[0][0] * rows[1][1] - rows[0][1] * rows[1][0]) >= MIN_DET
    except Exception:
        return False


# --------------------------------------------------------------------------
# Hint bank. Positional and observational, one per taxonomy id.
# --------------------------------------------------------------------------

HINTS: dict[str, tuple[str, str]] = {
    # error_id: (full sentence for the student, short caption burned into the scene)
    "LA01": ("Both grids stretch by the same amount — watch where your first column sends "
             "the first basis vector in {step}.", "watch where your first column lands"),
    "LA02": ("Freeze both panels halfway: the intermediate grids are the same shape. Watch "
             "which panel stretches first in {step}.", "watch which one stretches first"),
    "LA03": ("Count the numbers across one row of your left matrix, then count down one "
             "column of your right one, in {step}.", "count across, then count down"),
    "LA04": ("The area counter stops well before your number. Watch what happens between "
             "the two products you formed in {step}.", "watch where the counter stops"),
    "LA05": ("Watch how little the volume actually changes. Look at what sits in front of "
             "the second minor in {step}.", "watch how little the volume changes"),
    "LA06": ("Watch which color the square is showing when it lands in {step}.",
             "watch which side lands face up"),
    "LA07": ("The grid comes back square and pointing the right way. Watch its size against "
             "the faint original in {step}.", "watch the size it comes back at"),
    "LA08": ("It almost comes home. Watch the two numbers on the main diagonal of {step} as "
             "the grid settles.", "watch the main diagonal"),
    "LA09": ("Your vector's line is drawn on screen. Watch whether the arrow stays on that "
             "line in {step}.", "watch whether it stays on its line"),
    "LA10": ("The direction you found is right. Watch how far along that line the vector "
             "actually travels in {step}.", "watch how far along the line it stops"),
    "LA11": ("The circle on screen is every vector of length 1. Watch where your tip lands "
             "relative to it in {step}.", "watch where your tip lands"),
    "LA12": ("Watch whether your new line still passes through the point where the first two "
             "cross, in {step}.", "watch the point where they cross"),
    "LA13": ("Scaling a row should not move its line at all. Watch whether yours stays put "
             "in {step}.", "watch whether the line stays put"),
    "LA14": ("Watch how much thickness the solid your vectors make actually has, in {step}.",
             "watch the thickness of the solid"),
    "LA15": ("Watch how much of the plane actually fills in, and whether the marked point is "
             "ever reached, in {step}.", "watch how much of the plane fills in"),
    "LA16": ("Both panels shear by the same amount, one sideways and one upward. Watch which "
             "matrix acts first in {step}.", "watch which one acts first"),
    "LA17": ("Watch what your arrow does to the sheet the two vectors span, in {step}.",
             "watch it lean into the sheet"),
    "LA18": ("Count how many numbers are on each side of your equals sign in {step}.",
             "count the numbers on each side"),
    "LA19": ("A shadow cannot be longer than the thing casting it. Watch whether the corner "
             "marker closes in {step}.", "watch whether the corner closes"),
}

GENERIC_BASIS = ("Watch where the {which} basis vector lands in {step}.",
                 "watch the {which} basis vector")
GENERIC_ANY = ("Watch the left panel against the right one in {step}.",
               "watch the two panels")

BANNED = ("should be", "instead of", "you forgot", "the correct", "actually is",
          "is wrong because", "the answer is", "you needed to", "you should")

_STEP_REF = re.compile(r"\byour step [^\s.,;:!?]+|\bstep \d+\b|\bthis step\b", re.I)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:\s*/\s*\d+)?")


def lint_hint(hint: str, forbidden_values: list[str], allowed_values: list[str] | None = None) -> list[str]:
    """-> list of problems. Empty means the hint is safe to show a student.

    Rejects the banned corrective phrasings, and any number that appears in the
    correct answer but not in what the student themselves wrote. Step references
    ("your step 2") are stripped first, so pointing at a line is never a leak.
    """
    problems: list[str] = []
    if not hint or not hint.strip():
        return ["hint is empty"]
    low = hint.lower()
    for phrase in BANNED:
        if phrase in low:
            problems.append(f"hint states a correction: {phrase!r}")

    scanned = _STEP_REF.sub(" ", hint)
    allowed_nums = {_num(v) for v in (allowed_values or [])}
    allowed_nums.discard(None)
    for tok in _NUMBER.findall(scanned):
        n = _num(tok)
        if n is None or n in allowed_nums:
            continue
        for v in forbidden_values:
            fv = _num(v)
            if fv is not None and abs(fv - n) < 1e-9:
                problems.append(f"hint leaks the value {v!r}")
                break
    return problems


def _num(text: Any) -> Optional[float]:
    if text is None:
        return None
    s = str(text).strip()
    try:
        if "/" in s:
            a, b = s.split("/", 1)
            return float(a) / float(b)
        return float(s)
    except Exception:
        return None


def _forbidden(correct: Optional[Val]) -> list[str]:
    if correct is None:
        return []
    if correct.is_matrix:
        return [fmt_num(e) for e in correct.obj]
    if isinstance(correct.obj, list):
        return [fmt_num(e) for e in correct.obj]
    return [fmt_num(correct.obj)]


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------

@dataclass
class Plan:
    template: str
    params: dict[str, Any]
    hint: str
    forbidden_values: list[str] = field(default_factory=list)
    fallback: Optional[dict[str, Any]] = None   # {"template":..., "params":...}
    notes: list[str] = field(default_factory=list)

    def json(self) -> dict:
        return {
            "template": self.template,
            "params": self.params,
            "hint": self.hint,
            "fallback": self.fallback,
            "notes": self.notes,
        }


def step_ref(verdict: Verdict) -> str:
    """Speak in the student's own numbering, never our array index (§R5)."""
    label = (verdict.student_label or "").strip()
    if label:
        clean = label.rstrip(").:").strip()
        clean = re.sub(r"^step\s*", "", clean, flags=re.I)
        if clean:
            return f"your step {clean}"
    if verdict.first_error_index is not None:
        return f"your step {verdict.first_error_index + 1}"
    return "your work"


def plan(verdict: Verdict, ext: Extraction) -> Plan:
    """Pick the scene, fill its parameters, and write a hint that cannot leak."""
    env = verdict.givens
    S, C = verdict.student_value, verdict.correct_value
    eid = verdict.error_id
    ref = step_ref(verdict)
    notes: list[str] = []

    builder = {
        "LA01": _grid_single, "LA16": _grid_single,
        "LA02": _grid_order,
        "LA07": _grid_roundtrip, "LA08": _grid_roundtrip,
        "LA03": _static, "LA18": _static,
        "LA04": _determinant, "LA05": _determinant, "LA06": _determinant,
        "LA09": _eigen_vector, "LA10": _eigen_value,
        "LA11": _vector_op, "LA17": _vector_op, "LA19": _vector_op,
        "LA12": _line_system, "LA13": _line_system,
        "LA14": _span, "LA15": _span,
    }.get(eid or "", _grid_single)

    full, short = HINTS.get(eid or "", GENERIC_ANY)
    try:
        template, params = builder(verdict, ext, env, S, C)
    except SceneUnavailable as exc:
        notes.append(f"{eid or 'generic'} -> StaticStepHighlight: {exc}")
        template, params = _static(verdict, ext, env, S, C)
        full, short = HINTS.get(eid or "", GENERIC_ANY)

    if eid is None and template == "GridTransformCompare":
        which = _diverging_basis(S, C)
        if which:
            full, short = GENERIC_BASIS[0].replace("{which}", which), GENERIC_BASIS[1].replace("{which}", which)

    hint = full.format(step=ref)
    short_hint = short.format(step=ref) if "{step}" in short else short

    forbidden = _forbidden(C)
    allowed = _forbidden(S)
    problems = lint_hint(hint, forbidden, allowed)
    if problems:  # a leaked hint is a product failure: fall back to the safest wording
        notes.extend(problems)
        hint = f"Watch the highlighted part of {ref}."
        short_hint = "watch the highlighted part"

    params["hint"] = short_hint
    params.setdefault("title", _title(template, ref))
    params.setdefault("student_label", "WHAT YOU WROTE")
    params.setdefault("correct_label", "WHAT THE STEP SHOULD DO")

    fallback = None
    if template != "StaticStepHighlight":
        _t, fb_params = _static(verdict, ext, env, S, C)
        fb_params["hint"] = short_hint
        fb_params.setdefault("title", params["title"])
        fallback = {"template": "StaticStepHighlight", "params": fb_params}

    return Plan(template, params, hint, forbidden, fallback, notes)


class SceneUnavailable(Exception):
    """This template's guards say it cannot tell an honest story about this error."""


_TITLES = {
    "GridTransformCompare": "{ref}, applied to the plane",
    "EigenRayTest": "{ref}, and the line it has to stay on",
    "DeterminantAreaCompare": "{ref}, as an area",
    "VectorOpCompare": "{ref}, and the property it must have",
    "LineSystemCompare": "{ref}, as lines in the plane",
    "SpanCompare": "{ref}, and everything it reaches",
    "StaticStepHighlight": "{ref}",
}


def _title(template: str, ref: str) -> str:
    return _TITLES.get(template, "{ref}").format(ref=ref[0].upper() + ref[1:])


def _diverging_basis(S: Optional[Val], C: Optional[Val]) -> Optional[str]:
    """Which basis vector do the two matrices disagree about most? (T1's t=6.2 beat
    Indicates it on its own; the hint should name the same one.)"""
    a, b = _rows(S), _rows(C)
    if not a or not b or len(a) != 2 or len(b) != 2:
        return None
    gaps = []
    for j in range(min(len(a[0]), len(b[0]))):
        gaps.append(sum(abs(a[i][j] - b[i][j]) for i in range(2)))
    if not gaps or max(gaps) < 1e-9:
        return None
    return ["first", "second"][gaps.index(max(gaps))] if len(gaps) >= 2 else "first"


# --------------------------------------------------------------------------
# Builders. Each raises SceneUnavailable rather than emitting a scene that lies.
# --------------------------------------------------------------------------

def _need_2x2(v: Optional[Val], what: str) -> list[list[float]]:
    rows = _rows(v)
    if not _is_2x2(v) or not _finite(rows):
        raise SceneUnavailable(f"{what} is not a drawable 2x2 matrix")
    return rows


def _grid_single(verdict, ext, env, S, C):
    student = _need_2x2(S, "the student's value")
    correct = _need_2x2(C, "the correct value")
    for stage in (student, correct):
        if not _det_ok(stage):
            raise SceneUnavailable("a stage is near-singular; the grid would collapse to a line")
    return "GridTransformCompare", {
        "student_stages": [student],
        "correct_stages": [correct],
        "student_display": _display(S),
        "correct_display": _display(C),
        "stage_labels": [],
        "ghost_reference": False,
        "pause_between_stages": 0.0,
        "track_vectors": [[1, 0], [0, 1]],
    }


def _grid_order(verdict, ext, env, S, C):
    """LA02: the same two maps in both panels, applied in opposite orders."""
    A, B = env.get("A"), env.get("B")
    a, b = _rows(A), _rows(B)
    if not (_is_2x2(A) and _is_2x2(B) and _finite(a) and _finite(b) and _det_ok(a) and _det_ok(b)):
        return _grid_single(verdict, ext, env, S, C)
    return "GridTransformCompare", {
        # stages are APPLIED in order: the student's product BA means A first.
        "student_stages": [a, b],
        "correct_stages": [b, a],
        "student_display": _display(S),
        "correct_display": _display(C),
        "stage_labels": ["first", "then"],
        "ghost_reference": False,
        "pause_between_stages": 0.8,
        "track_vectors": [[1, 0], [0, 1]],
    }


def _grid_roundtrip(verdict, ext, env, S, C):
    """LA07/LA08: apply M, then the claimed inverse. Does the grid come home?"""
    M = env.get("M")
    m = _rows(M)
    if not (_is_2x2(M) and _finite(m) and _det_ok(m)):
        return _grid_single(verdict, ext, env, S, C)
    student = _need_2x2(S, "the claimed inverse")
    correct = _need_2x2(C, "the true inverse")
    return "GridTransformCompare", {
        "student_stages": [m, student],
        "correct_stages": [m, correct],
        "student_display": _display(S),
        "correct_display": _display(C),
        "stage_labels": ["apply M", "then undo it"],
        "ghost_reference": True,     # the ruler that makes "10x too big" readable
        "pause_between_stages": 0.8,
        "track_vectors": [[1, 0], [0, 1]],
        "student_label": "YOUR ROUND TRIP",
        "correct_label": "A ROUND TRIP",
    }


def _determinant(verdict, ext, env, S, C):
    M = env.get("M")
    m = _rows(M)
    if m is None or not _finite(m) or len(m) not in (2, 3) or len(m) != len(m[0]):
        raise SceneUnavailable("no square given matrix to stretch")
    claimed = S.obj if S is not None and not S.is_matrix else None
    actual = C.obj if C is not None and not C.is_matrix else None
    if claimed is None or actual is None:
        raise SceneUnavailable("the determinant claim is not a single number")
    if abs(float(sp.N(claimed)) - float(sp.N(actual))) <= 1e-9:
        raise SceneUnavailable("the two determinants agree; there is no story here")
    return "DeterminantAreaCompare", {
        "M": m,
        "M_display": _display(M),
        "claimed_det": fmt_num(claimed),
        "actual_det": fmt_num(actual),
        "show_ghost_scale": abs(float(sp.N(claimed))) <= 60,
        "student_label": "YOUR ANSWER",
        "correct_label": "AREA ON SCREEN" if len(m) == 2 else "VOLUME ON SCREEN",
    }


def _eigen_vector(verdict, ext, env, S, C):
    M = env.get("M")
    m = _rows(M)
    if not (_is_2x2(M) and _finite(m)):
        raise SceneUnavailable("eigen ray test needs a 2x2 given matrix")
    v_claimed, v_correct = _flat(S), _flat(C)
    if not v_claimed or not v_correct or len(v_claimed) != 2 or len(v_correct) != 2:
        raise SceneUnavailable("the vectors are not 2D")
    if max(abs(x) for x in v_claimed) < 1e-9 or max(abs(x) for x in v_correct) < 1e-9:
        raise SceneUnavailable("a zero vector has no direction to draw")
    return "EigenRayTest", {
        "M": m, "M_display": _display(M),
        "v_claimed": v_claimed, "v_correct": v_correct,
        "lambda_claimed": None, "lambda_correct": None,
        "mode": "vector",
        "student_label": "YOUR VECTOR", "correct_label": "AN EIGENVECTOR",
    }


def _eigen_value(verdict, ext, env, S, C):
    M = env.get("M")
    m = _rows(M)
    if not (_is_2x2(M) and _finite(m)):
        raise SceneUnavailable("eigen ray test needs a 2x2 given matrix")
    claimed = _first_scalar(S)
    correct = _first_scalar(C)
    if claimed is None or correct is None:
        raise SceneUnavailable("no single claimed eigenvalue to draw")
    if abs(complex(sp.N(claimed)).imag) > 1e-9:
        # A complex claimed eigenvalue has nothing to draw on a real plane.
        raise SceneUnavailable("the claimed eigenvalue is complex")
    vec = _real_eigenvector(M.obj)
    if vec is None:
        raise SceneUnavailable("no real eigenvector to travel along")
    return "EigenRayTest", {
        "M": m, "M_display": _display(M),
        "v_claimed": vec, "v_correct": vec,
        "lambda_claimed": float(sp.N(claimed)), "lambda_correct": float(sp.N(correct)),
        "mode": "eigenvalue",
        "student_label": "YOUR EIGENVALUE", "correct_label": "WHERE IT LANDS",
    }


def _first_scalar(v: Optional[Val]):
    if v is None:
        return None
    if isinstance(v.obj, list):
        return v.obj[0] if v.obj else None
    if v.is_matrix:
        return None
    return v.obj


def _real_eigenvector(M: sp.Matrix) -> Optional[list[float]]:
    try:
        for val, _m, vecs in M.eigenvects():
            if abs(complex(sp.N(val)).imag) > 1e-9:
                continue
            v = sp.Matrix(vecs[0])
            return [float(sp.N(x)) for x in v]
    except Exception:
        return None
    return None


def _vector_op(verdict, ext, env, S, C):
    eid = verdict.error_id
    op = {"LA11": "normalize", "LA17": "cross", "LA19": "projection"}.get(eid or "", "generic")
    u = _flat(env.get("u")) or _flat(env.get("v"))
    v = _flat(env.get("v")) or _flat(env.get("u"))
    w_claimed, w_correct = _flat(S), _flat(C)
    if not (u and v and w_claimed and w_correct):
        raise SceneUnavailable("missing one of the vectors this comparison needs")
    dim = len(w_correct)
    if dim not in (2, 3) or len({len(u), len(v), len(w_claimed), len(w_correct)}) != 1:
        raise SceneUnavailable("the vectors are not all the same drawable dimension")
    if op == "projection" and max(abs(x) for x in v) < 1e-9:
        raise SceneUnavailable("cannot project onto the zero vector")
    if op == "cross" and _parallel(u, v):
        raise SceneUnavailable("u and v are parallel; the sheet they span is degenerate")

    readouts = []
    if op == "projection":
        readouts = [
            ["your residual . v", fmt_num(_dotf([a - b for a, b in zip(u, w_claimed)], v))],
            ["a projection's residual . v", "0"],
        ]
    elif op == "normalize":
        readouts = [["your length", fmt_num(_normf(w_claimed))], ["a unit vector's length", "1"]]
    elif op == "cross":
        readouts = [
            ["u . your answer", fmt_num(_dotf(u, w_claimed))],
            ["v . your answer", fmt_num(_dotf(v, w_claimed))],
            ["a normal's dot products", "0"],
        ]
    return "VectorOpCompare", {
        "op": op, "u": u, "v": v,
        "w_claimed": w_claimed, "w_correct": w_correct,
        "labels": {"u": "u", "v": "v"},
        "readouts": readouts,
        "ambient": dim,
        "student_label": "YOUR ANSWER", "correct_label": "THE PROPERTY IT MUST HAVE",
    }


def _dotf(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _normf(a: list[float]) -> float:
    return sum(x * x for x in a) ** 0.5


def _parallel(a: list[float], b: list[float]) -> bool:
    try:
        return sp.Matrix.hstack(sp.Matrix(a), sp.Matrix(b)).rank() <= 1
    except Exception:
        return False


def _line_system(verdict, ext, env, S, C):
    eqs = _equations(env)
    if not eqs or len(eqs) < 2:
        raise SceneUnavailable("no 2-variable system to draw as lines")
    det = eqs[0][0] * eqs[1][1] - eqs[0][1] * eqs[1][0]
    if abs(det) < 1e-9:
        raise SceneUnavailable("the two lines do not meet; there is no hinge to pivot about")
    claimed, correct = _flat(S), _flat(C)
    if claimed and correct and len(claimed) == 2 and len(correct) == 2 and verdict.error_id != "LA13":
        subs = [[fmt_num(row[0] * claimed[0] + row[1] * claimed[1]), fmt_num(row[2])] for row in eqs]
        return "LineSystemCompare", {
            "mode": "solution", "equations": eqs,
            "x_claimed": claimed, "x_correct": correct,
            "substitutions": subs, "op_label": "",
            "student_result_line": None, "correct_result_line": None,
            "student_label": "YOUR SOLUTION", "correct_label": "WHERE THE LINES CROSS",
        }
    s_rows, c_rows = _rows(S), _rows(C)
    if not s_rows or not c_rows or len(s_rows[0]) < 3:
        raise SceneUnavailable("the claimed row is not an augmented row of three numbers")
    return "LineSystemCompare", {
        "mode": "row_op", "equations": eqs,
        "student_result_line": s_rows[-1][:3], "correct_result_line": c_rows[-1][:3],
        "op_label": (ext.steps[verdict.first_error_index].op_args.note or "row operation")
        if verdict.first_error_index is not None and verdict.first_error_index < len(ext.steps) else "row operation",
        "x_claimed": None, "x_correct": None, "substitutions": [],
        "student_label": "YOUR ROW", "correct_label": "THE ROW OPERATION",
    }


def _equations(env: dict[str, Val]) -> list[list[float]]:
    aug = env.get("Aug")
    if aug is not None and aug.is_matrix and aug.obj.cols >= 3:
        return [[float(sp.N(x)) for x in aug.obj.row(i)][:3] for i in range(aug.obj.rows)]
    A, b = env.get("A"), env.get("b")
    if A is not None and A.is_matrix and b is not None and b.is_matrix and A.obj.cols == 2:
        bv = _col(b.obj)
        return [
            [float(sp.N(A.obj[i, 0])), float(sp.N(A.obj[i, 1])), float(sp.N(bv[i]))]
            for i in range(min(A.obj.rows, bv.rows))
        ]
    return []


def _span(verdict, ext, env, S, C):
    vecs = _vector_list(env)
    if not vecs:
        raise SceneUnavailable("no set of vectors to sweep")
    ambient = len(vecs[0])
    if ambient not in (2, 3) or any(len(v) != ambient for v in vecs):
        raise SceneUnavailable("the vectors are not all 2D or all 3D")
    M = sp.Matrix.hstack(*[sp.Matrix(v) for v in vecs])
    actual = int(M.rank())
    claimed = _first_scalar(S)
    claimed_dim = int(float(sp.N(claimed))) if claimed is not None and _num(fmt_num(claimed)) is not None else len(vecs)
    if claimed_dim == actual:
        raise SceneUnavailable("the claimed dimension is the true one; no story")
    probe = _unreachable_probe(M, ambient)
    if probe is None:
        raise SceneUnavailable("could not verify a probe vector outside the span")
    return "SpanCompare", {
        "vectors": vecs, "claimed_dim": claimed_dim, "actual_dim": actual,
        "probe": probe, "ambient": ambient,
        "student_label": "YOUR CLAIM", "correct_label": "WHAT IS REACHED",
    }


def _vector_list(env: dict[str, Val]) -> list[list[float]]:
    V = env.get("V")
    if V is not None and V.is_matrix:
        M = V.obj
        if V.kind == "vector_list":
            return [[float(sp.N(x)) for x in M.row(i)] for i in range(M.rows)]
        return [[float(sp.N(x)) for x in M.col(j)] for j in range(M.cols)]
    out = []
    for key in ("v1", "v2", "v3", "u", "v", "w"):
        val = env.get(key)
        if val is not None and val.is_matrix and min(val.obj.shape) == 1:
            out.append([float(sp.N(x)) for x in _col(val.obj)])
    return out


def _unreachable_probe(M: sp.Matrix, ambient: int) -> Optional[list[float]]:
    """A vector VERIFIED outside the span - an animated search that could succeed is a lie."""
    rank = M.rank()
    for cand in [sp.eye(ambient).col(i) for i in range(ambient)]:
        if sp.Matrix.hstack(M, cand).rank() > rank:
            return [float(sp.N(x)) for x in cand]
    return None


def _static(verdict, ext, env, S, C):
    """The bottom of the ladder. Guards that cannot fail (SCENE_CATALOG.md T3)."""
    lines: list[dict[str, Any]] = []
    idx = verdict.first_error_index
    steps = sorted(ext.steps, key=lambda s: (s.page, s.reading_order))
    window = steps[max(0, (idx or 0) - 2): (idx or 0) + 1] if steps else []
    focus_line = 0
    for i, st in enumerate(window):
        disp = None
        if st.value is not None and st.value.rows:
            disp = [[fmt_num(x) for x in row] for row in st.value.rows]
        if disp and len(disp) <= 4 and len(disp[0]) <= 4:
            prefix = (st.claimed_expression or "").strip()[:12]
            lines.append({"kind": "matrix", "rows": disp, "prefix": f"{prefix} =" if prefix else ""})
        else:
            lines.append({"kind": "text", "text": (st.raw_text or "")[:60]})
        if idx is not None and st.id == verdict.step_id:
            focus_line = i
    if not lines:
        lines = [{"kind": "text", "text": "your work"}]
        focus_line = 0

    focus: dict[str, Any] = {"line": focus_line}
    cell = _first_differing_cell(S, C)
    if cell and lines[focus_line]["kind"] == "matrix":
        focus["cell"] = cell
    else:
        focus["chars"] = [0, min(len(lines[focus_line].get("text", "") or "x"), 40)]

    annotation = _annotation(verdict, S, C)
    params: dict[str, Any] = {
        "lines": lines[:6],
        "focus": focus,
        "annotation": annotation,
        "pairing": _pairing(verdict, env, S, C),
        "student_label": "WHAT YOU WROTE",
        "correct_label": "WHAT TO LOOK AT",
    }
    return "StaticStepHighlight", params


def _first_differing_cell(S: Optional[Val], C: Optional[Val]) -> Optional[list[int]]:
    a, b = _rows(S), _rows(C)
    if not a or not b:
        return None
    for i in range(min(len(a), len(b))):
        for j in range(min(len(a[i]), len(b[i]))):
            if abs(a[i][j] - b[i][j]) > 1e-9:
                return [i, j]
    return None


def _annotation(verdict: Verdict, S: Optional[Val], C: Optional[Val]) -> str:
    if verdict.error_id == "LA03":
        return "count the inner dimensions"
    if verdict.error_id == "LA18":
        return "one side is a number, the other is an arrow"
    if S is not None and C is not None and S.is_matrix and C.is_matrix and S.obj.shape != C.obj.shape:
        return "the shapes on the two sides do not match"
    return "look again at the marked entry"


def _pairing(verdict: Verdict, env: dict[str, Val], S: Optional[Val], C: Optional[Val]):
    """LA01's pairing sweep: which row/column did that entry come from? (T3)"""
    if verdict.error_id != "LA01":
        return None
    A, B = env.get("A"), env.get("B")
    cell = _first_differing_cell(S, C)
    if not (_is_2x2(A) and _is_2x2(B) and cell):
        return None
    s_rows, c_rows = _display(S), _display(C)
    return {
        "A_rows": _display(A), "B_rows": _display(B),
        "target": cell,
        "student_entry": s_rows[cell[0]][cell[1]],
        "correct_entry": c_rows[cell[0]][cell[1]],
        "wrong_source": "row",
    }


# --------------------------------------------------------------------------
# For the API layer
# --------------------------------------------------------------------------

def summarize(verdict: Verdict, plan_obj: Plan) -> dict[str, Any]:
    """The §4.9 output contract, JSON-ready."""
    return {
        "first_error_index": verdict.first_error_index,
        "step_id": verdict.step_id,
        "student_label": verdict.student_label,
        "confidence": verdict.confidence,
        "error_id": verdict.error_id,
        "student_value": val_json(verdict.student_value),
        "correct_value": val_json(verdict.correct_value),
        "scene_template": plan_obj.template,
        "scene_params": plan_obj.params,
        "positional_hint": plan_obj.hint,
        "flags": verdict.flags,
    }
