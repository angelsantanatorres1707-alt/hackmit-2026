"""How a 2x2 inverse is built -- on the student's own matrix, stopping short.

A port of Hanna's inverse_2x2.py template into this codebase, which required
two changes it could not keep:

  * NO LATEX. The original is built from Matrix, MathTex and Tex, all of which
    shell out to `latex`, which is deliberately not installed here (CLAUDE.md,
    "Things that break silently"). Matrix builds even its BRACKETS from a LaTeX
    array, so swapping the entry class is not enough. Everything here is
    TextMatrix and Text.

  * NO ANSWER. The original ends by printing A^-1, verifying A.A^-1 = I, and
    recapping the result. That is the one thing this product does not do. The
    recipe, the determinant sweep and the rearrangement are all kept -- they
    are the method, and the rearrangement is visibly made of the student's own
    numbers -- and the final division is shown as a step they take, with the
    result masked. What is withheld is the value, never the reasoning.

The structure, the beat order and the pacing are Hanna's.

Standalone render:
    .venv/bin/manim -qm --disable_caching backend/scenes/inverse_2x2.py InverseOf2x2
"""

from __future__ import annotations

import os
import sys
from fractions import Fraction

import numpy as np
from manim import (
    Circumscribe, Create, FadeIn, FadeOut, Indicate, Line, Transform,
    VGroup, Write,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import (  # noqa: E402
    CORRECT, GHOST, MASK, MASK_COLOR, PROBE, STUDENT, T, TextMatrix,
    Z_CHROME, Z_FLASH, ParamScene, SceneParamError, hint_text, label_text,
    reveal_correct_values, title_text,
)

CAP_Y = -3.18


def _int(x) -> str:
    f = Fraction(x).limit_denominator(10 ** 6)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


class InverseOf2x2(ParamScene):
    """The recipe, then the same recipe running on their matrix."""

    TEMPLATE = "InverseOf2x2"
    DURATION = 27.0

    DEFAULTS = {
        "matrix": [[4, 7], [2, 6]],
        "matrix_name": "A",
        # The determinant is shown only when the student wrote it down: it is
        # then THEIR number and always visible. Otherwise it is masked like any
        # other value computed from the problem.
        "student_det": None,
        "show_general_rule": True,
        # This scene opens with the recipe, which IS the concept beat. Playing
        # the generic one in front of it says the same thing twice and leaves
        # its grid on screen under the matrices.
        "skip_prologue": True,
        "title": "How a 2x2 inverse is built",
        "hint": "watch what the determinant does to every entry",
    }

    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})
        M = np.array(p.get("matrix"), dtype=float)
        if M.shape != (2, 2) or not np.all(np.isfinite(M)):
            raise SceneParamError("matrix must be a finite 2x2")
        p["matrix"] = M.tolist()
        det = float(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0])
        if abs(det) < 1e-9:
            # A singular matrix has no inverse, and saying so IS the answer to
            # "find A^-1". The collapse scene owns that case, not this one.
            raise SceneParamError("this matrix is singular; it has no inverse to build")
        p["_det"] = det
        sd = p.get("student_det")
        p["student_det"] = None if sd is None else str(sd)[:12]
        p["matrix_name"] = str(p.get("matrix_name") or "A")[:3]
        p["title"] = str(p.get("title") or "")[:70]
        p["hint"] = str(p.get("hint") or "")[:120]
        return p

    # ------------------------------------------------------------------
    def build_scene(self, p: dict) -> None:  # noqa: D102
        M = p["matrix"]
        a, b = M[0]
        c, d = M[1]
        det = p["_det"]
        name = p["matrix_name"]

        title = title_text(p["title"])
        self.add(title)

        if p["show_general_rule"]:
            self._recipe()

        self._on_their_matrix(a, b, c, d, det, name, p["student_det"])

        hint = hint_text(p["hint"])
        self.play(Write(hint), run_time=1.0)
        self.wait(0.50)

    # ------------------------------------------------------------------
    def _say(self, text: str, hold: float = 1.2):
        """One caption at a time, crossfaded. Hanna's `say`, without Tex."""
        new = label_text(text, font_size=27, color=GHOST, max_width=11.5)
        new.move_to(np.array([0.0, CAP_Y, 0.0])).set_z_index(Z_CHROME)
        old = getattr(self, "_cap", None)
        if old is None:
            self.play(FadeIn(new, shift=np.array([0.0, 0.2, 0.0])), run_time=0.5)
        else:
            self.play(FadeOut(old, shift=np.array([0.0, 0.15, 0.0])),
                      FadeIn(new, shift=np.array([0.0, 0.15, 0.0])), run_time=0.5)
        self._cap = new
        self.wait(hold)

    def _clear(self, keep=()):
        drop = [m for m in self.mobjects if m not in keep]
        if drop:
            self.play(*[FadeOut(m) for m in drop], run_time=0.55)
        self._cap = None

    # ------------------------------------------------------------------
    def _recipe(self) -> None:
        """The symbolic rule. Letters only, so it cannot leak anything."""
        A = TextMatrix([["a", "b"], ["c", "d"]], font_size=34, color=CORRECT)
        A.move_to(np.array([-3.1, 1.35, 0.0]))
        lab = T(f"A =", font_size=32, color=CORRECT).next_to(A, np.array([-1.0, 0, 0]), buff=0.28)
        self.play(FadeIn(VGroup(lab, A)), run_time=0.7)
        self._say("Every 2x2 matrix has the same four ingredients.", 0.55)

        adj = TextMatrix([["d", "-b"], ["-c", "a"]], font_size=34, color=CORRECT)
        adj.move_to(np.array([2.3, 1.35, 0.0]))
        one_over = T("1/(ad - bc)", font_size=30, color=PROBE)
        one_over.next_to(adj, np.array([-1.0, 0, 0]), buff=0.30)
        inv_lab = T("A" + "⁻¹ =", font_size=32, color=CORRECT)
        inv_lab.next_to(one_over, np.array([-1.0, 0, 0]), buff=0.26)
        self.play(FadeIn(adj), FadeIn(inv_lab), run_time=0.8)

        self._say("Swap the two on the main diagonal.", 0.55)
        self.play(Indicate(adj.entry(0, 0), color=CORRECT, scale_factor=1.45),
                  Indicate(adj.entry(1, 1), color=CORRECT, scale_factor=1.45),
                  run_time=0.9)

        self._say("Flip the sign of the other two.", 0.55)
        self.play(Indicate(adj.entry(0, 1), color=STUDENT, scale_factor=1.45),
                  Indicate(adj.entry(1, 0), color=STUDENT, scale_factor=1.45),
                  run_time=0.9)

        self.play(FadeIn(one_over), run_time=0.5)
        self._say("Then divide every entry by the determinant.", 0.65)
        self.play(Circumscribe(one_over, color=PROBE, buff=0.16), run_time=1.0)
        self.wait(0.20)
        self._clear()

    # ------------------------------------------------------------------
    def _on_their_matrix(self, a, b, c, d, det, name, student_det) -> None:
        A = TextMatrix([[_int(a), _int(b)], [_int(c), _int(d)]],
                       font_size=34, color=CORRECT)
        A.move_to(np.array([-3.6, 1.5, 0.0]))
        lab = T(f"{name} =", font_size=32, color=CORRECT)
        lab.next_to(A, np.array([-1.0, 0, 0]), buff=0.28)
        self.play(FadeIn(VGroup(lab, A)), run_time=0.7)

        # ---- the determinant sweep ------------------------------------
        self._say("The determinant: multiply down, then multiply up.", 1.1)
        down = Line(A.cell_center(0, 0), A.cell_center(1, 1),
                    color=CORRECT, stroke_width=6).set_z_index(-1)
        up = Line(A.cell_center(0, 1), A.cell_center(1, 0),
                  color=STUDENT, stroke_width=6).set_z_index(-1)
        self.play(Create(down), run_time=0.6)
        self.play(Create(up), run_time=0.6)

        shown = student_det if student_det is not None else (
            _int(det) if reveal_correct_values() else MASK)
        colour = STUDENT if student_det is not None else (
            CORRECT if reveal_correct_values() else MASK_COLOR)
        det_line = T(f"({_int(a)})({_int(d)})  -  ({_int(b)})({_int(c)})  =  {shown}",
                     font_size=32, color=CORRECT)
        det_line.move_to(np.array([1.9, 1.5, 0.0]))
        det_line.set_z_index(Z_CHROME)
        self.play(Write(det_line), run_time=1.6)
        if student_det is not None:
            self._say("That is the number you worked out.", 0.50)
        self.wait(0.30)
        self.play(FadeOut(down), FadeOut(up), run_time=0.4)

        # ---- the rearrangement, made of their own numbers --------------
        self._say("Now rearrange the four entries.", 0.55)
        work = TextMatrix([[_int(a), _int(b)], [_int(c), _int(d)]],
                          font_size=34, color=CORRECT)
        work.move_to(np.array([-1.0, -0.55, 0.0]))
        self.play(FadeIn(work), run_time=0.6)

        swapped = TextMatrix([[_int(d), _int(b)], [_int(c), _int(a)]],
                             font_size=34, color=CORRECT).move_to(work)
        self.play(Transform(work, swapped), run_time=1.1)
        self._say("Swap the diagonal.", 0.45)

        adj = TextMatrix([[_int(d), _int(-b)], [_int(-c), _int(a)]],
                         font_size=34, color=CORRECT).move_to(work)
        adj.entry(0, 1).set_color(STUDENT)
        adj.entry(1, 0).set_color(STUDENT)
        self.play(Transform(work, adj), run_time=1.1)
        self._say("Negate the other two.", 0.50)
        self.wait(0.25)

        # ---- the last step is theirs to take ---------------------------
        # Showing the divided entries would be printing A^-1, which is the
        # answer. The division is named, the result is masked.
        self._say("One step left: divide every entry by the determinant.", 0.70)
        masked = TextMatrix([[MASK, MASK], [MASK, MASK]],
                            font_size=34, color=MASK_COLOR)
        masked.move_to(np.array([2.6, -0.55, 0.0]))
        arrow = T("→", font_size=40, color=GHOST)
        arrow.move_to(np.array([0.9, -0.55, 0.0]))
        self.play(FadeIn(arrow), FadeIn(masked), run_time=0.8)
        self.play(Circumscribe(masked, color=PROBE, buff=0.18), run_time=1.0)
        self.wait(0.40)
