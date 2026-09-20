"""T6 -- LineSystemCompare.  Row operations as a hinge (P1 / P2).

Each equation is a line in the plane. A LEGAL row operation produces a new
line that still passes through the common intersection -- the line pivots
about that point like a hinge. Bad arithmetic swings it off the hinge and the
frame shows it detaching from the solution.

mode="solution"  (P1) -- plot the claimed solution against the two original
                  lines and substitute it back, row by row. This is the safe
                  layer: it carries the demo on its own.
mode="row_op"    (P2) -- the pivot itself, two panels.

Covers LA12, LA13, and any Ax=b solution claim.
Aliases: RowOpLinePivot (mode="row_op"), SolutionPointCheck (mode="solution").

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/line_system.py \
        LineSystemCompare
"""

from __future__ import annotations

import os
import sys

import numpy as np
from manim import (
    Circle,
    Create,
    Dot,
    FadeIn,
    Flash,
    Indicate,
    LaggedStart,
    Line,
    Transform,
    VGroup,
    Write,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import (  # noqa: E402
    BOX,
    MAT_Y,
    CORRECT,
    I_HAT,
    J_HAT,
    PROBE,
    STUDENT,
    ParamScene,
    SceneParamError,
    Panel,
    Z_CHROME,
    Z_FLASH,
    Z_OVERLAY,
    check_hint,
    fit_unit,
    fmt_num,
    label_text,
    one_panel_layout,
    residual,
    scoreboard,
    two_panel_layout,
)

# The plane used to be a 5.2 square at x=-2.5 with the scoreboard at 3.9,
# which left 2 units of dead frame on the left and a panel only 65% of the
# frame height. The frame is 16:9; so is the panel now.
PLANE_DX = -3.58
PLANE_BOX = 6.0        # HEIGHT -- what fit_unit and the in-panel captions use
PLANE_BOX_W = 6.4      # WIDTH
PLANE_DY = 0.10
BOARD_X = 3.45


def _line_mobject(P: Panel, coeffs, *, color: str, stroke_width: float = 4.0,
                  box: float = PLANE_BOX) -> Line:
    """The line a*x + b*y = c, CLIPPED to this panel's visible box.

    Clipping is not cosmetic. The matte is one mask with a hole per panel, so
    a line long enough to leave its own panel reappears through the OTHER
    panel's hole -- which showed up as both result lines being drawn in both
    panels. Liang-Barsky against the box keeps each line at home.
    """
    a, b, c = (float(x) for x in coeffs)
    n2 = a * a + b * b
    if n2 < 1e-12:
        raise SceneParamError("an equation has zero coefficients on x and y")
    p0 = np.array([a, b]) * (c / n2)
    d = np.array([-b, a]) / np.sqrt(n2)

    half = (box / 2 + 0.02) / P.unit          # box half-extent in math units
    t_lo, t_hi = -1e6, 1e6
    for axis in (0, 1):
        if abs(d[axis]) < 1e-9:
            if abs(p0[axis]) > half:          # parallel and outside: no segment
                t_lo, t_hi = 0.0, 0.0
                break
            continue
        t1 = (-half - p0[axis]) / d[axis]
        t2 = (half - p0[axis]) / d[axis]
        t_lo = max(t_lo, min(t1, t2))
        t_hi = min(t_hi, max(t1, t2))
    if t_hi - t_lo < 1e-6:                    # line misses the box entirely
        t_lo, t_hi = -0.02, 0.02
    ln = Line(P.pt(p0 + t_lo * d), P.pt(p0 + t_hi * d), color=color,
              stroke_width=stroke_width)
    ln.set_z_index(Z_OVERLAY - 1)
    return ln


def _closest_point(coeffs) -> np.ndarray:
    """The point of a*x + b*y = c nearest the origin -- what decides whether
    the line is inside the visible box at a given unit."""
    a, b, c = (float(x) for x in coeffs)
    n2 = a * a + b * b
    if n2 < 1e-12:
        return np.zeros(2)
    return np.array([a, b]) * (c / n2)


def _intersect(e1, e2) -> np.ndarray | None:
    A = np.array([[e1[0], e1[1]], [e2[0], e2[1]]], dtype=float)
    if abs(float(np.linalg.det(A))) < 1e-9:
        return None
    return np.linalg.solve(A, np.array([e1[2], e2[2]], dtype=float))


class LineSystemCompare(ParamScene):
    TEMPLATE = "LineSystemCompare"
    DURATION = 8.8

    DEFAULTS = {
        "mode": "solution",
        "equations": [[1, 2, 5], [3, 4, 11]],
        "student_result_line": [0, -2, -6],
        "correct_result_line": [0, -2, -4],
        "op_label": "R2 - 3R1",
        "x_claimed": [-1, 3],
        "x_correct": None,
        "substitutions": [["5", "5"], ["9", "11"]],
        "title": "Your solution, put back into both equations",
        "hint": "watch which equation the point misses",
    }

    # ------------------------------------------------------------------
    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})

        mode = str(p.get("mode") or "solution").lower()
        if mode not in ("solution", "row_op"):
            raise SceneParamError(f"mode must be 'solution' or 'row_op', got {mode!r}")
        p["mode"] = mode

        eqs = p.get("equations") or []
        if len(eqs) != 2:
            raise SceneParamError("exactly two equations are supported")
        clean = []
        for k, e in enumerate(eqs):
            arr = np.array(e, dtype=float).flatten()
            if arr.size != 3 or not np.all(np.isfinite(arr)):
                raise SceneParamError(f"equations[{k}] must be [a, b, c]")
            if abs(arr[0]) + abs(arr[1]) < 1e-9:
                raise SceneParamError(f"equations[{k}] has no x or y term")
            clean.append(arr.tolist())
        p["equations"] = clean

        # No intersection means no hinge, and the template is meaningless.
        x_star = _intersect(clean[0], clean[1])
        if x_star is None:
            raise SceneParamError(
                "the two equations are parallel: there is no hinge to pivot "
                "about -- route to StaticStepHighlight")
        p["x_correct"] = (p.get("x_correct") or x_star.tolist())

        if mode == "row_op":
            for key in ("student_result_line", "correct_result_line"):
                arr = np.array(p.get(key), dtype=float).flatten()
                if arr.size != 3 or not np.all(np.isfinite(arr)):
                    raise SceneParamError(f"{key} must be [a, b, c]")
                if abs(arr[0]) + abs(arr[1]) < 1e-9:
                    raise SceneParamError(f"{key} has no x or y term")
                p[key] = arr.tolist()
            p["op_label"] = str(p.get("op_label") or "")[:18]
        else:
            xc = np.array(p.get("x_claimed"), dtype=float).flatten()
            if xc.size != 2 or not np.all(np.isfinite(xc)):
                raise SceneParamError("x_claimed must be a 2-vector")
            p["x_claimed"] = xc.tolist()
            subs = []
            for r in (p.get("substitutions") or [])[:3]:
                subs.append([str(r[0])[:10], str(r[1])[:10]])
            p["substitutions"] = subs

        forbidden = [fmt_num(v) for v in np.asarray(p["x_correct"]).tolist()]
        p["hint"] = check_hint(str(p.get("hint", "")), forbidden)
        p["title"] = str(p.get("title") or "")
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:
        if p["mode"] == "row_op":
            self._row_op(p)
        else:
            self._solution(p)

    # -- solution mode -------------------------------------------------
    def _solution(self, p: dict) -> None:
        e1, e2 = p["equations"]
        xs = np.array(p["x_claimed"], dtype=float)
        xt = np.array(p["x_correct"], dtype=float)
        unit = fit_unit([xs, xt, np.array([2.0, 2.0])], box=PLANE_BOX)

        lay = one_panel_layout(self, title=p["title"], hint=p["hint"],
                               dx=PLANE_DX, dy=PLANE_DY, box=PLANE_BOX_W,
                               box_h=PLANE_BOX, unit=unit)
        P = lay.left

        l1 = _line_mobject(P, e1, color=I_HAT)
        l2 = _line_mobject(P, e2, color=J_HAT)
        true_dot = Circle(radius=0.11, color=CORRECT, stroke_width=3)
        true_dot.move_to(P.pt(xt)).set_z_index(Z_FLASH)

        # -- 0.0 / 1.2 --------------------------------------------------
        self.play(Create(P.plane), FadeIn(lay.title), run_time=1.2)
        # -- 1.2 / 1.4 --------------------------------------------------
        self.play(Create(l1), Create(l2), FadeIn(true_dot), run_time=1.4)
        self.wait(0.4)

        # -- 3.0 / 1.2  the claimed point flies in ----------------------
        claim = Dot(P.pt(xs), radius=0.12, color=STUDENT).set_z_index(Z_FLASH)
        start = claim.get_center() + np.array([-5.0, 3.0, 0.0])
        ghost_start = claim.copy().move_to(start)
        self.play(Transform(ghost_start, claim), run_time=1.2)
        self.add(claim)
        self.remove(ghost_start)

        # -- 4.2 / 2.0  substitute back, row by row ---------------------
        drops = VGroup()
        for e, col in ((e1, I_HAT), (e2, J_HAT)):
            a, b, c = e
            n2 = a * a + b * b
            t = (c - a * xs[0] - b * xs[1]) / n2
            foot = xs + t * np.array([a, b])
            drops.add(residual(P.pt(xs), P.pt(foot), color=col, label=None))
        rows = []
        for k, (lhs, rhs) in enumerate(p["substitutions"] or []):
            same = str(lhs).strip() == str(rhs).strip()
            rows.append((f"equation {k + 1}", f"{lhs} vs {rhs}",
                         CORRECT if same else STUDENT))
        if rows:
            board = scoreboard(rows, anchor=np.array([BOARD_X, 0.3, 0.0]),
                               label_size=22, value_size=38)
            self.play(LaggedStart(*[FadeIn(r) for r in board], lag_ratio=0.45),
                      FadeIn(drops), run_time=2.0)
        else:
            self.play(FadeIn(drops), run_time=2.0)
        self.wait(0.6)

        # -- 6.8 / 2.0 --------------------------------------------------
        self.play(Indicate(claim, color=STUDENT, scale_factor=1.35),
                  run_time=0.8)
        self.play(Write(lay.hint), run_time=1.2)
        self.wait(0.6)

    # -- row_op mode ---------------------------------------------------
    def _row_op(self, p: dict) -> None:
        e1, e2 = p["equations"]
        s_line = p["student_result_line"]
        c_line = p["correct_result_line"]
        hinge = np.array(p["x_correct"], dtype=float)
        # Both RESULT lines have to be inside the box, not just the hinge:
        # a line 3 units up is invisible at the default unit and all the
        # viewer sees is a residual pointing at nothing.
        unit = fit_unit([hinge, np.array([1.5, 1.5]),
                         _closest_point(e1), _closest_point(e2),
                         _closest_point(s_line), _closest_point(c_line)])

        # The right panel's heading names the INVARIANT to aim at (the two
        # lines still crossing where they did), not "the correct row". No
        # numbers are drawn on that side: the pivot is the whole argument.
        lay = two_panel_layout(self, title=p["title"],
                               student_label="YOUR ROW OPERATION",
                               correct_label="WHAT THE OPERATION MUST KEEP",
                               hint=p["hint"], unit=unit)
        L, R = lay.left, lay.right

        lines = {}
        for key, P in (("l", L), ("r", R)):
            lines[key] = (
                _line_mobject(P, e1, color=I_HAT, box=BOX),
                _line_mobject(P, e2, color=J_HAT, box=BOX),
            )
        dots = {key: Dot(P.pt(hinge), radius=0.1, color=CORRECT).set_z_index(Z_FLASH)
                for key, P in (("l", L), ("r", R))}
        rings = {key: Circle(radius=0.24, color=CORRECT, stroke_width=2.4)
                 .move_to(P.pt(hinge)).set_z_index(Z_FLASH)
                 for key, P in (("l", L), ("r", R))}

        # The gutter between the panels is now only ~0.8 wide, so the tag
        # goes in the empty matrix row above them instead of on top of the
        # right panel's edge.
        op_tag = label_text(p["op_label"], font_size=26, color=CORRECT,
                            max_width=3.2, weight="BOLD")
        op_tag.move_to(np.array([0.0, MAT_Y, 0.0])).set_z_index(Z_CHROME)

        # -- 0.0 / 1.2 --------------------------------------------------
        self.play(Create(L.plane), Create(R.plane), FadeIn(lay.title),
                  FadeIn(lay.l_head), FadeIn(lay.r_head), run_time=1.2)
        # -- 1.2 / 1.2 --------------------------------------------------
        self.play(*[Create(m) for k in lines for m in lines[k]],
                  *[FadeIn(d) for d in dots.values()],
                  *[FadeIn(r) for r in rings.values()], run_time=1.2)
        self.wait(0.4)
        # -- 2.8 / 0.6  establish the hinge -----------------------------
        self.play(FadeIn(op_tag),
                  Indicate(VGroup(dots["l"], rings["l"]), color=CORRECT,
                           scale_factor=1.3),
                  Indicate(VGroup(dots["r"], rings["r"]), color=CORRECT,
                           scale_factor=1.3), run_time=0.6)

        # -- 3.4 / 3.0  the act -----------------------------------------
        s_target = _line_mobject(L, s_line, color=STUDENT, box=BOX)
        c_target = _line_mobject(R, c_line, color=CORRECT, box=BOX)
        self.play(Transform(lines["l"][1], s_target),
                  Transform(lines["r"][1], c_target), run_time=3.0)

        # -- 6.4 / 1.2  mark the divergence -----------------------------
        a, b, c = s_line
        n2 = a * a + b * b
        t = (c - a * hinge[0] - b * hinge[1]) / n2
        foot = hinge + t * np.array([a, b])
        gap = residual(L.pt(hinge), L.pt(foot), color=PROBE,
                       label="off the crossing", away_from=L.center,
                       font_size=17, label_buff=0.2)
        marks = [FadeIn(gap),
                 Flash(R.pt(hinge), color=CORRECT, line_length=0.18,
                       flash_radius=0.5)]
        # LA13: a correct row SCALING is a genuine no-op, so the right panel
        # does nothing for three seconds and reads as a rendering bug. Say so.
        if np.allclose(np.array(c_line) / np.linalg.norm(c_line[:2]),
                       np.array(e2) / np.linalg.norm(e2[:2]), atol=1e-6) or \
           np.allclose(np.array(c_line) / np.linalg.norm(c_line[:2]),
                       -np.array(e2) / np.linalg.norm(e2[:2]), atol=1e-6):
            tag = label_text("unchanged", font_size=20, color=CORRECT,
                             max_width=2.4)
            tag.move_to(R.center + np.array([0.0, -PLANE_BOX / 2 + 0.3, 0.0]))
            tag.set_z_index(Z_CHROME)
            marks.append(FadeIn(tag))
        self.play(*marks, run_time=1.2)
        self.wait(0.4)

        # -- 8.0 / 2.6 --------------------------------------------------
        self.play(Write(lay.hint), run_time=1.2)
        self.wait(0.8)


class LineSystemRowOp(LineSystemCompare):
    """LA12/LA13 -- the pivot. P2."""

    TEMPLATE = "LineSystemCompare"
    DURATION = 10.6
    DEFAULTS = dict(
        LineSystemCompare.DEFAULTS,
        mode="row_op",
        equations=[[1, 2, 5], [3, 4, 11]],
        student_result_line=[0, -2, -6],
        correct_result_line=[0, -2, -4],
        op_label="R2 - 3R1",
        title="Your row operation, as a line",
        hint="watch whether the line lets go of the crossing point",
    )


class LineSystemScaleNoOp(LineSystemCompare):
    """LA13 -- a row SCALING should not move the line at all."""

    TEMPLATE = "LineSystemCompare"
    DURATION = 10.6
    DEFAULTS = dict(
        LineSystemCompare.DEFAULTS,
        mode="row_op",
        equations=[[1, 2, 5], [3, 4, 11]],
        student_result_line=[6, 8, 11],     # doubled the row, missed the c
        correct_result_line=[6, 8, 22],     # the same line, twice over
        op_label="2 R2",
        title="Your scaled row, as a line",
        hint="one of these panels should not move at all",
    )
