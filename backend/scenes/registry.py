"""Template registry -- the one thing the backend imports.

    from backend.scenes.registry import TEMPLATES, validate_params, render

    entry = TEMPLATES["GridTransformCompare"]
    params = validate_params("GridTransformCompare", payload["params"])
    mp4 = render("GridTransformCompare", params, job_id="abc")

Every id from ERROR_TAXONOMY.md resolves here, including the three that are
aliases for one class with different presets (CompositionOrderCompare,
InverseRoundTrip -> GridTransformCompare; RowOpLinePivot,
SolutionPointCheck -> LineSystemCompare).

``param_schema`` says, per parameter, what type it is and WHO fills it:
  "backend"  -- computed by sympy (every matrix, vector, scalar and its
                fmt_num display string). An LLM retyping a matrix sympy
                already produced is a pure opportunity to corrupt it.
  "planner"  -- editorial: which story to tell and how to word it.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import SceneParamError  # noqa: E402
from determinant_area import DeterminantAreaCompare  # noqa: E402
from eigen_ray import EigenRayTest  # noqa: E402
from grid_transform import GridTransformCompare  # noqa: E402
from angle_check import AnglePreservationCheck  # noqa: E402
from line_system import LineSystemCompare  # noqa: E402
from span_compare import SpanCompare  # noqa: E402
from step_focus import StaticStepHighlight  # noqa: E402
from step_replay import StepReplay  # noqa: E402
from vector_op import VectorOpCompare  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))

# Rendering is serialized: manim.config is global and the scene classes carry
# their params in a class attribute, neither of which is thread-safe.
RENDER_LOCK = threading.Lock()

_S = "backend"   # filled by sympy
_L = "planner"   # filled by the LLM


TEMPLATES: dict[str, dict[str, Any]] = {
    "AnglePreservationCheck": {
        "class": AnglePreservationCheck,
        "module": "angle_check",
        "file": os.path.join(_HERE, "angle_check.py"),
        "scene": "AnglePreservationCheck",
        "priority": "P1",
        "duration": 11.0,
        "covers": ["LA22", "LA23"],
        "summary": "Draw the basis and the right angle between it, apply the "
                   "student's own map, and watch the corner close (or, in "
                   "length mode, watch the tips leave the unit circle).",
        "param_schema": {
            "e1_image": (_S, "2-vector: where e1 lands"),
            "e2_image": (_S, "2-vector: where e2 lands"),
            "show": (_S, "'angle' (corner closes) or 'length' (tips leave the circle)"),
            "title": (_L, "str"),
            "hint": (_L, "str, positional only -- see check_hint"),
        },
    },
    # -- T1 ------------------------------------------------------------
    "GridTransformCompare": {
        "class": GridTransformCompare,
        "module": "grid_transform",
        "file": os.path.join(_HERE, "grid_transform.py"),
        "scene": "GridTransformCompare",
        "priority": "P0",
        "duration": 8.7,
        "covers": ["LA01", "LA02", "LA07", "LA08", "LA16", "unmatched"],
        "summary": "Apply the student's sequence of maps to a grid on the left "
                   "and the correct sequence on the right.",
        "param_schema": {
            "student_stages": (_S, "list[2x2 matrix], 1-3, applied in order"),
            "correct_stages": (_S, "list[2x2 matrix], same length"),
            "student_display": (_S, "[[str]] fmt_num; defaults to the product"),
            "correct_display": (_S, "[[str]] fmt_num; defaults to the product"),
            "track_vectors": (_S, "list[2-vector], defaults to the basis"),
            "ghost_reference": (_L, "bool: faint fixed original grid underneath"),
            "pause_between_stages": (_L, "float seconds on the intermediate"),
            "stage_labels": (_L, "list[str], one per stage"),
            "title": (_L, "str"),
            "student_label": (_L, "str, e.g. WHAT YOU WROTE"),
            "correct_label": (_L, "str"),
            "hint": (_L, "str, positional only -- see check_hint"),
        },
    },
    # -- T2 ------------------------------------------------------------
    "EigenRayTest": {
        "class": EigenRayTest,
        "module": "eigen_ray",
        "file": os.path.join(_HERE, "eigen_ray.py"),
        "scene": "EigenRayTest",
        "priority": "P0",
        "duration": 9.4,
        "covers": ["LA09", "LA10"],
        "summary": "Does the vector stay on its own line when M is applied?",
        "param_schema": {
            "M": (_S, "2x2 matrix"),
            "M_display": (_S, "[[str]] fmt_num"),
            "v_claimed": (_S, "2-vector, nonzero"),
            "v_correct": (_S, "2-vector, a genuine eigenvector"),
            "lambda_claimed": (_S, "real number, eigenvalue mode only"),
            "lambda_correct": (_S, "real number, eigenvalue mode only"),
            "mode": (_L, "'vector' (LA09) | 'eigenvalue' (LA10)"),
            "title": (_L, "str"),
            "student_label": (_L, "str"),
            "correct_label": (_L, "str"),
            "hint": (_L, "str"),
        },
    },
    # -- T3 ------------------------------------------------------------
    "StaticStepHighlight": {
        "class": StaticStepHighlight,
        "module": "step_focus",
        "file": os.path.join(_HERE, "step_focus.py"),
        "scene": "StaticStepHighlight",
        "priority": "P0",
        "duration": 8.0,
        "covers": ["LA03", "LA18", "LA01(pairing)", "every fallback"],
        "summary": "Re-typeset the student's own steps and point at one cell. "
                   "The bottom of the fallback ladder: never raises.",
        "param_schema": {
            "lines": (_S, "[{kind:'matrix',rows,prefix}|{kind:'text',text}]"),
            "shapes": (_S, "[[r,c],[r,c]] optional: circles the inner dims"),
            "pairing": (_S, "null | {A_rows,B_rows,target,student_entry,"
                            "correct_entry,wrong_source}"),
            "focus": (_L, "{line:int, cell:[i,j]} or {line:int, chars:[a,b]}"),
            "annotation": (_L, "str shown under the work"),
            "title": (_L, "str"),
            "hint": (_L, "str"),
        },
    },
    # -- T4 ------------------------------------------------------------
    "DeterminantAreaCompare": {
        "class": DeterminantAreaCompare,
        "module": "determinant_area",
        "file": os.path.join(_HERE, "determinant_area.py"),
        "scene": "DeterminantAreaCompare",
        "priority": "P1",
        "duration": 10.2,
        "covers": ["LA04", "LA06", "LA05(3x3, P2)"],
        "summary": "Unit square under M with a live signed-area readout beside "
                   "the student's frozen number.",
        "param_schema": {
            "M": (_S, "2x2 or 3x3 matrix"),
            "M_display": (_S, "[[str]] fmt_num"),
            "claimed_det": (_S, "str/number the student wrote"),
            "actual_det": (_S, "str; defaults to det(M)"),
            "show_ghost_scale": (_L, "bool: tile the claimed area in grey"),
            "title": (_L, "str"),
            "hint": (_L, "str"),
        },
    },
    # -- T5 ------------------------------------------------------------
    "VectorOpCompare": {
        "class": VectorOpCompare,
        "module": "vector_op",
        "file": os.path.join(_HERE, "vector_op.py"),
        "scene": "VectorOpCompare",
        "priority": "P1",
        "duration": 10.0,
        "covers": ["LA11", "LA19", "LA31", "LA17(3D, P2)"],
        "summary": "One plane, the invariant the operation must satisfy, the "
                   "true answer satisfying it, the claimed answer breaking it.",
        "param_schema": {
            "u": (_S, "2-vector (3-vector for cross)"),
            "v": (_S, "2-vector (3-vector for cross)"),
            "w_claimed": (_S, "the student's result"),
            "w_correct": (_S, "the true result"),
            "readouts": (_S, "[[label, value]] up to 3 rows"),
            "op": (_L, "'normalize'|'projection'|'cross'|'generic'"),
            "labels": (_L, "{u: str, v: str}"),
            "title": (_L, "str"),
            "hint": (_L, "str"),
        },
    },
    # -- T6 ------------------------------------------------------------
    "LineSystemCompare": {
        "class": LineSystemCompare,
        "module": "line_system",
        "file": os.path.join(_HERE, "line_system.py"),
        "scene": "LineSystemCompare",
        "priority": "P1",
        "duration": 8.8,
        "covers": ["LA12", "LA13", "generic Ax=b"],
        "summary": "Equations as lines: a legal row operation pivots about the "
                   "intersection, an illegal one lets go of it.",
        "param_schema": {
            "equations": (_S, "[[a,b,c],[a,b,c]] for ax+by=c"),
            "student_result_line": (_S, "[a,b,c], row_op mode"),
            "correct_result_line": (_S, "[a,b,c], row_op mode"),
            "x_claimed": (_S, "2-vector, solution mode"),
            "x_correct": (_S, "2-vector; defaults to the intersection"),
            "substitutions": (_S, "[[lhs, required_rhs]] as strings"),
            "mode": (_L, "'solution' | 'row_op'"),
            "op_label": (_L, "str, e.g. 'R2 - 3R1'"),
            "title": (_L, "str"),
            "hint": (_L, "str"),
        },
    },
    # -- T7 ------------------------------------------------------------
    "SpanCompare": {
        "class": SpanCompare,
        "module": "span_compare",
        "file": os.path.join(_HERE, "span_compare.py"),
        "scene": "SpanCompare",
        "priority": "P2",
        "duration": 11.3,
        "covers": ["LA15", "LA14(3D, P2)", "LA30"],
        "summary": "Paint every point the combinations reach, then fail to "
                   "reach a probe that is verified out of reach.",
        "param_schema": {
            "vectors": (_S, "1-3 vectors of length `ambient`"),
            "claimed_dim": (_S, "int the student asserted"),
            "actual_dim": (_S, "int; recomputed from rank anyway"),
            "probe": (_S, "vector verified unreachable, or null"),
            "ambient": (_L, "2 | 3"),
            "title": (_L, "str"),
            "hint": (_L, "str"),
        },
    },
    # -- T8 ------------------------------------------------------------
    # The only template that replays the student's REASONING rather than
    # summarising its endpoint. Try it FIRST whenever there are >= 2 parsed
    # steps and at least two of them carry geometry; the seven templates
    # above become the fallback tier. See docs/STEP_REPLAY.md.
    "StepReplay": {
        "class": StepReplay,
        "module": "step_replay",
        "file": os.path.join(_HERE, "step_replay.py"),
        "scene": "StepReplay",
        "priority": "P0",
        "duration": 15.4,
        "covers": ["any multi-step solution", "LA11", "LA19", "LA02", "LA12"],
        "summary": "Replay the student's own steps, in order, on one canvas: "
                   "each step's geometry driven by their own parsed numbers, "
                   "going wrong where their reasoning does.",
        "param_schema": {
            "givens": (_S, "symbol -> {kind,value,display,color}"),
            "steps": (_S, "ordered list; see docs/STEP_REPLAY.md section 3. "
                          "Each: {id,student_label,kind,expr,args,result,bind,"
                          "status,first_wrong,run_time,invariant,divergence}"),
            "canvas": (_S, "framing block {box,box_center,pad,margin,zoom_max}; "
                           "the solver fills it"),
            "leak_guard": (_S, "list[str] of kinds present DOWNSTREAM"),
            "title": (_L, "str"),
            "student_label": (_L, "str, the ledger rail heading"),
            "hint": (_L, "str, positional only -- see check_hint"),
        },
    },
}

# ---------------------------------------------------------------------------
# Aliases from ERROR_TAXONOMY.md. Same class, different preset params.
# ---------------------------------------------------------------------------
ALIASES: dict[str, tuple[str, dict[str, Any]]] = {
    "CompositionOrderCompare": ("GridTransformCompare",
                                {"pause_between_stages": 0.8}),
    "InverseRoundTrip": ("GridTransformCompare", {"ghost_reference": True}),
    "RowOpLinePivot": ("LineSystemCompare", {"mode": "row_op"}),
    "SolutionPointCheck": ("LineSystemCompare", {"mode": "solution"}),
    # convenience spellings
    "MatrixProductSteps": ("StaticStepHighlight", {}),
}

FALLBACK = "StaticStepHighlight"


def resolve(name: str) -> tuple[str, dict[str, Any]]:
    """Template id (or alias) -> (canonical id, preset params)."""
    if name in TEMPLATES:
        return name, {}
    if name in ALIASES:
        canon, preset = ALIASES[name]
        return canon, dict(preset)
    raise SceneParamError(f"unknown template {name!r}")


def get(name: str) -> dict[str, Any]:
    canon, _ = resolve(name)
    return TEMPLATES[canon]


def validate_params(name: str, params: dict | None) -> dict:
    """Raises SceneParamError -- the caller degrades down the ladder:
    chosen template -> StaticStepHighlight -> still-frame PNG + hint text."""
    canon, preset = resolve(name)
    merged = dict(preset)
    merged.update(params or {})
    return TEMPLATES[canon]["class"].validate(merged)


def render(name: str, params: dict, *, job_id: str = "scene",
           media_dir: str | None = None, quality: str = "medium_quality",
           validate: bool = True) -> str:
    """Render in-process and return the mp4 path.

    Follows RENDERING.md "Option A": tempconfig + a class attribute holding
    the whole validated param dict. Serialized behind RENDER_LOCK because
    manim.config and class attributes are global. Call it from
    ``asyncio.to_thread`` -- .render() is blocking CPU work.
    """
    from manim import tempconfig

    canon, _ = resolve(name)
    entry = TEMPLATES[canon]
    cls = entry["class"]
    p = validate_params(name, params) if validate else params
    media_dir = media_dir or os.path.join("/tmp/hackmit_jobs", job_id)
    res = {"low_quality": "480p15", "medium_quality": "720p30",
           "high_quality": "1080p60"}.get(quality, "720p30")

    with RENDER_LOCK:
        with tempconfig({
            "quality": quality,
            "disable_caching": True,
            "media_dir": media_dir,
            "output_file": job_id,
            "verbosity": "ERROR",
        }):
            prev = cls.P
            cls.P = p
            try:
                cls().render()
            finally:
                cls.P = prev
    # NB: the in-process path has NO <script_stem> directory -- there is no
    # input script. This differs from the CLI layout.
    return os.path.join(media_dir, "videos", res, f"{job_id}.mp4")


def render_with_fallback(name: str, params: dict, fallback_params: dict, *,
                         job_id: str = "scene", **kw) -> tuple[str, str]:
    """Try the chosen template, degrade to StaticStepHighlight on any
    SceneParamError or render failure. Returns (mp4_path, template_used)."""
    try:
        return render(name, params, job_id=job_id, **kw), name
    except Exception as exc:  # noqa: BLE001
        print(f"[registry] {name} failed ({exc}); falling back to {FALLBACK}")
        return (render(FALLBACK, fallback_params, job_id=job_id, **kw),
                FALLBACK)


def selftest(quality: str = "low_quality") -> list[tuple[str, float, str]]:
    """Render every template with its built-in defaults. Returns
    [(template, seconds, mp4)]. Used by scripts/render_all.sh."""
    out = []
    for name in TEMPLATES:
        t0 = time.time()
        mp4 = render(name, TEMPLATES[name]["class"].DEFAULTS,
                     job_id=f"selftest_{name}", quality=quality)
        out.append((name, time.time() - t0, mp4))
    return out


if __name__ == "__main__":
    for name, secs, mp4 in selftest():
        print(f"{name:26s} {secs:5.2f}s  {mp4}  "
              f"{'OK' if os.path.exists(mp4) else 'MISSING'}")
