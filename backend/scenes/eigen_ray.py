"""T2 -- EigenRayTest.  The definitional animation (P0).

Draw the infinite line spanned by a vector. Apply M. Watch whether the image
stays glued to that line or lifts off it. That is the definition of an
eigenvector rendered as a yes/no question a viewer answers in under a second.

mode="vector"      LA09 -- the claimed vector is not an eigenvector (hero).
mode="eigenvalue"  LA10 -- direction right, length wrong. Both panels show the
                   SAME correct eigenvector; the left carries a grey ghost
                   arrow out at lambda_claimed*v and the divergence beat draws
                   the gap between the real tip and the ghost tip.

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/eigen_ray.py EigenRayTest
"""

from __future__ import annotations

import os
import sys

import numpy as np
from manim import Create, FadeIn, Indicate, VGroup, Write

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import (  # noqa: E402
    CORRECT,
    GHOST,
    PROBE,
    STUDENT,
    ParamScene,
    SceneParamError,
    VecArrow,
    apply_matrix_anims,
    arrow_at,
    as_matrix,
    as_vector,
    check_hint,
    fit_unit,
    min_stretch,
    fmt_num,
    fmt_rows,
    foot_on_line,
    residual,
    side_label,
    span_line,
    two_panel_layout,
)


class EigenRayTest(ParamScene):
    TEMPLATE = "EigenRayTest"
    DURATION = 9.4

    DEFAULTS = {
        "M": [[2, 1], [1, 2]],
        "M_display": None,
        "v_claimed": [1, 0],
        "v_correct": [1, 1],
        "lambda_claimed": None,
        "lambda_correct": None,
        "mode": "vector",
        "title": "Your vector under the same matrix",
        "student_label": "YOUR VECTOR",
        # The goal, not the answer key: the panel shows what staying on the
        # line LOOKS like. No numbers are printed on this side.
        "correct_label": "WHAT AN EIGENVECTOR DOES",
        "hint": "watch whether each arrow stays on its own dashed line",
    }

    # ------------------------------------------------------------------
    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})

        M = as_matrix(p.get("M"), name="M", size=2)
        p["M"] = M.tolist()
        p["M_display"] = p.get("M_display") or fmt_rows(M)

        mode = str(p.get("mode") or "vector").lower()
        if mode not in ("vector", "eigenvalue"):
            raise SceneParamError(f"mode must be 'vector' or 'eigenvalue', got {mode!r}")
        p["mode"] = mode

        v_correct = as_vector(p.get("v_correct"), name="v_correct", dim=2, nonzero=True)
        p["v_correct"] = v_correct.tolist()

        if mode == "vector":
            v_claimed = as_vector(p.get("v_claimed"), name="v_claimed", dim=2,
                                  nonzero=True)
            p["v_claimed"] = v_claimed.tolist()
            # The whole scene is "does it lift off the line". If the claimed
            # vector really is an eigenvector there is nothing to show, and
            # animating it anyway would assert something false.
            img = M @ v_claimed
            cross = float(abs(v_claimed[0] * img[1] - v_claimed[1] * img[0]))
            if cross <= 1e-9 * max(1.0, float(np.linalg.norm(img))):
                raise SceneParamError(
                    "v_claimed IS an eigenvector of M -- nothing lifts off the "
                    "line, so this template has no story to tell")
        else:
            for key in ("lambda_claimed", "lambda_correct"):
                val = p.get(key)
                if val is None:
                    raise SceneParamError(f"{key} is required in eigenvalue mode")
                if isinstance(val, complex) or isinstance(val, (list, tuple, dict, str)):
                    raise SceneParamError(
                        f"{key} is not a real number -- a complex eigenvalue has "
                        "nothing to draw on a real plane; fall back to "
                        "StaticStepHighlight")
                try:
                    p[key] = float(val)
                except (TypeError, ValueError) as exc:
                    raise SceneParamError(f"{key}: not a real number") from exc
                if not np.isfinite(p[key]):
                    raise SceneParamError(f"{key}: not finite")
            if abs(p["lambda_claimed"] - p["lambda_correct"]) < 1e-9:
                raise SceneParamError(
                    "lambda_claimed == lambda_correct: no divergence to render")
            # v_correct must actually be an eigenvector, or the ghost-vs-real
            # length story is drawn on a vector that also changes direction.
            img = M @ v_correct
            cross = float(abs(v_correct[0] * img[1] - v_correct[1] * img[0]))
            if cross > 1e-6 * max(1.0, float(np.linalg.norm(img))):
                raise SceneParamError(
                    "v_correct is not an eigenvector of M -- eigenvalue mode "
                    "needs a genuine eigendirection to measure along")
            p["v_claimed"] = p["v_correct"]

        forbidden = [v for row in p["M_display"] for v in row]
        if mode == "eigenvalue":
            forbidden = forbidden + [fmt_num(p["lambda_correct"])]
        p["hint"] = check_hint(str(p.get("hint", "")), forbidden)
        p["title"] = str(p.get("title") or "")
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:
        M = np.array(p["M"], dtype=float)
        mode = p["mode"]
        v_c = np.array(p["v_claimed"], dtype=float)
        v_t = np.array(p["v_correct"], dtype=float)

        tips = [v_c, v_t, M @ v_c, M @ v_t]
        if mode == "eigenvalue":
            tips += [p["lambda_claimed"] * v_t, p["lambda_correct"] * v_t]
        unit = fit_unit(tips)

        lay = two_panel_layout(
            self,
            title=p["title"],
            student_label=p["student_label"],
            correct_label=p["correct_label"],
            hint=p["hint"],
            center_rows=p["M_display"],
            unit=unit,
            grid_shrink=min_stretch(M),
        )
        L, R = lay.left, lay.right

        l_vec = VecArrow(L, v_c, STUDENT)
        r_vec = VecArrow(R, v_t, CORRECT)
        # The span line is the rule of the game, so it carries its panel's
        # color (amber = what you claimed, near-white = the true object) and
        # is dashed, to stay distinguishable from the plane's own grey axes.
        l_line = span_line(L, v_c, color=STUDENT, opacity=0.62, stroke_width=3.0)
        r_line = span_line(R, v_t, color=CORRECT, opacity=0.55, stroke_width=3.0)

        ghost_arrow = None
        if mode == "eigenvalue":
            ghost_arrow = arrow_at(L.origin, p["lambda_claimed"] * v_t, GHOST,
                                   unit=unit, stroke_width=5)
            ghost_arrow.set_z_index(1)
            ghost_tag = side_label("your length",
                                   L.pt(0.62 * p["lambda_claimed"] * v_t),
                                   v_t, color=GHOST, font_size=22, side=+1)
        else:
            ghost_tag = None

        # -- 0.0 / 1.2 --------------------------------------------------
        self.play(Create(L.plane), Create(R.plane), FadeIn(lay.title),
                  FadeIn(lay.center_mat), run_time=1.2)

        # -- 1.2 / 0.8 --------------------------------------------------
        intro = [FadeIn(l_vec.mob, scale=0.6), FadeIn(r_vec.mob, scale=0.6),
                 FadeIn(lay.l_head), FadeIn(lay.r_head)]
        if ghost_arrow is not None:
            intro += [FadeIn(ghost_arrow), FadeIn(ghost_tag)]
        self.play(*intro, run_time=0.8)

        # -- 2.0 / 1.0  the span lines get their own beat ---------------
        # The viewer must register "this is the line it has to stay on"
        # BEFORE the transform, or the payoff lands on nothing. The lines are
        # added to the SCENE, not to the plane, so ApplyMatrix leaves them
        # fixed -- a reference that moves proves nothing.
        self.play(Create(l_line), Create(r_line), run_time=1.0)
        self.wait(0.4)

        # -- 3.4 / 3.0  the act -----------------------------------------
        self.play(*apply_matrix_anims(L, M, [l_vec], run_time=3.0),
                  *apply_matrix_anims(R, M, [r_vec], run_time=3.0))

        # -- 6.4 / 1.0  mark the divergence -----------------------------
        if mode == "vector":
            tip = l_vec.tip()
            foot = foot_on_line(L.origin, np.array([v_c[0], v_c[1], 0.0]) , tip)
            gap = residual(foot, tip, label="off the line", color=PROBE,
                           away_from=L.origin)
            self.play(FadeIn(gap),
                      Indicate(VGroup(r_line, r_vec.mob), color=CORRECT,
                               scale_factor=1.06),
                      run_time=1.0)
        else:
            real_tip = l_vec.tip()
            claim_tip = L.pt(p["lambda_claimed"] * v_t)
            # Both tips sit on one ray, so "away from the origin" cannot pick
            # a side -- force the gap label opposite the ghost caption.
            gap = residual(real_tip, claim_tip, label="gap", color=PROBE,
                           side=-1, label_buff=0.3)
            self.play(FadeIn(gap),
                      Indicate(VGroup(r_line, r_vec.mob), color=CORRECT,
                               scale_factor=1.06),
                      run_time=1.0)
        self.wait(0.4)

        # -- 7.8 / 1.6  hint + settle -----------------------------------
        self.play(Write(lay.hint), run_time=1.0)
        self.wait(0.6)


class EigenRayTestEigenvalue(EigenRayTest):
    """`mode="eigenvalue"` standing on its own so it can be rendered by name
    (LA10: direction right, magnitude wrong)."""

    TEMPLATE = "EigenRayTest"
    DEFAULTS = dict(
        EigenRayTest.DEFAULTS,
        M=[[2, 1], [1, 2]],
        v_correct=[1, 1],
        v_claimed=[1, 1],
        mode="eigenvalue",
        lambda_claimed=8.22,
        lambda_correct=3,
        title="How far your eigenvalue would stretch this vector",
        student_label="YOUR STRETCH",
        correct_label="WHERE THE VECTOR LANDS",
        hint="compare the two arrow tips on the left ray",
    )
