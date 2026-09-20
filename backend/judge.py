"""The model's opinion about WHICH step is wrong and WHY -- with sympy holding a veto.

Everything else in this pipeline is deliberately deterministic. The vision
model is a transcriber and is forbidden from reasoning about the mathematics;
sympy checks the arithmetic exactly; the misconception is then named by
hand-written checks in verify.py.

That last layer is regex over the student's own sentences, and it only knows
the phrasings someone wrote down. "The system has no solution" matched;
"Ax = b has a solution" did not, so a page whose every number was right and
whose conclusion was false came back as "nothing in this work disagrees". There
is always another phrasing. Generalising over how a student says a thing is the
one job here a language model is actually better at than a regex.

So this module runs ONLY when the deterministic pass found nothing, and it is
boxed in hard:

  * It never sees the photograph. It reads the extracted givens and steps, so
    it cannot re-transcribe the page into something more convenient.
  * It chooses a taxonomy CODE, not words. The hint the student reads is the
    pre-written, already-linted sentence for that code. Nothing the model
    writes reaches the screen -- its reasoning goes to notes, for us.
  * sympy has a veto. A step the deterministic checker PROVED correct cannot be
    blamed, whatever the model says. This is the guarantee that matters: a red
    mark on correct work is the worst thing this product can do, and no model
    output can cause one.

Disable with NOEMA_JUDGE=0.
"""

from __future__ import annotations

import itertools
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

# Codes the model may choose. Deliberately only the ones with a hint AND a
# scene: a code we cannot draw or safely phrase is not an option worth having.
CODES: dict[str, str] = {
    "LA01": "matrix product built by pairing rows with rows instead of rows with columns",
    "LA02": "the two matrices multiplied in the wrong order (BA where AB was asked)",
    "LA03": "shapes that do not conform multiplied anyway",
    "LA04": "2x2 determinant computed as ad + bc instead of ad - bc",
    "LA05": "cofactor expansion with every sign taken as plus",
    "LA06": "rows swapped during reduction without flipping the sign of the determinant",
    "LA07": "inverse written as the adjugate with the 1/det factor dropped",
    "LA08": "inverse with the off-diagonal negated but the diagonal not swapped",
    "LA09": "a vector claimed to be an eigenvector that is not one",
    "LA10": "a sign slip in the characteristic polynomial",
    "LA11": "normalised by the wrong divisor",
    "LA12": "an arithmetic slip inside a row operation",
    "LA13": "a row scaled but the augmented column left behind",
    "LA14": "a dependent set of vectors claimed to be independent",
    "LA15": "the dimension of a span overclaimed",
    "LA16": "(AB)^T expanded as A^T B^T",
    "LA17": "cross product with the j-component sign dropped",
    "LA18": "a dot product reported as a vector",
    "LA19": "projection divided by |v| instead of v.v",
    "LA20": "projections onto a non-orthogonal basis simply added together",
    "LA21": "a claimed projection whose residual is not perpendicular to the subspace",
    "LA22": "claiming the transformation preserves ANGLES when it does not "
            "(equal lengths on the basis do not imply preserved angles)",
    "LA23": "claiming the transformation preserves LENGTHS when it does not",
    "LA24": "claiming AB = BA, that matrix multiplication commutes",
    "LA25": "claiming a matrix is invertible when its determinant is zero, or singular when it is not",
    "LA26": "claiming two vectors are orthogonal when their dot product is not zero",
    "LA27": "the wrong conclusion about HOW MANY solutions a system has -- including "
            "claiming a solution exists when the system is inconsistent, confusing the "
            "column space with the whole ambient space, or miscounting free variables",
    "LA28": "a genuine eigenvector paired with the wrong eigenvalue",
    "LA29": "coordinates in a basis read off as the vector's own entries instead of "
            "the weights that rebuild it",
    "LA30": "a misunderstanding of SPAN -- assuming Ax can reach anywhere in the ambient "
            "space when A's columns are dependent, so the column space is only a line "
            "(or plane) and b lies off it",
}

SYSTEM = """\
You are a linear algebra teaching assistant reading a transcription of one student's work.

Another system has already checked every step's ARITHMETIC exactly. Where a step is
marked arithmetic_already_verified_correct, its NUMBERS are right and you must not say
otherwise. You are judging a different question: whether the work, taken in order,
actually answers the problem that was asked.

A step can be arithmetically perfect and still be the wrong move. That is the case you
exist for, and there are two separate judgements to make about each step:

  calculation_valid   -- are the numbers right?   (already settled; do not contradict it)
  relevant_to_target  -- does this step advance the operation the PROBLEM asked for?

Worked example. The problem asks for BAv, which means: apply A to v first, then B.
The student computes Bv, then A(Bv). Both lines are arithmetically flawless. But the
student has applied B first, so they have computed ABv -- a different composition.
calculation_valid is true for both steps; relevant_to_target is false; the misconception
is matrix composition order.

Rules, in order of importance:

1. If nothing is actually wrong, say so. wrong=false is a correct and expected answer,
   and it is far better than inventing a fault. A student shown a red mark on correct
   work stops trusting this tool.
2. Never say a verified calculation is wrong. If you think the numbers are bad on a step
   marked arithmetic_already_verified_correct, you have misread it -- say wrong=false.
3. claim_kind says which axis your complaint lives on:
     "arithmetic"         -- a number is wrong. Only for steps NOT already verified.
     "composition_order"  -- the numbers are right but the operations were applied in
                             the wrong order for what was asked. Use this ONLY when you
                             can name both sequences concretely.
     "other"              -- any other conceptual fault (a false conclusion, a property
                             that does not hold, a claim about a span or a basis).
4. For "composition_order" you must fill in requested_expression and student_expression
   as explicit products, e.g. "B*A*v" and "A*B*v". A checker recomputes both and will
   throw your answer away if they do not match what is on the page. Guessing costs you
   the diagnosis.
5. Blame the FIRST step that goes wrong, not a later one that merely carries it.
6. Judge against the GIVENS and the stated task, not against how you would have solved
   it. A different valid method is not an error.
7. Say confidence "high" only when you could defend the diagnosis line by line.
8. Pick the taxonomy code that names the misconception. If none fits but the work IS
   wrong, use error_id null and still describe it -- a diagnosis with no code is useful.

Return ONLY this JSON object:

{"wrong": bool,
 "step_id": "s3" or null,
 "claim_kind": "arithmetic" | "composition_order" | "other",
 "calculation_valid": bool,
 "relevant_to_target": bool,
 "error_id": "LA02" or null,
 "requested_expression": "B*A*v" or null,
 "student_expression": "A*B*v" or null,
 "misconception": "one short sentence, for the developers, not the student",
 "confidence": "high" | "medium" | "low"}
"""


@dataclass
class Judgement:
    step_id: str
    step_index: int
    error_id: Optional[str]
    misconception: str
    confidence: str
    meta: dict
    claim_kind: str = "other"
    calculation_valid: Optional[bool] = None   # sympy's answer, never the model's
    relevant_to_target: Optional[bool] = None
    requested_expression: Optional[str] = None
    student_expression: Optional[str] = None
    visualization_supported: bool = False
    # An advisory judgement is recorded for us and never shown to the student:
    # it is a diagnosis we could not verify structurally, or one the model was
    # not confident about. It must never produce a red mark.
    advisory: bool = True
    advisory_reason: str = ""


def enabled() -> bool:
    return (os.environ.get("NOEMA_JUDGE", "1").strip().lower()
            not in {"0", "false", "no", "off"})


def _obj_brief(obj: Any) -> Any:
    """A step's value, small enough to put in a prompt."""
    if obj is None:
        return None
    kind = getattr(obj, "kind", None)
    if kind == "text":
        return getattr(obj, "text", None)
    for attr in ("rows", "scalars", "exact"):
        v = getattr(obj, attr, None)
        if v:
            return v
    return None


def _payload(ext, verdict) -> str:
    provable = {r.step_id for r in (verdict.step_results or []) if r.status == "OK"}
    steps = sorted(ext.steps, key=lambda s: (s.page, s.reading_order))
    return json.dumps({
        "problem": {
            "statement": ext.problem.statement,
            "topic": ext.problem.topic,
            "asks_for": ext.problem.asks_for,
            "givens": [{"symbol": g.symbol, "value": _obj_brief(g.object)}
                       for g in (ext.problem.givens or [])],
        },
        "steps": [{
            "id": s.id,
            "wrote": s.raw_text,
            "value": _obj_brief(s.value),
            "crossed_out": s.crossed_out,
            "arithmetic_already_verified_correct": s.id in provable,
        } for s in steps if not s.crossed_out],
        "codes": CODES,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Structural confirmation
#
# The one conceptual claim this version lets past a verified step is "you
# applied these in the wrong order", and it is allowed ONLY because it can be
# settled by recomputation rather than taken on trust. The model's own account
# of the two expressions is never used as evidence: both are derived here from
# the givens and from the value the student actually reached.
# ---------------------------------------------------------------------------

def _step_column(step):
    """A step's value as a sympy column, or None."""
    import sympy as sp

    rows = getattr(getattr(step, "value", None), "rows", None)
    if not rows:
        return None
    try:
        M = sp.Matrix(rows)
        if M.rows == 1:
            M = M.T
        return M if M.cols == 1 else None
    except Exception:  # noqa: BLE001
        return None


def _expr_text(order, vec_name) -> str:
    return "*".join(list(order) + ([vec_name] if vec_name else []))


def _confirm_composition_order(ext, verdict):
    """-> (requested_expression, student_expression), or None when unconfirmed.

    None covers both "we cannot tell" and "they answered the question asked",
    and in either case no red mark is produced.
    """
    import sympy as sp

    env = verdict.givens or {}
    mats: dict = {}
    vec_name, vec = None, None
    for name, val in env.items():
        try:
            if val is None or not val.is_matrix:
                continue
            M = val.obj
            if M.rows > 1 and M.rows == M.cols:
                mats[name] = M
            elif vec is None and min(M.shape) == 1 and max(M.shape) > 1:
                # "(1,1)" on the page says nothing about row versus column.
                vec_name, vec = name, (M.T if M.rows == 1 else M)
        except Exception:  # noqa: BLE001
            continue
    if not (2 <= len(mats) <= 3) or vec is None:
        return None

    names = sorted(mats)
    perms = list(itertools.permutations(names))
    text = " ".join(filter(None, [getattr(ext.problem, "asks_for", "") or "",
                                  getattr(ext.problem, "statement", "") or ""]))

    def _find(with_vector: bool):
        for perm in perms:
            parts = [re.escape(n) for n in perm]
            if with_vector and vec_name:
                parts.append(re.escape(vec_name))
            pat = r"\b" + r"\s*\*?\s*".join(parts)
            if re.search(pat, text):
                return perm
        return None

    requested = _find(True) or _find(False)
    if requested is None:
        return None

    def value_of(perm):
        out = vec
        for name in reversed(perm):      # B*A*v applies A first
            out = mats[name] * out
        return out

    steps = [st for st in sorted(ext.steps, key=lambda s: (s.page, s.reading_order))
             if not st.crossed_out]
    final = None
    for st in reversed(steps):
        col = _step_column(st)
        if col is not None and col.rows == vec.rows:
            final = col
            break
    if final is None:
        return None

    try:
        if sp.simplify(final - value_of(requested)).is_zero_matrix:
            return None                  # they answered the question asked
    except Exception:  # noqa: BLE001
        return None

    for perm in perms:
        if perm == requested:
            continue
        try:
            if sp.simplify(final - value_of(perm)).is_zero_matrix:
                return _expr_text(requested, vec_name), _expr_text(perm, vec_name)
        except Exception:  # noqa: BLE001
            continue
    return None


def judge(ext, verdict) -> Optional[Judgement]:
    """-> a Judgement the caller may apply, or None to leave the verdict alone."""
    if not enabled():
        return None
    steps = [s for s in sorted(ext.steps, key=lambda s: (s.page, s.reading_order))]
    if len(steps) < 2:
        return None

    from . import vision_providers
    try:
        raw, meta = vision_providers.extract_json([], SYSTEM, _payload(ext, verdict))
    except Exception as exc:  # noqa: BLE001
        # The deterministic verdict stands. This layer is an improvement on
        # "nothing found", never a way for the request to fail.
        return None

    if not isinstance(raw, dict) or not raw.get("wrong"):
        return None

    step_id = raw.get("step_id")
    index = next((i for i, s in enumerate(steps) if s.id == step_id), None)
    if index is None:
        return None

    claim_kind = raw.get("claim_kind")
    if claim_kind not in ("arithmetic", "composition_order", "other"):
        claim_kind = "other"
    on_verified = step_id in {r.step_id for r in (verdict.step_results or [])
                              if r.status == "OK"}

    # --- veto 1: sympy is authoritative over ARITHMETIC ------------------
    # Narrowed from "a verified step cannot be blamed at all". A verified step
    # cannot be called numerically wrong -- but it can still be the wrong move
    # for the task, which is a claim about relevance, not about the numbers.
    if claim_kind == "arithmetic" and on_verified:
        return None
    if steps[index].crossed_out:
        return None

    error_id = raw.get("error_id")
    if error_id not in CODES:
        error_id = None          # keep the diagnosis; only the NAME is dropped

    # --- veto 2: a named code with a decidable test must be confirmed ----
    # The model recited "equal lengths do not imply preserved angles" over a
    # genuine rotation. If the property it accuses the student of breaking
    # actually holds, the student was right.
    if error_id is not None:
        from .verify import property_holds

        if property_holds(error_id, verdict.givens or {}) is True:
            return None

    confidence = str(raw.get("confidence") or "medium").strip().lower()
    requested_expr = student_expr = None
    advisory, reason = True, ""

    # --- what may reach the student -------------------------------------
    # Everything else is recorded and shown to nobody. A diagnosis we cannot
    # check is a note for us, not a red mark on someone's homework.
    if claim_kind == "composition_order":
        confirmed = _confirm_composition_order(ext, verdict)
        if confirmed is None:
            reason = "composition order not confirmed by recomputation"
        else:
            requested_expr, student_expr = confirmed
            if confidence == "high":
                advisory = False
            else:
                reason = f"composition order confirmed but confidence is {confidence}"
    elif claim_kind == "other":
        from .verify import property_holds

        if error_id is None:
            reason = "no taxonomy code, so nothing to check the claim against"
        elif property_holds(error_id, verdict.givens or {}) is not False:
            reason = f"{error_id} has no decidable test on these givens"
        elif confidence != "high":
            reason = f"{error_id} confirmed but confidence is {confidence}"
        else:
            advisory = False
    else:  # arithmetic, on a step sympy could not reach
        reason = "an arithmetic claim sympy could not independently confirm"

    return Judgement(
        step_id=step_id,
        step_index=index,
        error_id=error_id,
        misconception=str(raw.get("misconception") or "")[:200],
        confidence=confidence,
        meta=meta if isinstance(meta, dict) else {},
        claim_kind=claim_kind,
        # sympy's answer, never the model's: it is told not to contradict this
        # and this is where that is enforced rather than hoped for.
        calculation_valid=True if on_verified else raw.get("calculation_valid"),
        relevant_to_target=bool(raw.get("relevant_to_target", True)),
        requested_expression=requested_expr,
        student_expression=student_expr,
        visualization_supported=error_id is not None,
        advisory=advisory,
        advisory_reason=reason,
    )
