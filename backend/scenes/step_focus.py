"""T3 -- StaticStepHighlight.  The honest fallback (P0).

Two modes.

STATIC: re-typeset the student's own steps, grow a box around the exact cell
or characters at issue, pulse it, annotate. Used where there is genuinely NO
geometry to animate -- LA03 (incompatible shapes: the composition the student
wrote is not a linear map, so there is no grid to deform) and LA18 (a dot
product is a number, their answer is an arrow: a category error, not a wrong
arrow). Inventing a picture for these would break the contract of the whole
product.

PAIRING: the row-by-column sweep for LA01, where the tell is purely
positional -- the second sweep runs ACROSS instead of DOWN. LA01 has no usable
geometry (det(B^T) = det(B), so both grids stretch identically), which is
exactly why it needs this.

This template is also the bottom of the fallback ladder, so **it must never
raise**: ``validate`` clamps and truncates instead of rejecting, and
``build_scene`` catches everything and still emits a titled, hinted frame.

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/step_focus.py \
        StaticStepHighlight
"""

from __future__ import annotations

import os
import sys

import numpy as np
from manim import (
    Circle,
    Create,
    DashedLine,
    DashedVMobject,
    FadeIn,
    FadeOut,
    Flash,
    Indicate,
    LaggedStart,
    Line,
    MoveAlongPath,
    SurroundingRectangle,
    VGroup,
    Write,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import (  # noqa: E402
    CORRECT,
    GHOST,
    PROBE,
    STUDENT,
    ParamScene,
    T,
    TextMatrix,
    Z_CHROME,
    Z_FLASH,
    check_hint,
    hint_text,
    label_text,
    title_text,
    MASK,
    reveal_correct_values,
)

MAX_LINES = 6
MAX_CHARS = 60


class StaticStepHighlight(ParamScene):
    TEMPLATE = "StaticStepHighlight"
    DURATION = 8.0

    DEFAULTS = {
        "lines": [
            {"kind": "matrix", "rows": [["2", "1", "0"], ["1", "3", "4"]],
             "prefix": "A = "},
            {"kind": "matrix", "rows": [["1", "2"], ["0", "1"]], "prefix": "B = "},
            {"kind": "text", "text": "you wrote  A B = ..."},
        ],
        "focus": {"line": 2, "chars": [0, 12]},
        "annotation": "A has 3 columns, B has 2 rows",
        "shapes": [[2, 3], [2, 2]],
        "pairing": None,
        "title": "Your multiplication, step by step",
        "hint": "read the inner two counts in your line 3",
    }

    # ------------------------------------------------------------------
    @classmethod
    def validate(cls, params: dict) -> dict:
        """Clamps, never raises. This is the bottom of the ladder."""
        p = dict(cls.DEFAULTS)
        try:
            p.update(params or {})
        except Exception:  # noqa: BLE001
            pass

        lines = p.get("lines") or []
        if not isinstance(lines, (list, tuple)):
            lines = []
        clean: list[dict] = []
        for ln in list(lines)[:MAX_LINES]:
            if not isinstance(ln, dict):
                clean.append({"kind": "text", "text": str(ln)[:MAX_CHARS]})
                continue
            if ln.get("kind") == "matrix" and ln.get("rows"):
                rows = [[str(v)[:8] for v in row][:4] for row in list(ln["rows"])[:4]]
                clean.append({"kind": "matrix", "rows": rows,
                              "prefix": str(ln.get("prefix", ""))[:12]})
            else:
                clean.append({"kind": "text",
                              "text": str(ln.get("text", ""))[:MAX_CHARS]})
        if not clean:
            clean = [{"kind": "text", "text": "your work"}]
        p["lines"] = clean

        focus = p.get("focus")
        if isinstance(focus, dict):
            f = {"line": int(focus.get("line", 0))}
            f["line"] = max(0, min(len(clean) - 1, f["line"]))
            if "cell" in focus:
                try:
                    i, j = focus["cell"]
                    f["cell"] = [max(0, int(i)), max(0, int(j))]
                except Exception:  # noqa: BLE001
                    pass
            if "chars" in focus and "cell" not in f:
                try:
                    a, b = focus["chars"]
                    f["chars"] = [max(0, int(a)), max(0, int(b))]
                except Exception:  # noqa: BLE001
                    pass
            p["focus"] = f
        else:
            p["focus"] = {"line": 0}

        shapes = p.get("shapes")
        ok_shapes = None
        if isinstance(shapes, (list, tuple)) and len(shapes) == 2:
            try:
                ok_shapes = [[int(shapes[0][0]), int(shapes[0][1])],
                             [int(shapes[1][0]), int(shapes[1][1])]]
            except Exception:  # noqa: BLE001
                ok_shapes = None
        p["shapes"] = ok_shapes

        pairing = p.get("pairing")
        if isinstance(pairing, dict):
            try:
                pr = {
                    "A_rows": [[str(v)[:6] for v in r][:4]
                               for r in list(pairing["A_rows"])[:4]],
                    "B_rows": [[str(v)[:6] for v in r][:4]
                               for r in list(pairing["B_rows"])[:4]],
                    "target": [int(pairing.get("target", [0, 0])[0]),
                               int(pairing.get("target", [0, 0])[1])],
                    "student_entry": str(pairing.get("student_entry", "?"))[:6],
                    "correct_entry": str(pairing.get("correct_entry", "?"))[:6],
                    "wrong_source": str(pairing.get("wrong_source", "row")),
                }
                pr["target"][0] = max(0, min(len(pr["A_rows"]) - 1, pr["target"][0]))
                pr["target"][1] = max(0, min(len(pr["B_rows"][0]) - 1, pr["target"][1]))
                p["pairing"] = pr
            except Exception:  # noqa: BLE001
                p["pairing"] = None
        else:
            p["pairing"] = None

        p["title"] = str(p.get("title") or "")[:70]
        p["annotation"] = str(p.get("annotation") or "")[:80]
        hint = str(p.get("hint") or "look again at the highlighted step")
        try:
            hint = check_hint(hint, [])
        except Exception:  # noqa: BLE001
            hint = "look again at the highlighted step"
        p["hint"] = hint
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:
        title = title_text(p["title"])
        hint = hint_text(p["hint"])
        try:
            if p.get("pairing"):
                self._pairing(p, title, hint)
            else:
                self._static(p, title, hint)
        except Exception as exc:  # noqa: BLE001
            # Never let the bottom of the fallback ladder fail: still produce a
            # titled, hinted video rather than no video at all.
            self.clear()
            note = label_text(p.get("annotation") or "your work",
                              font_size=30, color=CORRECT, max_lines=2,
                              max_height=1.2)
            self.add(title)
            self.play(FadeIn(note), run_time=1.0)
            self.wait(1.0)
            self.play(Write(hint), run_time=1.2)
            self.wait(1.0)
            print(f"[StaticStepHighlight] degraded to minimal frame: {exc}")

    # -- static mode ---------------------------------------------------
    def _static(self, p: dict, title, hint) -> None:
        rendered = []
        for ln in p["lines"]:
            if ln["kind"] == "matrix":
                mat = TextMatrix(ln["rows"], color=CORRECT, font_size=26)
                if ln.get("prefix"):
                    pre = T(ln["prefix"], font_size=26, color=CORRECT)
                    pre.next_to(mat, np.array([-1.0, 0.0, 0.0]), buff=0.14)
                    rendered.append(VGroup(pre, mat))
                else:
                    rendered.append(VGroup(mat))
            else:
                rendered.append(VGroup(T(ln["text"], font_size=32, color=CORRECT)))

        stack = VGroup(*rendered)
        stack.arrange(np.array([0.0, -1.0, 0.0]), buff=0.58)
        if stack.height > 4.6:
            stack.scale(4.6 / stack.height)
        if stack.width > 12.6:
            stack.scale(12.6 / stack.width)
        stack.move_to(np.array([0.0, 0.42, 0.0]))

        # -- 0.0 / 1.0 --------------------------------------------------
        self.play(FadeIn(title), run_time=1.0)
        # -- 1.0 / 1.4 --------------------------------------------------
        self.play(LaggedStart(*[FadeIn(m, shift=0.2 * np.array([0.0, -1.0, 0.0]))
                                for m in stack],
                              lag_ratio=0.35), run_time=1.4)
        # -- 2.4 / 0.6 --------------------------------------------------
        self.wait(0.6)

        target = self._focus_target(p, stack)
        box = SurroundingRectangle(target, color=STUDENT, buff=0.12,
                                   corner_radius=0.04)
        box.set_z_index(Z_FLASH)

        # -- 3.0 / 1.2 --------------------------------------------------
        self.play(Create(box), run_time=1.2)
        # -- 4.2 / 1.4 : pulse, and for a shape mismatch let the two inner
        #     counts make the argument by themselves --------------------
        extra = self._shape_argument(p, stack)
        if extra is not None:
            self.play(FadeIn(extra), Indicate(box, color=STUDENT, scale_factor=1.06),
                      run_time=1.4)
        else:
            self.play(Indicate(box, color=STUDENT, scale_factor=1.08), run_time=0.7)
            self.play(Indicate(box, color=STUDENT, scale_factor=1.08), run_time=0.7)

        # -- 5.6 / 0.8 --------------------------------------------------
        if p["annotation"]:
            ann = label_text(p["annotation"], font_size=26, color=PROBE,
                             max_width=12.0, max_lines=2, max_height=0.72)
            ann.move_to(np.array([0.0, -2.72, 0.0])).set_z_index(Z_CHROME)
            self.play(FadeIn(ann), run_time=0.8)
        else:
            self.wait(0.8)

        # -- 6.4 / 1.6 --------------------------------------------------
        self.play(Write(hint), run_time=1.0)
        self.wait(0.6)

    def _focus_target(self, p: dict, stack) -> VGroup:
        f = p.get("focus") or {}
        idx = max(0, min(len(stack) - 1, int(f.get("line", 0))))
        group = stack[idx]
        body = group[-1]
        if "cell" in f and isinstance(body, TextMatrix):
            i = max(0, min(body.n_rows - 1, int(f["cell"][0])))
            j = max(0, min(body.n_cols - 1, int(f["cell"][1])))
            return VGroup(body.entry(i, j))
        if "chars" in f and hasattr(body, "__len__") and len(body) > 0:
            a, b = f["chars"]
            a = max(0, min(len(body) - 1, int(a)))
            b = max(a + 1, min(len(body), int(b)))
            return VGroup(*body[a:b])
        return VGroup(group)

    def _shape_argument(self, p: dict, stack):
        """LA03: circle the two INNER dimensions and connect them."""
        shapes = p.get("shapes")
        if not shapes or len(stack) < 2:
            return None
        left, right = shapes[0], shapes[1]
        tags = []
        for k, sh in enumerate((left, right)):
            if k >= len(stack):
                return None
            t = T(f"{sh[0]} x {sh[1]}", font_size=24, color=GHOST)
            t.next_to(stack[k], np.array([1.0, 0.0, 0.0]), buff=0.45)
            t.set_z_index(Z_CHROME)
            tags.append(t)
        # inner dimensions: columns of the first, rows of the second
        inner_a = tags[0][-1]
        inner_b = tags[1][0]
        ca = Circle(radius=0.19, color=PROBE, stroke_width=3).move_to(
            inner_a.get_center())
        cb = Circle(radius=0.19, color=PROBE, stroke_width=3).move_to(
            inner_b.get_center())
        link = DashedLine(ca.get_bottom(), cb.get_top(), color=PROBE,
                          stroke_width=2.6, dash_length=0.1)
        g = VGroup(*tags, ca, cb, link)
        g.set_z_index(Z_FLASH)
        return g

    # -- pairing mode --------------------------------------------------
    def _pairing(self, p: dict, title, hint) -> None:
        pr = p["pairing"]
        i, j = pr["target"]
        A = TextMatrix(pr["A_rows"], color=CORRECT, font_size=28)
        B = TextMatrix(pr["B_rows"], color=CORRECT, font_size=28)
        eq = T("=", font_size=32, color=CORRECT)
        n_r, n_c = A.n_rows, B.n_cols
        result = TextMatrix([["?" for _ in range(n_c)] for _ in range(n_r)],
                            color=GHOST, font_size=28)
        row = VGroup(A, B, eq, result).arrange(np.array([1.0, 0.0, 0.0]), buff=0.55)
        # Fill the frame: at default font the four blocks occupy a third of it
        # and the sweeps become too small to follow on a projector.
        row.scale(min(11.0 / row.width, 3.0 / row.height, 2.1))
        row.move_to(np.array([0.0, 0.45, 0.0]))

        # -- 0.0 / 1.0 --------------------------------------------------
        self.play(FadeIn(title), FadeIn(row), run_time=1.0)
        self.wait(1.0)

        cell = result.cell_center(i, j)

        # -- 2.0 / 2.0  correct pairing: across A, DOWN B ---------------
        d1 = self._sweep(A.cell_center(i, 0), A.cell_center(i, A.n_cols - 1),
                         CORRECT)
        d2 = self._sweep(B.cell_center(0, j), B.cell_center(B.n_rows - 1, j),
                         CORRECT)
        self.play(MoveAlongPath(d1[0], d1[1]), MoveAlongPath(d2[0], d2[1]),
                  FadeIn(d1[2]), FadeIn(d2[2]), run_time=1.3)
        # ``correct_entry`` is the value of that cell -- the answer. The
        # lesson of this mode is purely positional (WHICH row pairs with
        # WHICH column), and the two sweeps have just shown it, so the value
        # lands as a "?" and the student multiplies it out themselves. A
        # Flash marks the landing, because the glyph is unchanged from the
        # placeholder already in the result matrix.
        reveal = reveal_correct_values()
        good = T(pr["correct_entry"] if reveal else MASK, font_size=28,
                 color=CORRECT).move_to(cell)
        good.set_z_index(Z_FLASH)
        land = [] if reveal else [Flash(cell, color=CORRECT, line_length=0.14,
                                        flash_radius=0.45)]
        self.play(FadeOut(result.entry(i, j)), FadeIn(good, scale=1.6),
                  FadeOut(d1[0]), FadeOut(d2[0]), FadeOut(d1[2]), FadeOut(d2[2]),
                  *land, run_time=0.7)

        # -- 4.0 / 2.0  student pairing: the second sweep runs ACROSS ---
        if pr["wrong_source"] == "col":
            s1 = self._sweep(A.cell_center(0, i), A.cell_center(A.n_rows - 1, i),
                             STUDENT)
            s2 = self._sweep(B.cell_center(0, j), B.cell_center(B.n_rows - 1, j),
                             STUDENT)
        else:
            s1 = self._sweep(A.cell_center(i, 0), A.cell_center(i, A.n_cols - 1),
                             STUDENT)
            jj = min(j, B.n_rows - 1)
            s2 = self._sweep(B.cell_center(jj, 0),
                             B.cell_center(jj, B.n_cols - 1), STUDENT)
        self.play(MoveAlongPath(s1[0], s1[1]), MoveAlongPath(s2[0], s2[1]),
                  FadeIn(s1[2]), FadeIn(s2[2]), run_time=1.3)
        ghost = good.copy().set_color(GHOST).scale(0.85)
        ghost.next_to(result, np.array([0.0, 1.0, 0.0]), buff=0.22)
        ghost.shift(np.array([cell[0] - result.get_center()[0], 0.0, 0.0]))
        bad = T(pr["student_entry"], font_size=28, color=STUDENT).move_to(cell)
        bad.set_z_index(Z_FLASH)
        self.play(good.animate.become(ghost), FadeIn(bad, scale=1.6),
                  FadeOut(s1[0]), FadeOut(s2[0]), FadeOut(s1[2]), FadeOut(s2[2]),
                  run_time=0.7)

        # -- 6.0 / 1.0  the two candidates, boxed -----------------------
        box = DashedVMobject(
            SurroundingRectangle(VGroup(good, bad), color=PROBE, buff=0.14),
            num_dashes=28)
        box.set_z_index(Z_FLASH)
        self.play(Create(box), run_time=1.0)
        self.wait(0.6)

        # -- 7.6 / 1.8 --------------------------------------------------
        self.play(Write(hint), run_time=1.1)
        self.wait(0.7)

    @staticmethod
    def _sweep(start: np.ndarray, end: np.ndarray, color: str):
        """A dot plus the path it runs, and a faint trail showing the
        DIRECTION of the sweep -- which is the whole tell in pairing mode."""
        from manim import Dot

        if float(np.linalg.norm(np.asarray(end) - np.asarray(start))) < 1e-6:
            end = np.asarray(end) + np.array([0.01, 0.0, 0.0])
        path = Line(start, end)
        dot = Dot(start, radius=0.09, color=color).set_z_index(Z_FLASH)
        trail = Line(start, end, color=color, stroke_width=5)
        trail.set_stroke(opacity=0.5)
        trail.set_z_index(Z_FLASH - 1)
        return dot, path, trail


class StaticStepHighlightPairing(StaticStepHighlight):
    """LA01 pairing mode, renderable by name."""

    TEMPLATE = "StaticStepHighlight"
    DURATION = 9.4
    DEFAULTS = dict(
        StaticStepHighlight.DEFAULTS,
        lines=[],
        focus={"line": 0},
        shapes=None,
        annotation="",
        pairing={
            "A_rows": [["2", "1"], ["1", "3"]],
            "B_rows": [["1", "2"], ["0", "1"]],
            "target": [0, 0],
            "student_entry": "4",
            "correct_entry": "2",
            "wrong_source": "row",
        },
        title="Where each entry of the product comes from",
        hint="watch which way the second dot travels",
    )
