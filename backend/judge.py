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

import json
import os
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

Another system has already checked every step's ARITHMETIC exactly and found nothing
wrong with the numbers. Your job is the part it cannot do: decide whether the student
has nonetheless reached a FALSE CONCLUSION, and name the misconception behind it.

This is the case you exist for. A student computes a transformation perfectly and then
writes "both basis vectors have the same length, so it preserves angles". Every number
is right. The inference is not.

Rules, in order of importance:

1. If nothing is actually wrong, say so. Returning wrong=false is a correct and
   expected answer, and it is much better than inventing a fault. A student shown a
   red mark on correct work stops trusting this tool.
2. Blame the FIRST step that is wrong, not a later one that merely repeats it.
3. Judge against the GIVENS, not against how you would have solved it. A different
   valid method is not an error.
4. A step you cannot evaluate is not thereby wrong.
5. Pick the code that names the actual misconception. If none of them fit but the work
   IS wrong, use error_id null and still name the step.

Return ONLY this JSON object:

{"wrong": bool,
 "step_id": "s3" or null,
 "error_id": "LA27" or null,
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

    # --- the veto -------------------------------------------------------
    # sympy evaluated this step against the givens and it checked out. No
    # model opinion overrides that.
    proved_ok = {r.step_id for r in (verdict.step_results or []) if r.status == "OK"}
    if step_id in proved_ok:
        return None
    if steps[index].crossed_out:
        return None

    error_id = raw.get("error_id")
    if error_id not in CODES:
        error_id = None

    # --- the second veto ------------------------------------------------
    # The model proposes a code; the mathematics confirms it. Asked whether a
    # conclusion is wrong, a model will pattern-match the SHAPE of the problem:
    # shown the "equal lengths do not imply preserved angles" misconception, it
    # recited it over a genuine rotation, which preserves angles perfectly. So
    # for every code with a decidable test, run the test -- and if the property
    # the student asserted actually holds, the student was right and the
    # judgement is thrown away.
    if error_id is not None:
        from .verify import property_holds

        if property_holds(error_id, verdict.givens or {}) is True:
            return None

    return Judgement(
        step_id=step_id,
        step_index=index,
        error_id=error_id,
        misconception=str(raw.get("misconception") or "")[:200],
        confidence=str(raw.get("confidence") or "medium"),
        meta=meta if isinstance(meta, dict) else {},
    )
