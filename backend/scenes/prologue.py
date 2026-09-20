"""The two beats that open every animation, before the student's work appears.

Feedback that produced this: "each video should start with 'let's visualize what
you wrote', then provide an example animation of what the given thing you're
studying represents, then follow your logic."

So every render is three acts:

    1. TITLE    "Let's visualize what you wrote."          ~2.5s
    2. CONCEPT  what the thing under study actually IS,    ~7-9s
                demonstrated on numbers that are NOT the
                student's
    3. THE WORK the existing template                      unchanged

Act 2 is the part that earns the extra runtime. A student who mis-projected does
not need their own numbers replayed faster -- they need to have seen, once, what
a projection *is*, so that when their own arrow overshoots they already know what
it was supposed to look like.

Two rules hold throughout:

* **The concept beat never uses the student's numbers.** It is a worked example
  with its own values, so it cannot leak the answer to the problem in front of
  them. Everything here is hard-coded.
* **It never states the correction.** It shows the idea and gets out of the way.

``concept_for`` maps a template + params onto one of these, and returns None when
no beat fits -- an unknown topic gets the title and goes straight to the work
rather than a beat that says nothing.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np

# The manim CLI loads a scene file as a standalone script, so a relative import
# has no parent package to resolve against. Same shim common.py uses.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import (  # noqa: E402
    CORRECT,
    GHOST,
    STUDENT,
    T,
    make_plane,
    title_text,
)

from manim import (
    Arrow,
    DashedLine,
    FadeIn,
    FadeOut,
    Flash,
    Line,
    Polygon,
    Scene,
    Transform,
    VGroup,
    Write,
)

# The concept beat owns the whole frame, so it uses a single centred plane
# rather than the two-panel chrome the templates use.
CONCEPT_RADIUS = 3.6
CONCEPT_UNIT = 1.02
IHAT = "#4ADE80"
JHAT = "#F87171"

TITLE_LINE = "Let's visualize what you wrote."


def _caption(s: str, y: float = -3.45, color: str = CORRECT, size: int = 33):
    t = T(s, font_size=size, color=color)
    t.move_to(np.array([0.0, y, 0.0]))
    return t


def _plane():
    return make_plane(
        np.array([0.0, 0.0, 0.0]),
        radius=CONCEPT_RADIUS,
        unit=CONCEPT_UNIT,
        stroke_opacity=0.55,
        stroke_width=1.7,
    )


def _arrow(plane, vec, color, width: float = 7.5) -> Arrow:
    o = plane.get_origin()
    tip = o + np.array([vec[0] * CONCEPT_UNIT, vec[1] * CONCEPT_UNIT, 0.0])
    return Arrow(o, tip, buff=0, color=color, stroke_width=width,
                 max_tip_length_to_length_ratio=0.22)


def _label(text: str, at, color: str, size: int = 28):
    t = T(text, font_size=size, color=color)
    t.move_to(np.array([at[0], at[1], 0.0]))
    return t


# ---------------------------------------------------------------------------
# Act 1
# ---------------------------------------------------------------------------

def play_title(scene: Scene) -> None:
    line = title_text(TILE := TITLE_LINE)
    line.move_to(np.array([0.0, 0.35, 0.0]))
    sub = T("first, what this is really doing", font_size=27, color=GHOST)
    sub.move_to(np.array([0.0, -0.55, 0.0]))
    scene.play(Write(line), run_time=1.3)
    scene.play(FadeIn(sub, shift=0.2 * np.array([0.0, 1.0, 0.0])), run_time=0.7)
    scene.wait(0.7)
    scene.play(FadeOut(VGroup(line, sub)), run_time=0.5)


# ---------------------------------------------------------------------------
# Act 2 -- one function per concept. All values are hard-coded worked examples.
# ---------------------------------------------------------------------------

def _concept_transform(scene: Scene) -> None:
    """A matrix moves the whole plane, and the basis vectors say how."""
    plane = _plane()
    i = _arrow(plane, (1, 0), IHAT)
    j = _arrow(plane, (0, 1), JHAT)
    cap = _caption("a matrix moves the whole plane")
    scene.play(FadeIn(plane), run_time=0.8)
    scene.play(FadeIn(i), FadeIn(j), Write(cap), run_time=1.0)
    scene.wait(0.6)

    M = np.array([[1.0, 0.8], [0.35, 1.0]])
    cap2 = _caption("follow where the two arrows land -- the grid follows them")
    tgt_i = _arrow(plane, M @ np.array([1.0, 0.0]), IHAT)
    tgt_j = _arrow(plane, M @ np.array([0.0, 1.0]), JHAT)
    A = np.eye(3)
    A[:2, :2] = M
    scene.play(Transform(cap, cap2), run_time=0.5)
    scene.play(
        plane.animate.apply_matrix(A, about_point=plane.get_origin()),
        Transform(i, tgt_i),
        Transform(j, tgt_j),
        run_time=2.4,
    )
    scene.wait(1.1)
    scene.play(FadeOut(VGroup(plane, i, j, cap)), run_time=0.6)


def _concept_inverse(scene: Scene) -> None:
    """An inverse is whatever puts the plane back exactly where it started."""
    plane = _plane()
    i = _arrow(plane, (1, 0), IHAT)
    j = _arrow(plane, (0, 1), JHAT)
    home = plane.copy().set_stroke(GHOST, opacity=0.32)
    cap = _caption("an inverse puts the plane back where it started")
    scene.play(FadeIn(plane), FadeIn(i), FadeIn(j), Write(cap), run_time=1.1)
    scene.add(home)
    plane.set_z_index(1)
    scene.wait(0.5)

    M = np.array([[1.6, 0.9], [0.2, 1.3]])
    A = np.eye(3); A[:2, :2] = M
    Ainv = np.eye(3); Ainv[:2, :2] = np.linalg.inv(M)

    scene.play(Transform(cap, _caption("go out...")), run_time=0.4)
    scene.play(
        plane.animate.apply_matrix(A, about_point=plane.get_origin()),
        Transform(i, _arrow(plane, M @ np.array([1.0, 0.0]), IHAT)),
        Transform(j, _arrow(plane, M @ np.array([0.0, 1.0]), JHAT)),
        run_time=1.9,
    )
    scene.wait(0.7)
    scene.play(Transform(cap, _caption("...and the inverse brings it home")), run_time=0.4)
    scene.play(
        plane.animate.apply_matrix(Ainv, about_point=plane.get_origin()),
        Transform(i, _arrow(plane, (1, 0), IHAT)),
        Transform(j, _arrow(plane, (0, 1), JHAT)),
        run_time=1.9,
    )
    scene.play(Flash(plane.get_origin(), color=CORRECT, line_length=0.28), run_time=0.6)
    scene.wait(0.8)
    scene.play(FadeOut(VGroup(plane, home, i, j, cap)), run_time=0.6)


def _concept_projection(scene: Scene) -> None:
    """A projection is a shadow, and a shadow is never longer than its object."""
    plane = _plane()
    v = _arrow(plane, (3.0, 0.6), CORRECT)          # the line we project onto
    u = _arrow(plane, (1.3, 2.3), STUDENT)          # the vector casting the shadow
    lv = _label("v", (3.0 * CONCEPT_UNIT + 0.32, 0.6 * CONCEPT_UNIT), CORRECT)
    lu = _label("u", (1.3 * CONCEPT_UNIT - 0.1, 2.3 * CONCEPT_UNIT + 0.33), STUDENT)
    cap = _caption("a projection is a shadow cast onto a line")
    scene.play(FadeIn(plane), run_time=0.7)
    scene.play(FadeIn(v), FadeIn(lv), FadeIn(u), FadeIn(lu), Write(cap), run_time=1.1)
    scene.wait(0.6)

    o = plane.get_origin()
    vv = np.array([3.0, 0.6]); uu = np.array([1.3, 2.3])
    k = float(uu @ vv) / float(vv @ vv)
    foot = o + np.array([k * vv[0] * CONCEPT_UNIT, k * vv[1] * CONCEPT_UNIT, 0.0])
    tip_u = o + np.array([uu[0] * CONCEPT_UNIT, uu[1] * CONCEPT_UNIT, 0.0])

    ray = DashedLine(tip_u, foot, color=GHOST, stroke_width=3.2, dash_length=0.12)
    scene.play(Write(ray), run_time=0.9)
    shadow = Arrow(o, foot, buff=0, color=IHAT, stroke_width=8.0,
                   max_tip_length_to_length_ratio=0.25)
    scene.play(
        Transform(cap, _caption("the shadow lands ON the line, and is SHORTER than u")),
        FadeIn(shadow), run_time=1.0,
    )
    scene.wait(1.3)
    scene.play(FadeOut(VGroup(plane, v, u, lv, lu, ray, shadow, cap)), run_time=0.6)


def _concept_eigen(scene: Scene) -> None:
    """An eigenvector is the vector that refuses to leave its own line."""
    plane = _plane()
    M = np.array([[2.0, 1.0], [1.0, 2.0]])          # eigenvectors (1,1) and (1,-1)
    keeps = np.array([1.4, 1.4])
    leaves = np.array([0.4, 1.9])

    ray = Line(
        plane.get_origin() - np.array([3.0 * CONCEPT_UNIT, 3.0 * CONCEPT_UNIT, 0.0]),
        plane.get_origin() + np.array([3.0 * CONCEPT_UNIT, 3.0 * CONCEPT_UNIT, 0.0]),
        color=GHOST, stroke_width=2.6,
    )
    a = _arrow(plane, keeps, IHAT)
    b = _arrow(plane, leaves, STUDENT)
    cap = _caption("most vectors get knocked off their own line")
    scene.play(FadeIn(plane), FadeIn(ray), run_time=0.8)
    scene.play(FadeIn(a), FadeIn(b), Write(cap), run_time=1.0)
    scene.wait(0.6)

    A = np.eye(3); A[:2, :2] = M
    scene.play(
        plane.animate.apply_matrix(A, about_point=plane.get_origin()),
        Transform(a, _arrow(plane, M @ keeps, IHAT)),
        Transform(b, _arrow(plane, M @ leaves, STUDENT)),
        run_time=2.3,
    )
    scene.play(
        Transform(cap, _caption("an eigenvector stays on its own line -- only its length changes")),
        run_time=0.6,
    )
    scene.wait(1.4)
    scene.play(FadeOut(VGroup(plane, ray, a, b, cap)), run_time=0.6)


def _concept_determinant(scene: Scene) -> None:
    """The determinant is the factor the unit square's area is multiplied by."""
    plane = _plane()
    o = plane.get_origin()
    u = CONCEPT_UNIT

    def square(M):
        pts = [np.array([0.0, 0.0]), M @ np.array([1.0, 0.0]),
               M @ np.array([1.0, 1.0]), M @ np.array([0.0, 1.0])]
        return Polygon(*[o + np.array([p[0] * u, p[1] * u, 0.0]) for p in pts],
                       color=STUDENT, fill_opacity=0.28, stroke_width=4)

    sq = square(np.eye(2))
    cap = _caption("start with one unit of area")
    scene.play(FadeIn(plane), run_time=0.7)
    scene.play(FadeIn(sq), Write(cap), run_time=1.0)
    scene.wait(0.7)

    M = np.array([[2.0, 0.6], [0.4, 1.6]])          # det = 3.2 - 0.24
    A = np.eye(3); A[:2, :2] = M
    scene.play(Transform(cap, _caption("the determinant is how much that area grows")), run_time=0.5)
    scene.play(
        plane.animate.apply_matrix(A, about_point=o),
        Transform(sq, square(M)),
        run_time=2.3,
    )
    scene.wait(1.3)
    scene.play(FadeOut(VGroup(plane, sq, cap)), run_time=0.6)


def _concept_span(scene: Scene) -> None:
    """The span is everywhere the vectors can reach by scaling and adding."""
    plane = _plane()
    a = _arrow(plane, (1.6, 0.7), IHAT)
    b = _arrow(plane, (-0.8, 1.5), JHAT)
    cap = _caption("scale them, add them -- where can you land?")
    scene.play(FadeIn(plane), run_time=0.7)
    scene.play(FadeIn(a), FadeIn(b), Write(cap), run_time=1.0)
    scene.wait(0.5)

    o = plane.get_origin()
    va, vb = np.array([1.6, 0.7]), np.array([-0.8, 1.5])
    dots = VGroup()
    for s in (-1.4, -0.7, 0.7, 1.4):
        for t in (-1.4, -0.7, 0.7, 1.4):
            p = s * va + t * vb
            dots.add(_arrow(plane, p, GHOST, width=2.0).set_opacity(0.45))
    scene.play(FadeIn(dots, lag_ratio=0.04), run_time=1.8)
    scene.play(Transform(cap, _caption("two independent vectors reach the whole plane")), run_time=0.6)
    scene.wait(1.2)
    scene.play(FadeOut(VGroup(plane, a, b, dots, cap)), run_time=0.6)


def _concept_dot(scene: Scene) -> None:
    """The dot product measures how much one vector runs along another."""
    plane = _plane()
    v = _arrow(plane, (2.6, 0.0), CORRECT)
    u = _arrow(plane, (1.7, 1.9), STUDENT)
    cap = _caption("the dot product measures how much u runs along v")
    scene.play(FadeIn(plane), run_time=0.7)
    scene.play(FadeIn(v), FadeIn(u), Write(cap), run_time=1.0)
    scene.wait(0.6)

    o = plane.get_origin()
    foot = o + np.array([1.7 * CONCEPT_UNIT, 0.0, 0.0])
    tip_u = o + np.array([1.7 * CONCEPT_UNIT, 1.9 * CONCEPT_UNIT, 0.0])
    drop = DashedLine(tip_u, foot, color=GHOST, stroke_width=3.0, dash_length=0.12)
    along = Line(o, foot, color=IHAT, stroke_width=9)
    scene.play(Write(drop), run_time=0.8)
    scene.play(FadeIn(along), run_time=0.7)
    scene.play(Transform(cap, _caption("that overlap, times the length of v")), run_time=0.6)
    scene.wait(1.3)
    scene.play(FadeOut(VGroup(plane, v, u, drop, along, cap)), run_time=0.6)


CONCEPTS = {
    "transform": _concept_transform,
    "inverse": _concept_inverse,
    "projection": _concept_projection,
    "eigen": _concept_eigen,
    "determinant": _concept_determinant,
    "span": _concept_span,
    "dot": _concept_dot,
}


# ---------------------------------------------------------------------------
# Choosing a beat
# ---------------------------------------------------------------------------

def concept_for(scene_name: str, params: dict) -> Optional[str]:
    """Pick the concept beat for a template + its params, or None to skip.

    Deliberately conservative: an unrecognised scene gets the title and goes
    straight to the work. A beat that explains the wrong idea is worse than no
    beat, because it costs runtime AND misleads.
    """
    explicit = (params or {}).get("concept")
    if explicit in CONCEPTS:
        return explicit
    if explicit == "none":
        return None

    name = (scene_name or "").lower()
    blob = " ".join(
        str((params or {}).get(k, "")) for k in ("mode", "op", "topic", "title", "op_label")
    ).lower()

    # Order matters: the more specific ideas are tested before the generic
    # "a matrix moves the plane", which would otherwise swallow all of them.
    for key, hit in (
        ("inverse", "inverse" in name or "inverse" in blob or "roundtrip" in name),
        ("eigen", "eigen" in name or "eigen" in blob),
        ("projection", "projection" in name or "project" in blob),
        ("determinant", "determinant" in name or "det" in blob or "area" in name),
        ("span", "span" in name or "span" in blob),
        ("dot", "dot" in blob),
        ("transform", "grid" in name or "matrix" in name or "compose" in name
                      or "composition" in name or "product" in blob),
    ):
        if hit:
            return key
    return None


def play_prologue(scene: Scene, params: dict, *, scene_name: str = "") -> None:
    """Acts 1 and 2. Safe to call from any template.

    A failure here must never cost the student their animation, so the concept
    beat is best-effort: if it raises, the scene continues into the work.
    """
    if (params or {}).get("skip_prologue"):
        return
    # No title card. It was three seconds of words in front of every single
    # video, saying nothing the animation does not say better, and the first
    # thing anyone watching wants is the picture. play_title() is kept for the
    # standalone renders that still call it directly.
    key = concept_for(scene_name or type(scene).__name__, params)
    if not key:
        return
    try:
        CONCEPTS[key](scene)
    except Exception:
        # Leave nothing half-drawn on the way into act 3.
        scene.clear()
