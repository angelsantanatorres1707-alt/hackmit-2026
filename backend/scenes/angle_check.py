"""Does the map keep the corner square? Does it keep the lengths?

A student can compute a transformation perfectly and still conclude the wrong
thing about it. "Both basis vectors still have the same length, so it preserves
angles" is the case this scene exists for: the premise is true and the
conclusion does not follow from it.

Nothing numeric is wrong in that work, so there is no value to contrast and no
answer to withhold. What is wrong is a claim about a property, and the property
is visible: draw the two basis arrows, apply the student's own map, and watch.

- ``show="angle"``: a right-angle square rides along with the basis and closes.
- ``show="length"``: a ghost unit circle stays put and the tips leave it.

The collapse IS the argument -- equal lengths do not imply equal angles.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from manim import Angle, Circle, Create, FadeIn, FadeOut, Line, Transform, VGroup, Write

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import (  # noqa: E402
    CORRECT, GHOST, PROBE, STUDENT, ParamScene, T, Z_CHROME, Z_FLASH,
    arrow_at, fit_unit, fmt_num, one_panel_layout,
)

_MAX = 6.0


def _vec(pair, fallback):
    try:
        x, y = float(pair[0]), float(pair[1])
        if not (abs(x) <= _MAX and abs(y) <= _MAX) or (x == 0 and y == 0):
            raise ValueError
        return [x, y]
    except Exception:  # noqa: BLE001
        return list(fallback)


class AnglePreservationCheck(ParamScene):
    """The basis, the corner between it, and what the student's map does to it."""

    TEMPLATE = "AnglePreservationCheck"
    DURATION = 11.0

    DEFAULTS = {
        "e1_image": [2.0, 1.0],
        "e2_image": [1.0, 2.0],
        "show": "angle",
        "title": "Your transformation, applied to the corner",
        "hint": "",
    }

    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        try:
            p.update(params or {})
        except Exception:  # noqa: BLE001
            pass
        p["e1_image"] = _vec(p.get("e1_image"), cls.DEFAULTS["e1_image"])
        p["e2_image"] = _vec(p.get("e2_image"), cls.DEFAULTS["e2_image"])
        p["show"] = p.get("show") if p.get("show") in ("angle", "length") else "angle"
        p["title"] = str(p.get("title") or "")[:70]
        p["hint"] = str(p.get("hint") or "")[:120]
        return p

    def build_scene(self, p: dict) -> None:  # noqa: D102
        a = np.array(p["e1_image"], dtype=float)
        b = np.array(p["e2_image"], dtype=float)
        mode = p["show"]

        # Size the panel to what is actually DRAWN -- the two images and the
        # unit square. a+b is never a drawn tip, and including it shrank every
        # arrow by a third for nothing.
        unit = fit_unit([a, b, np.array([1.2, 1.2])], box=6.2)
        # Nothing is scored on the right here, so the plane takes the middle of
        # the frame instead of hugging the left edge with half the screen dark.
        L = one_panel_layout(self, title=p["title"], hint=p["hint"],
                             dx=0.0, dy=0.10, box=6.6, box_h=6.2, unit=unit)
        P = L.left or L.panels[0]
        o = P.origin

        # The plane is built by the layout but not shown by it.
        self.play(Create(P.plane), FadeIn(L.title), run_time=1.1)

        # ---- the corner as it starts: two unit arrows ----------------------
        e1 = arrow_at(o, [1, 0], CORRECT, unit=P.unit)
        e2 = arrow_at(o, [0, 1], PROBE, unit=P.unit)
        l1 = T("e₁", font_size=26, color=CORRECT).next_to(P.pt([1, 0]), np.array([0.0, -1.0, 0.0]), buff=0.18)
        l2 = T("e₂", font_size=26, color=PROBE).next_to(P.pt([0, 1]), np.array([-1.0, 0.0, 0.0]), buff=0.18)

        k = 0.42
        if mode == "angle":
            mark = VGroup(
                Line(P.pt([k, 0]), P.pt([k, k])),
                Line(P.pt([k, k]), P.pt([0, k])),
            )
        else:
            mark = VGroup(Circle(radius=P.unit, color=GHOST).move_to(o))
        mark.set_stroke(CORRECT, 4.5)
        mark.set_z_index(Z_CHROME)

        self.play(Create(e1), Create(e2), FadeIn(l1), FadeIn(l2), run_time=1.1)
        self.play(Create(mark), run_time=0.8)
        self.wait(1.1)

        # ---- apply the map ------------------------------------------------
        e1b = arrow_at(o, a, STUDENT, unit=P.unit)
        e2b = arrow_at(o, b, STUDENT, unit=P.unit)
        l1b = T(f"({fmt_num(a[0])}, {fmt_num(a[1])})", font_size=24, color=STUDENT)
        l1b.next_to(P.pt(a), np.array([1.0, -0.5, 0.0]), buff=0.16)
        l2b = T(f"({fmt_num(b[0])}, {fmt_num(b[1])})", font_size=24, color=STUDENT)
        l2b.next_to(P.pt(b), np.array([0.0, 1.0, 0.0]), buff=0.16)

        moving = [Transform(e1, e1b), Transform(e2, e2b), FadeOut(l1), FadeOut(l2)]
        if mode == "angle":
            # The corner is carried by the same map, not redrawn, so the
            # collapse is something the student watches happen rather than is
            # told about. The circle in length mode deliberately stays put:
            # it is the ruler the tips are leaving.
            moved = VGroup(
                Line(P.pt(k * a), P.pt(k * (a + b))),
                Line(P.pt(k * (a + b)), P.pt(k * b)),
            ).set_stroke(CORRECT, 4.5)
            moved.set_z_index(Z_CHROME)
            moving.append(Transform(mark, moved))

        self.play(*moving, run_time=2.2)
        self.play(FadeIn(l1b), FadeIn(l2b), run_time=0.7)
        self.wait(1.0)

        # ---- name what used to be true -------------------------------------
        na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if mode == "angle":
            try:
                ang = Angle(Line(o, P.pt(a)), Line(o, P.pt(b)),
                            radius=0.62, other_angle=False)
                ang.set_stroke(STUDENT, 4.0)
                ang.set_z_index(Z_FLASH)
                self.play(Create(ang), run_time=1.0)
            except Exception:  # noqa: BLE001
                pass
            cos = float(np.dot(a, b)) / (na * nb) if na * nb else 0.0
            label = f"{fmt_num(np.degrees(np.arccos(max(-1.0, min(1.0, cos)))))}°"
        else:
            label = f"1 → {fmt_num(max(na, nb))}"

        # Out along the bisector, past both tips, so the readout never sits on
        # the arc or on an arrow.
        d = a / na + b / nb if na and nb else np.array([1.0, 1.0])
        d = d / float(np.linalg.norm(d))
        read = T(label, font_size=32, color=STUDENT)
        read.move_to(P.pt(d * 1.15 * max(na, nb)))
        read.set_z_index(Z_FLASH)
        self.play(FadeIn(read, scale=1.4), run_time=0.8)
        self.wait(0.9)

        self.play(Write(L.hint), run_time=1.2)
        self.wait(1.2)
