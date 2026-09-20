"""T4 -- DeterminantAreaCompare.  Area, live (P1 for 2x2 / P2 for 3x3).

The unit square morphs under M with a live area readout ticking beside the
student's frozen number. Layout is NOT two panels, because the comparison is
number-vs-number: the plane takes the left ~60% and a scoreboard on the right
holds YOUR ANSWER (amber, static, filled from the start) above AREA ON SCREEN
(near-white, live).

Covers LA04 (2x2 det as ad+bc), LA06 (row swap, sign not flipped) and LA05
(3x3 cofactor signs, iso-projected cube, P2).

THE ORIENTATION FLIP IS THE POINT, NOT A GLITCH. For a negative determinant
the interpolated matrix (1-t)I + tM is singular at some t, so the area
genuinely passes through zero: the sheet turns edge-on, vanishes for a frame
and comes back the other color. That is the most literal possible picture of
"the orientation flipped". Let it play.

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/determinant_area.py \
        DeterminantAreaCompare
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
from manim import (
    ApplyMatrix,
    Create,
    DOWN,
    FadeIn,
    Flash,
    Line,
    Polygon,
    ValueTracker,
    VGroup,
    Write,
    always_redraw,
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
    T,
    TextMatrix,
    VecArrow,
    Z_CHROME,
    Z_FLASH,
    Z_OVERLAY,
    apply_matrix_anims,
    as_matrix,
    check_hint,
    fit_unit,
    min_stretch,
    fmt_num,
    fmt_rows,
    iso_project,
    label_text,
    live_text,
    MASK,
    MASK_COLOR,
    one_panel_layout,
    parse_num,
    reveal_correct_values,
    scoreboard,
    signed_area,
)

# The plane used to be a 5.2 square at x=-2.5 with the scoreboard at 3.9,
# which left 2 units of dead frame on the left and a panel only 65% of the
# frame height. The frame is 16:9; so is the panel now.
PLANE_DX = -3.58
PLANE_BOX = 6.0        # HEIGHT -- what fit_unit and the in-panel captions use
PLANE_BOX_W = 6.4      # WIDTH
PLANE_DY = 0.10
BOARD_X = 3.45


class DeterminantAreaCompare(ParamScene):
    TEMPLATE = "DeterminantAreaCompare"
    DURATION = 10.2

    DEFAULTS = {
        "M": [[3, 4], [1, 2]],
        "M_display": None,
        "claimed_det": "10",
        "actual_det": None,
        "show_ghost_scale": True,
        "title": "What your matrix does to one unit of area",
        # The counter no longer prints det(M) -- the grey tiles are the
        # comparison now, so the hint points at them.
        "hint": "compare the landed square with the grey tiles",
    }

    # ------------------------------------------------------------------
    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})

        M = as_matrix(p.get("M"), name="M")
        p["M"] = M.tolist()
        p["M_display"] = p.get("M_display") or fmt_rows(M)
        actual = float(np.linalg.det(M))
        if p.get("actual_det") is None:
            p["actual_det"] = fmt_num(actual)
        claimed = parse_num(p.get("claimed_det"), name="claimed_det")
        if abs(claimed - actual) <= 1e-9:
            raise SceneParamError(
                "claimed_det equals det(M): there is no story here and some "
                "other step is the error")
        p["claimed_det"] = fmt_num(claimed) if not isinstance(
            p.get("claimed_det"), str) else str(p["claimed_det"])
        p["claimed_value"] = claimed
        p["actual_value"] = actual
        p["dim"] = int(M.shape[0])
        # 60 outlined squares is noise, not a message.
        p["show_ghost_scale"] = bool(p.get("show_ghost_scale")) and abs(claimed) <= 60 \
            and p["dim"] == 2

        forbidden = [str(p["actual_det"])]
        p["hint"] = check_hint(str(p.get("hint", "")), forbidden)
        p["title"] = str(p.get("title") or "")
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:
        if int(p["dim"]) == 3:
            self._build_3d(p)
        else:
            self._build_2d(p)

    # -- 2x2 -----------------------------------------------------------
    def _build_2d(self, p: dict) -> None:
        M = np.array(p["M"], dtype=float)
        claimed = float(p["claimed_value"])

        n_tiles = int(min(60, math.floor(abs(claimed)))) if p["show_ghost_scale"] else 0
        cols = max(1, math.ceil(math.sqrt(n_tiles))) if n_tiles else 1
        rows = max(1, math.ceil(n_tiles / cols)) if n_tiles else 1

        corners = [M @ np.array([1.0, 0.0]), M @ np.array([0.0, 1.0]),
                   M @ np.array([1.0, 1.0])]
        unit = fit_unit(corners + [np.array([cols, rows], dtype=float)],
                        box=PLANE_BOX)

        lay = one_panel_layout(self, title=p["title"], hint=p["hint"],
                               dx=PLANE_DX, dy=PLANE_DY, box=PLANE_BOX_W,
                               box_h=PLANE_BOX, unit=unit,
                               # [[3,4],[1,2]] squeezes the lattice by 2.7x in
                               # one direction; without this the panel ends the
                               # scene as a hairball of near-parallel lines.
                               grid_shrink=min_stretch(M))
        P = lay.left

        # The live counter ticks to det(M), which IS the answer, so it is only
        # drawn when the reveal flag is on. Hidden, the row keeps its label
        # and shows a grey "?": the student compares the landed square with
        # the grey tiles that spell out their own claimed area.
        #
        # The readout is SIGNED, not absolute. For LA06 the claim and |det|
        # agree in magnitude and differ only in sign, so an abs() readout
        # would show the student's number as correct while the picture says
        # otherwise -- the worst possible mixed message. The word "SIGNED" in
        # the label is itself a tell, so it only appears alongside the number.
        reveal = reveal_correct_values()
        flips = p["actual_value"] < 0
        area_label = "SIGNED AREA ON SCREEN" if (flips and reveal) \
            else "AREA ON SCREEN"
        board = scoreboard(
            [("YOUR ANSWER", p["claimed_det"], STUDENT),
             (area_label, "0.00" if reveal else MASK,
              CORRECT if reveal else MASK_COLOR)],
            anchor=np.array([BOARD_X, 0.15, 0.0]))
        live_anchor = board[1][1].get_left()
        if reveal:
            board[1].remove(board[1][1])   # NB: must remove from the ROW, not
            # the board -- VGroup.remove only searches direct submobjects, so
            # removing a grandchild from the parent silently does nothing and
            # the static placeholder ends up drawn underneath the live readout.

        m_disp = TextMatrix(p["M_display"], color=CORRECT, font_size=26)
        m_disp.move_to(np.array([BOARD_X + 0.3, 2.35, 0.0])).set_z_index(Z_CHROME)

        sq = Polygon(P.pt([0, 0]), P.pt([1, 0]), P.pt([1, 1]), P.pt([0, 1]),
                     stroke_width=3, color=CORRECT)
        sq.set_fill(CORRECT, opacity=0.34)
        sq.set_z_index(Z_OVERLAY - 2)

        def recolor(m):
            # The instant the sheet turns over, the face you are looking at
            # changes. Two-tone fill is what makes "negative" mean something.
            a = signed_area(m, P.unit)
            m.set_fill(CORRECT if a >= 0 else PROBE,
                       opacity=0.34 if abs(a) > 1e-3 else 0.5)
            m.set_stroke(CORRECT if a >= 0 else PROBE)

        i_hat = VecArrow(P, [1, 0], I_HAT)
        j_hat = VecArrow(P, [0, 1], J_HAT)

        readout = live_text(lambda: f"{signed_area(sq, P.unit):.2f}",
                            at=live_anchor, font_size=38, color=CORRECT,
                            aligned_edge=np.array([-1.0, 0.0, 0.0])) \
            if reveal else None

        # -- 0.0 / 1.2 --------------------------------------------------
        self.play(Create(P.plane), FadeIn(lay.title), FadeIn(board), run_time=1.2)
        if readout is not None:
            self.add(readout)
        # -- 1.2 / 0.8 --------------------------------------------------
        self.play(FadeIn(sq), FadeIn(i_hat.mob, scale=0.6),
                  FadeIn(j_hat.mob, scale=0.6), FadeIn(m_disp), run_time=0.8)
        self.wait(0.4)

        # -- 2.4 / 3.5  the act -----------------------------------------
        sq.add_updater(recolor)
        self.play(*apply_matrix_anims(
            P, M, [i_hat, j_hat], run_time=3.5,
            extra=[ApplyMatrix(M, sq, about_point=P.origin, run_time=3.5)]))
        sq.remove_updater(recolor)
        recolor(sq)

        # -- 5.9 / 0.6  lock the readout --------------------------------
        if reveal:
            final = signed_area(sq, P.unit)
            locked = T(f"{final:.2f}", font_size=38, color=CORRECT)
            locked.move_to(live_anchor, aligned_edge=np.array([-1.0, 0.0, 0.0]))
            locked.set_z_index(Z_CHROME)
            self.remove(readout)
            self.add(locked)
            flash = [Flash(locked, color=CORRECT, line_length=0.16,
                           flash_radius=0.55)]
        else:
            # Nothing numeric to land on, so the beat lands on the square
            # itself -- which is the thing the student has to read.
            flash = [Flash(sq.get_center_of_mass(), color=CORRECT,
                           line_length=0.16, flash_radius=0.55)]
        if flips:
            turned = label_text("the sheet turned over", font_size=23,
                                color=PROBE, max_width=4.6)
            # Hung off the board, not a fixed y: the board's own height
            # moves with the font scale, and a fixed y lands this caption on
            # top of the area readout.
            turned.next_to(board, DOWN, buff=0.34)
            turned.set_z_index(Z_CHROME)
            flash.append(FadeIn(turned))
        self.play(*flash, run_time=0.6)

        # -- 6.5 / 1.7  mark the divergence -----------------------------
        if p["show_ghost_scale"] and n_tiles:
            tiles = VGroup()
            for k in range(n_tiles):
                cx, cy = k % cols, k // cols
                tiles.add(Polygon(P.pt([cx, cy]), P.pt([cx + 1, cy]),
                                  P.pt([cx + 1, cy + 1]), P.pt([cx, cy + 1]),
                                  stroke_width=2, color=GHOST))
            frac = abs(claimed) - n_tiles
            if frac > 0.02:
                cx, cy = n_tiles % cols, n_tiles // cols
                tiles.add(Polygon(P.pt([cx, cy]), P.pt([cx + frac, cy]),
                                  P.pt([cx + frac, cy + 1]), P.pt([cx, cy + 1]),
                                  stroke_width=2, color=GHOST))
            tiles.set_z_index(Z_OVERLAY - 3)
            cap = label_text("your answer means this much area", font_size=23,
                             color=GHOST, max_width=4.6)
            cap.move_to(np.array([BOARD_X, -2.1, 0.0])).set_z_index(Z_CHROME)
            self.play(Create(tiles), FadeIn(cap), run_time=1.7)
        else:
            self.wait(1.7)

        # -- 8.2 / 2.0 --------------------------------------------------
        self.play(Write(lay.hint), run_time=1.2)
        self.wait(0.8)

    # -- 3x3 (P2) ------------------------------------------------------
    def _build_3d(self, p: dict) -> None:
        M = np.array(p["M"], dtype=float)
        claimed = float(p["claimed_value"])
        I3 = np.eye(3)
        cube = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                         [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=float)
        faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
                 (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4)]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]

        img = np.array([M @ v for v in cube])
        unit = fit_unit([iso_project(v)[:2] for v in img] +
                        [iso_project(v)[:2] for v in cube], box=PLANE_BOX)

        lay = one_panel_layout(self, title=p["title"], hint=p["hint"],
                               dx=PLANE_DX, dy=PLANE_DY, box=PLANE_BOX_W,
                               box_h=PLANE_BOX, unit=unit)
        P = lay.left
        self.remove(P.plane)  # a square grid under an iso solid reads wrong

        # Same rule as the 2x2 path: the counter ends at |det(M)|, the answer.
        reveal = reveal_correct_values()
        board = scoreboard(
            [("YOUR ANSWER", p["claimed_det"], STUDENT),
             ("VOLUME ON SCREEN", "1.00" if reveal else MASK,
              CORRECT if reveal else MASK_COLOR)],
            anchor=np.array([BOARD_X, 0.15, 0.0]))
        live_anchor = board[1][1].get_left()
        if reveal:
            board[1].remove(board[1][1])

        m_disp = TextMatrix(p["M_display"], color=CORRECT, font_size=22)
        m_disp.move_to(np.array([BOARD_X + 0.3, 2.3, 0.0])).set_z_index(Z_CHROME)

        t = ValueTracker(0.0)

        def M_t():
            return (1 - t.get_value()) * I3 + t.get_value() * M

        def solid():
            Mt = M_t()
            pts = [P.origin + P.unit * iso_project(Mt @ v) for v in cube]
            det = float(np.linalg.det(Mt))
            col = CORRECT if det >= 0 else PROBE
            g = VGroup()
            for f in faces:
                poly = Polygon(*[pts[k] for k in f], stroke_width=0)
                poly.set_fill(col, opacity=0.13)
                g.add(poly)
            for a, b in edges:
                g.add(Line(pts[a], pts[b], color=col, stroke_width=2.4))
            g.set_z_index(Z_OVERLAY - 2)
            return g

        body = always_redraw(solid)
        readout = live_text(lambda: f"{abs(np.linalg.det(M_t())):.2f}",
                            at=live_anchor, font_size=38, color=CORRECT,
                            aligned_edge=np.array([-1.0, 0.0, 0.0])) \
            if reveal else None

        axes = VGroup(*[
            Line(P.origin, P.origin + P.unit * 1.6 * iso_project(e),
                 color=GHOST, stroke_width=2)
            for e in np.eye(3)])
        axes.set_z_index(Z_OVERLAY - 4)

        self.play(FadeIn(lay.title), FadeIn(board), Create(axes), run_time=1.2)
        self.add(body)
        if readout is not None:
            self.add(readout)
        self.play(FadeIn(m_disp), run_time=0.8)
        self.wait(0.4)
        # A 3x3 cannot go through ApplyMatrix (it acts on scene coordinates),
        # so the solid is rebuilt every frame from M_t = (1-t)I + tM.
        self.play(t.animate.set_value(1.0), run_time=3.5)
        self.wait(0.3)

        if reveal:
            final = float(np.linalg.det(M))
            locked = T(f"{abs(final):.2f}", font_size=38, color=CORRECT)
            locked.move_to(live_anchor, aligned_edge=np.array([-1.0, 0.0, 0.0]))
            locked.set_z_index(Z_CHROME)
            self.remove(readout)
            self.add(locked)
            self.play(Flash(locked, color=CORRECT, line_length=0.16,
                            flash_radius=0.55), run_time=0.6)
        else:
            self.play(Flash(P.origin, color=CORRECT, line_length=0.16,
                            flash_radius=0.55), run_time=0.6)

        cap = label_text(
            f"your answer asks for {fmt_num(abs(claimed))} times this volume",
            font_size=23, color=GHOST, max_width=5.4)
        cap.move_to(np.array([BOARD_X, -2.1, 0.0])).set_z_index(Z_FLASH)
        self.play(FadeIn(cap), run_time=1.4)
        self.play(Write(lay.hint), run_time=1.2)
        self.wait(0.8)


class DeterminantAreaFlip(DeterminantAreaCompare):
    """LA06 -- the row swap whose sign was not flipped. The sheet physically
    turns over and the fill comes back the other color."""

    TEMPLATE = "DeterminantAreaCompare"
    DEFAULTS = dict(
        DeterminantAreaCompare.DEFAULTS,
        M=[[0, 2], [1, 0]],
        claimed_det="2",
        title="Your swapped rows, applied to the unit square",
        hint="watch which face of the sheet you are looking at",
    )


class DeterminantVolume3D(DeterminantAreaCompare):
    """LA05 -- 3x3 cofactor signs. P2: the first thing to cut."""

    TEMPLATE = "DeterminantAreaCompare"
    DURATION = 10.2
    DEFAULTS = dict(
        DeterminantAreaCompare.DEFAULTS,
        M=[[1, 2, 3], [0, 1, 4], [0, 0, 1]],
        claimed_det="-79",
        show_ghost_scale=False,
        title="What your 3x3 does to one unit of volume",
        hint="watch how much the box actually changes",
    )
