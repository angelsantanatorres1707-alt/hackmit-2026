"""One vector, two orders, and the two places it lands.

The composition-order mistake has a shape that does not need a scoreboard to
explain: take the student's OWN vector, apply their two maps to it in each
order side by side, and let the two arrows finish somewhere different.

Parameterised entirely by the problem, so a page with other numbers and the
same mistake produces the same film with its own vector and its own matrices.
The opening beat is the only hard-coded thing in here, and deliberately so --
it demonstrates what "a matrix moves the plane" means on numbers that are not
the student's, and so cannot leak their answer.

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/composition_order.py \
        CompositionOrderVector
"""

from __future__ import annotations

import os
import sys

import numpy as np
from manim import FadeIn, FadeOut, Create, Indicate, VGroup, Write

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import (  # noqa: E402
    BOX, BOX_W, CORRECT, PANEL_DX, PROBE, STUDENT, Z_CHROME, Z_FLASH,
    ParamScene, SceneParamError, VecArrow, apply_matrix_anims, fit_unit,
    hint_text, label_text, panel, panel_matte, title_text,
)

PANEL_DY = -0.30
PANEL_H = 4.70
EXPR_Y = -3.02


def _mats(raw, what):
    out = []
    for k, M in enumerate(raw or []):
        A = np.array(M, dtype=float)
        if A.shape != (2, 2) or not np.all(np.isfinite(A)):
            raise SceneParamError(f"{what}[{k}] must be a finite 2x2 matrix")
        out.append(A)
    if not 1 <= len(out) <= 3:
        raise SceneParamError(f"{what} must hold between one and three matrices")
    return out


class CompositionOrderVector(ParamScene):
    """v, put through the same two maps in both orders."""

    TEMPLATE = "CompositionOrderVector"
    DURATION = 21.0

    DEFAULTS = {
        "vector": [1.0, 1.0],
        "vector_name": "v",
        # APPLIED order: stages[0] lands first.
        "student_stages": [[[0, -1], [1, 0]], [[1, 1], [0, 1]]],
        "correct_stages": [[[1, 1], [0, 1]], [[0, -1], [1, 0]]],
        "student_symbols": ["B", "A"],
        "correct_symbols": ["A", "B"],
        "opening": "matrix multiplication transforms the coordinate plane",
        "hint": "watch where the arrow ends up under each order",
    }

    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})
        v = np.array(p.get("vector"), dtype=float).flatten()
        if v.size != 2 or not np.all(np.isfinite(v)) or float(np.linalg.norm(v)) < 1e-9:
            raise SceneParamError("vector must be a non-zero finite 2-vector")
        p["vector"] = v.tolist()
        p["student_stages"] = [M.tolist() for M in _mats(p["student_stages"], "student_stages")]
        p["correct_stages"] = [M.tolist() for M in _mats(p["correct_stages"], "correct_stages")]
        if len(p["student_stages"]) != len(p["correct_stages"]):
            raise SceneParamError("both orders must have the same number of stages")
        n = len(p["student_stages"])
        for key in ("student_symbols", "correct_symbols"):
            syms = [str(x)[:3] for x in (p.get(key) or [])]
            if len(syms) != n:
                raise SceneParamError(f"{key} must name one symbol per stage")
            p[key] = syms
        p["vector_name"] = str(p.get("vector_name") or "v")[:3]
        p["opening"] = str(p.get("opening") or "")[:70]
        p["hint"] = str(p.get("hint") or "")[:120]
        # The two orders landing in the same place is not this scene's story.
        if np.allclose(_compose(p["student_stages"]) @ np.array(p["vector"]),
                       _compose(p["correct_stages"]) @ np.array(p["vector"]),
                       atol=1e-9):
            raise SceneParamError("both orders land the arrow in the same place")
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:  # noqa: D102
        v0 = np.array(p["vector"], dtype=float)
        s_stages = [np.array(M, dtype=float) for M in p["student_stages"]]
        c_stages = [np.array(M, dtype=float) for M in p["correct_stages"]]
        n = len(s_stages)

        self._opening(p["opening"])

        # ---- act 2: the same vector, both orders -----------------------
        tips = [v0]
        for stages in (s_stages, c_stages):
            w = v0.copy()
            for M in stages:
                w = M @ w
                tips.append(w.copy())
        unit = fit_unit(tips, box=PANEL_H)

        L = panel(-PANEL_DX, unit=unit, dy=PANEL_DY, box=BOX_W, box_h=PANEL_H,
                  max_reach=PANEL_DX - 0.20)
        R = panel(+PANEL_DX, unit=unit, dy=PANEL_DY, box=BOX_W, box_h=PANEL_H,
                  max_reach=PANEL_DX - 0.20)
        matte = panel_matte(L.box, R.box)
        borders = VGroup(L.box.copy().set_stroke(STUDENT, 3.0, opacity=0.85),
                         R.box.copy().set_stroke(CORRECT, 3.0, opacity=0.75))
        self.add(matte, borders)

        l_arrow = VecArrow(L, v0, STUDENT, stroke_width=9.0)
        r_arrow = VecArrow(R, v0, CORRECT, stroke_width=9.0)

        name = p["vector_name"]
        l_expr = self._expr(name, -PANEL_DX, STUDENT)
        r_expr = self._expr(name, +PANEL_DX, CORRECT)

        self.play(Create(L.plane), Create(R.plane), run_time=1.0)
        self.play(FadeIn(l_arrow.mob, scale=0.6), FadeIn(r_arrow.mob, scale=0.6),
                  FadeIn(l_expr), FadeIn(r_expr), run_time=0.8)
        self.wait(0.5)

        l_text = r_text = name
        for k in range(n):
            # The new symbol goes on the FRONT: applying B to v gives Bv.
            l_text = f"{p['student_symbols'][k]}{l_text}"
            r_text = f"{p['correct_symbols'][k]}{r_text}"
            self.play(
                *apply_matrix_anims(L, s_stages[k], [l_arrow], run_time=2.4),
                *apply_matrix_anims(R, c_stages[k], [r_arrow], run_time=2.4),
                self._grow(l_expr, l_text, -PANEL_DX, STUDENT),
                self._grow(r_expr, r_text, +PANEL_DX, CORRECT),
            )
            if k < n - 1:
                # Still identical here, which is the point: the divergence is
                # produced by the ORDER, not by the maps being different.
                self.play(Indicate(borders, color=CORRECT, scale_factor=1.02),
                          run_time=0.8)
        self.wait(0.9)

        # ---- act 3: just the arrows, their names, and a not-equals -----
        self.play(FadeOut(VGroup(L.plane, R.plane, matte, borders)), run_time=1.0)
        ne = label_text("≠", font_size=52, color=PROBE, max_width=1.2,
                        weight="BOLD")
        ne.move_to(np.array([0.0, EXPR_Y, 0.0])).set_z_index(Z_FLASH)
        self.play(FadeIn(ne, scale=1.7),
                  Indicate(l_expr, color=STUDENT, scale_factor=1.18),
                  Indicate(r_expr, color=CORRECT, scale_factor=1.18),
                  run_time=1.2)
        self.wait(0.7)
        self.play(Indicate(l_arrow.mob, color=STUDENT, scale_factor=1.15),
                  Indicate(r_arrow.mob, color=CORRECT, scale_factor=1.15),
                  run_time=1.0)
        self.wait(0.6)

        hint = hint_text(p["hint"])
        self.play(Write(hint), run_time=1.0)
        self.wait(0.9)

    # ------------------------------------------------------------------
    def _expr(self, text, x, color):
        m = label_text(text, font_size=34, color=color, max_width=5.2,
                       weight="BOLD")
        m.move_to(np.array([float(x), EXPR_Y, 0.0])).set_z_index(Z_CHROME)
        return m

    def _grow(self, mob, text, x, color):
        from manim import Transform
        return Transform(mob, self._expr(text, x, color))

    def _opening(self, words: str) -> None:
        """A matrix moving the plane, on numbers that are not the student's."""
        if not words:
            return
        P = panel(0.0, unit=1.05, dy=-0.30, box=BOX_W + 2.4, box_h=PANEL_H)
        matte = panel_matte(P.box)
        cap = title_text(words)
        i = VecArrow(P, [1, 0], STUDENT, stroke_width=8.0)
        j = VecArrow(P, [0, 1], CORRECT, stroke_width=8.0)
        self.add(matte)
        self.play(Create(P.plane), FadeIn(cap), run_time=1.1)
        self.play(FadeIn(i.mob, scale=0.6), FadeIn(j.mob, scale=0.6), run_time=0.6)
        self.play(*apply_matrix_anims(P, [[1.0, 0.85], [0.35, 1.0]], [i, j],
                                      run_time=2.3))
        self.wait(0.8)
        self.play(FadeOut(VGroup(P.plane, i.mob, j.mob, cap, matte)), run_time=0.7)


def _compose(stages):
    """Applied in order: stages[0] first, so the product is the reverse."""
    M = np.eye(2)
    for S in stages:
        M = np.array(S, dtype=float) @ M
    return M
