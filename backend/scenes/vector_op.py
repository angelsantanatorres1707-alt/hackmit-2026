"""T5 -- VectorOpCompare.  One plane, one invariant, one broken promise (P1).

Deliberately SINGLE-panel: unlike the grid templates, these results live in
the same space, so drawing them together is the honest comparison. The scene
first draws the INVARIANT the operation must satisfy (the unit circle, the
right angle, the sheet), then the true answer satisfying it, then the
student's answer failing it.

CORRECT FIRST, THEN STUDENT -- always. The viewer has to see what "closing"
looks like before they can recognise a failure to close.

Covers LA11 (normalize: tip stops short of the unit circle), LA19
(projection: the right-angle marker does not close, and their "shadow" is
longer than the thing casting it), LA17 (cross, 3D, P2).

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/vector_op.py \
        VectorOpCompare
"""

from __future__ import annotations

import os
import sys

import numpy as np
from manim import (
    Arrow,
    Circle,
    Create,
    FadeIn,
    Flash,
    Indicate,
    Line,
    Polygon,
    VGroup,
    Wiggle,
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
    Z_OVERLAY,
    arrow_at,
    as_vector,
    check_hint,
    fit_unit,
    fmt_num,
    iso_project,
    label_text,
    residual,
    right_angle_marker,
    scoreboard,
    side_label,
    span_line,
    one_panel_layout,
)

PLANE_DX = -2.5
PLANE_BOX = 5.2
BOARD_X = 3.9


class VectorOpCompare(ParamScene):
    TEMPLATE = "VectorOpCompare"
    DURATION = 10.0

    DEFAULTS = {
        "op": "projection",
        "u": [3, 4],
        "v": [2, 1],
        "w_claimed": [8.94, 4.47],
        "w_correct": [4, 2],
        "labels": {"u": "u", "v": "v"},
        "readouts": [["your residual . v", "-12.36"],
                     ["correct residual . v", "0.00"]],
        "title": "Your projection, drawn on the same axes",
        "hint": "watch whether the corner marker closes",
    }

    OPS = ("normalize", "projection", "cross", "generic")

    # ------------------------------------------------------------------
    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})

        op = str(p.get("op") or "generic").lower()
        if op not in cls.OPS:
            raise SceneParamError(f"op must be one of {cls.OPS}, got {op!r}")
        p["op"] = op
        dim = 3 if op == "cross" else 2

        u = as_vector(p.get("u"), name="u", dim=dim, nonzero=True)
        v = as_vector(p.get("v"), name="v", dim=dim,
                      nonzero=op in ("projection", "normalize", "cross"))
        wc = as_vector(p.get("w_claimed"), name="w_claimed", dim=dim)
        wt = as_vector(p.get("w_correct"), name="w_correct", dim=dim)

        if op == "cross":
            if float(np.linalg.norm(np.cross(u, v))) < 1e-6:
                raise SceneParamError(
                    "u and v are parallel: the sheet is degenerate and has no "
                    "normal to stand out of")
        if op == "normalize" and float(np.linalg.norm(wt)) < 1e-9:
            raise SceneParamError("w_correct is the zero vector")
        if float(np.linalg.norm(wc - wt)) < 1e-9:
            raise SceneParamError(
                "w_claimed equals w_correct: nothing to compare")

        p["u"], p["v"] = u.tolist(), v.tolist()
        p["w_claimed"], p["w_correct"] = wc.tolist(), wt.tolist()

        labels = p.get("labels") or {}
        p["labels"] = {"u": str(labels.get("u", "u"))[:12],
                       "v": str(labels.get("v", "v"))[:12]}

        rows = []
        for r in (p.get("readouts") or [])[:3]:
            try:
                rows.append([str(r[0])[:26], str(r[1])[:12]])
            except Exception as exc:  # noqa: BLE001
                raise SceneParamError(f"readouts: bad row {r!r}") from exc
        p["readouts"] = rows

        forbidden = [fmt_num(x) for x in np.asarray(p["w_correct"]).tolist()]
        p["hint"] = check_hint(str(p.get("hint", "")), forbidden)
        p["title"] = str(p.get("title") or "")
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:
        if p["op"] == "cross":
            self._build_cross(p)
        else:
            self._build_2d(p)

    # -- 2D ops --------------------------------------------------------
    def _build_2d(self, p: dict) -> None:
        u = np.array(p["u"], dtype=float)
        v = np.array(p["v"], dtype=float)
        wc = np.array(p["w_claimed"], dtype=float)
        wt = np.array(p["w_correct"], dtype=float)
        op = p["op"]

        # LA19's claimed point sits at (8.94, 4.47) -- well outside a default
        # window. Without this it leaves the frame silently.
        #
        # normalize is framed differently on purpose: the story is the unit
        # circle, and the input vector is typically 5 units long, so fitting
        # it would shrink the circle (and both answers inside it) to a dot.
        # There the input is a dashed direction ray, not an arrow.
        if op == "normalize":
            unit = fit_unit([wc, wt, np.array([1.45, 1.45])], box=PLANE_BOX,
                            allow_grow=True)
        else:
            unit = fit_unit([u, v, wc, wt, np.array([1.0, 1.0])], box=PLANE_BOX)
        lay = one_panel_layout(self, title=p["title"], hint=p["hint"],
                               dx=PLANE_DX, dy=-0.7, box=PLANE_BOX, unit=unit)
        P = lay.left

        inputs = VGroup()
        if op == "normalize":
            ray = span_line(P, u, color=GHOST, dashed=True, stroke_width=2.4)
            inputs.add(ray, side_label(p["labels"]["u"] or "your direction",
                                       P.pt(u / max(np.linalg.norm(u), 1e-9) * 1.25),
                                       u, color=GHOST, font_size=19))
        else:
            a_u = VecArrow(P, u, I_HAT)
            inputs.add(a_u.mob, side_label(p["labels"]["u"], P.pt(u * 0.62), u,
                                           color=I_HAT, font_size=20))
            if float(np.linalg.norm(v)) > 1e-9 and \
               float(np.linalg.norm(v - u)) > 1e-9:
                a_v = VecArrow(P, v, J_HAT)
                inputs.add(a_v.mob, side_label(p["labels"]["v"], P.pt(v * 0.62),
                                               v, color=J_HAT, font_size=20,
                                               side=-1))

        # -- 0.0 / 1.0 --------------------------------------------------
        self.play(Create(P.plane), FadeIn(lay.title), run_time=1.0)
        # -- 1.0 / 1.0 --------------------------------------------------
        self.play(FadeIn(inputs), run_time=1.0)

        # -- 2.0 / 1.2  the invariant overlay, on its own beat ----------
        # The viewer has to learn the rule before watching it break.
        overlay = VGroup()
        if op == "normalize":
            circ = Circle(radius=P.unit, color=GHOST, stroke_width=3)
            circ.move_to(P.origin)
            circ.set_z_index(Z_OVERLAY - 3)
            cap = label_text("length 1 lives here", font_size=19, color=GHOST,
                             max_width=3.4)
            # below the circle: the direction ray and its label own the
            # upper half in most cases
            cap.move_to(P.origin + np.array([0.0, -(P.unit + 0.42), 0.0]))
            cap.set_z_index(Z_CHROME)
            overlay.add(circ, cap)
        elif op == "projection":
            overlay.add(span_line(P, v, color=GHOST, dashed=True,
                                  stroke_width=2.6))
        if len(overlay):
            self.play(Create(overlay), run_time=1.2)
        else:
            self.wait(1.2)
        self.wait(0.4)

        # -- 3.6 / 1.5  the true answer, satisfying the invariant -------
        # The two answers are often collinear (a projection lands on v's
        # line), so the true one is drawn ON TOP of a deliberately fatter
        # claimed shaft -- otherwise whichever is shorter disappears.
        a_t = arrow_at(P.origin, wt, CORRECT, unit=P.unit, stroke_width=6)
        a_t.set_z_index(Z_OVERLAY + 2)
        good_mark = VGroup()
        if op == "projection":
            good_mark.add(residual(P.pt(wt), P.pt(u), color=CORRECT,
                                   label=None))
            good_mark.add(right_angle_marker(P.pt(wt), u - wt, -v,
                                             color=CORRECT, size=0.22))
        self.play(FadeIn(a_t, scale=0.6), run_time=0.8)
        self.play(FadeIn(good_mark),
                  Flash(P.pt(wt), color=CORRECT, line_length=0.14,
                        flash_radius=0.4),
                  run_time=0.7)

        # -- 5.1 / 1.5  the student's answer, breaking it ---------------
        a_c = arrow_at(P.origin, wc, STUDENT, unit=P.unit, stroke_width=9)
        a_c.set_z_index(Z_OVERLAY)
        bad_mark = VGroup()
        if op == "projection":
            bad_mark.add(residual(P.pt(wc), P.pt(u), color=PROBE, label=None))
            bad_mark.add(right_angle_marker(P.pt(wc), u - wc, -v, color=PROBE,
                                            size=0.22, stroke_width=3.4))
        elif op == "normalize":
            n = float(np.linalg.norm(wc))
            if n > 1e-9:
                on_circle = P.origin + P.unit * np.array([wc[0] / n, wc[1] / n, 0.0])
                bad_mark.add(residual(P.pt(wc), on_circle, color=PROBE,
                                      label="gap", side=-1, label_buff=0.3))
        else:
            bad_mark.add(residual(P.pt(wc), P.pt(wt), color=PROBE, label="gap",
                                  away_from=P.origin))
        self.play(FadeIn(a_c, scale=0.6), run_time=0.8)
        self.play(FadeIn(bad_mark), Wiggle(bad_mark, scale_value=1.08),
                  run_time=0.7)

        # -- 6.6 / 1.2  the numbers ------------------------------------
        self._readouts(p)
        self.wait(0.6)

        # -- 7.8 / 2.2 -------------------------------------------------
        self.play(Write(lay.hint), run_time=1.2)
        self.wait(0.6)

    # -- cross product, iso-projected (P2) -----------------------------
    def _build_cross(self, p: dict) -> None:
        u = np.array(p["u"], dtype=float)
        v = np.array(p["v"], dtype=float)
        wc = np.array(p["w_claimed"], dtype=float)
        wt = np.array(p["w_correct"], dtype=float)

        # Centre the figure: an iso-projected cross product is almost all
        # +z, so drawing it around the panel origin puts everything in the
        # top half of the box with dead space underneath.
        keys = [np.zeros(3), u, v, u + v, wc, wt]
        proj = np.array([iso_project(x)[:2] for x in keys])
        lo, hi = proj.min(axis=0), proj.max(axis=0)
        centre = (lo + hi) / 2
        extent = float(max((hi - lo).max() / 2, 1e-6))
        unit = min(2.4, (PLANE_BOX / 2) * 0.86 / extent)

        lay = one_panel_layout(self, title=p["title"], hint=p["hint"],
                               dx=PLANE_DX, dy=-0.7, box=PLANE_BOX, unit=unit)
        P = lay.left
        self.remove(P.plane)  # a flat square grid under an iso solid lies

        def ipt(x):
            q = iso_project(x)[:2] - centre
            return P.origin + P.unit * np.array([q[0], q[1], 0.0])

        origin = ipt(np.zeros(3))
        axes = VGroup(*[Line(origin, ipt(1.5 * e), color=GHOST, stroke_width=2)
                        for e in np.eye(3)])
        axes.set_z_index(Z_OVERLAY - 4)

        def ray(x, color, width=6):
            a = Arrow(origin, ipt(x), buff=0, color=color, stroke_width=width,
                      max_tip_length_to_length_ratio=0.22,
                      max_stroke_width_to_length_ratio=9)
            a.set_z_index(Z_OVERLAY)
            return a

        a_u, a_v = ray(u, I_HAT), ray(v, J_HAT)
        lab_u = side_label(p["labels"]["u"], ipt(u * 0.7),
                           iso_project(u)[:2], color=I_HAT, font_size=20)
        lab_v = side_label(p["labels"]["v"], ipt(v * 0.7),
                           iso_project(v)[:2], color=J_HAT, font_size=20, side=-1)

        self.play(Create(axes), FadeIn(lay.title), run_time=1.0)
        self.play(FadeIn(a_u), FadeIn(a_v), FadeIn(lab_u), FadeIn(lab_v),
                  run_time=1.0)

        sheet = Polygon(origin, ipt(u), ipt(u + v), ipt(v), stroke_width=2,
                        color=GHOST)
        sheet.set_fill(GHOST, opacity=0.25)
        sheet.set_z_index(Z_OVERLAY - 3)
        cap = label_text("every arrow in here is a combination of u and v",
                         font_size=17, color=GHOST, max_width=4.8)
        cap.move_to(P.center + np.array([0.0, -PLANE_BOX / 2 + 0.34, 0.0]))
        cap.set_z_index(Z_CHROME)
        self.play(FadeIn(sheet), FadeIn(cap), run_time=1.2)
        self.wait(0.4)

        arr_t = ray(wt, CORRECT)
        arr_t.set_z_index(Z_OVERLAY + 2)
        self.play(FadeIn(arr_t, scale=0.6), run_time=0.8)
        self.play(Flash(ipt(wt), color=CORRECT, line_length=0.14,
                        flash_radius=0.4), run_time=0.7)

        arr_c = ray(wc, STUDENT, width=9)
        arr_c.set_z_index(Z_OVERLAY + 1)
        self.play(FadeIn(arr_c, scale=0.6), run_time=0.8)
        self.play(Wiggle(arr_c, scale_value=1.06),
                  Indicate(sheet, color=PROBE, scale_factor=1.02), run_time=0.7)

        self._readouts(p)
        self.wait(0.6)
        self.play(Write(lay.hint), run_time=1.2)
        self.wait(0.6)

    # ------------------------------------------------------------------
    def _readouts(self, p: dict) -> None:
        rows = p.get("readouts") or []
        if not rows:
            self.wait(1.2)
            return
        colored = []
        for k, (lab, val) in enumerate(rows):
            colored.append((lab, val, STUDENT if k == 0 else CORRECT))
        board = scoreboard(colored, anchor=np.array([BOARD_X, 0.3, 0.0]),
                           label_size=18, value_size=30, max_width=4.4)
        self.play(FadeIn(board), run_time=1.2)


class VectorOpNormalize(VectorOpCompare):
    """LA11 -- normalized by the wrong divisor: the tip stops visibly short of
    the unit circle."""

    TEMPLATE = "VectorOpCompare"
    DEFAULTS = dict(
        VectorOpCompare.DEFAULTS,
        op="normalize",
        u=[3, 4],
        v=[3, 4],
        w_claimed=[0.428, 0.571],
        w_correct=[0.6, 0.8],
        labels={"u": "v", "v": ""},
        readouts=[["your length", "0.71"], ["length of a unit vector", "1.00"]],
        title="Your unit vector against the unit circle",
        hint="watch where each tip lands relative to the circle",
    )


class VectorOpCross(VectorOpCompare):
    """LA17 -- 'your normal isn't normal'. P2 (3D)."""

    TEMPLATE = "VectorOpCompare"
    DEFAULTS = dict(
        VectorOpCompare.DEFAULTS,
        op="cross",
        u=[2, 1, 0],
        v=[0, 3, 1],
        w_claimed=[1, 2, 6],      # the dropped j-sign
        w_correct=[1, -2, 6],     # u x v
        labels={"u": "u", "v": "v"},
        readouts=[["your answer . u", "4"], ["a normal . u", "0"]],
        title="Your cross product against the sheet it should stand out of",
        hint="watch whether the arrow leans into the sheet",
    )
