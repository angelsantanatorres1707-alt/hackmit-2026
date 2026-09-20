"""Hanna's six cases -- written by someone who was not looking at the code.

These are the cases I did not choose, which is the whole of their value. On the
first run three were right, two were missed and one was right with a useless
message. Each fix went at the CAUSE, not the case:

  TC2  adding two projections onto a non-orthogonal pair came back clean,
       because of a guard I had written that refused any projection when the
       span filled the space. The reasoning behind that guard was wrong --
       projecting onto R^n being the identity means the ANSWER is v, and a
       student who writes something else is perfectly detectable. Deleted, and
       replaced with the predicate it should have been: does this page talk
       about projecting at all?

  TC6  Gram-Schmidt. The gap was not "Gram-Schmidt is unsupported": properties
       were only ever tested against the GIVENS, so a claim about the set the
       student BUILT was never checked. Any construction problem had the same
       hole. Now the subject of a set-claim is the set the sentence names.

  TC5  correct work, and the answer was "nothing in this work disagrees with
       the problem as it was read" -- true, hedged, and no use to someone who
       was told they were wrong. Underneath it, the last step WAS checkable and
       was not being checked: verifying a claimed solution is substitution, not
       solving, and solving refuses singular and underdetermined systems.

    .venv/bin/python backend/tests/test_hanna_cases.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.extract import Extraction  # noqa: E402
from backend.hints import plan  # noqa: E402
from backend.verify import verify  # noqa: E402


def mat(r):  return {"kind": "matrix", "shape": [len(r), len(r[0])], "rows": r}
def vec(*x): return {"kind": "vector", "shape": [1, len(x)], "rows": [list(x)]}
def sca(x):  return {"kind": "scalar", "scalars": [x]}
def txt(t):  return {"kind": "text", "text": t}


def S(n, raw, value, op="unknown", final=False):
    return {"id": f"s{n}", "student_label": f"{n})", "page": 1, "reading_order": n,
            "raw_text": raw, "claimed_operation": op, "value": value,
            "is_final_answer": final, "parse_ok": True, "confidence": 0.95}


def G(sym, obj):
    return {"symbol": sym, "object": obj, "source": "printed", "confidence": 0.97}


def P(statement, topic, asks, givens, steps):
    return {"problem": {"present": True, "statement": statement, "topic": topic,
                        "asks_for": asks, "confidence": 0.95, "givens": givens},
            "steps": steps, "notes": [], "page_count": 1}


# What Hanna said the mistake was, written down before any of these fixes.
EXPECTED = {
    "TC1": ("s4", "LA02", "every calculation correct, but computed ABv not BAv"),
    "TC2": ("s4", "LA20", "the two projections cannot be added unless u1, u2 are orthogonal"),
    "TC3": ("s5", "LA30", "Col(A) is only a line inside R^2"),
    "TC4": ("s1", "LA07", "first error is step 1, the missing 1/det; step 2 carries it"),
    "TC5": (None, None, "completely correct -- must be affirmed, not hedged"),
    "TC6": ("s5", "LA41", "forgot to divide by u1.u1; the set produced is not orthogonal"),
}



HANNA = [
("TC1", P("Let A = [[1,2],[0,1]], B = [[0,-1],[1,0]], v = [2,1]^T. Compute BAv.",
   "Linear Algebra", "BAv",
   [G("A", mat([[1,2],[0,1]])), G("B", mat([[0,-1],[1,0]])), G("v", vec(2,1))],
   [S(1,"I applied B first because it is written first in BAv.", txt("applied B first")),
    S(2,"Bv = [[0,-1],[1,0]] [2,1]^T = [-1,2]^T.", vec(-1,2)),
    S(3,"A(Bv) = [[1,2],[0,1]] [-1,2]^T = [3,2]^T.", vec(3,2)),
    S(4,"Therefore, BAv = [3,2]^T.", vec(3,2), final=True)])),

("TC2", P("Let u1 = [1,0]^T, u2 = [1,1]^T, v = [1,2]^T. Find the orthogonal projection of v onto W = span{u1,u2}.",
   "projection", "the orthogonal projection of v onto W = span{u1,u2}",
   [G("u1", vec(1,0)), G("u2", vec(1,1)), G("v", vec(1,2))],
   [S(1,"proj_u1(v) = (v.u1 / u1.u1)u1 = [1,0]^T.", vec(1,0)),
    S(2,"proj_u2(v) = (v.u2 / u2.u2)u2 = (3/2)[1,1]^T = [3/2,3/2]^T.", vec(1.5,1.5)),
    S(3,"Since W is spanned by u1 and u2, I add the two projections.", txt("I add the two projections")),
    S(4,"proj_W(v) = [1,0]^T + [3/2,3/2]^T = [5/2,3/2]^T.", vec(2.5,1.5), final=True)])),

("TC3", P("Let A = [[2,4],[1,2]], b = [1,2]^T. Determine whether Ax = b has a solution.",
   "Linear Algebra", "whether Ax = b has a solution",
   [G("A", mat([[2,4],[1,2]])), G("b", vec(1,2))],
   [S(1,"The columns of A are [2,1]^T and [4,2]^T.", vec(2,1)),
    S(2,"Both columns are vectors in R^2.", txt("both columns are vectors in R^2")),
    S(3,"b = [1,2]^T is also in R^2.", vec(1,2)),
    S(4,"Since b is in the same space as the columns of A, b is in Col(A).", txt("b is in Col(A)")),
    S(5,"Therefore Ax = b has a solution.", txt("Ax = b has a solution"), final=True)])),

("TC4", P("Let A = [[2,1],[0,3]]. Find A^(-1).", "inverse", "A^-1",
   [G("A", mat([[2,1],[0,3]]))],
   [S(1,"For a 2x2 matrix, I swap the diagonal entries and negate the off-diagonal entries: A^-1 = [[3,-1],[0,2]].",
      mat([[3,-1],[0,2]]), "inverse"),
    S(2,"I checked by multiplying: A [[3,-1],[0,2]] = [[6,0],[0,6]].", mat([[6,0],[0,6]])),
    S(3,"Since this is almost the identity, I think my multiplication in step 2 must be where I went wrong.",
      txt("I think my multiplication in step 2 must be where I went wrong")),
    S(4,"So I would redo step 2.", txt("So I would redo step 2"), final=True)])),

("TC5", P("Let A = [[1,2],[2,4]], b = [3,6]^T. Determine whether Ax = b has a solution.",
   "Linear Algebra", "whether Ax = b has a solution",
   [G("A", mat([[1,2],[2,4]])), G("b", vec(3,6))],
   [S(1,"The second column of A is twice the first.", txt("second column is twice the first")),
    S(2,"Col(A) = span{[1,2]^T}.", txt("Col(A) = span{[1,2]^T}")),
    S(3,"b = [3,6]^T = 3[1,2]^T.", vec(3,6)),
    S(4,"Therefore b is in Col(A).", txt("b is in Col(A)")),
    S(5,"Therefore Ax = b has a solution.", txt("Ax = b has a solution")),
    S(6,"In fact, one solution is x = [3,0]^T.", vec(3,0), final=True)])),

("TC6", P("Use Gram-Schmidt to produce an orthogonal basis from v1 = [1,1,0]^T, v2 = [1,0,1]^T.",
   "Linear Algebra", "an orthogonal basis",
   [G("v1", vec(1,1,0)), G("v2", vec(1,0,1))],
   [S(1,"u1 = v1 = [1,1,0]^T.", vec(1,1,0)),
    S(2,"v2.u1 = 1.", sca(1.0), "dot_product"),
    S(3,"u2 = v2 - (v2.u1)u1.", txt("u2 = v2 - (v2.u1)u1")),
    S(4,"u2 = [1,0,1]^T - [1,1,0]^T = [0,-1,1]^T.", vec(0,-1,1)),
    S(5,"Therefore {[1,1,0]^T, [0,-1,1]^T} is the orthogonal basis.", vec(0,-1,1), final=True)])),
]

def main() -> int:
    bad = 0
    for cid, raw in HANNA:
        want_step, want_id, why = EXPECTED[cid]
        e = Extraction.model_validate(raw)
        v = verify(e)
        steps = sorted(e.steps, key=lambda s: (s.page, s.reading_order))
        got_step = steps[v.first_error_index].id if v.first_error_index is not None else None
        ok = got_step == want_step and v.error_id == want_id
        if got_step is not None:
            try:
                plan(v, e)
            except Exception as exc:  # noqa: BLE001
                ok = False
                why += f"  [PLAN FAILED: {type(exc).__name__}]"
        else:
            # Correct work must have something VERIFIED behind the all-clear,
            # or the affirmation is a blank cheque.
            if not any(r.status == "OK" for r in v.step_results):
                ok = False
                why += "  [nothing was actually verified]"
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {cid}  step={str(got_step):4s} "
              f"id={str(v.error_id):6s}  {why}")
    print(f"\n{len(HANNA) - bad}/{len(HANNA)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
