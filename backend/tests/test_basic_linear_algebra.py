"""Can it tell right from wrong on basic linear algebra?

Every case is a problem plus worked steps with a KNOWN answer: either a planted
mistake at a named step, or a fully correct derivation that must NOT be accused.
verify() is called directly -- no HTTP, no vision model, no render -- so the only
thing under test is the mathematics.

The false positives matter as much as the misses. A student shown a red mark on
correct work stops trusting the tool, and four of the bugs this file was written
to find were exactly that:

  * naming ONE eigenvalue of two was called wrong;
  * A(1,1) was called a shape error, because "(1,1)" on paper has no orientation
    and the extractor had to store a guess;
  * a wrong solution to Ax = b was never checked at all, because the branch was
    gated on topic == "solve_system" and the model labels uploads "Linear Algebra";
  * four conceptual claims (commuting, invertibility, perpendicularity, how many
    solutions) had no check behind them at all.

    .venv/bin/python backend/tests/test_basic_linear_algebra.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.extract import Extraction  # noqa: E402
from backend.verify import verify  # noqa: E402


def vec(*xs):    return {"kind": "vector", "shape": [1, len(xs)], "rows": [list(xs)]}
def mat(rows):   return {"kind": "matrix", "shape": [len(rows), len(rows[0])], "rows": rows}
def scalar(x):   return {"kind": "scalar", "scalars": [x]}
def text(t):     return {"kind": "text", "text": t}


def step(n, raw, value, *, op="unknown", final=False):
    return {"id": f"s{n}", "student_label": f"{n})", "page": 1, "reading_order": n,
            "raw_text": raw, "claimed_operation": op, "value": value,
            "is_final_answer": final, "parse_ok": True, "confidence": 0.95}


def given(sym, obj):
    return {"symbol": sym, "object": obj, "source": "printed", "confidence": 0.97}


def ext(statement, topic, asks, givens, steps):
    return Extraction.model_validate({
        "problem": {"present": True, "statement": statement, "topic": topic,
                    "asks_for": asks, "confidence": 0.95, "givens": givens},
        "steps": steps, "notes": [], "page_count": 1})


ARITHMETIC = []
C = ARITHMETIC   # (name, expect_wrong_step_id_or_None, extraction)

# ---- 1. matrix product ---------------------------------------------------
A, B = [[2,-1],[3,1]], [[4,0],[2,5]]
C.append(("product, right", None, ext("Compute AB.", "matrix_multiply", "AB",
    [given("A", mat(A)), given("B", mat(B))],
    [step(1,"A=[2 -1;3 1] B=[4 0;2 5]", mat(A)),
     step(2,"AB = [6 -5;14 5]", mat([[6,-5],[14,5]]), op="matrix_multiply", final=True)])))
C.append(("product, one entry wrong", "s2", ext("Compute AB.", "matrix_multiply", "AB",
    [given("A", mat(A)), given("B", mat(B))],
    [step(1,"A=[2 -1;3 1] B=[4 0;2 5]", mat(A)),
     step(2,"AB = [6 -5;2 5]", mat([[6,-5],[2,5]]), op="matrix_multiply", final=True)])))

# ---- 2. determinant ------------------------------------------------------
C.append(("det 2x2, right", None, ext("Compute det A.","determinant","det A",
    [given("A", mat([[3,5],[2,4]]))],
    [step(1,"A=[3 5;2 4]", mat([[3,5],[2,4]])),
     step(2,"det A = 12 - 10 = 2", scalar(2.0), op="determinant", final=True)])))
C.append(("det 2x2, added instead", "s2", ext("Compute det A.","determinant","det A",
    [given("A", mat([[3,5],[2,4]]))],
    [step(1,"A=[3 5;2 4]", mat([[3,5],[2,4]])),
     step(2,"det A = 12 + 10 = 22", scalar(22.0), op="determinant", final=True)])))
C.append(("det 3x3, right", None, ext("Compute det A.","determinant","det A",
    [given("A", mat([[1,2,3],[4,5,6],[7,8,10]]))],
    [step(1,"A given", mat([[1,2,3],[4,5,6],[7,8,10]])),
     step(2,"det A = -3", scalar(-3.0), op="determinant", final=True)])))
C.append(("det 3x3, wrong", "s2", ext("Compute det A.","determinant","det A",
    [given("A", mat([[1,2,3],[4,5,6],[7,8,10]]))],
    [step(1,"A given", mat([[1,2,3],[4,5,6],[7,8,10]])),
     step(2,"det A = 3", scalar(3.0), op="determinant", final=True)])))

# ---- 3. inverse ----------------------------------------------------------
C.append(("inverse, right", None, ext("Find A^-1.","inverse","A^-1",
    [given("A", mat([[4,7],[2,6]]))],
    [step(1,"A=[4 7;2 6]", mat([[4,7],[2,6]])),
     step(2,"det A = 10", scalar(10.0), op="determinant"),
     step(3,"A^-1 = [0.6 -0.7;-0.2 0.4]", mat([[0.6,-0.7],[-0.2,0.4]]), op="inverse", final=True)])))
C.append(("inverse, forgot 1/det", "s3", ext("Find A^-1.","inverse","A^-1",
    [given("A", mat([[4,7],[2,6]]))],
    [step(1,"A=[4 7;2 6]", mat([[4,7],[2,6]])),
     step(2,"det A = 10", scalar(10.0), op="determinant"),
     step(3,"A^-1 = [6 -7;-2 4]", mat([[6,-7],[-2,4]]), op="inverse", final=True)])))

# ---- 4. eigen ------------------------------------------------------------
E = [[2,1],[1,2]]
C.append(("eigenvector, right", None, ext("Is (1,1) an eigenvector of A?","eigen","eigenvector",
    [given("A", mat(E))],
    [step(1,"A=[2 1;1 2]", mat(E)),
     step(2,"v = (1,1) is an eigenvector", vec(1,1), op="eigenvector", final=True)])))
C.append(("eigenvector, wrong", "s2", ext("Is (1,0) an eigenvector of A?","eigen","eigenvector",
    [given("A", mat(E))],
    [step(1,"A=[2 1;1 2]", mat(E)),
     step(2,"v = (1,0) is an eigenvector", vec(1,0), op="eigenvector", final=True)])))
C.append(("eigenvalue, right", None, ext("Find an eigenvalue of A.","eigen","eigenvalue",
    [given("A", mat(E))],
    [step(1,"A=[2 1;1 2]", mat(E)),
     step(2,"lambda = 3", scalar(3.0), op="eigenvalue", final=True)])))
C.append(("eigenvalue, wrong", "s2", ext("Find an eigenvalue of A.","eigen","eigenvalue",
    [given("A", mat(E))],
    [step(1,"A=[2 1;1 2]", mat(E)),
     step(2,"lambda = 2", scalar(2.0), op="eigenvalue", final=True)])))

# ---- 5. dot / norm / projection -----------------------------------------
C.append(("dot product, right", None, ext("Compute u.v","dot_product","u . v",
    [given("u", vec(3,4)), given("v", vec(1,2))],
    [step(1,"u=(3,4) v=(1,2)", vec(3,4)),
     step(2,"u . v = 3 + 8 = 11", scalar(11.0), op="dot_product", final=True)])))
C.append(("dot product, wrong", "s2", ext("Compute u.v","dot_product","u . v",
    [given("u", vec(3,4)), given("v", vec(1,2))],
    [step(1,"u=(3,4) v=(1,2)", vec(3,4)),
     step(2,"u . v = 3 + 4 = 7", scalar(7.0), op="dot_product", final=True)])))
C.append(("norm, right", None, ext("Compute ||u||","norm","||u||",
    [given("u", vec(3,4))],
    [step(1,"u=(3,4)", vec(3,4)),
     step(2,"||u|| = 5", scalar(5.0), op="norm", final=True)])))
C.append(("norm, forgot sqrt", "s2", ext("Compute ||u||","norm","||u||",
    [given("u", vec(3,4))],
    [step(1,"u=(3,4)", vec(3,4)),
     step(2,"||u|| = 25", scalar(25.0), op="norm", final=True)])))
C.append(("projection, right", None, ext("Find proj_v(u).","projection","proj_v(u)",
    [given("u", vec(3,4)), given("v", vec(1,2))],
    [step(1,"u=(3,4) v=(1,2)", vec(3,4)),
     step(2,"proj = (2.2, 4.4)", vec(2.2,4.4), op="projection", final=True)])))
C.append(("projection, /||v|| not v.v", "s2", ext("Find proj_v(u).","projection","proj_v(u)",
    [given("u", vec(3,4)), given("v", vec(1,2))],
    [step(1,"u=(3,4) v=(1,2)", vec(3,4)),
     step(2,"proj = (4.92, 9.84)", vec(4.92,9.84), op="projection", final=True)])))

# ---- 6. transpose / sum / scalar multiple -------------------------------
C.append(("transpose, right", None, ext("Compute A^T.","transpose","A^T",
    [given("A", mat([[1,2],[3,4]]))],
    [step(1,"A=[1 2;3 4]", mat([[1,2],[3,4]])),
     step(2,"A^T = [1 3;2 4]", mat([[1,3],[2,4]]), op="transpose", final=True)])))
C.append(("transpose, wrong", "s2", ext("Compute A^T.","transpose","A^T",
    [given("A", mat([[1,2],[3,4]]))],
    [step(1,"A=[1 2;3 4]", mat([[1,2],[3,4]])),
     step(2,"A^T = [1 2;3 4]", mat([[1,2],[3,4]]), op="transpose", final=True)])))

# ---- 7. linear system ----------------------------------------------------
C.append(("2x2 system, right", None, ext("Solve Ax=b.","linear_system","x",
    [given("A", mat([[1,1],[1,-1]])), given("b", vec(6,2))],
    [step(1,"A, b given", mat([[1,1],[1,-1]])),
     step(2,"x = (4, 2)", vec(4,2), op="solve", final=True)])))
C.append(("2x2 system, wrong", "s2", ext("Solve Ax=b.","linear_system","x",
    [given("A", mat([[1,1],[1,-1]])), given("b", vec(6,2))],
    [step(1,"A, b given", mat([[1,1],[1,-1]])),
     step(2,"x = (2, 4)", vec(2,4), op="solve", final=True)])))

# ---- 8. property claims (the conceptual layer) ---------------------------
C.append(("shear claims angles preserved", "s2", ext(
    "T(e1)=(2,1), T(e2)=(1,2). Does T preserve angles?","Linear Algebra","conclusion",
    [given("T(e1)", vec(2,1)), given("T(e2)", vec(1,2))],
    [step(1,"|T(e1)| = |T(e2)| = sqrt5", scalar(2.2360679)),
     step(2,"both have the same length, so T preserves angles", text("so T preserves angles"), final=True)])))
C.append(("rotation claims angles preserved", None, ext(
    "T(e1)=(0,1), T(e2)=(-1,0). Does T preserve angles?","Linear Algebra","conclusion",
    [given("T(e1)", vec(0,1)), given("T(e2)", vec(-1,0))],
    [step(1,"lengths are both 1", scalar(1.0)),
     step(2,"T preserves angles", text("T preserves angles"), final=True)])))
C.append(("shear claims lengths preserved", "s2", ext(
    "T(e1)=(2,1), T(e2)=(1,2). Does T preserve lengths?","Linear Algebra","conclusion",
    [given("T(e1)", vec(2,1)), given("T(e2)", vec(1,2))],
    [step(1,"images computed", vec(2,1)),
     step(2,"T preserves lengths", text("T preserves lengths"), final=True)])))



CONCEPTUAL = []
C = CONCEPTUAL
M1, M2 = [[1,2],[3,4]], [[0,1],[1,0]]
SING = [[1,2],[2,4]]

C.append(("claims AB = BA (false)", "s2", ext("Is AB = BA?","Linear Algebra","conclusion",
    [given("A", mat(M1)), given("B", mat(M2))],
    [step(1,"A, B given", mat(M1)),
     step(2,"matrix multiplication is commutative, so AB = BA", text("AB = BA"), final=True)])))
C.append(("claims AB != BA (true)", None, ext("Is AB = BA?","Linear Algebra","conclusion",
    [given("A", mat(M1)), given("B", mat(M2))],
    [step(1,"A, B given", mat(M1)),
     step(2,"AB is not equal to BA", text("AB is not equal to BA"), final=True)])))
C.append(("claims A is invertible (det 0)", "s2", ext("Is A invertible?","Linear Algebra","conclusion",
    [given("A", mat(SING))],
    [step(1,"A = [1 2; 2 4]", mat(SING)),
     step(2,"A is invertible", text("A is invertible"), final=True)])))
C.append(("claims A is invertible (det 2)", None, ext("Is A invertible?","Linear Algebra","conclusion",
    [given("A", mat([[3,5],[2,4]]))],
    [step(1,"A = [3 5; 2 4]", mat([[3,5],[2,4]])),
     step(2,"A is invertible", text("A is invertible"), final=True)])))
C.append(("claims independent (they are not)", "s2", ext("Independent?","Linear Algebra","conclusion",
    [given("u", vec(1,2)), given("v", vec(2,4))],
    [step(1,"u=(1,2) v=(2,4)", vec(1,2)),
     step(2,"u and v are linearly independent", text("linearly independent"), final=True)])))
C.append(("claims independent (they are)", None, ext("Independent?","Linear Algebra","conclusion",
    [given("u", vec(1,2)), given("v", vec(2,1))],
    [step(1,"u=(1,2) v=(2,1)", vec(1,2)),
     step(2,"u and v are linearly independent", text("linearly independent"), final=True)])))
C.append(("claims u and v orthogonal (they are not)", "s2", ext("Orthogonal?","Linear Algebra","conclusion",
    [given("u", vec(1,2)), given("v", vec(2,1))],
    [step(1,"u.v = 4", scalar(4.0), op="dot_product"),
     step(2,"u and v are orthogonal", text("u and v are orthogonal"), final=True)])))
C.append(("claims u and v orthogonal (they are)", None, ext("Orthogonal?","Linear Algebra","conclusion",
    [given("u", vec(1,2)), given("v", vec(2,-1))],
    [step(1,"u.v = 0", scalar(0.0), op="dot_product"),
     step(2,"u and v are orthogonal", text("u and v are orthogonal"), final=True)])))
C.append(("claims infinitely many solutions (unique)", "s2", ext("How many solutions?","Linear Algebra","conclusion",
    [given("A", mat([[1,1],[1,-1]])), given("b", vec(6,2))],
    [step(1,"A, b given", mat([[1,1],[1,-1]])),
     step(2,"there are infinitely many solutions", text("infinitely many solutions"), final=True)])))
C.append(("claims unique solution (there is one)", None, ext("How many solutions?","Linear Algebra","conclusion",
    [given("A", mat([[1,1],[1,-1]])), given("b", vec(6,2))],
    [step(1,"A, b given", mat([[1,1],[1,-1]])),
     step(2,"there is a unique solution", text("unique solution"), final=True)])))
C.append(("claims (AB)^T = A^T B^T", "s2", ext("Compute (AB)^T.","transpose","(AB)^T",
    [given("A", mat(M1)), given("B", mat(M2))],
    [step(1,"A, B given", mat(M1)),
     step(2,"(AB)^T = A^T B^T = [3 1; 4 2]", mat([[3,1],[4,2]]), op="transpose", final=True)])))
C.append(("claims rank 2 (rank is 1)", "s2", ext("What is the rank?","Linear Algebra","rank",
    [given("u", vec(1,2)), given("v", vec(2,4))],
    [step(1,"u=(1,2) v=(2,4)", vec(1,2)),
     step(2,"the span has dimension 2", text("dimension 2"), final=True)])))
C.append(("3x3 system, wrong", "s2", ext("Solve Ax=b.","Linear Algebra","x",
    [given("A", mat([[2,1,0],[1,3,1],[0,1,2]])), given("b", vec(3,5,3))],
    [step(1,"A, b given", mat([[2,1,0],[1,3,1],[0,1,2]])),
     step(2,"x = (1, 2, 1)", vec(1,2,1), op="solve", final=True)])))
C.append(("3x3 system, right", None, ext("Solve Ax=b.","Linear Algebra","x",
    [given("A", mat([[2,1,0],[1,3,1],[0,1,2]])), given("b", vec(3,5,3))],
    [step(1,"A, b given", mat([[2,1,0],[1,3,1],[0,1,2]])),
     step(2,"x = (1, 1, 1)", vec(1,1,1), op="solve", final=True)])))
C.append(("matrix-vector product, wrong", "s2", ext("Compute Au.","matrix_multiply","Au",
    [given("A", mat([[1,2],[3,4]])), given("u", vec(1,1))],
    [step(1,"A, u given", mat([[1,2],[3,4]])),
     step(2,"Au = (3, 8)", vec(3,8), op="matrix_multiply", final=True)])))
C.append(("matrix-vector product, right", None, ext("Compute Au.","matrix_multiply","Au",
    [given("A", mat([[1,2],[3,4]])), given("u", vec(1,1))],
    [step(1,"A, u given", mat([[1,2],[3,4]])),
     step(2,"Au = (3, 7)", vec(3,7), op="matrix_multiply", final=True)])))
C.append(("claims det(A+B) = detA + detB", "s3", ext("Compute det(A+B).","determinant","det(A+B)",
    [given("A", mat(M1)), given("B", mat(M2))],
    [step(1,"det A = -2", scalar(-2.0), op="determinant"),
     step(2,"det B = -1", scalar(-1.0), op="determinant"),
     step(3,"det(A+B) = -2 + -1 = -3", scalar(-3.0), op="determinant", final=True)])))


CASES = ARITHMETIC + CONCEPTUAL


def main() -> int:
    ok = bad = 0
    for name, expect, e in CASES:
        try:
            v = verify(e)
        except Exception as exc:  # noqa: BLE001
            print(f"  CRASH  {name:42s} {type(exc).__name__}: {exc}")
            bad += 1
            continue
        got = None
        if v.first_error_index is not None:
            ordered = sorted(e.steps, key=lambda s: (s.page, s.reading_order))
            got = ordered[v.first_error_index].id
        hit = got == expect
        ok += hit
        bad += not hit
        print(f"  {'PASS' if hit else 'FAIL'}  {name:42s} "
              f"expected={expect or '(no error)':<11s} got={got or '(no error)':<11s} "
              f"{v.error_id or ''}")
    print(f"\n{ok}/{len(CASES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
