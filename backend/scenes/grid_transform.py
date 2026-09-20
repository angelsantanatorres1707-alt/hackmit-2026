"""T1 -- GridTransformCompare.  The workhorse (P0).

Two copies of the plane, same grid, same i-hat / j-hat. Apply the student's
ordered sequence of maps on the left and the correct sequence on the right.
Most linear-algebra errors reduce to "your matrix sends the basis vectors
somewhere else", so this template also absorbs every Layer-1-only detection
(a step verified wrong whose signature matched nothing in the taxonomy) --
which is what makes coverage unbounded instead of capped at 19 errors.

Aliases:
  CompositionOrderCompare -> 2 stages + pause_between_stages   (LA02)
  InverseRoundTrip        -> [M, S_claimed] vs [M, M_inv], ghost_reference
                                                              (LA07, LA08)
Covers: LA01, LA02, LA07, LA08, LA16 + unmatched detections.

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/grid_transform.py \
        GridTransformCompare
    SCENE_PARAMS=/tmp/x.json .venv/bin/manim -ql ... (same)
"""

from __future__ import annotations

import os
import sys

import numpy as np
from manim import (
    Create,
    FadeIn,
    Indicate,
    Transform,
    VGroup,
    Write,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import (  # noqa: E402
    CORRECT,
    I_HAT,
    J_HAT,
    PROBE,
    STUDENT,
    MAT_Y,
    Z_CHROME,
    ParamScene,
    SceneParamError,
    VecArrow,
    apply_matrix_anims,
    as_matrix,
    check_hint,
    fit_unit,
    fmt_rows,
    min_stretch,
    label_text,
    two_panel_layout,
)

TRACK_COLORS = (I_HAT, J_HAT, PROBE)


class GridTransformCompare(ParamScene):
    TEMPLATE = "GridTransformCompare"
    DURATION = 8.7

    DEFAULTS = {
        "student_stages": [[[2, 1], [0, 1]]],
        "correct_stages": [[[2, -1], [0, 1]]],
        "student_display": None,
        "correct_display": None,
        "stage_labels": None,
        "title": "Your step 3, applied to the plane",
        "student_label": "WHAT YOU WROTE",
        # NOT "WHAT THE STEP SHOULD DO": that heading plus the numbers under
        # it was an answer key. The right panel shows the target GEOMETRY and
        # a masked matrix -- see two_panel_layout / reveal_correct_values.
        "correct_label": "WHAT THE PROBLEM ASKS FOR",
        "hint": "watch the second basis vector in your step 3",
        "ghost_reference": False,
        "pause_between_stages": 0.8,
        "track_vectors": [[1, 0], [0, 1]],
    }

    # ------------------------------------------------------------------
    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})

        s_raw = p.get("student_stages") or []
        c_raw = p.get("correct_stages") or []
        if not isinstance(s_raw, (list, tuple)) or not isinstance(c_raw, (list, tuple)):
            raise SceneParamError("student_stages/correct_stages must be lists")
        if len(s_raw) == 0 or len(c_raw) == 0:
            raise SceneParamError("at least one stage is required")
        if len(s_raw) != len(c_raw):
            raise SceneParamError(
                f"stage count mismatch: {len(s_raw)} vs {len(c_raw)}")
        if len(s_raw) > 3:
            raise SceneParamError("at most 3 stages (the scene would exceed 15s)")

        stages_s, stages_c = [], []
        for k, (a, b) in enumerate(zip(s_raw, c_raw)):
            A = as_matrix(a, name=f"student_stages[{k}]", size=2)
            B = as_matrix(b, name=f"correct_stages[{k}]", size=2)
            for M, who in ((A, "student"), (B, "correct")):
                if abs(float(np.linalg.det(M))) < 0.05:
                    raise SceneParamError(
                        f"{who}_stages[{k}] is near-singular (|det| < 0.05): the "
                        "grid collapses to a line and later stages have nothing "
                        "to act on -- route to StaticStepHighlight")
            stages_s.append(A)
            stages_c.append(B)

        def product(stages):
            M = np.eye(2)
            for S in stages:
                M = S @ M
            return M

        p["student_stages"] = [S.tolist() for S in stages_s]
        p["correct_stages"] = [S.tolist() for S in stages_c]
        p["student_display"] = p.get("student_display") or fmt_rows(product(stages_s))
        # Still computed: it is the ban list for check_hint below. It is NOT
        # drawn -- two_panel_layout masks the reference matrix unless
        # REVEAL_CORRECT_VALUES is on.
        p["correct_display"] = p.get("correct_display") or fmt_rows(product(stages_c))

        tracks = p.get("track_vectors") or [[1, 0], [0, 1]]
        clean = []
        for k, v in enumerate(tracks[:3]):
            vv = np.array(v, dtype=float).flatten()
            if vv.size != 2 or not np.all(np.isfinite(vv)):
                raise SceneParamError(f"track_vectors[{k}] must be a finite 2-vector")
            if float(np.linalg.norm(vv)) < 1e-9:
                raise SceneParamError(f"track_vectors[{k}] is the zero vector")
            clean.append(vv.tolist())
        p["track_vectors"] = clean or [[1, 0], [0, 1]]

        labels = p.get("stage_labels")
        if labels is not None:
            labels = [str(x) for x in labels][:len(stages_s)]
            while len(labels) < len(stages_s):
                labels.append("")
        p["stage_labels"] = labels

        forbidden = [v for row in p["correct_display"] for v in row]
        p["hint"] = check_hint(str(p.get("hint", "")), forbidden)
        p["title"] = str(p.get("title") or "")
        p["ghost_reference"] = bool(p.get("ghost_reference"))
        p["pause_between_stages"] = float(p.get("pause_between_stages") or 0.8)
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:
        s_stages = [np.array(S, dtype=float) for S in p["student_stages"]]
        c_stages = [np.array(S, dtype=float) for S in p["correct_stages"]]
        tracks = [np.array(v, dtype=float) for v in p["track_vectors"]]
        n_stages = len(s_stages)

        # Zoom out if either sequence throws a tracked vector out of frame.
        tips = []
        for stages in (s_stages, c_stages):
            for v in tracks:
                w = v.copy()
                for S in stages:
                    w = S @ w
                    tips.append(w)
        unit = fit_unit(tips + tracks)

        # Pick the grid spacing for the state the scene ENDS in: a squeezing
        # matrix pulls the lattice lines together and a unit-step grid turns
        # into a moire wash at 720p.
        prods = []
        for stages in (s_stages, c_stages):
            M = np.eye(2)
            for S in stages:
                M = S @ M
                prods.append(M.copy())
        shrink = min_stretch(*prods)

        lay = two_panel_layout(
            self,
            title=p["title"],
            student_label=p["student_label"],
            correct_label=p["correct_label"],
            hint=p["hint"],
            student_rows=p["student_display"],
            correct_rows=p["correct_display"],
            ghost_reference=p["ghost_reference"],
            unit=unit,
            grid_shrink=shrink,
        )

        l_arrows = [VecArrow(lay.left, v, TRACK_COLORS[i % 3])
                    for i, v in enumerate(tracks)]
        r_arrows = [VecArrow(lay.right, v, TRACK_COLORS[i % 3])
                    for i, v in enumerate(tracks)]

        caption = None
        labels = p["stage_labels"]

        # -- 0.0 / 1.2 --------------------------------------------------
        if lay.ghosts is not None:
            self.add(lay.ghosts)
        self.play(Create(lay.left.plane), Create(lay.right.plane),
                  FadeIn(lay.title), run_time=1.2)

        # -- 1.2 / 1.0 --------------------------------------------------
        intro = [FadeIn(lay.l_head), FadeIn(lay.r_head),
                 FadeIn(lay.l_mat), FadeIn(lay.r_mat)]
        for a in l_arrows + r_arrows:
            intro.append(FadeIn(a.mob, scale=0.6))
        if labels and n_stages > 1:
            # Between the panels there is now only ~0.8 of gutter, so the
            # stage caption goes in the free column between the two matrices
            # instead of half on top of the right panel.
            caption = label_text(labels[0], font_size=24, color=CORRECT,
                                 max_width=4.4, weight="BOLD")
            caption.move_to(np.array([0.0, MAT_Y, 0.0])).set_z_index(Z_CHROME)
            intro.append(FadeIn(caption))
        self.play(*intro, run_time=1.0)

        # -- 2.2 / 0.4 --------------------------------------------------
        self.wait(0.4)

        # -- the act ----------------------------------------------------
        stage_rt = 3.0 if n_stages == 1 else (2.5 if n_stages == 2 else 2.0)
        for k in range(n_stages):
            self.play(*apply_matrix_anims(lay.left, s_stages[k], l_arrows,
                                          run_time=stage_rt),
                      *apply_matrix_anims(lay.right, c_stages[k], r_arrows,
                                          run_time=stage_rt))
            if k < n_stages - 1:
                # Pause on the intermediate. For LA02 this is the whole point:
                # both grids are still identical here, so pulse the borders to
                # say "same so far" before they diverge.
                self.play(Indicate(lay.borders, color=CORRECT, scale_factor=1.02),
                          run_time=float(p["pause_between_stages"]))
                if labels and caption is not None:
                    nxt = label_text(labels[k + 1], font_size=24, color=CORRECT,
                                     max_width=4.4, weight="BOLD")
                    nxt.move_to(caption.get_center()).set_z_index(Z_CHROME)
                    self.play(Transform(caption, nxt), run_time=0.5)

        # -- hold -------------------------------------------------------
        self.wait(0.6 if n_stages == 1 else 0.7)

        # -- mark the divergence ---------------------------------------
        gap = [float(np.linalg.norm(l.vec - r.vec)) for l, r in zip(l_arrows, r_arrows)]
        idx = int(np.argmax(gap)) if gap else 0
        if gap and gap[idx] > 1e-6:
            self.play(Indicate(l_arrows[idx].mob, color=STUDENT, scale_factor=1.18),
                      Indicate(r_arrows[idx].mob, color=CORRECT, scale_factor=1.18),
                      run_time=1.0)
        else:
            # Same endpoint both sides (e.g. a round trip that comes home too
            # large): pulse the whole panel content instead of one arrow.
            self.play(Indicate(VGroup(*[a.mob for a in l_arrows]), color=STUDENT),
                      Indicate(VGroup(*[a.mob for a in r_arrows]), color=CORRECT),
                      run_time=1.0)

        # -- hint + settle ---------------------------------------------
        self.play(Write(lay.hint), run_time=0.8)
        self.wait(0.7)


# Aliases from ERROR_TAXONOMY.md. Same class, different default params; the
# registry supplies the presets, these exist so `manim file.py Name` works.
class CompositionOrderCompare(GridTransformCompare):
    TEMPLATE = "CompositionOrderCompare"
    DURATION = 12.3
    DEFAULTS = dict(
        GridTransformCompare.DEFAULTS,
        student_stages=[[[3, 0], [0, 1]], [[0, -1], [1, 0]]],
        correct_stages=[[[0, -1], [1, 0]], [[3, 0], [0, 1]]],
        stage_labels=["first map", "then the other"],
        title="Your two maps, in the order you applied them",
        student_label="YOUR ORDER",
        correct_label="THE OTHER ORDER",
        hint="watch which way the long axis points at the end",
        pause_between_stages=0.8,
    )


class InverseRoundTrip(GridTransformCompare):
    TEMPLATE = "InverseRoundTrip"
    DURATION = 12.3
    DEFAULTS = dict(
        GridTransformCompare.DEFAULTS,
        student_stages=[[[3, 1], [2, 4]], [[4, -1], [-2, 3]]],
        correct_stages=[[[3, 1], [2, 4]], [[0.4, -0.1], [-0.2, 0.3]]],
        stage_labels=["apply M", "then undo it"],
        title="Does the grid come home?",
        student_label="YOUR ROUND TRIP",
        correct_label="A ROUND TRIP",
        hint="the faint grid is where you started -- compare one square",
        ghost_reference=True,
        pause_between_stages=0.8,
    )
