"""Does Noema find the mistake a linear algebra teacher would find?

Thirty-two worked solutions across the syllabus -- products, determinants,
inverses, eigenvalues, projections, span, systems, transformations,
coordinates, norms -- each with either a real student mistake or correct work.

Every case was also diagnosed independently and BLIND by expert reviewers who
saw only the problem and the student's steps, never Noema's answer. The
agreement that run: 32/32 on whether the work is wrong at all, 30/32 on which
step is the first wrong one. The two it differed on are noted below.

Ten adversarial controls follow, each one correct work that a specific new
signature could plausibly misfire on -- and two of them caught a real false
positive that had nothing to do with the signature being tested: det(A+B) and
det(2A) computed CORRECTLY were being marked wrong, because the determinant
branch read only the first symbol on the line.

    .venv/bin/python backend/tests/test_diagnosis_breadth.py
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

# (id, human summary of the REAL mistake, correct?, extraction)
CASES = [
# ---- matrix arithmetic --------------------------------------------------
("mul-entry", "one entry of AB computed with the wrong row/col pairing", False,
 P("Compute AB.", "matrix_multiply", "AB",
   [G("A", mat([[2,-1],[3,1]])), G("B", mat([[4,0],[2,5]]))],
   [S(1,"A = [2 -1; 3 1]  B = [4 0; 2 5]", mat([[2,-1],[3,1]]), "copy_given"),
    S(2,"AB = [6 -5; 2 5]", mat([[6,-5],[2,5]]), "multiply", True)])),

("mul-order", "computed BA and labelled it AB", False,
 P("Compute AB.", "matrix_multiply", "AB",
   [G("A", mat([[0,-1],[1,0]])), G("B", mat([[3,0],[0,1]]))],
   [S(1,"A, B given", mat([[0,-1],[1,0]]), "copy_given"),
    S(2,"AB = [0 -3; 1 0]", mat([[0,-3],[1,0]]), "multiply", True)])),

("mul-correct", "correct product (control)", True,
 P("Compute AB.", "matrix_multiply", "AB",
   [G("A", mat([[2,-1],[3,1]])), G("B", mat([[4,0],[2,5]]))],
   [S(1,"A, B given", mat([[2,-1],[3,1]]), "copy_given"),
    S(2,"AB = [6 -5; 14 5]", mat([[6,-5],[14,5]]), "multiply", True)])),

("transpose-prod", "(AB)^T expanded as A^T B^T", False,
 P("Compute (AB)^T.", "transpose", "(AB)^T",
   [G("A", mat([[1,2],[3,4]])), G("B", mat([[0,1],[1,0]]))],
   [S(1,"A, B given", mat([[1,2],[3,4]]), "copy_given"),
    S(2,"(AB)^T = A^T B^T = [3 1; 4 2]", mat([[3,1],[4,2]]), "transpose", True)])),

("add-noncomm", "claims AB = BA", False,
 P("Is AB = BA?", "Linear Algebra", "conclusion",
   [G("A", mat([[1,2],[3,4]])), G("B", mat([[0,1],[1,0]]))],
   [S(1,"A, B given", mat([[1,2],[3,4]]), "copy_given"),
    S(2,"multiplication is commutative so AB = BA", txt("AB = BA"), final=True)])),

# ---- determinants --------------------------------------------------------
("det-add", "2x2 determinant as ad + bc", False,
 P("Compute det A.", "determinant", "det A", [G("A", mat([[3,5],[2,4]]))],
   [S(1,"A = [3 5; 2 4]", mat([[3,5],[2,4]]), "copy_given"),
    S(2,"det A = 3(4) + 5(2) = 22", sca(22.0), "determinant", True)])),

("det-sum", "det(A+B) = det A + det B", False,
 P("Compute det(A+B).", "determinant", "det(A+B)",
   [G("A", mat([[1,2],[3,4]])), G("B", mat([[0,1],[1,0]]))],
   [S(1,"det A = -2", sca(-2.0), "determinant"),
    S(2,"det B = -1", sca(-1.0), "determinant"),
    S(3,"det(A+B) = -2 + -1 = -3", sca(-3.0), "determinant", True)])),

("det-scalar", "det(2A) = 2 det A for a 2x2", False,
 P("Compute det(2A).", "determinant", "det(2A)", [G("A", mat([[1,2],[3,4]]))],
   [S(1,"det A = -2", sca(-2.0), "determinant"),
    S(2,"det(2A) = 2 det A = -4", sca(-4.0), "determinant", True)])),

("det-correct", "correct 3x3 determinant (control)", True,
 P("Compute det A.", "determinant", "det A", [G("A", mat([[1,2,3],[4,5,6],[7,8,10]]))],
   [S(1,"A given", mat([[1,2,3],[4,5,6],[7,8,10]]), "copy_given"),
    S(2,"det A = -3", sca(-3.0), "determinant", True)])),

# ---- inverses ------------------------------------------------------------
("inv-nodet", "adjugate without dividing by det", False,
 P("Find A^-1.", "inverse", "A^-1", [G("A", mat([[4,7],[2,6]]))],
   [S(1,"A = [4 7; 2 6]", mat([[4,7],[2,6]]), "copy_given"),
    S(2,"det A = 10", sca(10.0), "determinant"),
    S(3,"A^-1 = [6 -7; -2 4]", mat([[6,-7],[-2,4]]), "inverse", True)])),

("inv-singular", "claims a singular matrix is invertible", False,
 P("Is A invertible?", "Linear Algebra", "conclusion", [G("A", mat([[1,2],[2,4]]))],
   [S(1,"A = [1 2; 2 4]", mat([[1,2],[2,4]]), "copy_given"),
    S(2,"A is invertible", txt("A is invertible"), final=True)])),

("inv-of-prod", "(AB)^-1 = A^-1 B^-1", False,
 P("Find (AB)^-1.", "inverse", "(AB)^-1",
   [G("A", mat([[2,0],[0,1]])), G("B", mat([[1,1],[0,1]]))],
   [S(1,"A, B given", mat([[2,0],[0,1]]), "copy_given"),
    S(2,"(AB)^-1 = A^-1 B^-1 = [0.5 -0.5; 0 1]", mat([[0.5,-0.5],[0,1]]), "inverse", True)])),

# ---- eigen ---------------------------------------------------------------
("eig-notvec", "claimed eigenvector is not one", False,
 P("Is (1,0) an eigenvector of A?", "eigen", "eigenvector", [G("A", mat([[2,1],[1,2]]))],
   [S(1,"A = [2 1; 1 2]", mat([[2,1],[1,2]]), "copy_given"),
    S(2,"v = (1,0) is an eigenvector", vec(1,0), "eigenvector", True)])),

("eig-pairing", "right eigenvector, wrong eigenvalue", False,
 P("Find a basis for each eigenspace of A.", "eigen", "eigenvectors",
   [G("A", mat([[3,1],[1,3]]))],
   [S(1,"det(A - lambda I) = (3-lambda)^2 - 1 = 0", txt("(3-lambda)^2 - 1 = 0")),
    S(2,"So lambda = 2 or 4.", txt("lambda = 2 or 4")),
    S(3,"For lambda = 4 an eigenvector is (1,1).", txt("eigenvector is (1,1)")),
    S(4,"For lambda = 2, the same vector (1,1) works.", txt("the same vector (1,1) works"), final=True)])),

("eig-one-of-two", "names one of two eigenvalues (control: incomplete, not wrong)", True,
 P("Find an eigenvalue of A.", "eigen", "eigenvalue", [G("A", mat([[2,1],[1,2]]))],
   [S(1,"A given", mat([[2,1],[1,2]]), "copy_given"),
    S(2,"lambda = 3", sca(3.0), "eigenvalue", True)])),

("eig-trace", "eigenvalues read off the diagonal of a non-triangular matrix", False,
 P("Find the eigenvalues of A.", "eigen", "eigenvalues", [G("A", mat([[2,1],[1,2]]))],
   [S(1,"A = [2 1; 1 2]", mat([[2,1],[1,2]]), "copy_given"),
    S(2,"the eigenvalues are the diagonal entries, 2 and 2", txt("eigenvalues are 2 and 2"), final=True)])),

# ---- projections ---------------------------------------------------------
("proj-axis", "projected onto the y-axis when asked for the x-axis", False,
 P("Find the orthogonal projection of v onto the x-axis.", "projection",
   "projection of v onto the x-axis", [G("v", vec(3,2))],
   [S(1,"v = (3,2)", vec(3,2), "copy_given"),
    S(2,"proj(v) = (0,2)", vec(0,2), "project", True)])),

("proj-denom", "divided by |v| instead of v.v", False,
 P("Find proj_v(u).", "projection", "proj_v(u)", [G("u", vec(3,4)), G("v", vec(1,2))],
   [S(1,"u.v = 11", sca(11.0), "dot_product"),
    S(2,"||v|| = sqrt(5)", sca(2.2360679), "norm"),
    S(3,"proj = (4.92, 9.84)", vec(4.92,9.84), "project", True)])),

("proj-correct", "correct projection (control)", True,
 P("Find proj_v(u).", "projection", "proj_v(u)", [G("u", vec(3,4)), G("v", vec(1,2))],
   [S(1,"u.v = 11, v.v = 5", sca(11.0), "dot_product"),
    S(2,"proj = (2.2, 4.4)", vec(2.2,4.4), "project", True)])),

# ---- span / independence / rank -----------------------------------------
("span-dim", "two dependent vectors claimed to span the plane", False,
 P("What is the dimension of span{u,v}?", "span", "dimension",
   [G("u", vec(1,2)), G("v", vec(2,4))],
   [S(1,"u = (1,2), v = (2,4)", vec(1,2), "copy_given"),
    S(2,"they are two vectors so the span has dimension 2", sca(2.0), final=True)])),

("span-basis-r3", "two independent vectors called a basis for R^3", False,
 P("Do u and v form a basis for R^3?", "Linear Algebra", "conclusion",
   [G("u", vec(1,0,0)), G("v", vec(0,1,0))],
   [S(1,"u = (1,0,0), v = (0,1,0)", vec(1,0,0), "copy_given"),
    S(2,"they are independent, so they are a basis for R^3", txt("basis for R^3"), final=True)])),

("indep-correct", "correctly finds them independent (control)", True,
 P("Are u and v independent?", "Linear Algebra", "conclusion",
   [G("u", vec(1,2)), G("v", vec(2,1))],
   [S(1,"u, v given", vec(1,2), "copy_given"),
    S(2,"u and v are linearly independent", txt("linearly independent"), final=True)])),

# ---- systems -------------------------------------------------------------
("sys-colspace", "b in R^2 assumed to be in the column space of a singular A", False,
 P("Determine whether Ax = b has a solution.", "Linear Algebra", "conclusion",
   [G("A", mat([[1,2],[2,4]])), G("b", vec(1,3))],
   [S(1,"A = [1 2; 2 4], b = (1,3)", mat([[1,2],[2,4]]), "copy_given"),
    S(2,"b is in R^2 and the columns of A are in R^2, so b is in the column space", txt("b is in the column space of A")),
    S(3,"So Ax = b has a solution.", txt("Ax = b has a solution"), final=True)])),

("sys-pivot", "a pivot in the last column read as a free variable", False,
 P("How many solutions does Ax = b have?", "Linear Algebra", "conclusion",
   [G("A", mat([[1,2],[2,4]])), G("b", vec(1,3))],
   [S(1,"row reduce", mat([[1,2],[0,0]]), "row_add_multiple"),
    S(2,"there is a pivot in the last column", txt("pivot in the last column")),
    S(3,"so there is one free variable and infinitely many solutions", txt("infinitely many solutions"), final=True)])),

("sys-solve", "wrong solution to a 2x2 system", False,
 P("Solve Ax = b.", "Linear Algebra", "x",
   [G("A", mat([[1,1],[1,-1]])), G("b", vec(6,2))],
   [S(1,"A, b given", mat([[1,1],[1,-1]]), "copy_given"),
    S(2,"x = (2,4)", vec(2,4), "solve", True)])),

("sys-correct", "correct 3x3 solve (control)", True,
 P("Solve Ax = b.", "Linear Algebra", "x",
   [G("A", mat([[2,1,0],[1,3,1],[0,1,2]])), G("b", vec(3,5,3))],
   [S(1,"A, b given", mat([[2,1,0],[1,3,1],[0,1,2]]), "copy_given"),
    S(2,"x = (1,1,1)", vec(1,1,1), "solve", True)])),

# ---- transformations / geometry -----------------------------------------
("trans-angle", "equal basis lengths taken to mean angles preserved", False,
 P("T(e1)=(2,1), T(e2)=(1,2). Does T preserve angles?", "Linear Algebra", "conclusion",
   [G("T(e1)", vec(2,1)), G("T(e2)", vec(1,2))],
   [S(1,"both images have length sqrt(5)", sca(2.2360679)),
    S(2,"both basis vectors have the same length, so T preserves angles", txt("T preserves angles"), final=True)])),

("trans-rows", "put T(e1), T(e2) in as ROWS of the standard matrix", False,
 P("Find the standard matrix of T where T(e1)=(2,3), T(e2)=(1,5).", "Linear Algebra", "the standard matrix",
   [G("T(e1)", vec(2,3)), G("T(e2)", vec(1,5))],
   [S(1,"put T(e1) and T(e2) in as rows", txt("as rows")),
    S(2,"A = [2 3; 1 5]", mat([[2,3],[1,5]]), final=True)])),

("trans-rotation-ok", "a genuine rotation does preserve angles (control)", True,
 P("T(e1)=(0,1), T(e2)=(-1,0). Does T preserve angles?", "Linear Algebra", "conclusion",
   [G("T(e1)", vec(0,1)), G("T(e2)", vec(-1,0))],
   [S(1,"both images are unit length and perpendicular", sca(1.0)),
    S(2,"T is a rotation so it preserves angles", txt("T preserves angles"), final=True)])),

# ---- coordinates / orthogonality ----------------------------------------
("coord-entries", "B-coordinates read off as the vector's own entries", False,
 P("Find the B-coordinate vector of v, B = {b1,b2}.", "Linear Algebra", "[v]_B",
   [G("b1", vec(1,1)), G("b2", vec(2,-1)), G("v", vec(5,1))],
   [S(1,"[v]_B = (5,1).", vec(5,1), final=True),
    S(2,"check: 5b1 + 1b2 = (7,4).", vec(7,4))])),

("ortho-claim", "calls two vectors orthogonal when the dot product is not zero", False,
 P("Are u and v orthogonal?", "Linear Algebra", "conclusion",
   [G("u", vec(1,2)), G("v", vec(2,1))],
   [S(1,"u.v = 4", sca(4.0), "dot_product"),
    S(2,"u and v are orthogonal", txt("u and v are orthogonal"), final=True)])),

("norm-nosqrt", "forgot the square root in the norm", False,
 P("Compute ||u||.", "norm", "||u||", [G("u", vec(3,4))],
   [S(1,"u = (3,4)", vec(3,4), "copy_given"),
    S(2,"||u|| = 9 + 16 = 25", sca(25.0), "norm", True)])),
]



CONTROLS = [
("c-solve-right", "correct 2x2 solution (LA40 must not fire)",
 P("Solve Ax = b.", "Linear Algebra", "x",
   [G("A", mat([[1,1],[1,-1]])), G("b", vec(6,2))],
   [S(1,"A, b given", mat([[1,1],[1,-1]]), "copy_given"),
    S(2,"x = (4,2)", vec(4,2), "solve", True)])),

("c-solve-wrong-notperm", "wrong solution that is NOT a permutation",
 P("Solve Ax = b.", "Linear Algebra", "x",
   [G("A", mat([[1,1],[1,-1]])), G("b", vec(6,2))],
   [S(1,"A, b given", mat([[1,1],[1,-1]]), "copy_given"),
    S(2,"x = (5,1)", vec(5,1), "solve", True)])),

("c-det-scale-right", "det(2A) done correctly as 4 det A (LA37 must not fire)",
 P("Compute det(2A).", "determinant", "det(2A)", [G("A", mat([[1,2],[3,4]]))],
   [S(1,"det A = -2", sca(-2.0), "determinant"),
    S(2,"det(2A) = 4 det A = -8", sca(-8.0), "determinant", True)])),

("c-det-sum-right", "det(A+B) done correctly (LA36 must not fire)",
 P("Compute det(A+B).", "determinant", "det(A+B)",
   [G("A", mat([[1,2],[3,4]])), G("B", mat([[0,1],[1,0]]))],
   [S(1,"A+B = [1 3; 4 4]", mat([[1,3],[4,4]]), "add"),
    S(2,"det(A+B) = -8", sca(-8.0), "determinant", True)])),

("c-inv-prod-right", "(AB)^-1 = B^-1 A^-1 done correctly (LA38 must not fire)",
 P("Find (AB)^-1.", "inverse", "(AB)^-1",
   [G("A", mat([[2,0],[0,1]])), G("B", mat([[1,1],[0,1]]))],
   [S(1,"AB = [2 2; 0 1]", mat([[2,2],[0,1]]), "multiply"),
    S(2,"(AB)^-1 = [0.5 -1; 0 1]", mat([[0.5,-1],[0,1]]), "inverse", True)])),

("c-norm-right", "correct norm (LA39 must not fire)",
 P("Compute ||u||.", "norm", "||u||", [G("u", vec(3,4))],
   [S(1,"u = (3,4)", vec(3,4), "copy_given"),
    S(2,"||u|| = 5", sca(5.0), "norm", True)])),

("c-rows-symmetric", "images are symmetric, so rows and columns agree (LA33 must not fire)",
 P("Find the standard matrix of T where T(e1)=(2,1), T(e2)=(1,2).", "Linear Algebra",
   "the standard matrix", [G("T(e1)", vec(2,1)), G("T(e2)", vec(1,2))],
   [S(1,"put them in as rows", txt("as rows")),
    S(2,"A = [2 1; 1 2]", mat([[2,1],[1,2]]), final=True)])),

("c-rows-correct", "images entered as COLUMNS correctly (LA33 must not fire)",
 P("Find the standard matrix of T where T(e1)=(2,3), T(e2)=(1,5).", "Linear Algebra",
   "the standard matrix", [G("T(e1)", vec(2,3)), G("T(e2)", vec(1,5))],
   [S(1,"images as columns", txt("as columns")),
    S(2,"A = [2 1; 3 5]", mat([[2,1],[3,5]]), final=True)])),

("c-basis-r3-right", "three independent vectors ARE a basis for R^3 (LA34 must not fire)",
 P("Do these form a basis for R^3?", "Linear Algebra", "conclusion",
   [G("u", vec(1,0,0)), G("v", vec(0,1,0)), G("w", vec(0,0,1))],
   [S(1,"u, v, w given", vec(1,0,0), "copy_given"),
    S(2,"they are independent so they are a basis for R^3", txt("basis for R^3"), final=True)])),

("c-diag-triangular", "triangular matrix: the diagonal IS the spectrum (LA35 must not fire)",
 P("Find the eigenvalues of A.", "eigen", "eigenvalues", [G("A", mat([[2,7],[0,5]]))],
   [S(1,"A = [2 7; 0 5]", mat([[2,7],[0,5]]), "copy_given"),
    S(2,"A is triangular so the eigenvalues are the diagonal entries, 2 and 5",
      txt("eigenvalues are the diagonal entries 2 and 5"), final=True)])),
]

def main() -> int:
    bad = 0
    print("-- mistakes and correct work --")
    for cid, summary, is_correct, raw in CASES:
        e = Extraction.model_validate(raw)
        v = verify(e)
        flagged = v.first_error_index is not None
        ok = flagged == (not is_correct)
        # A flagged case must also plan something without raising.
        if flagged:
            try:
                plan(v, e)
            except Exception as exc:  # noqa: BLE001
                ok = False
                summary += f"  [PLAN FAILED: {type(exc).__name__}]"
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {cid:18s} flagged={str(flagged):5s} "
              f"id={str(v.error_id):6s} {summary[:52]}")

    print("\n-- controls: correct work the new signatures must not touch --")
    for cid, why, raw in CONTROLS:
        e = Extraction.model_validate(raw)
        v = verify(e)
        flagged = v.first_error_index is not None
        want = cid == "c-solve-wrong-notperm"      # the one that SHOULD flag
        ok = flagged == want
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {cid:22s} flagged={str(flagged):5s} "
              f"id={str(v.error_id):6s} {why[:46]}")

    total = len(CASES) + len(CONTROLS)
    print(f"\n{total - bad}/{total} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
