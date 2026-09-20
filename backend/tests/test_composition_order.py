"""Correct arithmetic, wrong operation sequence.

The architectural case: every line on the page is numerically right, and the
student has still answered a different question. SymPy marks each step OK --
which used to mean no model judgement could touch any of them -- so the work
came back clean.

The veto is now split by axis. SymPy stays authoritative over the NUMBERS; the
reasoning layer may still say a verified step is the wrong move for the task.
That licence is deliberately narrow: it applies only where the mismatch can be
settled by recomputation, which today means composition order. Everything else
the model proposes is recorded as an advisory note and shown to nobody.

No network: the provider is stubbed, so this runs offline and tests the
decision logic rather than the model's mood.

    .venv/bin/python backend/tests/test_composition_order.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend import judge as judge_mod  # noqa: E402
from backend import vision_providers  # noqa: E402
from backend.extract import Extraction  # noqa: E402
from backend.verify import verify  # noqa: E402

A = [[1, 1], [0, 1]]
B = [[0, -1], [1, 0]]
V = [1, 1]
# A*v = (2,1);  B*(A*v) = (-1,2)  <- BAv, what was asked
# B*v = (-1,1); A*(B*v) = (0,1)   <- ABv, the other order


def mat(r):  return {"kind": "matrix", "shape": [len(r), len(r[0])], "rows": r}
def vec(*x): return {"kind": "vector", "shape": [1, len(x)], "rows": [list(x)]}


def step(n, raw, value, final=False):
    return {"id": f"s{n}", "student_label": f"{n})", "page": 1, "reading_order": n,
            "raw_text": raw, "claimed_operation": "unknown", "value": value,
            "is_final_answer": final, "parse_ok": True, "confidence": 0.95}


def ext(steps):
    return Extraction.model_validate({
        "problem": {"present": True, "statement": "Compute BAv.",
                    "topic": "Linear Algebra", "asks_for": "BAv", "confidence": 0.95,
                    "givens": [
                        {"symbol": "A", "object": mat(A), "source": "printed", "confidence": 0.97},
                        {"symbol": "B", "object": mat(B), "source": "printed", "confidence": 0.97},
                        {"symbol": "v", "object": vec(*V), "source": "printed", "confidence": 0.97}]},
        "steps": steps, "notes": [], "page_count": 1})


WRONG_ORDER_LABELLED = ext([
    step(1, "Bv = (0 -1 ; 1 0)(1 ; 1) = (-1 ; 1).", vec(-1, 1)),
    step(2, "A(Bv) = (1 1 ; 0 1)(-1 ; 1) = (0 ; 1).", vec(0, 1)),
    step(3, "Therefore BAv = (0 ; 1)", vec(0, 1), final=True)])

WRONG_ORDER_HONEST = ext([          # every step OK; only the TASK is wrong
    step(1, "Bv = (-1 ; 1).", vec(-1, 1)),
    step(2, "A(Bv) = (0 ; 1).", vec(0, 1)),
    step(3, "ABv = (0 ; 1)", vec(0, 1), final=True)])

PARAPHRASED = ext([                 # never names an order, or a matrix, at all
    step(1, "First I rotate the vector: (-1 ; 1).", vec(-1, 1)),
    step(2, "Then I shear that result: (0 ; 1).", vec(0, 1)),
    step(3, "So the answer is (0 ; 1).", vec(0, 1), final=True)])

CORRECT = ext([
    step(1, "Av = (1 1 ; 0 1)(1 ; 1) = (2 ; 1).", vec(2, 1)),
    step(2, "B(Av) = (0 -1 ; 1 0)(2 ; 1) = (-1 ; 2).", vec(-1, 2)),
    step(3, "Therefore BAv = (-1 ; 2)", vec(-1, 2), final=True)])


def reply(**kw):
    """A stubbed model answer."""
    base = {"wrong": True, "step_id": "s1", "claim_kind": "composition_order",
            "calculation_valid": True, "relevant_to_target": False,
            "error_id": "LA02", "requested_expression": "B*A*v",
            "student_expression": "A*B*v",
            "misconception": "applied B before A, so computed ABv",
            "confidence": "high"}
    base.update(kw)
    return base


def judged(extraction, **kw):
    """Run verify + judge with the provider stubbed. -> (verdict, judgement)."""
    v = verify(extraction)
    real = vision_providers.extract_json
    vision_providers.extract_json = lambda *a, **k: (reply(**kw), {"model": "stub"})
    try:
        return v, judge_mod.judge(extraction, v)
    finally:
        vision_providers.extract_json = real


def status_of(v, sid):
    return next((r.status for r in v.step_results if r.step_id == sid), None)


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# -- the required test ------------------------------------------------------

@case("REQUIRED: arithmetic verified, composition order still flagged")
def _():
    v = verify(WRONG_ORDER_LABELLED)
    assert status_of(v, "s1") == "OK", "Bv is correct and must verify"
    assert status_of(v, "s2") == "OK", "A(Bv) is correct and must verify"
    assert v.first_error_index is not None, "a conceptual error must still be found"
    assert v.error_id == "LA02", f"expected LA02, got {v.error_id}"


@case("REQUIRED: all three steps OK, judge still allowed to flag the task")
def _():
    v, j = judged(WRONG_ORDER_HONEST)
    assert all(status_of(v, s) == "OK" for s in ("s1", "s2", "s3")), \
        "every step is arithmetically correct here"
    assert v.first_error_index is None, "sympy alone finds nothing, by design"
    assert j is not None, "the judgement must NOT be discarded"
    assert j.advisory is False, f"must reach the student, got advisory: {j.advisory_reason}"
    assert j.error_id == "LA02"
    assert j.claim_kind == "composition_order"
    assert j.calculation_valid is True, "sympy's answer, not the model's"
    assert j.requested_expression == "B*A*v", j.requested_expression
    assert j.student_expression == "A*B*v", j.student_expression


@case("PARAPHRASE: order inferred from the values, never named on the page")
def _():
    v, j = judged(PARAPHRASED, requested_expression=None, student_expression=None)
    assert j is not None and j.advisory is False, "must still be confirmed"
    # Derived here, not taken from the model -- it sent null for both.
    assert j.requested_expression == "B*A*v"
    assert j.student_expression == "A*B*v"


# -- controls: the work is right and must stay unmarked ---------------------

@case("CONTROL: correct BAv is not flagged, even when the model says it is")
def _():
    v, j = judged(CORRECT)
    assert v.first_error_index is None, "sympy must find nothing"
    assert j is None or j.advisory is True, \
        "a correct answer must never get a red mark from the model"


# -- the veto must still bite ----------------------------------------------

@case("VETO: an ARITHMETIC claim against a verified step is discarded")
def _():
    v, j = judged(WRONG_ORDER_HONEST, claim_kind="arithmetic",
                  calculation_valid=False, error_id=None)
    assert j is None, "sympy stays authoritative over the numbers"


@case("VETO: low confidence never reaches the student")
def _():
    v, j = judged(WRONG_ORDER_HONEST, confidence="medium")
    assert j is not None, "still recorded"
    assert j.advisory is True, "but not applied"


@case("VETO: an unverifiable conceptual claim is advisory only")
def _():
    v, j = judged(WRONG_ORDER_HONEST, claim_kind="other", error_id=None,
                  misconception="this reasoning seems suspicious")
    assert j is not None and j.advisory is True, \
        "a vague claim must never mark the work wrong"


@case("VETO: composition_order that recomputation cannot confirm is advisory")
def _():
    v, j = judged(CORRECT, claim_kind="composition_order")
    assert j is None or j.advisory is True


def main() -> int:
    bad = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as exc:
            print(f"  FAIL  {name}\n          {exc}")
            bad += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {name}\n          {type(exc).__name__}: {exc}")
            bad += 1
    print(f"\n{len(CASES) - bad}/{len(CASES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
