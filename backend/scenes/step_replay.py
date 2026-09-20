"""T8 -- StepReplay.  The student's own steps, replayed in order, one canvas.

This is NOT a template that picks a preset picture for an error code. It is a
tiny interpreter with a graphics backend:

  * a REGISTER FILE maps symbol -> (the student's number, its live mobject);
  * it is seeded from ``givens``;
  * each step READS registers named in its ``args``, performs its geometric
    action on the shared canvas, and WRITES its claimed ``result`` into the
    register named by ``bind``.

Step i+1's input arrow is literally the mobject step i left on screen. That
continuity IS the replay. Everything drawn is a function of the givens and the
student's own claimed numbers -- ``verdict.correct_value`` is never passed in,
so a leak is impossible by construction rather than by masking.

Divergence is shown by drawing the INVARIANT the operation must satisfy (a
region, computable from the givens alone) BEFORE the claim lands, then letting
the claim miss it. See docs/STEP_REPLAY.md sections 5 and 6.

Standalone render:
    .venv/bin/manim -qm --disable_caching -v ERROR --media_dir /tmp/sr \\
        backend/scenes/step_replay.py StepReplay
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np
from manim import (
    ApplyMatrix,
    Arc,
    Arrow,
    Circle,
    Create,
    DashedLine,
    DrawBorderThenFill,
    Dot,
    FadeIn,
    FadeOut,
    GrowArrow,
    GrowFromEdge,
    LEFT,
    LaggedStart,
    Line,
    Polygon,
    Rectangle,
    Rotate,
    Transform,
    UP,
    VGroup,
    VMobject,
    ValueTracker,
    Wiggle,
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
    Z_BORDER,
    Z_CHROME,
    Z_MATTE,
    Z_PLANE,
    arrow_at,
    as_matrix,
    as_vector,
    check_hint,
    fmt_num,
    hint_text,
    label_text,
    lattice_weight,
    make_plane,
    panel_matte,
    parse_num,
    residual,
    right_angle_marker,
    span_line,
    title_text,
)

# ---------------------------------------------------------------------------
# Canvas constants.  All of these are VERIFIED at -qm; see STEP_REPLAY.md 5.
#
# THE Z RULE (pitfall 1, cost an entire prototype): panel_matte sits at
# Z_MATTE = 10, and helpers like ``residual`` / ``right_angle_marker`` default
# to Z_FLASH = 13, i.e. ABOVE the matte -- so they escape the box and float in
# the black gutter.  EVERY mobject expressed in panel coordinates gets Z_GEO.
# Only the title, the ledger, the hint and the border may sit above the matte,
# and none of those are in panel coordinates.
# ---------------------------------------------------------------------------
Z_GEO = Z_MATTE - 1

BOX_W_D, BOX_H_D = 9.5, 6.05
BOX_C_D = (-1.85, -0.30)
PAD_D, MARGIN_D, ZOOM_MAX_D = 0.9, 0.55, 2.6
HYST = 0.88                 # only re-frame when the unit drops below this

UNIT_FLOOR, UNIT_CEIL = 0.06, 3.0

# The ledger rail: the student's own lines, re-typeset, appearing as they are
# played.  This is the "it read my work" evidence and it is where a step with
# no honest geometry lives.
LEDGER_L, LEDGER_R = 3.10, 6.94
LEDGER_TOP = 2.46
LEDGER_GAP = 0.24
MARK_X = LEDGER_L + 0.14
TEXT_X = LEDGER_L + 0.36

FS_LEDGER = 20
FS_LEDGER_NUM = 19
FS_LABEL = 28
FS_CAPTION = 23

# The dot-product arithmetic strip, in SCENE coordinates at the bottom of the
# box (deliberately not in panel coordinates -- it is arithmetic, not geometry).
BAR_LEN = 3.55
BAR_H = 0.21

PALETTE = {
    "i_hat": I_HAT, "j_hat": J_HAT, "probe": PROBE, "student": STUDENT,
    "correct": CORRECT, "ghost": GHOST, "green": I_HAT, "red": J_HAT,
}
ROTA = (I_HAT, J_HAT, PROBE, CORRECT)

# Kinds that have no honest geometry.  ERROR_TAXONOMY.md section 3 is explicit
# that inventing a picture for an arithmetic line "would actively mislead" --
# which is the exact failure mode this template exists to fix.
LEDGER_ONLY_KINDS = {
    "scalar_value", "state_answer", "unknown", "determinant_expand",
    "cofactor", "char_poly", "solve_char_poly", "back_substitute", "elision",
}

KIND_ALIASES = {
    "projection": "project",
    "scalar_multiply": "scale_vector",
    "dot": "dot_product",
    "add": "add_vectors",
    "subtract": "add_vectors",
    "copy_given": "define_vector",
}

DEFAULT_RUN_TIME = {
    "define_vector": 0.6, "define_matrix": 0.7, "dot_product": 2.4,
    "scale_vector": 2.6, "add_vectors": 1.8, "matrix_apply": 2.2,
    "matrix_product": 2.6, "row_op": 2.0, "normalize": 1.6, "project": 2.2,
}

BUDGET, BUDGET_CEILING, RT_FLOOR = 16.5, 20.0, 0.4
MAX_LEDGER_LINES = 7


# ---------------------------------------------------------------------------
# The register file
# ---------------------------------------------------------------------------

@dataclass
class Reg:
    """A symbol's current value AND its live mobject on the canvas.

    ``label`` is REWRITTEN on every write: after ``scale_vector(k=5, v=a) -> p``
    the arrow is no longer "a", it is "5a".  Prototype 2 missed this and the
    final frame captioned a (5,10) arrow as "a", which is simply a lie about
    the student's work.
    """
    value: Any
    display: str = ""
    mob: VMobject | None = None
    label_mob: VMobject | None = None
    color: str = CORRECT
    label: str = ""
    kind: str = "vector"
    stroke_width: float = 9.0


@dataclass
class Live:
    """Anything in PANEL coordinates that must be rebuilt when the frame moves.

    ``get`` returns the mobject currently on the canvas (or None if it has been
    consumed); ``build(unit, origin)`` returns a fresh one at the new frame.
    Re-framing is then a Transform of every one of these, played INSIDE the
    step's own play() -- never as its own beat.
    """
    get: Callable[[], VMobject | None]
    build: Callable[[float, np.ndarray], VMobject]


def _is_number(x: Any) -> bool:
    if isinstance(x, (int, float)):
        return True
    try:
        parse_num(x)
        return True
    except SceneParamError:
        return False


def _vec2(value, name: str) -> np.ndarray:
    v = as_vector(value, name=name, dim=None)
    return np.array([float(v[0]), float(v[1])], dtype=float)


# ---------------------------------------------------------------------------

class StepReplay(ParamScene):
    TEMPLATE = "StepReplay"
    DURATION = 15.4

    # The user's real homework.  a=(1,2), b=(3,1), "proj_a(b) = (b.a)a" --
    # the dot product is right, the scale forgets to divide by a.a.
    DEFAULTS: dict = {
        "title": "Your steps, replayed",
        "hint": "a shadow can't be longer than the thing casting it",
        "student_label": "YOUR WORK",
        "canvas": {
            "box": [BOX_W_D, BOX_H_D], "box_center": list(BOX_C_D),
            "ledger_x": 4.95, "zoom_max": ZOOM_MAX_D,
            "pad": PAD_D, "margin": MARGIN_D, "grow": False,
        },
        "givens": {
            "a": {"kind": "vector", "value": [1, 2], "display": "(1, 2)",
                  "color": "i_hat"},
            "b": {"kind": "vector", "value": [3, 1], "display": "(3, 1)",
                  "color": "j_hat"},
        },
        "leak_guard": ["project"],
        "steps": [
            {
                "id": "s1", "student_label": "1)", "kind": "dot_product",
                "expr": "b.a = 3(1) + 1(2) = 5",
                "args": {"u": "b", "v": "a"},
                "terms": ["3(1)", "1(2)"],
                "result": {"kind": "scalar", "value": 5, "display": "5"},
                "bind": "k", "status": "ok", "first_wrong": False,
                "run_time": 2.4, "invariant": None, "divergence": None,
            },
            {
                "id": "s2", "student_label": "2)", "kind": "scale_vector",
                "expr": "proj_a(b) = 5(1,2) = (5,10)",
                "args": {"k": "k", "v": "a"},
                "result": {"kind": "vector", "value": [5, 10],
                           "display": "(5, 10)"},
                "bind": "p", "status": "wrong", "first_wrong": True,
                "run_time": 3.0,
                "invariant": {"kind": "disc", "radius_of": "b",
                              "caption": "every shadow of b lands in here"},
                "divergence": {"absurdity": "length", "compare_to": "b",
                               "residual_from": "b", "right_angle_at": "result"},
            },
        ],
    }

    # ==================================================================
    # Validation -- the seven cases from STEP_REPLAY.md section 3.
    # Every one of them degrades via render_with_fallback to
    # StaticStepHighlight, which is unchanged.
    # ==================================================================
    @classmethod
    def validate(cls, params: dict) -> dict:
        p = dict(cls.DEFAULTS)
        p.update(params or {})

        c = dict(cls.DEFAULTS["canvas"])
        c.update(p.get("canvas") or {})
        p["canvas"] = c
        box = [float(x) for x in c.get("box", [BOX_W_D, BOX_H_D])][:2]
        zoom_max = max(1.05, float(c.get("zoom_max", ZOOM_MAX_D)))
        pad = float(c.get("pad", PAD_D))
        margin = float(c.get("margin", MARGIN_D))

        # -- givens seed the scope -------------------------------------
        givens = p.get("givens") or {}
        if not isinstance(givens, dict):
            raise SceneParamError("givens must be an object")
        scope: dict[str, str] = {}
        clean_g: dict[str, dict] = {}
        for name, g in givens.items():
            if not isinstance(g, dict):
                raise SceneParamError(f"givens.{name} must be an object")
            kind = str(g.get("kind") or "vector")
            g = dict(g)
            if kind == "matrix":
                g["value"] = as_matrix(g.get("value"),
                                       name=f"givens.{name}").tolist()
            elif kind == "scalar":
                g["value"] = parse_num(g.get("value"), name=f"givens.{name}")
            else:
                kind = "vector"
                g["value"] = _vec2(g.get("value"), f"givens.{name}").tolist()
            g["kind"] = kind
            scope[str(name)] = kind
            clean_g[str(name)] = g
        p["givens"] = clean_g

        # -- steps ------------------------------------------------------
        steps = p.get("steps") or []
        if not isinstance(steps, list):
            raise SceneParamError("steps must be a list")
        # (1) fewer than two steps is not a replay.
        if len(steps) < 2:
            raise SceneParamError(
                f"StepReplay needs >= 2 steps to replay, got {len(steps)}")

        clean: list[dict] = []
        n_wrong = 0
        n_geo = 0
        for i, raw in enumerate(steps):
            if not isinstance(raw, dict):
                raise SceneParamError(f"steps[{i}] must be an object")
            st = dict(raw)
            kind = str(st.get("kind") or "unknown").strip().lower()
            kind = KIND_ALIASES.get(kind, kind)
            st["kind"] = kind
            if kind not in LEDGER_ONLY_KINDS:
                n_geo += 1

            st["expr"] = " ".join(str(st.get("expr") or "").split())
            st["student_label"] = str(st.get("student_label") or f"{i + 1})")
            st["status"] = str(st.get("status") or "unchecked")
            st["first_wrong"] = bool(st.get("first_wrong"))
            n_wrong += 1 if st["first_wrong"] else 0

            args = st.get("args") or {}
            if not isinstance(args, dict):
                raise SceneParamError(f"steps[{i}].args must be an object")
            # (3) every symbol an arg names must already be bound HERE --
            #     a forward reference or an unbound name has no mobject to
            #     read and would silently draw the wrong thing.
            for key, val in args.items():
                if isinstance(val, str) and not _is_number(val):
                    if val not in scope:
                        raise SceneParamError(
                            f"steps[{i}].args.{key}: symbol {val!r} is not in "
                            f"scope (bound so far: {sorted(scope)})")
            st["args"] = dict(args)

            # (6) as_vector / as_matrix reject the student's claim.
            res = st.get("result") or {}
            if not isinstance(res, dict):
                raise SceneParamError(f"steps[{i}].result must be an object")
            res = dict(res)
            rkind = str(res.get("kind") or "scalar")
            if rkind == "vector":
                res["value"] = _vec2(res.get("value"),
                                     f"steps[{i}].result").tolist()
            elif rkind == "matrix":
                res["value"] = as_matrix(res.get("value"),
                                         name=f"steps[{i}].result").tolist()
            else:
                rkind = "scalar"
                res["value"] = parse_num(res.get("value"),
                                         name=f"steps[{i}].result")
            res["kind"] = rkind
            res.setdefault("display", fmt_num(res["value"])
                           if rkind == "scalar" else "")
            st["result"] = res

            # (5) an invariant that carries a literal instead of a symbol is
            #     an answer smuggled in as a picture.  Only symbols in scope.
            inv = st.get("invariant")
            if inv:
                if not isinstance(inv, dict):
                    raise SceneParamError(f"steps[{i}].invariant must be an object")
                inv = dict(inv)
                for key, val in list(inv.items()):
                    if key.endswith("_of"):
                        if not isinstance(val, str) or _is_number(val):
                            raise SceneParamError(
                                f"steps[{i}].invariant.{key} must NAME A SYMBOL, "
                                f"got the literal {val!r}")
                        if val not in scope:
                            raise SceneParamError(
                                f"steps[{i}].invariant.{key}: {val!r} not in scope")
                if inv.get("caption"):
                    # Captions are burned into the frame and are every bit as
                    # public as the hint, so they are linted the same way.
                    inv["caption"] = check_hint(str(inv["caption"]))
                st["invariant"] = inv

            div = st.get("divergence")
            if div:
                if not isinstance(div, dict):
                    raise SceneParamError(f"steps[{i}].divergence must be an object")
                div = dict(div)
                for key in ("compare_to", "residual_from"):
                    val = div.get(key)
                    if val in (None, "", "result"):
                        continue
                    if not isinstance(val, str) or val not in scope:
                        raise SceneParamError(
                            f"steps[{i}].divergence.{key}: {val!r} is not a "
                            f"symbol in scope")
                st["divergence"] = div

            rt = st.get("run_time")
            st["run_time"] = (float(rt) if rt is not None
                              else DEFAULT_RUN_TIME.get(kind, 0.5))
            if kind == "scale_vector" and rt is None:
                try:
                    k = abs(cls._peek_scalar(args.get("k"), scope, p))
                except Exception:  # noqa: BLE001
                    k = 2.0
                st["run_time"] = 0.28 * min(k, 5.0) + 1.2
            st["run_time"] = float(np.clip(st["run_time"], 0.25, 6.0))

            bind = st.get("bind")
            if bind:
                scope[str(bind)] = rkind
            clean.append(st)

        # (4) exactly one step may be the first wrong one.
        if n_wrong > 1:
            raise SceneParamError(
                f"{n_wrong} steps marked first_wrong; at most one is allowed")
        # (2) a replay in which nothing has geometry is not a replay.
        if n_geo == 0:
            raise SceneParamError(
                "every step is ledger-only (no geometry) -- nothing to replay")

        clean = cls._elide(clean)
        p["steps"] = clean

        # -- framing, and (7) the zoom-ratio guard ----------------------
        gpts = [np.array(g["value"], float) for g in clean_g.values()
                if g["kind"] == "vector"]
        spts = [np.array(s["result"]["value"], float) for s in clean
                if s["result"]["kind"] == "vector"]
        u_end, _ = _frame_for(gpts + spts, box, BOX_C_D, pad, margin)
        u_start, _ = _frame_for(gpts or spts, box, BOX_C_D, pad, margin)
        ratio = u_start / max(u_end, 1e-9)
        if ratio > 40.0:
            raise SceneParamError(
                f"zoom ratio {ratio:.0f}x: no framing holds both ends of this "
                "replay; degrade to the two-panel compare")
        p["_zoom_max"] = zoom_max

        p["title"] = str(p.get("title") or "Your steps, replayed")
        p["hint"] = check_hint(p.get("hint") or "watch where this lands")
        p["student_label"] = str(p.get("student_label") or "YOUR WORK")
        p["leak_guard"] = [str(x) for x in (p.get("leak_guard") or [])]

        cls._fit_budget(p["steps"])
        return p

    # ------------------------------------------------------------------
    @staticmethod
    def _peek_scalar(arg, scope, p) -> float:
        if _is_number(arg):
            return parse_num(arg)
        for st in (p.get("steps") or []):
            if st.get("bind") == arg:
                return float(parse_num((st.get("result") or {}).get("value", 1)))
        g = (p.get("givens") or {}).get(arg) or {}
        return float(parse_num(g.get("value", 1)))

    @staticmethod
    def _elide(steps: list[dict]) -> list[dict]:
        """Past MAX_LEDGER_LINES the rail overflows, so a long run of ``ok``
        steps in the middle collapses behind one honest ledger line.  The
        first wrong step and everything after it is NEVER elided."""
        if len(steps) <= MAX_LEDGER_LINES:
            return steps
        wrong_at = next((i for i, s in enumerate(steps) if s["first_wrong"]),
                        len(steps) - 1)
        keep = {0, len(steps) - 1, wrong_at}
        keep.update(range(wrong_at, len(steps)))
        droppable = [i for i in range(len(steps))
                     if i not in keep and steps[i]["status"] == "ok"]
        n_drop = len(steps) - MAX_LEDGER_LINES + 1
        dropped = set(droppable[:max(0, n_drop)])
        if not dropped:
            return steps
        out: list[dict] = []
        placed = False
        for i, s in enumerate(steps):
            if i in dropped:
                if not placed:
                    out.append({
                        "id": "elide", "student_label": "", "kind": "elision",
                        "expr": f"...{len(dropped)} more steps checked",
                        "args": {}, "result": {"kind": "scalar", "value": 0,
                                               "display": ""},
                        "status": "unchecked", "first_wrong": False,
                        "run_time": 0.45, "invariant": None, "divergence": None,
                    })
                    placed = True
                continue
            out.append(s)
        return out

    @staticmethod
    def _fit_budget(steps: list[dict]) -> None:
        """Target 12-18s, hard ceiling 20s.  The first wrong step's beat is
        NEVER compressed -- it is the only beat the video exists for."""
        fixed = 1.5 + 1.2 + 1.8 + 0.55 * len(steps)
        wrong = sum(s["run_time"] for s in steps if s["first_wrong"])
        rest_steps = [s for s in steps if not s["first_wrong"]]
        rest = sum(s["run_time"] for s in rest_steps)
        if fixed + wrong + rest <= BUDGET:
            return
        avail = BUDGET - fixed - wrong
        if rest > 1e-6 and avail > 0:
            scale = avail / rest
            for s in rest_steps:
                s["run_time"] = max(RT_FLOOR, s["run_time"] * scale)
        for s in rest_steps:
            if s["kind"] in LEDGER_ONLY_KINDS:
                s["run_time"] = min(s["run_time"], 0.3)

    # ==================================================================
    # Scene
    # ==================================================================
    def build_scene(self, p: dict) -> None:
        c = p["canvas"]
        self.BOX = np.array([float(c["box"][0]), float(c["box"][1])])
        bc = list(c.get("box_center", BOX_C_D))
        self.BOXC = np.array([float(bc[0]), float(bc[1]), 0.0])
        self.PAD = float(c.get("pad", PAD_D))
        self.MARGIN = float(c.get("margin", MARGIN_D))
        self.ZMAX = float(p.get("_zoom_max", c.get("zoom_max", ZOOM_MAX_D)))

        steps: list[dict] = p["steps"]
        givens: dict = p["givens"]

        self.regs: dict[str, Reg] = {}
        self.live: list[Live] = []
        self.transient = VGroup()
        self._extra: list = []
        self._frame_target: tuple[float, np.ndarray] | None = None

        # -- solve the framing ------------------------------------------
        gpts = [np.array(g["value"], float) for g in givens.values()
                if g["kind"] == "vector"]
        spts = [np.array(s["result"]["value"], float) for s in steps
                if s["result"]["kind"] == "vector"]
        u_end, _o_end = self._frame(gpts + spts)
        u0, o0 = self._frame(gpts or spts)
        if u0 > self.ZMAX * u_end:
            u0, o0 = self._frame(gpts or spts, cap=self.ZMAX * u_end)

        # The grid step and radius are FIXED for the whole scene: changing
        # either alters the plane's submobject count, and Transform then
        # null-pads, which looks like grid lines being born at a point.
        self.gstep = 1 if (self.BOX[0] / max(u_end, 1e-6)) <= 24 else 2
        self.radius = int(min(26, max(4, math.ceil(
            (max(self.BOX[0], self.BOX[1]) / 2 + 1.6) / max(u_end, 1e-6)))))
        cells_a = self.BOX[0] / max(u0 * self.gstep, 1e-6)
        cells_b = self.BOX[0] / max(u_end * self.gstep, 1e-6)
        self.gw, self.go = lattice_weight(math.sqrt(max(cells_a, 1.0)
                                                    * max(cells_b, 1.0)))

        # Per-step frames with hysteresis: re-frame only when the unit has to
        # drop by more than 12%, or the canvas breathes on every step and the
        # viewer loses the thread.
        seq: list[tuple[float, np.ndarray] | None] = []
        visited = list(gpts)
        u_cur = u0
        for st in steps:
            if st["result"]["kind"] == "vector":
                visited.append(np.array(st["result"]["value"], float))
                if st["kind"] == "scale_vector":
                    pass
            ui, oi = self._frame(visited or gpts)
            ui = min(ui, u_cur)
            if ui < HYST * u_cur:
                seq.append((ui, oi))
                u_cur = ui
            else:
                seq.append(None)

        self.unit, self.origin = u0, o0

        # -- chrome -----------------------------------------------------
        self.box_rect = Rectangle(width=self.BOX[0],
                                  height=self.BOX[1]).move_to(self.BOXC)
        matte = panel_matte(self.box_rect).set_z_index(Z_MATTE)
        border = (self.box_rect.copy()
                  .set_stroke(GHOST, 2.6, opacity=0.5).set_z_index(Z_BORDER))
        self.add(matte, border)

        self.plane = self._plane_at(u0, o0)
        self.add(self.plane)

        title = title_text(p["title"])
        head = T(p["student_label"], font_size=19, color=GHOST, weight="BOLD")
        head.move_to(np.array([TEXT_X + head.width / 2, 2.86, 0.0]))
        head.set_z_index(Z_CHROME)
        rule = Line(np.array([LEDGER_L, 2.70, 0.0]),
                    np.array([LEDGER_R, 2.70, 0.0]),
                    stroke_width=1.6, color=GHOST).set_stroke(opacity=0.55)
        rule.set_z_index(Z_CHROME)
        self.add(head, rule)

        self.ledger = self._build_ledger(steps)

        # -- B1: the givens --------------------------------------------
        first = True
        for i, (name, g) in enumerate(givens.items()):
            if g["kind"] != "vector":
                self._seed_matrix(name, g)
                continue
            if any(s.get("bind") == name and s["kind"] == "define_vector"
                   for s in steps):
                continue
            color = PALETTE.get(str(g.get("color") or ""), ROTA[i % len(ROTA)])
            reg = self._new_vector(name, np.array(g["value"], float), color,
                                   label=str(g.get("label") or name))
            anims = [GrowArrow(reg.mob), FadeIn(reg.label_mob)]
            if first:
                anims.append(Write(title))
                first = False
            self.play(*anims, run_time=0.62)
        if first:
            self.play(Write(title), run_time=0.6)
        self.wait(0.28)

        # -- the replay -------------------------------------------------
        for i, st in enumerate(steps):
            self._play_step(i, st, seq[i])

        # -- hint, then hold --------------------------------------------
        hint = hint_text(p["hint"])
        hint.set_z_index(Z_CHROME)
        self.play(Write(hint), run_time=1.0)
        self.wait(1.7)

    # ------------------------------------------------------------------
    # Framing
    # ------------------------------------------------------------------
    def _frame(self, points, cap: float | None = None):
        return _frame_for(points, self.BOX, self.BOXC[:2], self.PAD,
                          self.MARGIN, cap=cap)

    def _plane_at(self, unit: float, org: np.ndarray):
        pl = make_plane(org, radius=self.radius, radius_y=self.radius,
                        unit=unit, step=self.gstep, stroke_width=self.gw,
                        stroke_opacity=self.go)
        pl.set_z_index(Z_PLANE)
        return pl

    def pt(self, vec, unit=None, origin=None) -> np.ndarray:
        u = self.unit if unit is None else unit
        o = self.origin if origin is None else origin
        v = np.asarray(vec, float).flatten()
        return o + u * np.array([float(v[0]), float(v[1]), 0.0])

    def _reframe_pack(self, exclude: Sequence[VMobject] = ()):
        tgt = self._frame_target
        if tgt is None:
            return [], (lambda: None)
        u, o = tgt
        ex = [id(m) for m in exclude]
        anims: list = [Transform(self.plane, self._plane_at(u, o))]
        for lv in self.live:
            m = lv.get()
            if m is None or id(m) in ex:
                continue
            try:
                anims.append(Transform(m, lv.build(u, o)))
            except Exception:  # noqa: BLE001
                pass

        def commit() -> None:
            self.unit, self.origin = u, o
            self._frame_target = None
        return anims, commit

    def _play1(self, anims, run_time: float,
               exclude: Sequence[VMobject] = ()) -> None:
        """The step's ACTION beat.  The pending re-frame is folded in HERE and
        nowhere else, so the frame chases the arrow as it shoots out -- which
        is the drama.  A separate "and now we zoom out" beat throws it away."""
        pack, commit = self._reframe_pack(exclude)
        a = [x for x in anims if x is not None] + pack + self._extra
        self._extra = []
        if a:
            self.play(*a, run_time=max(0.12, run_time))
        else:
            self.wait(max(0.12, run_time))
        commit()

    def _beat(self, anims, run_time: float) -> None:
        """A supporting beat (ledger line, invariant, setup).  Drains the
        pending fades but NEVER the re-frame -- an invariant that quietly ate
        the zoom is exactly how the hero step loses its punch."""
        a = [x for x in anims if x is not None] + self._extra
        self._extra = []
        if a:
            self.play(*a, run_time=max(0.12, run_time))
        else:
            self.wait(max(0.12, run_time))

    # ------------------------------------------------------------------
    # Registers and their mobjects
    # ------------------------------------------------------------------
    def _color(self, name, fallback=CORRECT) -> str:
        return PALETTE.get(str(name or "").lower(), fallback)

    def _arrow(self, vec, color, sw: float = 9.0, unit=None, origin=None):
        u = self.unit if unit is None else unit
        o = self.origin if origin is None else origin
        m = arrow_at(o, vec, color, unit=u, stroke_width=sw)
        m.set_z_index(Z_GEO)
        return m

    def _label_at(self, text: str, vec, color, unit=None, origin=None):
        u = self.unit if unit is None else unit
        o = self.origin if origin is None else origin
        t = T(str(text), font_size=FS_LABEL, color=color, weight="BOLD")
        v = np.asarray(vec, float).flatten()
        d = np.array([float(v[0]), float(v[1]), 0.0])
        n = float(np.linalg.norm(d))
        d = d / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        perp = np.array([-d[1], d[0], 0.0])
        tip = o + u * np.array([float(v[0]), float(v[1]), 0.0])
        others = [lv.get() for lv in self.live]
        tips = [m.get_end() for m in others
                if isinstance(m, Arrow)]
        best, best_score = None, -1e9
        for s in (1.0, -1.0):
            cand = tip + 0.22 * d + (0.40 + 0.45 * t.width) * perp * s
            score = min([float(np.linalg.norm(cand - q)) for q in tips]
                        + [float(np.linalg.norm(cand - o))])
            if score > best_score:
                best, best_score = cand, score
        t.move_to(self._clamp_in_box(best, t))
        t.set_z_index(Z_GEO)
        return t

    def _clamp_in_box(self, pos: np.ndarray, mob: VMobject) -> np.ndarray:
        hw, hh = self.BOX[0] / 2 - 0.22, self.BOX[1] / 2 - 0.20
        x = float(np.clip(pos[0], self.BOXC[0] - hw + mob.width / 2,
                          self.BOXC[0] + hw - mob.width / 2))
        y = float(np.clip(pos[1], self.BOXC[1] - hh + mob.height / 2,
                          self.BOXC[1] + hh - mob.height / 2))
        return np.array([x, y, 0.0])

    def _new_vector(self, sym: str, value, color: str, label: str | None = None,
                    sw: float = 9.0, add: bool = True) -> Reg:
        value = np.asarray(value, float).flatten()[:2]
        lab = label if label is not None else sym
        reg = Reg(value=value, display=f"({fmt_num(value[0])}, "
                                       f"{fmt_num(value[1])})",
                  color=color, label=lab, kind="vector", stroke_width=sw)
        reg.mob = self._arrow(value, color, sw=sw)
        reg.label_mob = self._label_at(lab, value, color)
        self.regs[sym] = reg
        self.live.append(Live(
            (lambda r=reg: r.mob),
            (lambda u, o, r=reg: arrow_at(o, r.value, r.color, unit=u,
                                          stroke_width=r.stroke_width)
             .set_z_index(Z_GEO))))
        self.live.append(Live(
            (lambda r=reg: r.label_mob),
            (lambda u, o, r=reg: self._label_at(r.label, r.value, r.color,
                                                unit=u, origin=o))))
        if add:
            self.add(reg.mob, reg.label_mob)
        return reg

    def _seed_matrix(self, sym: str, g: dict) -> None:
        M = np.array(g["value"], float)
        self.regs[sym] = Reg(value=M, display=str(g.get("display") or ""),
                             mob=None, color=CORRECT, label=sym, kind="matrix")

    def _reg(self, name) -> Reg | None:
        if isinstance(name, str) and name in self.regs:
            return self.regs[name]
        return None

    def _vecval(self, name) -> np.ndarray | None:
        r = self._reg(name)
        if r is not None and r.kind == "vector":
            return np.asarray(r.value, float).flatten()[:2]
        return None

    def _scalar(self, arg, default: float = 1.0) -> float:
        r = self._reg(arg)
        if r is not None and r.kind == "scalar":
            return float(r.value)
        if _is_number(arg):
            return float(parse_num(arg))
        return float(default)

    def _res_vec(self, st) -> np.ndarray:
        return np.asarray(st["result"]["value"], float).flatten()[:2]

    def _track_overlay(self, mob, build) -> None:
        """Register a panel-coordinate overlay so a later re-frame moves it."""
        holder = [mob]
        self.live.append(Live((lambda h=holder: h[0]),
                              (lambda u, o, b=build: b(u, o))))

    # ------------------------------------------------------------------
    # The ledger rail
    # ------------------------------------------------------------------
    def _build_ledger(self, steps: list[dict]) -> list[dict]:
        rows: list[dict] = []
        width = LEDGER_R - TEXT_X
        y = LEDGER_TOP
        for i, st in enumerate(steps):
            dim = st["status"] in ("unchecked", "crossed_out")
            col = GHOST if dim else CORRECT
            num_s = st.get("student_label") or ""
            num = (T(num_s, font_size=FS_LEDGER_NUM, color=GHOST)
                   if num_s else None)
            nw = (num.width + 0.14) if num is not None else 0.0

            expr = str(st.get("expr") or "")
            head_s, tail_s = expr, ""
            if st["first_wrong"] and "=" in expr:
                j = expr.rfind("=")
                if 6 <= j < len(expr) - 1:
                    head_s, tail_s = expr[:j].strip(), expr[j:].strip()

            head = _left_align(label_text(head_s or " ", font_size=FS_LEDGER,
                                          color=col,
                                          max_width=max(0.8, width - nw),
                                          max_lines=2))
            grp = VGroup()
            if num is not None:
                grp.add(num)
            grp.add(head)
            if num is not None:
                head.next_to(num, np.array([1.0, 0.0, 0.0]), buff=0.14)
                head.align_to(num, UP)
            grp.align_to(np.array([TEXT_X, 0.0, 0.0]), LEFT)
            grp.shift(np.array([0.0, y - grp.get_top()[1], 0.0]))
            grp.set_z_index(Z_CHROME)
            y = grp.get_bottom()[1] - LEDGER_GAP

            tail = None
            if tail_s:
                tail = label_text(tail_s, font_size=FS_LEDGER, color=STUDENT,
                                  max_width=max(0.8, width - 0.45), max_lines=1)
                tail.align_to(np.array([TEXT_X + 0.45, 0.0, 0.0]), LEFT)
                tail.shift(np.array([0.0, y - tail.get_top()[1], 0.0]))
                tail.set_z_index(Z_CHROME)
                y = tail.get_bottom()[1] - LEDGER_GAP

            rows.append({"group": grp, "head": head, "tail": tail,
                         "mark_y": float(grp[0].get_center()[1]),
                         "dim": dim})
        return rows

    def _mark(self, kind: str, y: float) -> VMobject:
        if kind == "tick":
            pts = [np.array([-0.10, 0.01, 0.0]), np.array([-0.025, -0.085, 0.0]),
                   np.array([0.12, 0.11, 0.0])]
            col = CORRECT
        else:
            pts = [np.array([-0.10, -0.05, 0.0]), np.array([0.0, 0.09, 0.0]),
                   np.array([0.10, -0.05, 0.0])]
            col = STUDENT
        m = VMobject(stroke_color=col, stroke_width=4.2)
        m.set_points_as_corners([p + np.array([MARK_X, y, 0.0]) for p in pts])
        m.set_z_index(Z_CHROME)
        return m

    # ------------------------------------------------------------------
    # Step driver
    # ------------------------------------------------------------------
    def _play_step(self, i: int, st: dict, frame) -> None:
        row = self.ledger[i]
        self._frame_target = frame

        # The previous step's working (component segments, the arithmetic
        # strip, a caption) clears as this step's line types in. Left up, it
        # is stale panel geometry that the next re-frame would strand.
        if len(self.transient):
            self._extra.append(FadeOut(self.transient))
            self.transient = VGroup()

        # 1. the student's own line types into the rail, in their own numbering
        self._beat([Write(row["group"])], 0.62)

        # 2. the invariant goes up BEFORE the claim lands (section 6)
        if st.get("invariant"):
            self._invariant(st["invariant"])

        # 3. the action
        kind = st["kind"]
        handler = getattr(self, "_k_" + kind, None)
        if handler is None or kind in LEDGER_ONLY_KINDS:
            handler = self._k_ledger_only
        try:
            handler(st)
        except Exception as exc:  # noqa: BLE001
            # An unknown or malformed step shows its written line and holds.
            # It never takes the video down with it.
            print(f"[StepReplay] step {i} ({kind}) degraded: {exc}")
            self._k_ledger_only(st)
        if self._frame_target is not None:
            # A handler that never got to its action beat still owes the
            # canvas its re-frame, or the next step draws at a stale scale.
            self._play1([], 0.7)

        # 4. mark it -- correct steps must VISIBLY check out, which is what
        #    makes the wrong one mean something and what proves the app read
        #    the work rather than pattern-matching a template.
        if st["first_wrong"]:
            anims = [row["group"].animate.set_color(STUDENT)]
            if row["tail"] is not None:
                anims.append(FadeIn(row["tail"]))
            self.play(*anims, run_time=0.4)
            self.play(Create(self._mark("caret", row["mark_y"])), run_time=0.3)
            self._divergence(st)
        elif st["status"] == "ok":
            self.play(Create(self._mark("tick", row["mark_y"])), run_time=0.35)
        else:
            self.wait(0.12)

    # ------------------------------------------------------------------
    # Invariants -- a REGION or a PROPERTY, never a point.
    # Every field is *_of and names a symbol already on the canvas, so the
    # region constrains the answer without ever being the answer.
    # ------------------------------------------------------------------
    def _invariant(self, inv: dict) -> None:
        kind = str(inv.get("kind") or "disc")
        mobs = VGroup()
        if kind in ("disc", "circle"):
            sym = inv.get("radius_of")
            v = self._vecval(sym)
            r = float(np.linalg.norm(v)) if v is not None else 1.0

            def build_disc(u, o, r=r):
                c = Circle(radius=max(0.05, r * u), color=PROBE,
                           stroke_width=2.8).move_to(o)
                c.set_stroke(opacity=0.9)
                c.set_fill(PROBE, opacity=0.10)
                # Under the arrows, above the grid: a REGION, not an overlay.
                c.set_z_index(Z_GEO - 3)
                return c
            disc = build_disc(self.unit, self.origin)
            self._track_overlay(disc, build_disc)
            mobs.add(disc)
        elif kind == "unit_circle":
            def build_unit(u, o):
                c = Circle(radius=max(0.05, u), color=PROBE, stroke_width=2.8)
                c.move_to(o).set_stroke(opacity=0.9)
                c.set_z_index(Z_GEO)
                return c
            uc = build_unit(self.unit, self.origin)
            self._track_overlay(uc, build_unit)
            mobs.add(uc)
        elif kind == "line":
            v = self._vecval(inv.get("along_of") or inv.get("radius_of"))
            if v is not None:
                ln = self._span(v)
                mobs.add(ln)
        cap_mob = None
        if inv.get("caption"):
            cap_mob = label_text(str(inv["caption"]), font_size=FS_CAPTION,
                                 color=PROBE,
                                 max_width=self.BOX[0] - 1.0, max_lines=2)
            cap_mob.move_to(np.array([self.BOXC[0],
                                      self.BOXC[1] - self.BOX[1] / 2 + 0.40,
                                      0.0]))
            cap_mob.set_z_index(Z_GEO)
            self.transient.add(cap_mob)
        # DrawBorderThenFill, not Create: Create on a FILLED shape reveals the
        # fill in step with the partial stroke, which draws the half-finished
        # disc as an ugly wedge.
        anims = [(DrawBorderThenFill(m) if m.get_fill_opacity() > 0
                  else Create(m)) for m in mobs]
        if cap_mob is not None:
            anims.append(FadeIn(cap_mob))
        if anims:
            # Deliberately NOT _play1: the viewer is shown the target zone
            # first, with nothing moving, so the miss means something.
            self._beat(anims, 1.0)
            self.wait(0.25)

    def _span(self, vec, color=GHOST):
        def build(u, o, v=np.array(vec, float)):
            p = _FakePanel(o, u)
            ln = span_line(p, v, color=color, dashed=True,
                           reach=max(self.BOX) * 1.3)
            ln.set_z_index(Z_GEO - 1)
            return ln
        ln = build(self.unit, self.origin)
        self._track_overlay(ln, build)
        return ln

    # ==================================================================
    # Step kinds
    # ==================================================================

    # -- ledger only: no geometry, and it SAYS so ----------------------
    def _k_ledger_only(self, st: dict) -> None:
        row_rt = max(0.3, float(st.get("run_time", 0.5)))
        self._play1([], row_rt)

    # -- define_vector -------------------------------------------------
    def _k_define_vector(self, st: dict) -> None:
        sym = str(st.get("bind") or st["args"].get("v") or "v")
        val = self._res_vec(st)
        idx = len([r for r in self.regs.values() if r.kind == "vector"])
        color = self._color(st.get("color"), ROTA[idx % len(ROTA)])
        reg = self._new_vector(sym, val, color,
                               label=str(st.get("label") or sym), add=False)
        anims = [GrowArrow(reg.mob), FadeIn(reg.label_mob)]
        ghost = None
        if st["first_wrong"] and st.get("given_value") is not None:
            # The ONE kind allowed a second arrow: the problem statement is
            # public, so the printed given is not the answer.
            g = _vec2(st["given_value"], "given_value")
            ghost = self._arrow(g, GHOST, sw=6.0)
            anims.append(GrowArrow(ghost))
            self._track_overlay(ghost, lambda u, o, g=g: self._arrow(
                g, GHOST, sw=6.0, unit=u, origin=o))
        self._play1(anims, float(st["run_time"]))

    # -- define_matrix -------------------------------------------------
    def _k_define_matrix(self, st: dict) -> None:
        sym = str(st.get("bind") or "A")
        rows = st.get("rows") or st["result"]["value"]
        M = as_matrix(rows, name=f"{sym}")
        self.regs[sym] = Reg(value=M, display="", mob=None, color=CORRECT,
                             label=sym, kind="matrix")
        tm = TextMatrix([[fmt_num(x) for x in r] for r in M.tolist()],
                        font_size=22, color=CORRECT)
        tm.move_to(np.array([(TEXT_X + LEDGER_R) / 2,
                             self.ledger[-1]["group"].get_bottom()[1] - 0.6,
                             0.0]))
        tm.set_z_index(Z_CHROME)
        # No grid action: a matrix is a MAP, so the plane pulses once to say
        # "this will act on this grid", and nothing moves yet.
        self._play1([FadeIn(tm),
                     self.plane.animate.set_stroke(opacity=min(
                         1.0, self.go * 1.7))],
                    float(st["run_time"]) * 0.6)
        self.play(self.plane.animate.set_stroke(opacity=self.go),
                  run_time=float(st["run_time"]) * 0.4)

    # -- dot_product ---------------------------------------------------
    def _k_dot_product(self, st: dict) -> None:
        """COMPONENT DECOMPOSITION, deliberately not the projection picture.

        THE TRAP: the textbook rendering of a dot product is "drop a
        perpendicular from u to v's line and multiply the foot's length by
        |v|" -- and in a projection problem that foot IS the correct final
        answer.  Drawing it would leak the answer out of a step that was
        RIGHT.  So this beat does arithmetic on the axes and never draws a
        perpendicular.  General rule: a correct step must still be replayed
        without drawing any construction that gives away a later step's
        answer.
        """
        u_sym = st["args"].get("u")
        v_sym = st["args"].get("v")
        U = self._vecval(u_sym)
        V = self._vecval(v_sym)
        if U is None or V is None:
            raise SceneParamError("dot_product needs two vector registers")
        ru, rv = self.regs[u_sym], self.regs[v_sym]
        claimed = float(parse_num(st["result"]["value"]))
        terms = [float(U[0] * V[0]), float(U[1] * V[1])]
        tdisp = list(st.get("terms") or [])
        if len(tdisp) != 2:
            tdisp = [f"{fmt_num(U[j])}({fmt_num(V[j])})" for j in (0, 1)]
        cap = float(np.linalg.norm(U) * np.linalg.norm(V))
        rt = float(st["run_time"])

        # --- components lit up on the axes (never a perpendicular) ----
        def comps(vec, color):
            g = VGroup()
            o = self.origin
            px = o + self.unit * np.array([float(vec[0]), 0.0, 0.0])
            py = px + self.unit * np.array([0.0, float(vec[1]), 0.0])
            for a, b, val in ((o, px, vec[0]), (px, py, vec[1])):
                if float(np.linalg.norm(b - a)) < 0.04:
                    continue
                ln = Line(a, b, color=color, stroke_width=7.0)
                ln.set_stroke(opacity=0.95)
                ln.set_z_index(Z_GEO)
                t = T(fmt_num(val), font_size=22, color=color)
                d = b - a
                perp = np.array([-d[1], d[0], 0.0])
                n = float(np.linalg.norm(perp))
                perp = perp / n if n > 1e-9 else np.array([0.0, 1.0, 0.0])
                t.move_to(self._clamp_in_box(
                    (a + b) / 2 + 0.30 * perp * (-1 if d[0] != 0 else 1), t))
                t.set_z_index(Z_GEO)
                g.add(ln, t)
            return g

        gu, gv = comps(U, ru.color), comps(V, rv.color)
        self.transient.add(gu, gv)
        self._play1([Create(gu)], min(0.65, rt * 0.26))
        self.play(Create(gv), run_time=min(0.55, rt * 0.22))

        # --- the arithmetic strip -------------------------------------
        reach = max(abs(cap), abs(claimed), abs(terms[0]) + abs(terms[1]), 1e-6)
        bu = BAR_LEN / reach
        x0 = self.BOXC[0] - self.BOX[0] / 2 + 0.52
        base = self.BOXC[1] - self.BOX[1] / 2 + 0.40
        y_track, y_terms, y_sum = base + 0.74, base + 0.38, base

        backing = Rectangle(width=BAR_LEN + 1.9, height=1.34)
        backing.move_to(np.array([x0 + (BAR_LEN + 1.9) / 2 - 0.16,
                                  base + 0.36, 0.0]))
        backing.set_fill("#000000", opacity=0.72).set_stroke(width=0)
        backing.set_z_index(Z_GEO - 3)

        track = VGroup()
        tl = Line(np.array([x0, y_track, 0.0]),
                  np.array([x0 + cap * bu, y_track, 0.0]),
                  color=GHOST, stroke_width=3.0)
        for x in (x0, x0 + cap * bu):
            track.add(Line(np.array([x, y_track - 0.11, 0.0]),
                           np.array([x, y_track + 0.11, 0.0]),
                           color=GHOST, stroke_width=3.0))
        track.add(tl)
        tlab = T(f"|{u_sym}||{v_sym}|", font_size=20, color=GHOST)
        tlab.move_to(np.array([x0 + cap * bu + 0.16 + tlab.width / 2,
                               y_track, 0.0]))
        track.add(tlab)
        track.set_z_index(Z_GEO)

        bars = VGroup()
        cursor = x0
        for j, (tv, td) in enumerate(zip(terms, tdisp)):
            w = max(0.03, abs(tv) * bu)
            col = I_HAT if j == 0 else J_HAT
            r = Rectangle(width=w, height=BAR_H)
            r.set_fill(col, opacity=0.92).set_stroke(col, 1.4)
            r.move_to(np.array([cursor + w / 2, y_terms, 0.0]))
            lab = T(td, font_size=19, color=col)
            lab.move_to(np.array([cursor + w / 2, y_terms + 0.30, 0.0]))
            bars.add(r, lab)
            cursor += w
        bars.set_z_index(Z_GEO)
        end_tick = DashedLine(np.array([cursor, y_terms - 0.16, 0.0]),
                              np.array([cursor, y_sum - 0.20, 0.0]),
                              color=GHOST, stroke_width=2.4, dash_length=0.08)
        end_tick.set_z_index(Z_GEO)

        sum_w = max(0.03, abs(claimed) * bu)
        sum_col = CORRECT if st["status"] == "ok" else STUDENT
        sbar = Rectangle(width=sum_w, height=BAR_H)
        sbar.set_fill(sum_col, opacity=0.95).set_stroke(sum_col, 1.4)
        sbar.move_to(np.array([x0 + sum_w / 2, y_sum, 0.0]))
        slab = T(str(st["result"].get("display") or fmt_num(claimed)),
                 font_size=22, color=sum_col)
        slab.move_to(np.array([x0 + sum_w + 0.16 + slab.width / 2, y_sum, 0.0]))
        for m in (sbar, slab):
            m.set_z_index(Z_GEO)

        self.transient.add(backing, track, bars, end_tick, sbar, slab)
        self.play(FadeIn(backing), Create(track), run_time=min(0.4, rt * 0.16))
        self.play(LaggedStart(*[GrowFromEdge(bars[k], LEFT)
                                for k in (0, 2)], lag_ratio=0.45),
                  FadeIn(bars[1]), FadeIn(bars[3]),
                  run_time=max(0.45, rt * 0.24))
        self.play(GrowFromEdge(sbar, LEFT), Create(end_tick), FadeIn(slab),
                  run_time=max(0.45, rt * 0.22))

        bind = st.get("bind")
        if bind:
            self.regs[str(bind)] = Reg(value=claimed, kind="scalar",
                                       display=str(st["result"].get("display")
                                                   or fmt_num(claimed)),
                                       color=sum_col, label=str(bind))
        self.wait(0.2)

    # -- scale_vector: THE HERO ACTION ---------------------------------
    def _k_scale_vector(self, st: dict) -> None:
        """|k| ghost copies of v laid END TO END along v's line while the live
        arrow stretches to follow them.  Built from nothing but the student's
        own k.  Nothing about the ACTION is wrong -- the action is what makes
        it wrong: the tiles march straight out of the invariant region and the
        world has to shrink to contain the answer."""
        v_sym = st["args"].get("v")
        V = self._vecval(v_sym)
        if V is None:
            raise SceneParamError("scale_vector needs a vector register")
        src = self.regs[v_sym]
        k = self._scalar(st["args"].get("k"), 1.0)
        RES = self._res_vec(st)
        rt = float(st["run_time"])
        k_disp = str(st.get("k_display")
                     or (self._reg(st["args"].get("k")).display
                         if self._reg(st["args"].get("k")) else fmt_num(k)))
        new_label = str(st.get("result_label") or f"{k_disp}{v_sym}")

        u0_, o0_ = self.unit, self.origin
        u1_, o1_ = self._frame_target if self._frame_target else (u0_, o0_)

        self._span(V)                      # v's line: the tiles' track

        # Trackers.  zs is synced with the plane Transform (both default to
        # rate_func=smooth over the same run_time), so the analytic frame
        # below is EXACTLY where the interpolated plane is at every frame.
        zs, lt = ValueTracker(0.0), ValueTracker(0.0)

        def cur():
            s = float(zs.get_value())
            return (1 - s) * u0_ + s * u1_, (1 - s) * o0_ + s * o1_

        sgn = 1.0 if k >= 0 else -1.0
        mag = abs(k)
        n_tiles = int(math.ceil(mag - 1e-6))
        ellipsis = n_tiles > 8
        show = [0, 1, 2] if ellipsis else list(range(max(0, n_tiles)))

        def tile_span(j, u, o):
            f0, f1 = float(j), min(float(j + 1), mag)
            p0 = o + u * np.array([sgn * f0 * V[0], sgn * f0 * V[1], 0.0])
            p1 = o + u * np.array([sgn * f1 * V[0], sgn * f1 * V[1], 0.0])
            return p0, p1

        def make_tile(j):
            def build(j=j):
                u, o = cur()
                p0, p1 = tile_span(j, u, o)
                coef = abs(1.0 + (k - 1.0) * float(lt.get_value()))
                alpha = float(np.clip((coef - j) / 0.22, 0.0, 1.0))
                if float(np.linalg.norm(p1 - p0)) < 0.05:
                    p1 = p0 + np.array([0.05, 0.0, 0.0])
                m = Arrow(p0, p1, buff=0, color=GHOST, stroke_width=4.6,
                          max_tip_length_to_length_ratio=0.3,
                          max_stroke_width_to_length_ratio=16)
                m.set_opacity(0.85 * alpha)
                m.set_z_index(Z_GEO - 2)
                return m
            return always_redraw(build)

        tiles = [make_tile(j) for j in show]

        def build_live():
            u, o = cur()
            coef = 1.0 + (k - 1.0) * float(lt.get_value())
            m = arrow_at(o, coef * V, STUDENT, unit=u, stroke_width=10.0)
            m.set_z_index(Z_GEO)
            return m

        old_arrow, old_label = src.mob, src.label_mob
        if old_arrow is not None:
            self.remove(old_arrow)
        live = always_redraw(build_live)
        self.add(live, *tiles)

        anims = [zs.animate.set_value(1.0), lt.animate.set_value(1.0)]
        if old_label is not None:
            # play() forces one run_time on every animation, so the old
            # caption is retired with a rate_func instead -- left to linger it
            # drifts, unanchored, while the frame moves underneath it.
            anims.append(FadeOut(old_label, rate_func=_rush_out))
        excl = [m for m in (old_arrow, old_label) if m is not None]
        self._play1(anims, rt, exclude=excl)

        # Freeze: swap the updater mobjects for static ones at the final
        # frame, so later beats (and later re-frames) have something solid.
        u1_, o1_ = self.unit, self.origin
        final = arrow_at(o1_, RES, STUDENT, unit=u1_, stroke_width=10.0)
        final.set_z_index(Z_GEO)
        statics = VGroup()
        for j in show:
            p0, p1 = tile_span(j, u1_, o1_)
            if float(np.linalg.norm(p1 - p0)) < 0.05:
                continue
            m = Arrow(p0, p1, buff=0, color=GHOST, stroke_width=4.6,
                      max_tip_length_to_length_ratio=0.3,
                      max_stroke_width_to_length_ratio=16)
            m.set_opacity(0.85)
            m.set_z_index(Z_GEO - 2)
            statics.add(m)
        if ellipsis:
            p0, _ = tile_span(3, u1_, o1_)
            e = T("...", font_size=26, color=GHOST).move_to(p0)
            e.set_z_index(Z_GEO - 2)
            statics.add(e)
        self.remove(live, *tiles)
        self.add(final, statics)
        self._track_overlay(statics, lambda u, o: statics)

        src.mob, src.label_mob = None, None
        bind = str(st.get("bind") or v_sym)
        reg = Reg(value=RES, kind="vector", color=STUDENT, label=new_label,
                  display=str(st["result"].get("display") or ""),
                  mob=final, stroke_width=10.0)
        reg.label_mob = self._label_at(new_label, RES, STUDENT)
        self.regs[bind] = reg
        self.live.append(Live(
            (lambda r=reg: r.mob),
            (lambda u, o, r=reg: arrow_at(o, r.value, r.color, unit=u,
                                          stroke_width=r.stroke_width)
             .set_z_index(Z_GEO))))
        self.live.append(Live(
            (lambda r=reg: r.label_mob),
            (lambda u, o, r=reg: self._label_at(r.label, r.value, r.color,
                                                unit=u, origin=o))))
        self.play(FadeIn(reg.label_mob), run_time=0.45)

    # -- add_vectors ---------------------------------------------------
    def _k_add_vectors(self, st: dict) -> None:
        u_sym, v_sym = st["args"].get("u"), st["args"].get("v")
        U, V = self._vecval(u_sym), self._vecval(v_sym)
        if U is None or V is None:
            raise SceneParamError("add_vectors needs two vector registers")
        sign = str(st.get("sign") or ("-" if st.get("op") == "subtract" else "+"))
        RES = self._res_vec(st)
        rt = float(st["run_time"])
        rv = self.regs[v_sym]

        ghost = self._arrow(V, GHOST, sw=6.0)
        self.add(ghost)
        if sign == "-":
            # The sign change is ANIMATED, not assumed.
            self._play1([Rotate(ghost, angle=math.pi,
                                about_point=self.origin)], rt * 0.3)
            Vs = -V
        else:
            Vs = V
            self._play1([FadeIn(ghost)], max(0.2, rt * 0.16))

        tgt = Arrow(self.pt(U), self.pt(U + Vs), buff=0, color=GHOST,
                    stroke_width=6.0, max_tip_length_to_length_ratio=0.32,
                    max_stroke_width_to_length_ratio=16)
        tgt.set_z_index(Z_GEO)
        self.play(Transform(ghost, tgt), run_time=max(0.4, rt * 0.34))

        para = Polygon(self.origin, self.pt(U), self.pt(U + Vs), self.pt(Vs),
                       color=GHOST, stroke_width=2.0)
        para.set_stroke(opacity=0.55)
        para.set_z_index(Z_GEO - 2)
        bind = str(st.get("bind") or "r")
        reg = self._new_vector(bind, RES,
                               STUDENT if st["first_wrong"] else CORRECT,
                               label=str(st.get("result_label")
                                         or f"{u_sym}{sign}{v_sym}"), add=False)
        self.play(Create(para), GrowArrow(reg.mob), FadeIn(reg.label_mob),
                  run_time=max(0.5, rt * 0.5))
        self._track_overlay(para, lambda u, o: para)
        self._track_overlay(ghost, lambda u, o: ghost)
        _ = rv

    # -- matrix_apply --------------------------------------------------
    def _k_matrix_apply(self, st: dict) -> None:
        """ApplyMatrix on the plane, Transform on every tracked arrow.
        about_point MUST be the panel origin, and arrows are never fed to
        ApplyMatrix or the tip shears into a bent wedge (RENDERING.md 5)."""
        m_sym, v_sym = st["args"].get("M"), st["args"].get("v")
        rm = self._reg(m_sym)
        if rm is None or rm.kind != "matrix":
            raise SceneParamError("matrix_apply needs a matrix register")
        M = np.asarray(rm.value, float)[:2, :2]
        V = self._vecval(v_sym)
        RES = self._res_vec(st)
        rt = float(st["run_time"])

        anims: list = [ApplyMatrix(M, self.plane, about_point=self.origin)]
        for sym, reg in list(self.regs.items()):
            if reg.kind != "vector" or reg.mob is None:
                continue
            new = RES if sym == v_sym else (M @ reg.value)
            col = STUDENT if (sym == v_sym and st["first_wrong"]) else reg.color
            anims.append(Transform(reg.mob,
                                   self._arrow(new, col, sw=reg.stroke_width)))
            if reg.label_mob is not None:
                anims.append(Transform(reg.label_mob,
                                       self._label_at(reg.label, new, col)))
            reg.value = np.asarray(new, float).flatten()[:2]
            reg.color = col
        self._play1(anims, rt)

        if V is not None:
            # The lattice is the witness: the grid carries the point under v
            # to one place, and it is the student's OWN M that put it there.
            landed = M @ V
            dot = Dot(self.pt(landed), radius=0.075, color=CORRECT)
            dot.set_z_index(Z_GEO)
            self._track_overlay(dot, lambda u, o, p=landed: Dot(
                self.pt(p, u, o), radius=0.075,
                color=CORRECT).set_z_index(Z_GEO))
            self.play(Create(dot), run_time=0.4)
        bind = st.get("bind")
        if bind and v_sym in self.regs:
            self.regs[str(bind)] = self.regs[v_sym]

    # -- matrix_product ------------------------------------------------
    def _k_matrix_product(self, st: dict) -> None:
        order = [str(x) for x in (st.get("order") or st.get("factors") or [])]
        mats = [np.asarray(self._reg(s).value, float)[:2, :2]
                for s in order if self._reg(s) is not None]
        if len(mats) < 2:
            raise SceneParamError("matrix_product needs two matrix registers")
        rt = float(st["run_time"]) / len(mats)
        for j, M in enumerate(mats):
            anims: list = [ApplyMatrix(M, self.plane, about_point=self.origin)]
            for reg in self.regs.values():
                if reg.kind != "vector" or reg.mob is None:
                    continue
                new = M @ reg.value
                anims.append(Transform(reg.mob,
                                       self._arrow(new, reg.color,
                                                   sw=reg.stroke_width)))
                if reg.label_mob is not None:
                    anims.append(Transform(reg.label_mob,
                                           self._label_at(reg.label, new,
                                                          reg.color)))
                reg.value = np.asarray(new, float).flatten()[:2]
            self._play1(anims, rt)
            if j == 0:
                self.wait(0.6)      # hold on the INTERMEDIATE state

    # -- normalize -----------------------------------------------------
    def _k_normalize(self, st: dict) -> None:
        v_sym = st["args"].get("v")
        V = self._vecval(v_sym)
        if V is None:
            raise SceneParamError("normalize needs a vector register")
        reg = self.regs[v_sym]
        RES = self._res_vec(st)
        circ = Circle(radius=self.unit, color=PROBE,
                      stroke_width=2.8).move_to(self.origin)
        circ.set_stroke(opacity=0.9)
        circ.set_z_index(Z_GEO)
        self._track_overlay(circ, lambda u, o: Circle(
            radius=u, color=PROBE, stroke_width=2.8).move_to(o)
            .set_stroke(opacity=0.9).set_z_index(Z_GEO))
        # The invariant FIRST, then the shrink toward it.
        self._beat([Create(circ)], 0.6)
        col = STUDENT if st["first_wrong"] else reg.color
        lbl = str(st.get("result_label") or f"{v_sym}-hat")
        anims = [Transform(reg.mob, self._arrow(RES, col, sw=reg.stroke_width))]
        if reg.label_mob is not None:
            anims.append(Transform(reg.label_mob,
                                   self._label_at(lbl, RES, col)))
        self.play(*anims, run_time=float(st["run_time"]))
        reg.value, reg.color, reg.label = RES, col, lbl
        if st.get("bind"):
            self.regs[str(st["bind"])] = reg

    # -- project -------------------------------------------------------
    def _k_project(self, st: dict) -> None:
        u_sym, v_sym = st["args"].get("u"), st["args"].get("v")
        U, V = self._vecval(u_sym), self._vecval(v_sym)
        if U is None or V is None:
            raise SceneParamError("project needs two vector registers")
        RES = self._res_vec(st)
        rt = float(st["run_time"])
        self._span(V)
        if not st.get("invariant"):
            r = float(np.linalg.norm(U))

            def build(u, o, r=r):
                c = Circle(radius=max(0.05, r * u), color=PROBE,
                           stroke_width=2.8).move_to(o)
                return c.set_stroke(opacity=0.9).set_z_index(Z_GEO)
            disc = build(self.unit, self.origin)
            self._track_overlay(disc, build)
            self._beat([Create(disc)], 0.7)
        bind = str(st.get("bind") or "p")
        reg = self._new_vector(bind, RES,
                               STUDENT if st["first_wrong"] else CORRECT,
                               label=str(st.get("result_label")
                                         or f"proj({u_sym})"), add=False)
        self._play1([GrowArrow(reg.mob), FadeIn(reg.label_mob)], rt)

    # -- row_op --------------------------------------------------------
    def _k_row_op(self, st: dict) -> None:
        eqs = st.get("equations") or []
        res_line = st.get("result_line")
        if len(eqs) < 2 or res_line is None:
            raise SceneParamError("row_op needs equations and a result line")

        def line_of(abc):
            a, b, cc = (float(parse_num(x)) for x in abc)
            d = np.array([b, -a])
            n = float(np.linalg.norm(d))
            if n < 1e-9:
                raise SceneParamError("degenerate row")
            d = d / n
            denom = a * a + b * b
            p = np.array([a * cc / denom, b * cc / denom])
            reach = max(self.BOX) * 1.4 / max(self.unit, 1e-6)
            ln = Line(self.pt(p - reach * d), self.pt(p + reach * d),
                      stroke_width=4.0)
            ln.set_z_index(Z_GEO)
            return ln
        l1 = line_of(eqs[0]).set_color(I_HAT)
        l2 = line_of(eqs[1]).set_color(J_HAT)
        A = np.array([[float(parse_num(eqs[0][0])), float(parse_num(eqs[0][1]))],
                      [float(parse_num(eqs[1][0])), float(parse_num(eqs[1][1]))]])
        bvec = np.array([float(parse_num(eqs[0][2])), float(parse_num(eqs[1][2]))])
        try:
            x = np.linalg.solve(A, bvec)
            ring = Circle(radius=0.22, color=PROBE,
                          stroke_width=3.2).move_to(self.pt(x))
            ring.set_z_index(Z_GEO)
        except np.linalg.LinAlgError:
            ring = VGroup()
        self._play1([Create(l1), Create(l2)], max(0.4, float(st["run_time"]) * 0.3))
        self.play(Create(ring), run_time=0.4)
        tgt = line_of(res_line).set_color(STUDENT if st["first_wrong"] else J_HAT)
        self.play(Transform(l2, tgt), run_time=max(0.6, float(st["run_time"]) * 0.6))

    # ==================================================================
    # Divergence -- three independent, escalating cues.
    # Cue 1 (the region is missed) is already on screen; it was drawn BEFORE
    # the claim landed and it does most of the work.
    # ==================================================================
    def _divergence(self, st: dict) -> None:
        d = st.get("divergence") or {}
        claim = (self._res_vec(st) if st["result"]["kind"] == "vector"
                 else None)
        if claim is None:
            return
        cmob = VGroup()

        # Cue 2: ABSURDITY OF SCALE.  Swing an arc of the object's own length
        # up to the claim's line and let it fall visibly short.  Both things
        # are already on screen; nothing new is asserted.
        if str(d.get("absurdity") or "") == "length":
            C = self._vecval(d.get("compare_to"))
            nc = float(np.linalg.norm(claim))
            if C is not None and nc > 1e-9:
                r = float(np.linalg.norm(C))
                a0 = math.atan2(float(C[1]), float(C[0]))
                a1 = math.atan2(float(claim[1]), float(claim[0]))
                delta = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
                arc = Arc(radius=r * self.unit, start_angle=a0, angle=delta,
                          arc_center=self.origin, color=PROBE,
                          stroke_width=4.4)
                arc.set_z_index(Z_GEO + 0)
                self.play(Create(arc), run_time=0.6)

                # The arc lands ON the claim's own ray, so a gap drawn along
                # that ray would be hidden underneath the arrow.  Offset the
                # measurement sideways instead: a caliper showing how far the
                # object's OWN length reaches along the claim, with the rest
                # of the arrow left over in plain sight.
                foot = self.pt(claim * (r / nc))
                dirc = np.array([claim[0], claim[1], 0.0]) / nc
                perp = np.array([-dirc[1], dirc[0], 0.0])
                cdir = np.array([C[0], C[1], 0.0])
                side = -1.0 if float(np.dot(perp, cdir)) > 0 else 1.0
                off = 0.36 * perp * side
                rail = DashedLine(self.origin + off, foot + off, color=PROBE,
                                  stroke_width=3.4, dash_length=0.1)
                cross = Line(foot - 0.19 * perp, foot + 0.19 * perp,
                             color=PROBE, stroke_width=5.0)
                stub_a = Line(self.origin, self.origin + off, color=PROBE,
                              stroke_width=2.0).set_stroke(opacity=0.7)
                stub_b = Line(foot, foot + off, color=PROBE,
                              stroke_width=2.0).set_stroke(opacity=0.7)
                tag = T(f"|{d.get('compare_to')}|", font_size=22, color=PROBE)
                tag.move_to(self._clamp_in_box(
                    (self.origin + foot) / 2 + off * 2.6, tag))
                grp = VGroup(rail, cross, stub_a, stub_b, tag)
                grp.set_z_index(Z_GEO)
                cmob.add(arc, grp)
                self.play(Create(rail), Create(cross), FadeIn(stub_a),
                          FadeIn(stub_b), FadeIn(tag), run_time=0.55)

        # Cue 3: THE PROPERTY FAILS.  Last, never first -- TEMPLATE_AUDIT row
        # 8 already found the corner marker reads as nothing on its own, so
        # it is drawn at >= 0.30 and WIGGLED so the failure is animated.
        rf = self._vecval(d.get("residual_from"))
        if rf is not None:
            seg = residual(self.pt(rf), self.pt(claim), color=PROBE)
            seg.set_z_index(Z_GEO)
            for m in seg.get_family():
                m.set_z_index(Z_GEO)
            nc = float(np.linalg.norm(claim))
            back = -claim / nc if nc > 1e-9 else np.array([-1.0, 0.0])
            rm = right_angle_marker(self.pt(claim), back,
                                    self.pt(rf) - self.pt(claim),
                                    size=0.38, color=PROBE,
                                    stroke_width=4.0)
            rm.set_z_index(Z_GEO)
            self.play(Create(seg), run_time=0.6)
            self.play(Create(rm), run_time=0.4)
            self.play(Wiggle(rm, scale_value=1.35), run_time=0.6)
            cmob.add(seg, rm)
        self._track_overlay(cmob, lambda u, o: cmob)


# ---------------------------------------------------------------------------

class _FakePanel:
    """The two-argument shape ``span_line`` wants, without dragging a whole
    Panel (and its NumberPlane) into a scene that owns exactly one plane."""

    def __init__(self, origin: np.ndarray, unit: float):
        self.origin = origin
        self.unit = unit

    def pt(self, vec) -> np.ndarray:
        v = np.asarray(vec, float).flatten()
        return self.origin + np.array([v[0] * self.unit, v[1] * self.unit, 0.0])


def _rush_out(t: float) -> float:
    """Finish in the first sixth of the beat it is played in."""
    return float(np.clip(t * 6.0, 0.0, 1.0))


def _left_align(mob: VMobject) -> VMobject:
    """``label_text`` centres its wrapped lines (``stack_lines`` does), which
    under a left-anchored rail reads as a ragged paragraph rather than as the
    student's own written work.  Flush them left."""
    try:
        if isinstance(mob, VGroup) and len(mob) > 1:
            x = float(mob.get_left()[0])
            for ln in mob:
                ln.shift(np.array([x - float(ln.get_left()[0]), 0.0, 0.0]))
    except Exception:  # noqa: BLE001
        pass
    return mob


def _frame_for(points, box, box_center, pad: float, margin: float,
               cap: float | None = None):
    """bbox of every point visited so far -> (unit, origin in scene coords).

    Two things this does that a plain ``fit_unit`` does not, both necessary:
    it includes the ORIGIN in the bbox (every arrow starts there), and it
    ANCHORS THE ORIGIN OFF-CENTRE.  A problem living entirely in the first
    quadrant wastes three quadrants if the origin is centred, which costs
    about 2x of scale -- the difference between readable arrows and the
    4-pixel basis vectors in TEMPLATE_AUDIT.md row 10.
    """
    pts = [[0.0, 0.0]]
    for p in points:
        arr = np.asarray(p, float).flatten()
        if arr.size >= 2:
            pts.append([float(arr[0]), float(arr[1])])
    P = np.array(pts, float)
    lo, hi = P.min(axis=0) - pad, P.max(axis=0) + pad
    span = np.maximum(hi - lo, 1e-6)
    unit = min((box[0] - 2 * margin) / span[0], (box[1] - 2 * margin) / span[1])
    unit = float(np.clip(unit, UNIT_FLOOR, UNIT_CEIL))
    if cap is not None:
        unit = min(unit, float(cap))
    mid = (lo + hi) / 2
    bc = np.array([float(box_center[0]), float(box_center[1]), 0.0])
    origin = bc - unit * np.array([mid[0], mid[1], 0.0])
    return unit, origin


if __name__ == "__main__":  # pragma: no cover
    print(StepReplay.validate({}))
