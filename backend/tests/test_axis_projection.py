"""Projection onto a named coordinate axis.

"Find the projection of v onto the x-axis" hands the extractor no vector for
the target subspace -- the axis is a NAME, not a symbol -- so topic_target()
built nothing, the final step went UNCHECKED, and a wrong answer came back as
"nothing in this work disagrees".

The axis is now turned into the basis vector it always was and handed to the
existing projection machinery. Nothing about projections is special-cased, and
no answer is hardcoded.

LA31 is the misconception worth naming here: the student returned the part of
v PERPENDICULAR to the axis -- the dropped vertical -- instead of the shadow
lying along it. Both are honest pieces of v and they sum to v, which is why
the swap is so easy to make.

    .venv/bin/python backend/tests/test_axis_projection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.extract import Extraction  # noqa: E402
from backend.hints import plan  # noqa: E402
from backend.verify import named_axis, verify  # noqa: E402


def vec(*x):
    return {"kind": "vector", "shape": [1, len(x)], "rows": [list(x)]}


def step(n, raw, value, op="unknown", final=False):
    return {"id": f"s{n}", "student_label": f"{n})", "page": 1, "reading_order": n,
            "raw_text": raw, "claimed_operation": op, "value": value,
            "is_final_answer": final, "parse_ok": True, "confidence": 0.95}


def ext(statement, asks, given, answer):
    return Extraction.model_validate({
        "problem": {"present": True, "statement": statement, "topic": "projection",
                    "asks_for": asks, "confidence": 0.95,
                    "givens": [{"symbol": "v", "object": vec(*given),
                                "source": "printed", "confidence": 0.97}]},
        "steps": [step(1, f"v = {given}", vec(*given), "copy_given"),
                  step(2, f"proj(v) = {answer}", vec(*answer), "project", True)],
        "notes": [], "page_count": 1})


X = "Find the orthogonal projection of v onto the x-axis."
Y = "Find the orthogonal projection of v onto the y-axis."

CASES = [
    # (name, expect_wrong, expect_error_id, extraction)
    ("T1  x-axis, answered (0,2) -- the residual", True, "LA31",
     ext(X, "projection of v onto the x-axis", (3, 2), (0, 2))),
    ("T2  x-axis, answered (3,0) -- correct", False, None,
     ext(X, "projection of v onto the x-axis", (3, 2), (3, 0))),
    ("T3  y-axis, answered (0,2) -- correct", False, None,
     ext(Y, "projection of v onto the y-axis", (3, 2), (0, 2))),
    ("T4  paraphrase: 'component along the horizontal axis'", True, "LA31",
     ext("Find the component of v along the horizontal axis.",
         "component of v along the horizontal axis", (3, 2), (0, 2))),
    ("T5  3D z-axis, answered (0,0,5) -- correct", False, None,
     ext("Project v onto the z-axis.", "projection of v onto the z-axis",
         (1, 4, 5), (0, 0, 5))),
    ("T6  3D z-axis, answered (1,4,0) -- the residual", True, "LA31",
     ext("Project v onto the z-axis.", "projection of v onto the z-axis",
         (1, 4, 5), (1, 4, 0))),
    # Controls: the axis machinery must not fire where no axis is named, and
    # must not fire on a problem that merely mentions one.
    ("C1  no axis named, correct work", False, None,
     ext("Find the norm of v.", "the norm of v", (3, 2), (3, 2))),
    ("C2  two axes named -- ambiguous, left alone", False, None,
     ext("Project v onto the x-axis and the y-axis.",
         "projections onto the x-axis and the y-axis", (3, 2), (3, 0))),
    ("C3  axis named but the task is not a projection", False, None,
     ext("Reflect v across the x-axis.", "the reflection of v", (3, 2), (3, -2))),
]


def main() -> int:
    bad = 0

    # named_axis is the whole of the new parsing surface; pin it directly.
    assert named_axis("onto the x-axis", 2) == __import__("sympy").Matrix([1, 0])
    assert named_axis("onto the y axis", 2) == __import__("sympy").Matrix([0, 1])
    assert named_axis("the z-axis", 3) == __import__("sympy").Matrix([0, 0, 1])
    assert named_axis("the z-axis", 2) is None, "no z in the plane"
    assert named_axis("onto the x-axis and y-axis", 2) is None, "ambiguous"
    assert named_axis("onto the line y = 2x", 2) is None, "not an axis"
    print("  PASS  named_axis parsing")

    for name, expect_wrong, expect_id, e in CASES:
        v = verify(e)
        got_wrong = v.first_error_index is not None
        ok = got_wrong == expect_wrong and (not expect_wrong or v.error_id == expect_id)
        template = ""
        if got_wrong:
            try:
                template = " -> " + plan(v, e).template
            except Exception as exc:  # noqa: BLE001
                template = f" -> planning failed: {exc}"
        if not ok:
            bad += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name:50s} "
              f"wrong={got_wrong} id={v.error_id}{template}")

    total = len(CASES) + 1
    print(f"\n{total - bad}/{total} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
