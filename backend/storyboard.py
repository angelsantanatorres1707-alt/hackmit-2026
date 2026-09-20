"""The visual explanation planner: a diagnosis in, a storyboard out.

Between "we know what went wrong" and "render this scene" there was nothing.
The scene was chosen by a lookup on the error code and then handed whatever
parameters the builder happened to produce, with no statement anywhere of what
the film was supposed to TEACH -- and so no way to notice when a scene had been
given parameters that could not teach it.

This module writes that statement down. For each misconception it names the
teaching goal, the contrast that carries it, the objects that must appear, and
the beat where the student's reasoning first leaves the road -- the climax, not
one of five equally-weighted lines.

Then it checks. A VISUAL CONTRACT says what must be on screen for a given
misconception to be teachable at all, and the check is arithmetic, not a
checklist: the column-space storyboard is rejected unless b really is outside
the reachable set, the composition-order one unless the two orders really do
land somewhere different. A storyboard that fails its contract is refused
BEFORE rendering and the caller falls down its existing ladder, because a video
that cannot make its point is worse than the plain one that admits it.

No model writes Manim here, or anything else. The planner is ordinary code
reading the verified diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import sympy as sp

# --------------------------------------------------------------------------
# Concepts, and the error codes that mean them
# --------------------------------------------------------------------------

CONCEPT_FOR_ERROR = {
    "LA02": "MATRIX_COMPOSITION_ORDER",
    "LA24": "MATRIX_COMPOSITION_ORDER",
    "LA31": "PROJECTION_VS_RESIDUAL",
    "LA32": "PROJECTION_VS_RESIDUAL",
    "LA30": "COLUMN_SPACE",
    "LA15": "COLUMN_SPACE",
}

# What must be on screen for the misconception to be teachable. `roles` are
# object roles the storyboard must carry; `beats` are beat kinds it must
# contain; `check` is the arithmetic that makes the contract mean something.
CONTRACTS: dict[str, dict[str, Any]] = {
    "MATRIX_COMPOSITION_ORDER": {
        "must_show": ["the same starting object in both paths",
                      "the student's order",
                      "the order the problem asked for",
                      "a visible divergence between the two"],
        "roles": ("start_vector", "student_operators", "target_operators"),
        "beats": ("establish", "apply", "freeze", "compare"),
    },
    "PROJECTION_VS_RESIDUAL": {
        "must_show": ["the original vector",
                      "the target subspace",
                      "the perpendicular segment the student kept",
                      "the shadow lying in the subspace"],
        "roles": ("source_vector", "target_subspace", "student_claim", "shadow"),
        "beats": ("establish", "drop_perpendicular", "highlight", "compare"),
    },
    "COLUMN_SPACE": {
        "must_show": ["the columns themselves",
                      "every Ax they can reach",
                      "b, drawn outside that reachable set"],
        "roles": ("columns", "reachable_set", "target_b"),
        "beats": ("establish", "sweep", "probe", "compare"),
    },
}


@dataclass
class Storyboard:
    concept: str
    teaching_goal: str
    visual_contrast: str
    required_objects: list[dict] = field(default_factory=list)
    first_divergence_step: Optional[str] = None
    beats: list[dict] = field(default_factory=list)
    final_hold: str = ""
    fallback: str = ""
    scene: str = ""
    params: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    # True when the planner could not read this scene's parameters at all, so
    # `problems` describes the planner's blindness rather than the scene's.
    inapplicable: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems

    def json(self) -> dict:
        return {
            "concept": self.concept,
            "teaching_goal": self.teaching_goal,
            "visual_contrast": self.visual_contrast,
            "required_objects": self.required_objects,
            "first_divergence_step": self.first_divergence_step,
            "beats": self.beats,
            "final_hold": self.final_hold,
            "fallback": self.fallback,
            "scene": self.scene,
            "contract_problems": self.problems,
            "inapplicable": self.inapplicable,
        }


def _obj(role, name, value=None, note=""):
    return {"role": role, "name": name, "value": value, "note": note}


def _beat(kind, says, **detail):
    b = {"kind": kind, "says": says}
    b.update(detail)
    return b


def _num(x):
    try:
        return sp.Matrix(x)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# Planners, one per concept. Each reads the DIAGNOSIS and the scene parameters
# that were already chosen for it, and says what that film is meant to teach.
# --------------------------------------------------------------------------

def _plan_order(verdict, ext, scene, p, step_id) -> Storyboard:
    v = p.get("vector")
    s_syms, t_syms = p.get("student_symbols"), p.get("correct_symbols")
    s_stages, t_stages = p.get("student_stages"), p.get("correct_stages")
    name = p.get("vector_name") or "v"

    student_expr = "".join(list(s_syms or [])[::-1]) + name if s_syms else "?"
    target_expr = "".join(list(t_syms or [])[::-1]) + name if t_syms else "?"

    beats = [_beat("establish", f"one starting vector, {name}, in both panels",
                   object=name, value=v)]
    for k, sym in enumerate(s_syms or []):
        beats.append(_beat("apply", f"the student applies {sym}",
                           path="student", operator=sym, index=k))
        beats.append(_beat("apply", f"the problem's order applies "
                                    f"{(t_syms or ['?'])[k]}",
                           path="target", operator=(t_syms or ["?"])[k], index=k))
        if k == 0:
            beats.append(_beat("freeze",
                               "hold here: the two panels are still identical, so "
                               "the divergence comes from the ORDER, not from the "
                               "maps being different", divergence=True))
    beats.append(_beat("compare", f"{student_expr} against {target_expr}",
                       of=[student_expr, target_expr]))

    return Storyboard(
        concept="MATRIX_COMPOSITION_ORDER",
        teaching_goal="Applying the same two maps in the other order is a "
                      "different journey and lands somewhere else.",
        visual_contrast="One vector, two orders, side by side from the same start.",
        required_objects=[
            _obj("start_vector", name, v, "the same object begins both paths"),
            _obj("student_operators", "+".join(s_syms or []), s_stages,
                 "in the order the student applied them"),
            _obj("target_operators", "+".join(t_syms or []), t_stages,
                 "in the order the problem asked for"),
        ],
        first_divergence_step=step_id,
        beats=beats,
        final_hold=f"{student_expr} and {target_expr}, their arrows, and a "
                   f"not-equals between them",
        fallback="GridTransformCompare on the basis vectors",
        scene=scene, params=p,
    )


def _plan_projection(verdict, ext, scene, p, step_id) -> Storyboard:
    u = p.get("u")
    axis = p.get("v")
    claimed = p.get("w_claimed")
    shadow = p.get("w_correct")
    axis_name = (p.get("labels") or {}).get("v") or "the axis"

    return Storyboard(
        concept="PROJECTION_VS_RESIDUAL",
        teaching_goal="A shadow lies ALONG the thing it falls on. The piece that "
                      "stands away from it at a right angle is what is left over, "
                      "not the shadow.",
        visual_contrast="The perpendicular segment the student kept, beside the "
                        "one lying in the subspace.",
        required_objects=[
            _obj("source_vector", "v", u, "the vector being projected"),
            _obj("target_subspace", axis_name, axis, "the line it falls onto"),
            _obj("student_claim", "your answer", claimed,
                 "stands away from the subspace at a right angle"),
            _obj("shadow", "the shadow", shadow, "lies along the subspace"),
        ],
        first_divergence_step=step_id,
        beats=[
            _beat("establish", "draw v and the target axis", objects=["v", axis_name]),
            _beat("drop_perpendicular",
                  "drop a perpendicular from the tip of v to the axis"),
            _beat("highlight", "the segment the student kept, standing away from "
                               "the axis", of="student_claim", divergence=True),
            _beat("compare", "against the piece lying along the axis",
                  of=["student_claim", "shadow"]),
        ],
        final_hold="both segments on screen at once: one along the axis, one "
                   "square to it, and no corrected number anywhere",
        fallback="StepReplay of the student's own steps",
        scene=scene, params=p,
    )


def _plan_column_space(verdict, ext, scene, p, step_id) -> Storyboard:
    cols = p.get("vectors")
    probe = p.get("probe")
    actual, claimed = p.get("actual_dim"), p.get("claimed_dim")
    word = {1: "a line", 2: "a plane", 3: "all of space"}.get(actual, "a smaller set")

    return Storyboard(
        concept="COLUMN_SPACE",
        teaching_goal="Every Ax is a combination of A's own columns, so the "
                      "reachable set is only as big as the columns are different "
                      "from each other.",
        visual_contrast=f"What was assumed reachable against what is: {word}, with "
                        f"the rest of the space staying dark.",
        required_objects=[
            _obj("columns", "columns of A", cols, "the only directions available"),
            _obj("reachable_set", f"span of the columns ({word})", actual,
                 f"claimed to be dimension {claimed}"),
            _obj("target_b", "b", probe, "must be shown OUTSIDE the reachable set"),
        ],
        first_divergence_step=step_id,
        beats=[
            _beat("establish", "draw the columns from the origin", objects=["columns"]),
            _beat("sweep", "paint every combination they reach; the rest of the "
                           "plane stays dark"),
            _beat("probe", "place b, and try to reach it along the set",
                  of="target_b", divergence=True),
            _beat("compare", "the reachable set against where b actually sits",
                  of=["reachable_set", "target_b"]),
        ],
        final_hold="b sitting off the reachable set, with the gap marked",
        fallback="StaticStepHighlight on the claim",
        scene=scene, params=p,
    )


_PLANNERS = {
    "MATRIX_COMPOSITION_ORDER": _plan_order,
    "PROJECTION_VS_RESIDUAL": _plan_projection,
    "COLUMN_SPACE": _plan_column_space,
}


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------

def _roles(sb: Storyboard) -> set:
    return {o.get("role") for o in sb.required_objects}


def check(sb: Storyboard) -> list[str]:
    """-> problems. Empty means this storyboard can teach its misconception."""
    contract = CONTRACTS.get(sb.concept)
    if contract is None:
        return [f"no visual contract for {sb.concept}"]

    problems: list[str] = []
    for role in contract["roles"]:
        if role not in _roles(sb):
            problems.append(f"contract needs a {role} and the storyboard has none")
    kinds = {b.get("kind") for b in sb.beats}
    for kind in contract["beats"]:
        if kind not in kinds:
            problems.append(f"contract needs a '{kind}' beat")
    if not any(b.get("divergence") for b in sb.beats):
        problems.append("no beat is marked as the divergence; there is no climax")

    for o in sb.required_objects:
        if o.get("value") in (None, [], {}):
            problems.append(f"{o['role']} has no value to draw")

    problems += _arithmetic(sb)
    return problems


def _arithmetic(sb: Storyboard) -> list[str]:
    """The part that makes a contract more than a checklist."""
    out: list[str] = []
    by_role = {o["role"]: o for o in sb.required_objects}
    try:
        if sb.concept == "MATRIX_COMPOSITION_ORDER":
            v = _num(by_role["start_vector"]["value"])
            s = by_role["student_operators"]["value"]
            t = by_role["target_operators"]["value"]
            if v is None or not s or not t:
                return ["cannot check: the vector or a stage list is missing"]
            if _compose(s) * v == _compose(t) * v:
                out.append("both orders land the vector in the same place; there "
                           "is no divergence to show")
        elif sb.concept == "PROJECTION_VS_RESIDUAL":
            claim = _num(by_role["student_claim"]["value"])
            shadow = _num(by_role["shadow"]["value"])
            axis = _num(by_role["target_subspace"]["value"])
            if claim is None or shadow is None or axis is None:
                return ["cannot check: a vector is missing"]
            if claim == shadow:
                out.append("the claim IS the shadow; nothing distinguishes them")
            if sp.simplify(claim.dot(axis)) != 0:
                out.append("the student's segment is not perpendicular to the "
                           "subspace, so this is a different mistake")
        elif sb.concept == "COLUMN_SPACE":
            cols = by_role["columns"]["value"] or []
            b = _num(by_role["target_b"]["value"])
            if not cols or b is None:
                return ["cannot check: columns or b are missing"]
            A = sp.Matrix.hstack(*[sp.Matrix(c) for c in cols])
            if A.rank() >= A.rows:
                out.append("the columns already reach everything; nothing is "
                           "outside the reachable set")
            elif A.rank() == A.row_join(b).rank():
                out.append("b IS reachable from these columns; the picture would "
                           "show it being reached")
    except Exception as exc:  # noqa: BLE001
        out.append(f"contract check failed: {type(exc).__name__}: {exc}")
    return out


def _compose(stages):
    M = None
    for S in stages:                       # applied in order
        A = sp.Matrix(S)
        M = A if M is None else A * M
    return M


# --------------------------------------------------------------------------

def build(verdict, ext, scene: str, params: dict) -> Optional[Storyboard]:
    """-> a checked Storyboard, or None when this error has no planner.

    `sb.ok` is False when the contract refused it; the caller should then use
    its own fallback rather than render something that cannot teach.
    """
    concept = CONCEPT_FOR_ERROR.get(getattr(verdict, "error_id", None) or "")
    planner = _PLANNERS.get(concept or "")
    if planner is None:
        return None
    try:
        sb = planner(verdict, ext, scene, dict(params or {}),
                     getattr(verdict, "step_id", None))
    except Exception as exc:  # noqa: BLE001
        return Storyboard(concept=concept or "?", teaching_goal="", visual_contrast="",
                          problems=[f"planner raised: {type(exc).__name__}: {exc}"])
    sb.problems = check(sb)
    # Each planner reads the parameters of the scene it was written for.
    # Handed a different scene's parameters it comes back missing the pieces it
    # reads, and `check` reads those gaps as a refusal -- condemning a scene it
    # never actually looked at. _plan_order wants
    # CompositionOrderVector's `vector`/`student_symbols`; give it
    # GridTransformCompare's basis-vector parameters and it fails its own
    # contract every time, which is how LA02 -- the flagship "you multiplied in
    # the other order" sample -- ended up as a still frame.
    #
    # A check that never ran is not a verdict. Each planner already says so in
    # its own words -- `_arithmetic` returns "cannot check: ..." when the data
    # it needs is absent -- so key on that rather than guessing. A scene that
    # really cannot make its point still fails normally: its arithmetic runs
    # and disagrees, which is a different sentence entirely.
    if any(str(x).startswith("cannot check") for x in sb.problems):
        sb.inapplicable = True
    return sb
