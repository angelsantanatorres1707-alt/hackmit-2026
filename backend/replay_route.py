"""Should this job be a step-through replay of the student's own work?

This is the routing layer between :mod:`backend.step_compiler` (which turns
extracted steps into ``StepReplay`` params) and :mod:`backend.hints` (which
picks a scene). It exists so the planner's edit stays four lines.

The product rule it implements
------------------------------

    A replay of the student's OWN steps is the DEFAULT. The seven canned
    comparison templates are the fallback, for work a replay cannot be built
    from.

That inverts what the app did before, which was: locate the first wrong step,
then pick one of seven pre-made comparisons and show a single before/after of
the *endpoint*. The endpoint is not the reasoning. This module is the switch.

What "can be built" means, concretely (``step_compiler.viable`` plus the two
extra gates here):

  * at least two steps survived parsing, and
  * at least ``MIN_MOTION`` of them move something on the canvas -- a replay of
    two arithmetic lines is a slideshow, not a replay, and
  * a framing exists that holds the opening and the closing state, and
  * ``step_compiler`` actually imported. It is written by a separate workstream;
    if it is missing or broken this module reports "not available" and the old
    ladder runs untouched. Nothing here may take the demo down.

Nothing in this module reads ``verdict.correct_value``, and neither does the
compiler (see its module docstring). A scene that is never handed the right
answer cannot leak it.
"""

from __future__ import annotations

from typing import Any, Optional

#: A replay needs this many steps that actually move something. One moving step
#: and one ledger line is a still frame with a caption; the comparison
#: templates tell that story better.
MIN_MOTION = 2

#: Scene-side overhead model, copied from ``StepReplay._fit_budget`` so the
#: per-step windows below line up with what the scene actually plays.
PROLOGUE = 1.2          # givens grow in, title writes
EPILOGUE = 2.7          # hint writes (1.0) + final hold (1.7)
LEDGER_BEAT = 0.62      # the student's line types into the rail
MARK_BEAT = 0.35        # the tick (or, for the wrong step, part of the caret)
INVARIANT_BEAT = 1.25   # region goes up, then holds
WRONG_BEAT = 3.45       # caret + the three escalating divergence cues
ACTION_OVERHEAD = 1.15  # handlers cost ~15% more than their nominal run_time


# --------------------------------------------------------------------------
# Defensive import -- step_compiler is another workstream's file
# --------------------------------------------------------------------------

def _compiler():
    """-> (module, None) or (None, why-not). Never raises."""
    try:
        from . import step_compiler as sc
    except Exception as exc:  # pragma: no cover - the whole point is not caring
        return None, f"step_compiler unavailable ({type(exc).__name__}: {exc})"
    for fn in ("compile_replay", "viable"):
        if not callable(getattr(sc, fn, None)):
            return None, f"step_compiler has no {fn}()"
    return sc, None


def available() -> bool:
    return _compiler()[0] is not None


# --------------------------------------------------------------------------
# The timeline the frontend scrubs against
# --------------------------------------------------------------------------

def _timeline(steps: list[dict]) -> tuple[list[tuple[float, float]], float]:
    """Per-step (start, end) in seconds, plus the predicted total.

    Estimated, not measured: the scene's handlers pick their own sub-beats and
    only the renderer knows the exact cut points. The model is the one the
    scene itself budgets with, so it is the closest thing to the truth that is
    available before the mp4 exists. The response says so, and hands the
    frontend a total to normalise against the real ``video.duration``.
    """
    windows: list[tuple[float, float]] = []
    t = PROLOGUE
    for st in steps:
        start = t
        t += LEDGER_BEAT
        if st.get("invariant"):
            t += INVARIANT_BEAT
        t += float(st.get("run_time") or 0.0) * ACTION_OVERHEAD
        t += WRONG_BEAT if st.get("first_wrong") else MARK_BEAT
        windows.append((round(start, 2), round(t, 2)))
    return windows, round(t + EPILOGUE, 2)


def _reads(st: dict) -> str:
    """The one-line proof that this step came off the student's page.

    ``why`` is the compiler's own justification, e.g. "the scalar k a previous
    step bound, times a -- checked: 5 x (1, 2) = (5, 10)". Putting it in the
    response is what turns "it just defaults to a template" from a claim into
    something a judge can read off the screen.
    """
    return str(st.get("why") or "").strip()


def replay_view(params: dict, result: Any, *, hint: str = "") -> dict:
    """The block the frontend needs to show which step the replay is on."""
    steps = list(params.get("steps") or [])
    windows, total = _timeline(steps)
    first_wrong_index = next(
        (i for i, s in enumerate(steps) if s.get("first_wrong")), None
    )
    out_steps = []
    for i, (st, (start, end)) in enumerate(zip(steps, windows)):
        res = st.get("result") or {}
        out_steps.append(
            {
                "index": i,
                "id": st.get("id"),
                # Their numbering, off their page -- never our array index.
                "student_label": st.get("student_label") or "",
                "kind": st.get("kind"),
                "expr": st.get("expr") or "",
                "status": st.get("status"),
                "first_wrong": bool(st.get("first_wrong")),
                "result_display": res.get("display"),
                "operands": sorted(
                    (st.get("operands") or {}).get(k, {}).get("symbol", k)
                    for k in (st.get("operands") or {})
                ),
                "reads": _reads(st),
                "run_time": st.get("run_time"),
                "start": start,
                "end": end,
                "has_invariant": bool(st.get("invariant")),
            }
        )
    return {
        "available": True,
        "template": "StepReplay",
        "hint": hint or params.get("hint") or "",
        "title": params.get("title") or "",
        "step_count": len(out_steps),
        "motion_steps": int(getattr(result, "motion_steps", 0) or 0),
        "first_wrong_index": first_wrong_index,
        "first_wrong_id": (
            steps[first_wrong_index].get("id") if first_wrong_index is not None else None
        ),
        "first_wrong_label": (
            steps[first_wrong_index].get("student_label")
            if first_wrong_index is not None else None
        ),
        "givens": {
            k: {"display": g.get("display"), "kind": g.get("kind"),
                "color": g.get("color")}
            for k, g in (params.get("givens") or {}).items()
        },
        "steps": out_steps,
        # Timing contract for the player, stated rather than implied.
        "timing": {
            "basis": "estimated",
            "estimated_duration": total,
            # currentTime * (estimated_duration / video.duration) lands inside
            # the right [start, end) even when the render runs a little long.
            "scale_to_duration": True,
        },
        "warnings": list(getattr(result, "warnings", []) or []),
    }


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def build(ext: Any, verdict: Any, *, title: Optional[str] = None,
          hint: Optional[str] = None, student_label: str = "YOUR WORK",
          min_motion: int = MIN_MOTION) -> dict:
    """Try to compile a replay of this student's work.

    -> ``{"ok": bool, "reason": str, "params": dict|None, "result": obj|None,
          "caption": str, "warnings": [str]}``. Never raises: a compiler that
    falls over is a reason to use the old ladder, never a 500.
    """
    sc, why = _compiler()
    if sc is None:
        return {"ok": False, "reason": why, "params": None, "result": None,
                "caption": "", "warnings": []}
    try:
        result = sc.compile_replay(ext, verdict, title=title, hint=hint,
                                   student_label=student_label)
    except Exception as exc:  # the compiler promises not to, but promises break
        return {"ok": False,
                "reason": f"compile_replay raised {type(exc).__name__}: {exc}",
                "params": None, "result": None, "caption": "", "warnings": []}

    params = getattr(result, "params", None)
    if not isinstance(params, dict):
        return {"ok": False, "reason": "compiler returned no params",
                "params": None, "result": None, "caption": "", "warnings": []}

    warnings = list(getattr(result, "warnings", []) or [])
    try:
        ok, reason = sc.viable(params, min_motion=min_motion)
    except TypeError:          # an older signature without min_motion
        ok, reason = sc.viable(params)
        if ok:
            motion = int(getattr(result, "motion_steps", 0) or 0)
            if motion < min_motion:
                ok, reason = False, f"only {motion} step(s) move anything on the canvas"
    except Exception as exc:
        ok, reason = False, f"viable() raised {type(exc).__name__}: {exc}"

    # A replay whose wrong step was never located plays the student's reasoning
    # and then just stops. The comparison templates at least point somewhere.
    if ok and not any(s.get("first_wrong") for s in (params.get("steps") or [])):
        ok, reason = False, "no step is marked first_wrong -- nothing to walk into"

    return {
        "ok": bool(ok),
        "reason": "" if ok else str(reason or "not viable"),
        "params": params,
        "result": result,
        "caption": str(params.get("hint") or "").strip(),
        "warnings": warnings,
    }
