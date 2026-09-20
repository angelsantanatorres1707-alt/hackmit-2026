"""The visual contract, and that it actually refuses things.

A contract that only counts fields is a checklist. These pin the arithmetic
ones -- the checks that catch a storyboard which would render happily and
teach nothing, because the thing it exists to contrast is not there.

    .venv/bin/python backend/tests/test_storyboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend import storyboard as S  # noqa: E402
from backend.extract import Extraction  # noqa: E402
from backend.hints import plan  # noqa: E402
from backend.verify import verify  # noqa: E402

I2 = [[1, 0], [0, 1]]
SCALE2 = [[2, 0], [0, 2]]
SHEAR = [[1, 1], [0, 1]]
ROT90 = [[0, -1], [1, 0]]


def sb_order(v, s_stages, t_stages, beats=None):
    return S.Storyboard(
        concept="MATRIX_COMPOSITION_ORDER", teaching_goal="g", visual_contrast="c",
        required_objects=[S._obj("start_vector", "v", v),
                          S._obj("student_operators", "s", s_stages),
                          S._obj("target_operators", "t", t_stages)],
        beats=beats or [S._beat("establish", "x"), S._beat("apply", "x"),
                        S._beat("freeze", "x", divergence=True), S._beat("compare", "x")])


def sb_span(cols, b):
    return S.Storyboard(
        concept="COLUMN_SPACE", teaching_goal="g", visual_contrast="c",
        required_objects=[S._obj("columns", "cols", cols),
                          S._obj("reachable_set", "span", 1),
                          S._obj("target_b", "b", b)],
        beats=[S._beat("establish", "x"), S._beat("sweep", "x"),
               S._beat("probe", "x", divergence=True), S._beat("compare", "x")])


def sb_proj(claim, shadow, axis):
    return S.Storyboard(
        concept="PROJECTION_VS_RESIDUAL", teaching_goal="g", visual_contrast="c",
        required_objects=[S._obj("source_vector", "v", [3, 2]),
                          S._obj("target_subspace", "x-axis", axis),
                          S._obj("student_claim", "claim", claim),
                          S._obj("shadow", "shadow", shadow)],
        beats=[S._beat("establish", "x"), S._beat("drop_perpendicular", "x"),
               S._beat("highlight", "x", divergence=True), S._beat("compare", "x")])


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# -- the contract accepts a storyboard that can teach ----------------------

@case("ACCEPT: two orders that land apart")
def _():
    assert S.check(sb_order([1, 1], [ROT90, SHEAR], [SHEAR, ROT90])) == []


@case("ACCEPT: b outside the reachable set")
def _():
    assert S.check(sb_span([[1, 2], [2, 4]], [1, 3])) == []


@case("ACCEPT: a perpendicular claim distinct from the shadow")
def _():
    assert S.check(sb_proj([0, 2], [3, 0], [1, 0])) == []


# -- and refuses the ones that cannot --------------------------------------

@case("REFUSE: maps that commute, so there is no divergence")
def _():
    out = S.check(sb_order([1, 1], [I2, SCALE2], [SCALE2, I2]))
    assert any("same place" in p for p in out), out


@case("REFUSE: columns that already reach everything")
def _():
    out = S.check(sb_span([[1, 0], [0, 1]], [1, 3]))
    assert any("reach everything" in p for p in out), out


@case("REFUSE: b that IS reachable from dependent columns")
def _():
    out = S.check(sb_span([[1, 2], [2, 4]], [2, 4]))
    assert any("IS reachable" in p for p in out), out


@case("REFUSE: the claim IS the shadow")
def _():
    out = S.check(sb_proj([3, 0], [3, 0], [1, 0]))
    assert any("IS the shadow" in p for p in out), out


@case("REFUSE: a claim that is not perpendicular to the subspace")
def _():
    out = S.check(sb_proj([1, 2], [3, 0], [1, 0]))
    assert any("not perpendicular" in p for p in out), out


@case("REFUSE: no beat marked as the divergence -- no climax")
def _():
    flat = [S._beat("establish", "x"), S._beat("apply", "x"),
            S._beat("freeze", "x"), S._beat("compare", "x")]
    out = S.check(sb_order([1, 1], [ROT90, SHEAR], [SHEAR, ROT90], beats=flat))
    assert any("climax" in p for p in out), out


@case("REFUSE: a missing required object")
def _():
    board = sb_order([1, 1], [ROT90, SHEAR], [SHEAR, ROT90])
    board.required_objects = [o for o in board.required_objects
                              if o["role"] != "target_operators"]
    out = S.check(board)
    assert any("target_operators" in p for p in out), out


# -- and the real pipeline produces satisfied ones -------------------------

def _order_extraction():
    def mat(r): return {"kind": "matrix", "shape": [len(r), len(r[0])], "rows": r}
    def vec(*x): return {"kind": "vector", "shape": [1, len(x)], "rows": [list(x)]}
    def st(n, t, v, f=False):
        return {"id": f"s{n}", "student_label": f"{n})", "page": 1, "reading_order": n,
                "raw_text": t, "claimed_operation": "unknown", "value": v,
                "is_final_answer": f, "parse_ok": True, "confidence": 0.95}
    return Extraction.model_validate({
        "problem": {"present": True, "statement": "Compute BAv.", "topic": "Linear Algebra",
                    "asks_for": "BAv", "confidence": 0.95,
                    "givens": [{"symbol": "A", "object": mat(SHEAR), "source": "printed", "confidence": .97},
                               {"symbol": "B", "object": mat(ROT90), "source": "printed", "confidence": .97},
                               {"symbol": "v", "object": vec(1, 1), "source": "printed", "confidence": .97}]},
        "steps": [st(1, "Bv = (-1,1)", vec(-1, 1)), st(2, "A(Bv) = (0,1)", vec(0, 1)),
                  st(3, "Therefore BAv = (0,1)", vec(0, 1), True)],
        "notes": [], "page_count": 1})


@case("PIPELINE: the real order problem plans a satisfied storyboard")
def _():
    e = _order_extraction()
    p = plan(verify(e), e)
    board = p.storyboard
    assert board is not None, "no storyboard planned"
    assert board["concept"] == "MATRIX_COMPOSITION_ORDER"
    assert board["contract_problems"] == [], board["contract_problems"]
    assert any(b.get("divergence") for b in board["beats"]), "no climax beat"
    assert board["first_divergence_step"] == "s3"


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
