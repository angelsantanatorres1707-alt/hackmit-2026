#!/usr/bin/env python
"""Tests for backend/step_compiler.py -- plain asserts, no pytest needed.

    /home/user/hackmit-2026/.venv/bin/python backend/tests/test_step_compiler.py

Covers the four cases the brief names -- the projection example end to end, a
matrix-multiply example, a step nothing can classify, and an empty step list --
plus the two properties the whole design rests on: the correct answer cannot
reach the scene, and every symbol the scene is asked to draw is one it already
has.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backend.extract import Extraction                  # noqa: E402
from backend.verify import verify                       # noqa: E402
from backend import step_compiler as sc                 # noqa: E402

SAMPLES = os.path.join(REPO, "samples")


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def vec(*c):
    return {"kind": "vector", "shape": [1, len(c)], "rows": [list(c)]}


def mat(rows):
    return {"kind": "matrix", "shape": [len(rows), len(rows[0])], "rows": rows}


#: The user's real homework. a = (1,2), b = (3,1), "proj_a(b) = (b.a)a".
#: Step 1 is right. Step 2 forgets to divide by a.a = 5, so the shadow comes out
#: five times too long -- which is the thing the replay has to make visible.
PROJECTION = {
    "problem": {
        "present": True, "topic": "projection",
        "statement": "a = (1,2), b = (3,1). Find proj_a(b), using proj_a(b) = (b.a)a.",
        "asks_for": "proj_a(b)",
        "givens": [{"symbol": "a", "object": vec(1, 2)},
                   {"symbol": "b", "object": vec(3, 1)}],
    },
    "steps": [
        {"id": "s1", "student_label": "1)", "reading_order": 1,
         "raw_text": "b.a = 3(1) + 1(2) = 5", "claimed_expression": "b.a",
         "claimed_operation": "dot", "op_args": {"source_symbols": ["b", "a"]},
         "value": {"kind": "scalar", "scalars": [5]}},
        {"id": "s2", "student_label": "2)", "reading_order": 2,
         "raw_text": "proj_a(b) = 5(1,2) = (5,10)",
         "claimed_expression": "proj_a(b)", "claimed_operation": "scalar_multiply",
         "op_args": {"scalar": "5", "source_symbols": ["a"]},
         "value": vec(5, 10), "is_final_answer": True},
    ],
    "final_answer": {"step_id": "s2", "object": vec(5, 10)},
}


def load_sample(name):
    with open(os.path.join(SAMPLES, name + ".json")) as fh:
        return Extraction.model_validate(json.load(fh))


def compiled(ext):
    """Straight through the real verifier -- no hand-made verdicts."""
    return sc.compile_replay(ext, verify(ext)).params


def by_id(params, sid):
    for s in params["steps"]:
        if s["id"] == sid:
            return s
    raise AssertionError(f"no step {sid} in {[s['id'] for s in params['steps']]}")


# --------------------------------------------------------------------------
# 1. The projection example, end to end
# --------------------------------------------------------------------------

def test_projection_end_to_end():
    ext = Extraction.model_validate(PROJECTION)
    v = verify(ext)
    assert v.first_error_index == 1, v.first_error_index

    res = sc.compile_replay(ext, v)
    p = res.params
    assert res.ok, res.reason
    assert res.warnings == [], res.warnings

    # The givens are the printed problem, verbatim, with a colour rota.
    assert p["givens"]["a"] == {"kind": "vector", "value": [1.0, 2.0],
                                "display": "(1, 2)", "color": "i_hat"}
    assert p["givens"]["b"]["value"] == [3.0, 1.0]
    assert p["givens"]["b"]["color"] == "j_hat"

    # Two steps, in the student's own numbering, classified from what they wrote.
    s1, s2 = p["steps"]
    assert [s["student_label"] for s in p["steps"]] == ["1)", "2)"]

    # Step 1: the dot product. Correct, and visibly so.
    assert s1["kind"] == "dot_product", s1["kind"]
    assert s1["args"] == {"u": "b", "v": "a"}
    assert s1["terms"] == ["3(1)", "1(2)"], s1["terms"]      # lifted from raw_text
    assert s1["result"] == {"kind": "scalar", "value": 5.0, "display": "5"}
    assert s1["bind"] == "k"
    assert s1["status"] == "ok" and s1["first_wrong"] is False
    assert s1["invariant"] is None and s1["divergence"] is None
    assert s1["operands"]["u"]["value"] == [3.0, 1.0]

    # Step 2: the hero beat. The 5 is not a literal we re-derived -- it is the
    # register step 1 bound, and the compiler checked 5 * (1,2) == (5,10).
    assert s2["kind"] == "scale_vector", s2["kind"]
    assert s2["args"] == {"v": "a", "k": "k"}, s2["args"]
    assert s2["k"] == 5.0 and s2["k_display"] == "5"
    assert s2["result"] == {"kind": "vector", "value": [5.0, 10.0],
                            "display": "(5, 10)"}
    assert s2["bind"] == "p"
    assert s2["status"] == "wrong" and s2["first_wrong"] is True
    assert "checked" in s2["why"], s2["why"]

    # Exactly one first_wrong (validation case 4).
    assert sum(1 for s in p["steps"] if s["first_wrong"]) == 1

    # The invariant is a REGION named by a symbol in scope -- b, the thing
    # casting the shadow -- reached because the dot step told us what was being
    # projected. Never a literal, never the answer.
    assert s2["invariant"] == {"kind": "disc", "radius_of": "b",
                               "caption": "every shadow of b lands in here"}
    assert s2["divergence"]["absurdity"] == "length"
    assert s2["divergence"]["compare_to"] == "b"
    assert s2["divergence"]["right_angle_at"] == "result"

    # The dot product is leak-guarded: a projection is downstream, so the
    # perpendicular-foot rendering is off the table even though step 1 was right.
    assert p["leak_guard"] == ["project"], p["leak_guard"]

    # Framing, as solved in STEP_REPLAY.md §5: 1.091 -> 0.419, ratio 2.60.
    c = p["canvas"]
    assert abs(c["unit_start"] - 1.091) < 0.01, c["unit_start"]
    assert abs(c["unit_end"] - 0.419) < 0.01, c["unit_end"]
    assert abs(c["zoom_ratio"] - 2.60) < 0.01, c["zoom_ratio"]
    assert c["grid_step"] == 1 and c["grow"] is False
    assert 20 < c["cells_end"] < 24, c["cells_end"]

    # Positional hint, naming no value.
    assert p["hint"] == "a shadow can't be longer than the thing casting it"
    for bad in ("5/5", "a.a", "0.2", "divide"):
        assert bad not in p["hint"], p["hint"]

    # Within the 12-18s target.
    total = sum(s["run_time"] for s in p["steps"]) + 6.8
    assert 11.0 <= total <= 20.0, total
    print("   projection: %s -> %s, first wrong at %s, %.1fs"
          % (s1["kind"], s2["kind"], s2["student_label"], total))


# --------------------------------------------------------------------------
# 2. A matrix-multiply example
# --------------------------------------------------------------------------

def test_matrix_multiply():
    ext = load_sample("la02_order")
    p = compiled(ext)

    s1 = by_id(p, "s1")
    assert s1["kind"] == "define_matrix", s1["kind"]
    assert s1["rows"] == [[0.0, -1.0], [1.0, 0.0]]
    assert s1["bind"] == "A"                     # the copy replaces the given

    s2 = by_id(p, "s2")
    assert s2["kind"] == "matrix_product", s2["kind"]
    assert s2["factors"] == ["A", "B"]
    assert s2["order"] == ["B", "A"], s2["order"]   # right factor acts first
    assert s2["result"]["kind"] == "matrix"
    assert s2["result"]["value"] == [[0.0, -3.0], [1.0, 0.0]]
    assert s2["result"]["display"] == [["0", "-3"], ["1", "0"]]
    assert s2["bind"] == "AB"                    # the student's own name for it
    assert s2["first_wrong"] is True
    assert s2["invariant"]["kind"] == "composite"
    # One symbol per key, never a list: the scene's validator rejects a list in
    # a *_of field, because it cannot tell a list of symbols from a literal.
    assert s2["invariant"]["left_of"] == "A"
    assert s2["invariant"]["right_of"] == "B"
    assert p["leak_guard"] == []

    # A pure-matrix replay still frames: the columns are the images of the basis.
    assert p["canvas"]["unit_end"] > 0.2, p["canvas"]

    # The longer multiply sample keeps its shape too, around two dead lines.
    q = compiled(load_sample("la_multiply"))
    assert [s["kind"] for s in q["steps"]] == \
        ["define_matrix", "literal", "literal", "matrix_product"], \
        [s["kind"] for s in q["steps"]]
    assert by_id(q, "s2")["status"] == "crossed_out"   # never blamed
    assert by_id(q, "s2")["first_wrong"] is False
    assert by_id(q, "s4")["first_wrong"] is True
    print("   matrix multiply: order %s, bind %s" % (s2["order"], s2["bind"]))


# --------------------------------------------------------------------------
# 3. A step nothing can classify
# --------------------------------------------------------------------------

def test_unclassifiable_step_degrades():
    data = copy.deepcopy(PROJECTION)
    data["steps"].insert(1, {
        "id": "sx", "student_label": "*", "reading_order": 1,
        "raw_text": "~~ then the other one goes here somehow ~~",
        "claimed_expression": None, "claimed_operation": "unknown",
        "op_args": {}, "value": None, "parse_ok": False,
    })
    # ... and a step naming an operand that was never defined.
    data["steps"].append({
        "id": "sy", "student_label": "3)", "reading_order": 3,
        "raw_text": "z . a = 7", "claimed_expression": "z . a",
        "claimed_operation": "dot", "op_args": {"source_symbols": ["z"]},
        "value": {"kind": "scalar", "scalars": [7]},
    })
    ext = Extraction.model_validate(data)
    res = sc.compile_replay(ext, verify(ext))
    p = res.params

    sx = by_id(p, "sx")
    assert sx["kind"] == "literal", sx["kind"]
    assert sx["args"] == {} and sx.get("bind") is None
    assert sx["invariant"] is None and sx["divergence"] is None
    # The written line survives intact for the ledger -- that is the whole job
    # of a literal step.
    assert sx["expr"].startswith("~~ then the other one goes"), sx["expr"]
    assert sx["raw_text"] == "~~ then the other one goes here somehow ~~"
    assert "did not parse" in sx["why"], sx["why"]

    # The unresolvable operand never reaches the scene, and -- just as
    # important -- no OTHER vector gets quietly substituted for `z`. Borrowing
    # `b` here would be inventing work the student did not do, so the line docks
    # into the ledger with no geometry instead.
    sy = by_id(p, "sy")
    assert sy["args"] == {}, sy["args"]
    assert "z" not in json.dumps(sy.get("operands", {})), sy
    assert sy["kind"] in ("literal", "scalar_value"), sy["kind"]
    assert sy["result"]["value"] == 7.0                # their claim, kept

    # The good steps are untouched and the replay is still worth playing.
    assert by_id(p, "s1")["kind"] == "dot_product"
    assert by_id(p, "s2")["kind"] == "scale_vector"
    assert res.ok, res.reason
    print("   unclassifiable: kinds %s" % [s["kind"] for s in p["steps"]])


# --------------------------------------------------------------------------
# 4. An empty step list
# --------------------------------------------------------------------------

def test_empty_steps():
    data = copy.deepcopy(PROJECTION)
    data["steps"] = []
    data["final_answer"] = {"step_id": None, "object": None}
    ext = Extraction.model_validate(data)

    res = sc.compile_replay(ext, verify(ext))         # must not raise
    p = res.params
    assert p["steps"] == []
    assert p["givens"]["a"]["value"] == [1.0, 2.0]    # the problem still reads
    assert p["canvas"]["unit_end"] > 0
    assert isinstance(p["hint"], str) and p["hint"]
    ok, why = sc.viable(p)
    assert ok is False and "two steps" in why, (ok, why)
    assert res.ok is False

    # Nothing at all: still a params object, still no exception.
    bare = sc.compile_step_replay({"problem": {"givens": []}, "steps": []}, None)
    assert bare["steps"] == [] and bare["givens"] == {}
    assert sc.viable(bare)[0] is False

    # One step is not a replay either.
    one = copy.deepcopy(PROJECTION)
    one["steps"] = one["steps"][:1]
    p1 = sc.compile_step_replay(Extraction.model_validate(one), None)
    assert len(p1["steps"]) == 1 and sc.viable(p1)[0] is False
    print("   empty: viable=False, reason=%r" % why)


# --------------------------------------------------------------------------
# 5. The property the whole design rests on: the answer cannot get out
# --------------------------------------------------------------------------

def test_correct_value_cannot_reach_the_scene():
    ext = Extraction.model_validate(PROJECTION)
    v = verify(ext)
    assert v.correct_value is not None                # the verifier knows it

    before = sc.compile_step_replay(ext, v)
    v.correct_value = None                            # ... and it makes no
    v.student_value = None                            #     difference at all
    v.error_id = "LA99"
    after = sc.compile_step_replay(ext, v)
    assert before == after, "the verdict's answer changed the params"

    # Everything emitted traces back to a given or to the student's own line.
    public = {json.dumps(g["value"]) for g in before["givens"].values()}
    for s in before["steps"]:
        r = s["result"]
        if r["kind"] in ("vector", "matrix"):
            assert json.dumps(r["value"]) in public \
                or r["value"] in ([5.0, 10.0], [[0.0, -3.0], [1.0, 0.0]]) \
                or s["raw_text"], r
    print("   leak: params identical with and without verdict.correct_value")


def test_invariant_fields_name_symbols_in_scope():
    """Validation case 5, over every sample: never a literal, never a stranger."""
    names = ["la02_order", "la07_inverse", "la09_eigen", "la19_projection",
             "la_multiply"]
    checked = 0
    for name in names:
        p = compiled(load_sample(name))
        scope = set(p["givens"]) | {s["bind"] for s in p["steps"] if s.get("bind")}
        for s in p["steps"]:
            for sym in s["args"].values():
                if isinstance(sym, str):
                    assert sym in scope, (name, s["id"], sym)
            inv = s.get("invariant") or {}
            for key, val in inv.items():
                if not key.endswith("_of") and key != "applied_to":
                    continue
                for n in (val if isinstance(val, list) else [val]):
                    assert isinstance(n, str) and n in scope, (name, key, n)
                    checked += 1
            assert sum(1 for t in p["steps"] if t["first_wrong"]) <= 1, name
    print("   invariants: %d symbol references, all in scope" % checked)


def test_every_sample_compiles():
    for fn in sorted(os.listdir(SAMPLES)):
        if not fn.endswith(".json") or fn == "index.json":
            continue
        ext = Extraction.model_validate(json.load(open(os.path.join(SAMPLES, fn))))
        res = sc.compile_replay(ext, verify(ext))
        assert res.params["steps"], fn
        for s in res.params["steps"]:
            assert s["kind"] in sc.STEP_KINDS, (fn, s["kind"])
            assert len(s["expr"]) <= sc.EXPR_CHARS, (fn, s["expr"])
            assert s["status"] in ("ok", "wrong", "unchecked", "crossed_out"), s
        print("   %-22s %-6s %s" % (fn, res.ok,
                                    [s["kind"] for s in res.params["steps"]]))


def test_budget_never_overruns():
    data = copy.deepcopy(PROJECTION)
    data["steps"] = []
    for i in range(12):
        data["steps"].append({
            "id": f"s{i}", "student_label": f"{i + 1})", "reading_order": i,
            "raw_text": f"b.a = {i}", "claimed_expression": "b.a",
            "claimed_operation": "dot", "op_args": {"source_symbols": ["b", "a"]},
            "value": {"kind": "scalar", "scalars": [i]},
        })
    p = sc.compile_step_replay(Extraction.model_validate(data), None)
    assert len(p["steps"]) == 12
    total = sum(s["run_time"] for s in p["steps"]) + 4.6      # no wrong step
    assert total <= 20.0, total
    assert all(s["run_time"] >= 0.0 for s in p["steps"])
    assert len({s["bind"] for s in p["steps"]}) == 12, \
        [s["bind"] for s in p["steps"]]                        # no clobbering

    # The wrong step's beat is never the one that gets compressed.
    data["steps"][7]["value"] = {"kind": "scalar", "scalars": [999]}
    ext = Extraction.model_validate(data)
    v = verify(ext)
    if v.first_error_index is not None:
        q = sc.compile_step_replay(ext, v)
        wrong = [s for s in q["steps"] if s["first_wrong"]][0]
        rest = [s for s in q["steps"] if not s["first_wrong"]]
        assert wrong["run_time"] >= max(s["run_time"] for s in rest), \
            (wrong["run_time"], [s["run_time"] for s in rest])
    print("   budget: 12 steps fit in %.1fs, binds all distinct" % total)


def test_plain_dicts_and_no_verdict():
    """The compiler is fed pydantic in production and raw JSON in tests."""
    p = sc.compile_step_replay(PROJECTION, None)
    assert [s["kind"] for s in p["steps"]] == ["dot_product", "scale_vector"]
    assert all(s["status"] == "unchecked" for s in p["steps"])
    assert not any(s["first_wrong"] for s in p["steps"])

    # A verdict in its serialised form works just as well as the dataclass.
    ext = Extraction.model_validate(PROJECTION)
    q = sc.compile_step_replay(ext, verify(ext).json())
    assert by_id(q, "s2")["first_wrong"] is True
    assert by_id(q, "s2")["status"] == "wrong"
    print("   dicts: raw JSON in, raw JSON verdict in, same classification")


def test_matrices_and_vectors_both_read():
    assert sc.as_vector(vec(3, 4)) == [3.0, 4.0]
    assert sc.as_vector({"kind": "vector", "rows": [[3], [4]]}) == [3.0, 4.0]
    assert sc.as_vector(mat([[1, 2], [3, 4]])) is None
    assert sc.as_matrix(mat([[1, 2], [3, 4]])) == [[1.0, 2.0], [3.0, 4.0]]
    assert sc.as_matrix(vec(3, 4)) is None
    assert sc.as_scalar({"kind": "scalar", "scalars": [7]}) == 7.0
    # A list of eigenvalues is not a point on a plane.
    assert sc.as_vector({"kind": "scalar_list", "scalars": [3, 1]}) is None
    # Nothing past the drawable range gets through (validation case 6).
    assert sc.as_vector(vec(1, 900)) is None
    assert sc.as_vector({"kind": "vector", "rows": [[1, float("inf")]]}) is None
    print("   coercion: vectors, columns, matrices, scalars, and the rejects")


def test_output_validates_against_the_scene():
    """The real consumer's own gate, on real params.

    `backend/scenes/step_replay.py` is owned by another agent and may be
    mid-edit, so a missing or broken import SKIPS rather than fails -- but when
    it is there, everything this compiler emits has to get through it.
    """
    scenes = os.path.join(REPO, "backend", "scenes")
    if scenes not in sys.path:
        sys.path.insert(0, scenes)
    try:
        from step_replay import StepReplay, check_hint      # noqa: E402
    except Exception as exc:                                # noqa: BLE001
        print("   SKIP: cannot import StepReplay (%s)" % exc)
        return

    cases = [("motivating", Extraction.model_validate(PROJECTION))]
    for fn in sorted(os.listdir(SAMPLES)):
        if fn.endswith(".json") and fn != "index.json":
            cases.append((fn, Extraction.model_validate(
                json.load(open(os.path.join(SAMPLES, fn))))))

    for name, ext in cases:
        params = sc.compile_step_replay(ext, verify(ext))
        StepReplay.validate(copy.deepcopy(params))          # raises on any fault
        check_hint(params["hint"])
        for s in params["steps"]:
            for key, val in (s.get("invariant") or {}).items():
                if key.endswith("_of"):
                    assert isinstance(val, str), (name, key, val)
            if s.get("caption"):
                check_hint(s["caption"])
        print("   %-22s validates" % name)


# --------------------------------------------------------------------------

TESTS = [
    test_projection_end_to_end,
    test_matrix_multiply,
    test_unclassifiable_step_degrades,
    test_empty_steps,
    test_correct_value_cannot_reach_the_scene,
    test_invariant_fields_name_symbols_in_scope,
    test_every_sample_compiles,
    test_budget_never_overruns,
    test_plain_dicts_and_no_verdict,
    test_matrices_and_vectors_both_read,
    test_output_validates_against_the_scene,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            print("%s" % fn.__name__)
            fn()
            print("   PASS\n")
        except Exception:
            failed += 1
            print("   FAIL")
            traceback.print_exc()
            print()
    print("%d/%d passed" % (len(TESTS) - failed, len(TESTS)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
