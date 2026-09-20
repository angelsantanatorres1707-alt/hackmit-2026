"""T7 -- SpanCompare.  Emptiness as evidence (P2).

Sweep the coefficients and paint every point the combinations actually
reach, then drop a probe vector outside the span and fail to reach it.
Their claim says the plane floods with colour; what happens is that every
combination lands on one line and the rest of the plane stays black.

Covers LA15 (span dimension overclaimed, 2D) and LA14 (dependent set called
independent, 3D parallelepiped with no volume, P2 of a P2).

Deterministic on purpose: pre-computed dots plus a lagged FadeIn, never
``TracedPath``. TracedPath depends on updater-vs-render ordering and gives a
slightly different picture every run, and "deterministic" is worth a great
deal when the render happens live in front of judges.

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/span_compare.py \
        SpanCompare
"""

from __future__ import annotations

import os
import sys

import numpy as np
from manim import (
    Create,
    Dot,
    FadeIn,
    FadeOut,
    Indicate,
    Line,
    MoveAlongPath,
    Polygon,
    Transform,
    VGroup,
    Write,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import (  # noqa: E402
    CORRECT,
    GHOST,
    I_HAT,
    J_HAT,
    PROBE,
    STUDENT,
    ParamScene,
    SceneParamError,
    VecArrow,
    Z_CHROME,
    Z_FLASH,
    Z_OVERLAY,
    arrow_at,
    check_hint,
    fit_unit,
    iso_project,
    label_text,
    MASK,
    MASK_COLOR,
    one_panel_layout,
    residual,
    reveal_correct_values,
    scoreboard,
)

# The plane used to be a 5.2 square at x=-2.5 with the scoreboard at 3.9,
# which left 2 units of dead frame on the left and a panel only 65% of the
# frame height. The frame is 16:9; so is the panel now.
PLANE_DX = -3.58
PLANE_BOX = 6.0        # HEIGHT -- what fit_unit and the in-panel captions use
PLANE_BOX_W = 6.4      # WIDTH
PLANE_DY = 0.10
BOARD_X = 3.45
DOT_COLORS = (I_HAT, J_HAT, PROBE)


def _dim_word(d: int) -> str:
    return {0: "a point", 1: "a line", 2: "a plane", 3: "all of space"}.get(
        int(d), f"dimension {int(d)}")


def _reached_row(actual_dim: int) -> tuple:
    """The "REACHED" scoreboard row.

    The dimension actually spanned IS the answer, in words instead of digits
    -- "a line" tells a student who claimed "a plane" exactly what to write.
    So it is masked unless REVEAL_CORRECT_VALUES is on; the dots that did or
    did not flood the plane are what the student reads instead.
    """
    if reveal_correct_values():
        return ("REACHED", _dim_word(actual_dim), CORRECT)
    return ("REACHED", MASK, MASK_COLOR)


class SpanCompare(ParamScene):
    TEMPLATE = "SpanCompare"
    DURATION = 10.4

    DEFAULTS = {
        "vectors": [[1, 2], [2, 4]],
        "claimed_dim": 2,
        "actual_dim": 1,
        "probe": [0, 1],
        "ambient": 2,
        "title": "Everything your two vectors can reach",
        "hint": "watch how much of the plane stays black",
    }

    # ------------------------------------------------------------------
    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})

        ambient = int(p.get("ambient") or 2)
        if ambient not in (2, 3):
            raise SceneParamError("ambient must be 2 or 3")
        p["ambient"] = ambient

        vecs = p.get("vectors") or []
        if not (1 <= len(vecs) <= 3):
            raise SceneParamError("between 1 and 3 vectors are supported")
        V = []
        for k, v in enumerate(vecs):
            arr = np.array(v, dtype=float).flatten()
            if arr.size != ambient or not np.all(np.isfinite(arr)):
                raise SceneParamError(
                    f"vectors[{k}] must have {ambient} finite components")
            if float(np.linalg.norm(arr)) < 1e-9:
                raise SceneParamError(f"vectors[{k}] is the zero vector")
            V.append(arr.tolist())
        p["vectors"] = V
        A = np.array(V, dtype=float).T

        claimed = int(p.get("claimed_dim", 0))
        actual = int(np.linalg.matrix_rank(A))
        if p.get("actual_dim") is not None and int(p["actual_dim"]) != actual:
            # trust the geometry, not the label
            pass
        p["actual_dim"] = actual
        p["claimed_dim"] = claimed
        if claimed == actual:
            raise SceneParamError(
                "claimed_dim equals the real rank: there is no story here")

        probe = p.get("probe")
        if probe is not None:
            pr = np.array(probe, dtype=float).flatten()
            if pr.size != ambient or not np.all(np.isfinite(pr)):
                raise SceneParamError(f"probe must have {ambient} components")
            # A search animation that could succeed is a lie: verify the probe
            # really is out of reach before promising it never arrives.
            aug = np.column_stack([A, pr])
            if np.linalg.matrix_rank(aug) <= np.linalg.matrix_rank(A):
                raise SceneParamError(
                    "probe IS reachable from these vectors -- the search would "
                    "be dishonest")
            p["probe"] = pr.tolist()

        p["hint"] = check_hint(str(p.get("hint", "")), [])
        p["title"] = str(p.get("title") or "")
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:
        if int(p["ambient"]) == 3:
            self._build_3d(p)
        else:
            self._build_2d(p)

    # -- 2D ------------------------------------------------------------
    def _build_2d(self, p: dict) -> None:
        V = [np.array(v, dtype=float) for v in p["vectors"]]
        probe = np.array(p["probe"], dtype=float) if p.get("probe") is not None \
            else None

        span_pts = [c * v for v in V for c in (-2.2, 2.2)]
        unit = fit_unit(span_pts + ([probe] if probe is not None else []),
                        box=PLANE_BOX)
        lay = one_panel_layout(self, title=p["title"], hint=p["hint"],
                               dx=PLANE_DX, dy=PLANE_DY, box=PLANE_BOX_W,
                               box_h=PLANE_BOX, unit=unit)
        P = lay.left

        board = scoreboard([("YOUR CLAIM", _dim_word(p["claimed_dim"]), STUDENT)],
                           anchor=np.array([BOARD_X, 1.0, 0.0]),
                           label_size=22, value_size=38)

        # Dependent inputs are collinear by construction, so the later arrow
        # would sit exactly on top of the earlier one: step the widths down so
        # both are still visible.
        arrows = [VecArrow(P, v, DOT_COLORS[k % 3], stroke_width=10 - 3 * k)
                  for k, v in enumerate(V)]
        # ...and draw the SHORTEST on top, or a dependent pair shows only the
        # longer arrow and the viewer never sees there were two.
        order = sorted(range(len(arrows)),
                       key=lambda k: -float(np.linalg.norm(V[k])))
        for rank, k in enumerate(order):
            arrows[k].mob.set_z_index(Z_OVERLAY + rank)

        # -- 0.0 / 1.2 --------------------------------------------------
        self.play(Create(P.plane), FadeIn(lay.title), FadeIn(board), run_time=1.2)
        # -- 1.2 / 1.0 --------------------------------------------------
        self.play(*[FadeIn(a.mob, scale=0.6) for a in arrows], run_time=1.0)
        self.wait(0.4)

        # -- 2.6 / 3.5  the sweep --------------------------------------
        reach = (PLANE_BOX / 2) / P.unit
        dots = VGroup()
        if len(V) == 1:
            grid = np.linspace(-reach, reach, 320)
            pts = [a * V[0] for a in grid]
        else:
            # The coefficient grid has to be FINE, not just wide: for a
            # dependent pair every combination collapses onto multiples of a
            # single step, so a coarse grid paints a dotted line with visible
            # holes instead of a filled one.
            n = 90
            g = np.linspace(-reach, reach, n)
            pts = [a * V[0] + b * V[1] for a in g for b in g]
        seen = set()
        for q in pts:
            if abs(q[0]) > reach + 0.5 or abs(q[1]) > reach + 0.5:
                continue
            key = (round(float(q[0]), 2), round(float(q[1]), 2))
            if key in seen or len(seen) >= 700:
                continue
            seen.add(key)
            dots.add(Dot(P.pt(q), radius=0.035, color=CORRECT,
                         fill_opacity=0.85))
        dots.set_z_index(Z_OVERLAY - 2)
        self.play(FadeIn(dots, lag_ratio=0.004), run_time=3.5)

        # -- 6.1 / 0.6  hold on the emptiness ---------------------------
        # Counter-intuitive but essential: the message is what FAILED to
        # happen, and absence needs airtime to register.
        self.wait(0.6)

        # -- 6.7 / 1.8  the probe --------------------------------------
        if probe is not None:
            p_dot = Dot(P.pt(probe), radius=0.11, color=PROBE)
            p_dot.set_z_index(Z_FLASH)
            p_lab = label_text("can you reach this?", font_size=18, color=PROBE,
                               max_width=3.0)
            p_lab.next_to(p_dot, np.array([-1.0, 0.0, 0.0]), buff=0.16)
            p_lab.set_z_index(Z_CHROME)
            d = V[0] / float(np.linalg.norm(V[0]))
            hunter = Dot(P.pt(-reach * d), radius=0.08, color=PROBE)
            hunter.set_z_index(Z_FLASH)
            path = Line(P.pt(-reach * d), P.pt(reach * d))
            back = Line(P.pt(reach * d), P.pt(-reach * d))
            t = float(np.dot(probe, d))
            foot = t * d
            self.play(FadeIn(p_dot), FadeIn(p_lab), FadeIn(hunter), run_time=0.4)
            self.play(MoveAlongPath(hunter, path), run_time=0.7)
            self.play(MoveAlongPath(hunter, back), run_time=0.7)
            gap = residual(P.pt(foot), P.pt(probe), color=PROBE, label="gap",
                           font_size=17, away_from=P.origin, label_buff=0.16)
            self.play(FadeIn(gap), FadeOut(hunter), run_time=0.5)
        else:
            self.wait(1.8)

        # -- 8.5 / 0.5  the scoreboard resolves -------------------------
        resolved = scoreboard(
            [("YOUR CLAIM", _dim_word(p["claimed_dim"]), STUDENT),
             _reached_row(p["actual_dim"])],
            anchor=np.array([BOARD_X, 0.6, 0.0]), label_size=22, value_size=38)
        self.play(Transform(board, resolved), run_time=0.6)

        # -- 9.0 / 1.4 --------------------------------------------------
        self.play(Write(lay.hint), run_time=1.0)
        self.wait(0.6)

    # -- 3D (P2 of a P2) -----------------------------------------------
    def _build_3d(self, p: dict) -> None:
        V = [np.array(v, dtype=float) for v in p["vectors"]]
        while len(V) < 3:
            V.append(np.zeros(3))

        keys = [np.zeros(3)] + V + [V[0] + V[1], V[0] + V[2], V[1] + V[2],
                                    V[0] + V[1] + V[2]]
        proj = np.array([iso_project(x)[:2] for x in keys])
        lo, hi = proj.min(axis=0), proj.max(axis=0)
        centre = (lo + hi) / 2
        extent = float(max((hi - lo).max() / 2, 1e-6))
        unit = min(2.0, (PLANE_BOX / 2) * 0.86 / extent)

        lay = one_panel_layout(self, title=p["title"], hint=p["hint"],
                               dx=PLANE_DX, dy=PLANE_DY, box=PLANE_BOX_W,
                               box_h=PLANE_BOX, unit=unit)
        P = lay.left
        self.remove(P.plane)

        def ipt(x):
            q = iso_project(x)[:2] - centre
            return P.origin + P.unit * np.array([q[0], q[1], 0.0])

        origin = ipt(np.zeros(3))
        axes = VGroup(*[Line(origin, ipt(1.4 * e), color=GHOST, stroke_width=2)
                        for e in np.eye(3)])
        axes.set_z_index(Z_OVERLAY - 4)

        board = scoreboard([("YOUR CLAIM", _dim_word(p["claimed_dim"]), STUDENT)],
                           anchor=np.array([BOARD_X, 1.0, 0.0]),
                           label_size=22, value_size=38)

        arrows = [arrow_at(origin, ipt(v)[:2] - origin[:2], DOT_COLORS[k % 3],
                           unit=1.0, stroke_width=6) for k, v in enumerate(V)]
        for a in arrows:
            a.set_z_index(Z_OVERLAY)

        self.play(Create(axes), FadeIn(lay.title), FadeIn(board), run_time=1.2)
        self.play(*[FadeIn(a, scale=0.6) for a in arrows], run_time=1.0)
        self.wait(0.4)

        # The solid every triple of vectors is supposed to span. With a
        # dependent set it closes to zero thickness -- "independence" is an
        # abstract word, a solid with no volume is not.
        faces = VGroup()
        combos = [(V[0], V[1]), (V[0], V[2]), (V[1], V[2])]
        for a, b in combos:
            faces.add(Polygon(origin, ipt(a), ipt(a + b), ipt(b),
                              stroke_width=2, color=CORRECT)
                      .set_fill(CORRECT, opacity=0.16))
        faces.set_z_index(Z_OVERLAY - 3)
        self.play(FadeIn(faces), run_time=2.0)
        self.wait(0.8)

        # why it is flat: one vector lies along another
        pairs = [(i, j) for i in range(3) for j in range(i + 1, 3)
                 if float(np.linalg.norm(np.cross(V[i], V[j]))) < 1e-6
                 and float(np.linalg.norm(V[j])) > 1e-9]
        if pairs:
            i, j = pairs[0]
            self.play(Indicate(arrows[i], color=STUDENT, scale_factor=1.15),
                      Indicate(arrows[j], color=STUDENT, scale_factor=1.15),
                      run_time=1.0)
            slid = arrow_at(origin, ipt(V[i])[:2] - origin[:2], DOT_COLORS[j % 3],
                            unit=1.0, stroke_width=6)
            slid.set_z_index(Z_OVERLAY)
            self.play(Transform(arrows[j], slid), run_time=1.2)
        else:
            self.wait(2.2)

        resolved = scoreboard(
            [("YOUR CLAIM", _dim_word(p["claimed_dim"]), STUDENT),
             _reached_row(p["actual_dim"])],
            anchor=np.array([BOARD_X, 0.6, 0.0]), label_size=22, value_size=38)
        self.play(Transform(board, resolved), run_time=0.6)
        self.play(Write(lay.hint), run_time=1.0)
        self.wait(0.6)


class SpanCompare3D(SpanCompare):
    """LA14 -- three vectors called independent that span only a plane."""

    TEMPLATE = "SpanCompare"
    DURATION = 11.8
    DEFAULTS = dict(
        SpanCompare.DEFAULTS,
        vectors=[[1, 1, 0], [2, 2, 0], [0, 1, 1]],
        claimed_dim=3,
        actual_dim=2,
        probe=None,
        ambient=3,
        title="The solid your three vectors span",
        hint="watch how thick the solid turns out to be",
    )
