"""Shared layout / drawing utilities for every Manim scene template.

HARD RULES enforced here (see docs/RENDERING.md):
  * NO LaTeX anywhere. Every glyph comes from ``Text``. manim's ``Matrix``
    family always builds its brackets with ``MathTex``, so ``TextMatrix``
    below is the ONLY way to draw a matrix in this container.
  * ``ApplyMatrix`` works in SCENE coordinates: x and y must share one
    ``unit``, and ``about_point`` must be the panel origin.
  * cairo cannot clip -> ``panel_matte`` paints an opaque mask on top.
  * ``ApplyMatrix`` mangles arrowheads -> arrows are ``Transform``ed onto
    freshly built arrows instead (``apply_matrix_anims``).

Import style: scene files are loaded by manim BY PATH (no package context),
so they do ``sys.path.insert(0, dirname(__file__)); from helpers import *``.
``registry.py`` does the same, so there is exactly one instance of this
module no matter how the backend reaches it.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable, Iterable, Sequence

import numpy as np
from manim import (
    Arrow,
    DOWN,
    LEFT,
    ApplyMatrix,
    BLACK,
    DashedLine,
    Difference,
    GREY_B,
    Line,
    Rectangle,
    Scene,
    Text,
    Transform,
    VGroup,
    VMobject,
    Write,
    always_redraw,
    config,
)

# ---------------------------------------------------------------------------
# Palette -- six colors, zero collisions.
# GREEN/RED are permanently reserved for i-hat / j-hat (3Blue1Brown
# convention), so panel identity rides on amber-vs-near-white and NEVER on
# green or red.
# ---------------------------------------------------------------------------
BG = "#000000"
GRID = "#3B6CB7"
AXIS = GREY_B
I_HAT = "#83C167"
J_HAT = "#FC6255"
STUDENT = "#FFB020"   # amber: everything the student claimed, and the hint
CORRECT = "#E9ECEF"   # near-white: the true object
GHOST = "#6C757D"     # grey: reference overlays
PROBE = "#C77DFF"     # violet: unreachable targets, residual markers

# ---------------------------------------------------------------------------
# Font. Text goes through Pango; the system default here is a serif, and
# digits in a serif read badly on a projector. "DejaVu Sans" is present in
# this container (fc-list confirms 59 families). Every Text in the app goes
# through T() so there is one place to change it.
# ---------------------------------------------------------------------------
def _pick_font() -> str:
    try:
        import manimpango
        fams = set(manimpango.list_fonts())
        for cand in ("DejaVu Sans", "Liberation Sans", "FreeSans"):
            if cand in fams:
                return cand
    except Exception:  # noqa: BLE001
        pass
    return ""


FONT = _pick_font()


def T(s: Any, **kwargs) -> Text:
    """Text with the app font. Never use bare Text() in a template."""
    if FONT and "font" not in kwargs:
        kwargs["font"] = FONT
    return Text(str(s), **kwargs)


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
UNIT = 0.78           # scene units per math unit (x and y MUST share it)
PLANE_RADIUS = 7      # draw the plane far past the box; the matte clips
PANEL_DX = 3.6
PANEL_DY = -1.0
BOX = 4.6
TITLE_Y, HEAD_Y, MAT_Y, HINT_Y = 3.58, 2.82, 2.02, -3.66

Z_PLANE, Z_OVERLAY, Z_MATTE, Z_BORDER, Z_CHROME, Z_FLASH = 0, 5, 10, 11, 12, 13

MAX_TITLE_W = 12.0
MAX_HINT_W = 12.0


class SceneParamError(Exception):
    """Raised by ``validate`` -- the backend catches it and degrades down the
    fallback ladder: chosen template -> StaticStepHighlight -> PNG + text."""


# ---------------------------------------------------------------------------
# Numbers and text
# ---------------------------------------------------------------------------

def fmt_num(x: Any, max_den: int = 20) -> str:
    """int -> '3';  nice rational -> '2/5';  else -> '0.71'.

    Never '0.30000000000000004'. There is no \\frac without LaTeX, so
    rationals are rendered inline. Use for EVERY number that reaches the
    screen, including live readouts.
    """
    if isinstance(x, str):
        return x
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not math.isfinite(f):
        return "?"
    if abs(f) < 5e-9:
        return "0"
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    fr = Fraction(f).limit_denominator(max_den)
    if abs(float(fr) - f) < 1e-9:
        return f"{fr.numerator}/{fr.denominator}"
    s = f"{f:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def parse_num(x: Any, *, name: str = "value") -> float:
    """Accept 3, 3.0, '3', '2/5', '-1/10' -- the display strings the backend
    already produced -- and give back a float for the geometry."""
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    try:
        if "/" in s:
            return float(Fraction(s))
        return float(s)
    except (ValueError, ZeroDivisionError) as exc:
        raise SceneParamError(f"{name}: cannot read {x!r} as a number") from exc


def fmt_rows(M) -> list[list[str]]:
    """2D numeric array -> display strings."""
    return [[fmt_num(v) for v in row] for row in np.asarray(M, dtype=float).tolist()]


def fit_text(t: VMobject, max_width: float) -> VMobject:
    """Shrink a Text in place if it would run off frame. Cheap insurance
    against an LLM-written title that is two words too long."""
    if t.width > max_width:
        t.scale(max_width / t.width)
    return t


def label_text(s: str, *, font_size: int = 24, color: str = CORRECT,
               max_width: float = MAX_TITLE_W, weight=None) -> Text:
    kw: dict[str, Any] = {"font_size": font_size, "color": color}
    if weight is not None:
        kw["weight"] = weight
    t = T(s, **kw)
    return fit_text(t, max_width)


BANNED_HINT_PHRASES = (
    "should be", "instead of", "you forgot", "the correct",
    "actually is", "is wrong because", "correct answer",
)


def check_hint(hint: str, forbidden_values: Sequence[str] = ()) -> str:
    """Product requirement, not style: the student must SEE the error, never
    be told the fix. Positional and observational hints only."""
    if not hint or not str(hint).strip():
        raise SceneParamError("hint is empty")
    hint = str(hint).strip()
    low = hint.lower()
    for b in BANNED_HINT_PHRASES:
        if b in low:
            raise SceneParamError(f"hint states the correction: {hint!r}")
    for v in forbidden_values:
        v = str(v).strip()
        if len(v) >= 2 and v in hint:
            raise SceneParamError(f"hint leaks the value {v!r}")
    return hint


# ---------------------------------------------------------------------------
# Parameter plumbing:  SCENE_PARAMS env var -> JSON file -> validate()
# ---------------------------------------------------------------------------

def load_raw_params(defaults: dict) -> dict:
    """Merge ``$SCENE_PARAMS`` over the template's defaults.

    ``SCENE_PARAMS`` is normally a path to a JSON file (that is how the
    backend invokes the manim CLI); inline JSON is also accepted so a scene
    can be poked at from the shell. The file may be either a bare params dict
    or the full ``{"template": ..., "params": {...}}`` envelope.
    """
    raw = os.environ.get("SCENE_PARAMS", "").strip()
    params = dict(defaults)
    if not raw:
        return params
    if raw.startswith("{"):
        loaded = json.loads(raw)
    else:
        with open(raw, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
    if isinstance(loaded, dict) and "params" in loaded and "template" in loaded:
        loaded = loaded["params"]
    if not isinstance(loaded, dict):
        raise SceneParamError("SCENE_PARAMS must contain a JSON object")
    params.update(loaded)
    return params


def as_matrix(value, *, name: str, size: int | None = None) -> np.ndarray:
    try:
        M = np.array(value, dtype=float)
    except Exception as exc:  # noqa: BLE001
        raise SceneParamError(f"{name}: not numeric ({exc})") from exc
    if M.ndim != 2 or M.shape[0] != M.shape[1]:
        raise SceneParamError(f"{name}: must be a square matrix, got shape {M.shape}")
    if size is not None and M.shape[0] != size:
        raise SceneParamError(f"{name}: must be {size}x{size}, got {M.shape}")
    if M.shape[0] not in (2, 3):
        raise SceneParamError(f"{name}: only 2x2 and 3x3 supported")
    if not np.all(np.isfinite(M)):
        raise SceneParamError(f"{name}: non-finite entry")
    if np.max(np.abs(M)) > 50:
        raise SceneParamError(f"{name}: entry magnitude > 50, will not fit on screen")
    return M


def as_vector(value, *, name: str, dim: int | None = None,
              nonzero: bool = False) -> np.ndarray:
    try:
        v = np.array(value, dtype=float).flatten()
    except Exception as exc:  # noqa: BLE001
        raise SceneParamError(f"{name}: not numeric ({exc})") from exc
    if dim is not None and v.size != dim:
        raise SceneParamError(f"{name}: expected {dim} components, got {v.size}")
    if v.size not in (2, 3):
        raise SceneParamError(f"{name}: only 2D and 3D vectors supported")
    if not np.all(np.isfinite(v)):
        raise SceneParamError(f"{name}: non-finite entry")
    if nonzero and float(np.linalg.norm(v)) < 1e-9:
        raise SceneParamError(f"{name}: must be nonzero")
    return v


# ---------------------------------------------------------------------------
# TextMatrix -- the LaTeX-free matrix
# ---------------------------------------------------------------------------

class TextMatrix(VGroup):
    """Bracketed matrix built only from ``Text``.

    manim's ``Matrix.__init__`` calls ``_add_brackets()`` unconditionally and
    builds the brackets from a LaTeX array environment, so ``Matrix``,
    ``IntegerMatrix``, ``DecimalMatrix`` and ``MobjectMatrix`` are ALL
    unusable here. Entries are centred on a fixed pitch so columns stay
    aligned when widths differ ('-1' vs '1').
    """

    def __init__(self, rows: Sequence[Sequence[Any]], *, font_size: int = 26,
                 color: str = CORRECT, h_buff: float = 0.62, v_buff: float = 0.46,
                 bracket_pad: float = 0.14, bracket_lip: float = 0.10,
                 stroke_width: float = 2.0, **kwargs) -> None:
        super().__init__(**kwargs)
        rows = [list(r) for r in rows]
        if not rows or not rows[0]:
            rows = [[""]]
        self.n_rows = len(rows)
        self.n_cols = max(len(r) for r in rows)
        for r in rows:
            while len(r) < self.n_cols:
                r.append("")
        self.rows_text = [[str(v) for v in r] for r in rows]

        # Build first, THEN measure: entry widths decide both the column pitch
        # and where the brackets go. Guessing from character counts puts
        # "-1/10" straight through the right bracket.
        cells = [[T(item, font_size=font_size, color=color) for item in row]
                 for row in rows]
        w_max = max((c.width for r in cells for c in r), default=0.3)
        h_max = max((c.height for r in cells for c in r), default=0.3)
        pitch = max(h_buff, w_max + 0.22)
        v_pitch = max(v_buff, h_max + 0.18)

        entries = VGroup()
        for i, row in enumerate(cells):
            for j, t in enumerate(row):
                t.move_to(np.array([
                    (j - (self.n_cols - 1) / 2) * pitch,
                    -(i - (self.n_rows - 1) / 2) * v_pitch,
                    0.0,
                ]))
                entries.add(t)
        self.entries = entries

        half_w = (self.n_cols - 1) / 2 * pitch + w_max / 2 + bracket_pad
        half_h = (self.n_rows - 1) / 2 * v_pitch + h_max / 2 + bracket_pad * 0.8

        def bracket(sign: int) -> VMobject:
            x = sign * half_w
            lip = sign * bracket_lip
            m = VMobject(stroke_color=color, stroke_width=stroke_width)
            m.set_points_as_corners([
                np.array([x - lip, half_h, 0.0]),
                np.array([x, half_h, 0.0]),
                np.array([x, -half_h, 0.0]),
                np.array([x - lip, -half_h, 0.0]),
            ])
            return m

        self.l_bracket = bracket(-1)
        self.r_bracket = bracket(+1)
        self.add(entries, self.l_bracket, self.r_bracket)

    # -- cell accessors: what keeps the pairing sweep and "which column
    #    moved" flashes short in the templates -------------------------------
    def entry(self, i: int, j: int) -> Text:
        return self.entries[i * self.n_cols + j]

    def row(self, i: int) -> VGroup:
        return VGroup(*[self.entry(i, j) for j in range(self.n_cols)])

    def col(self, j: int) -> VGroup:
        return VGroup(*[self.entry(i, j) for i in range(self.n_rows)])

    def cell_center(self, i: int, j: int) -> np.ndarray:
        return self.entry(i, j).get_center()


def text_matrix(rows, **kwargs) -> TextMatrix:
    """Functional alias kept for the de-risk scene's call style."""
    return TextMatrix(rows, **kwargs)


# ---------------------------------------------------------------------------
# Planes, panels, mattes
# ---------------------------------------------------------------------------

@dataclass
class Panel:
    plane: Any
    origin: np.ndarray
    center: np.ndarray
    box: Rectangle
    unit: float
    radius: float = PLANE_RADIUS

    def pt(self, vec) -> np.ndarray:
        """Math coordinates -> scene coordinates inside this panel."""
        v = np.asarray(vec, dtype=float).flatten()
        return self.origin + np.array([v[0] * self.unit, v[1] * self.unit, 0.0])


def make_plane(center: np.ndarray, *, radius: float = PLANE_RADIUS,
               unit: float = UNIT, grid_color: str = GRID,
               stroke_opacity: float = 0.65):
    from manim.mobject.graphing.coordinate_systems import NumberPlane

    length = 2 * radius * unit
    plane = NumberPlane(
        x_range=[-radius, radius, 1],
        y_range=[-radius, radius, 1],
        x_length=length,
        y_length=length,
        # No include_numbers / add_coordinates: axis labels are DecimalNumber
        # -> MathTex -> LaTeX. Unreadable at panel size anyway.
        background_line_style={
            "stroke_color": grid_color,
            "stroke_width": 1.6,
            "stroke_opacity": stroke_opacity,
        },
        axis_config={"stroke_color": AXIS, "stroke_width": 2.4},
    )
    plane.move_to(center)
    return plane


def panel(dx: float, *, radius: float | None = None, unit: float = UNIT,
          dy: float = PANEL_DY, box: float = BOX, box_h: float | None = None) -> Panel:
    center = np.array([dx, dy, 0.0])
    if radius is None:
        # Always DRAW the plane past the visible box -- the matte clips it --
        # otherwise a shear pulls the grid lines apart and leaves the box with
        # four lonely lines in it. When fit_unit has shrunk the unit, a fixed
        # radius no longer reaches the box edge, so scale the radius with it.
        need = math.ceil((max(box, box_h or box) / 2 + 1.0) / max(unit, 1e-6))
        radius = int(min(20, max(PLANE_RADIUS, need)))
    plane = make_plane(center, radius=radius, unit=unit)
    plane.set_z_index(Z_PLANE)
    rect = Rectangle(width=box, height=box_h if box_h is not None else box).move_to(center)
    return Panel(plane=plane, origin=plane.get_origin(), center=center, box=rect,
                 unit=unit, radius=radius)


def panel_matte(*panel_rects: Rectangle) -> VMobject:
    """Full-frame black mask with a rectangular hole per panel.

    ``ApplyMatrix`` pushes grid lines far outside the panel (a shear can
    double the extent) and manim's cairo renderer has no clipping primitive,
    so an opaque matte on top is the only reliable separation.
    """
    full = Rectangle(width=config.frame_width + 1, height=config.frame_height + 1)
    matte: VMobject = full
    for r in panel_rects:
        matte = Difference(matte, r)
    matte.set_fill(BLACK, opacity=1).set_stroke(width=0)
    return matte


def ghost_plane(p: Panel) -> Any:
    # Same radius as the panel's own plane. With a fixed radius the reference
    # grid stops short of the box and reads as a grey rectangle floating in
    # the middle of the panel instead of as the original grid.
    g = make_plane(p.center, radius=p.radius, unit=p.unit,
                   grid_color=GHOST, stroke_opacity=0.32)
    g.set_z_index(Z_PLANE - 1)
    for m in g.get_family():
        m.set_stroke(opacity=min(0.34, m.get_stroke_opacity()))
    return g


@dataclass
class Layout:
    left: Panel | None = None
    right: Panel | None = None
    panels: list = field(default_factory=list)
    matte: VMobject | None = None
    borders: VGroup | None = None
    title: Text | None = None
    l_head: Text | None = None
    r_head: Text | None = None
    l_mat: TextMatrix | None = None
    r_mat: TextMatrix | None = None
    center_mat: TextMatrix | None = None
    hint: Text | None = None
    ghosts: VGroup | None = None


def two_panel_layout(scene: Scene, *, title: str, student_label: str,
                     correct_label: str, hint: str,
                     student_rows=None, correct_rows=None, center_rows=None,
                     ghost_reference: bool = False, unit: float = UNIT,
                     dx: float = PANEL_DX, dy: float = PANEL_DY,
                     box: float = BOX) -> Layout:
    """Build + z-index + add the chrome shared by five templates.

    Adds the matte and the borders to the scene (they must be present from
    frame 0). Everything else is returned for the template to animate in. The
    hint is created but NOT added -- templates ``Write`` it in the last beat.
    """
    L = panel(-dx, unit=unit, dy=dy, box=box)
    R = panel(+dx, unit=unit, dy=dy, box=box)

    matte = panel_matte(L.box, R.box).set_z_index(Z_MATTE)
    borders = VGroup(
        L.box.copy().set_stroke(STUDENT, 2.0, opacity=0.55),
        R.box.copy().set_stroke(CORRECT, 2.0, opacity=0.45),
    ).set_z_index(Z_BORDER)

    title_m = label_text(title, font_size=32, color=CORRECT, max_width=MAX_TITLE_W)
    title_m.move_to(np.array([0.0, TITLE_Y, 0.0]))
    l_head = label_text(student_label, font_size=22, color=STUDENT, max_width=5.4)
    l_head.move_to(np.array([-dx, HEAD_Y, 0.0]))
    r_head = label_text(correct_label, font_size=22, color=CORRECT, max_width=5.4)
    r_head.move_to(np.array([dx, HEAD_Y, 0.0]))

    l_mat = r_mat = center_mat = None
    if center_rows is not None:
        center_mat = TextMatrix(center_rows, color=CORRECT, font_size=26)
        center_mat.move_to(np.array([0.0, MAT_Y + 0.55, 0.0]))
    if student_rows is not None:
        l_mat = TextMatrix(student_rows, color=STUDENT, font_size=26)
        l_mat.move_to(np.array([-dx, MAT_Y, 0.0]))
    if correct_rows is not None:
        r_mat = TextMatrix(correct_rows, color=CORRECT, font_size=26)
        r_mat.move_to(np.array([dx, MAT_Y, 0.0]))

    hint_m = label_text(hint, font_size=24, color=STUDENT, max_width=MAX_HINT_W)
    hint_m.move_to(np.array([0.0, HINT_Y, 0.0]))

    for m in (title_m, l_head, r_head, l_mat, r_mat, center_mat, hint_m):
        if m is not None:
            m.set_z_index(Z_CHROME)

    ghosts = None
    if ghost_reference:
        ghosts = VGroup(ghost_plane(L), ghost_plane(R))

    scene.add(matte, borders)
    return Layout(left=L, right=R, panels=[L, R], matte=matte, borders=borders,
                  title=title_m, l_head=l_head, r_head=r_head, l_mat=l_mat,
                  r_mat=r_mat, center_mat=center_mat, hint=hint_m, ghosts=ghosts)


def one_panel_layout(scene: Scene, *, title: str, hint: str, dx: float = -2.4,
                     dy: float = -0.7, box: float = 5.2, unit: float = UNIT,
                     border_color: str = GHOST) -> Layout:
    """Single plane on the left, room for a scoreboard on the right.

    Used by the templates whose comparison is number-vs-number or
    same-space (T4, T5, T6 solution mode, T7) rather than panel-vs-panel.
    """
    P = panel(dx, unit=unit, dy=dy, box=box)
    matte = panel_matte(P.box).set_z_index(Z_MATTE)
    borders = VGroup(P.box.copy().set_stroke(border_color, 2.0, opacity=0.5))
    borders.set_z_index(Z_BORDER)

    title_m = label_text(title, font_size=32, color=CORRECT, max_width=MAX_TITLE_W)
    title_m.move_to(np.array([0.0, TITLE_Y, 0.0]))
    hint_m = label_text(hint, font_size=24, color=STUDENT, max_width=MAX_HINT_W)
    hint_m.move_to(np.array([0.0, HINT_Y, 0.0]))
    title_m.set_z_index(Z_CHROME)
    hint_m.set_z_index(Z_CHROME)

    scene.add(matte, borders)
    return Layout(left=P, panels=[P], matte=matte, borders=borders,
                  title=title_m, hint=hint_m)


# ---------------------------------------------------------------------------
# Arrows and the ApplyMatrix dance
# ---------------------------------------------------------------------------

def arrow_at(origin: np.ndarray, vec, color: str, *, unit: float = UNIT,
             stroke_width: float = 6.0) -> Arrow:
    """Arrow from a panel origin along ``vec`` (math units)."""
    v = np.asarray(vec, dtype=float).flatten()
    end = origin + np.array([v[0] * unit, v[1] * unit, 0.0])
    if float(np.linalg.norm(end - origin)) < 0.06:
        # A zero-length Arrow divides by zero while scaling its tip.
        d = np.array([v[0], v[1], 0.0])
        n = float(np.linalg.norm(d))
        d = d / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        end = origin + 0.06 * d
    return Arrow(origin, end, buff=0, color=color, stroke_width=stroke_width,
                 max_tip_length_to_length_ratio=0.28,
                 max_stroke_width_to_length_ratio=9)


class VecArrow:
    """An arrow that remembers the math vector it currently represents, so a
    multi-stage template can keep composing transforms on it."""

    def __init__(self, panel_: Panel, vec, color: str, *, stroke_width: float = 6.0):
        self.panel = panel_
        self.vec = np.asarray(vec, dtype=float).flatten()[:2].astype(float)
        self.color = color
        self.stroke_width = stroke_width
        self.mob = arrow_at(panel_.origin, self.vec, color, unit=panel_.unit,
                            stroke_width=stroke_width)
        self.mob.set_z_index(Z_OVERLAY)

    def target(self, M) -> tuple[np.ndarray, Arrow]:
        new_vec = np.asarray(M, dtype=float) @ self.vec
        return new_vec, arrow_at(self.panel.origin, new_vec, self.color,
                                 unit=self.panel.unit, stroke_width=self.stroke_width)

    def tip(self) -> np.ndarray:
        return self.panel.pt(self.vec)


def apply_matrix_anims(panel_: Panel, M, arrows: Iterable[VecArrow], *,
                       run_time: float, extra: Sequence = ()) -> list:
    """``ApplyMatrix`` on the plane + ``Transform`` on each arrow.

    Returns animations, does NOT play them, so both panels can run inside one
    ``scene.play()``. Encapsulates the two traps from RENDERING.md:
      * ``about_point=panel.origin`` (the default ORIGIN translates an
        off-centre panel away instead of transforming it in place);
      * arrows are not fed to ``ApplyMatrix`` -- under p_t = (1-t)p + t*Mp the
        tip travels a straight line, exactly what ``Transform`` interpolates,
        so the head stays crisp instead of shearing into a bent wedge.
    """
    M = np.asarray(M, dtype=float)
    anims = [ApplyMatrix(M, panel_.plane, about_point=panel_.origin, run_time=run_time)]
    for a in arrows:
        new_vec, tgt = a.target(M)
        anims.append(Transform(a.mob, tgt, run_time=run_time))
        a.vec = new_vec
    anims.extend(extra)
    return anims


# ---------------------------------------------------------------------------
# Readouts, markers, overlays
# ---------------------------------------------------------------------------

def live_text(fn: Callable[[], str], *, at=None, font_size: int = 34,
              color: str = CORRECT, z_index: int = Z_CHROME, aligned_edge=None):
    """always_redraw(Text(...)) -- a readout that ticks while an animation
    runs. ``fn`` must return an already-formatted string (use ``fmt_num``)."""
    def build():
        t = T(fn(), font_size=font_size, color=color)
        if at is not None:
            # Align rather than centre: a ticking readout changes width every
            # frame ("1.00" -> "-2.00") and a centred one visibly jitters.
            if aligned_edge is not None:
                t.move_to(at, aligned_edge=aligned_edge)
            else:
                t.move_to(at)
        t.set_z_index(z_index)
        return t
    return always_redraw(build)


def signed_area(poly, unit: float = 1.0) -> float:
    """Shoelace over a polygon's vertices, in math units if ``unit`` given.

    Verified equal to ``det M`` to 1e-9 after ``ApplyMatrix``, and it keeps
    the SIGN -- which is how the orientation flip gets rendered.
    """
    pts = np.array(poly.get_vertices())[:, :2]
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    a = 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    return a / (unit * unit)


def scoreboard(rows: Sequence[tuple], *, anchor, label_size: int = 19,
               value_size: int = 34, row_buff: float = 0.52,
               max_width: float = 4.4) -> VGroup:
    """[(label, value, color)] -> a stacked two-line-per-row readout block.

    How "student's claim vs true value" appears in the single-plane
    templates, where there is no second panel to carry the comparison.
    """
    group = VGroup()
    for label, value, color in rows:
        lab = fit_text(T(label, font_size=label_size, color=GHOST), max_width)
        val = fit_text(T(value, font_size=value_size, color=color), max_width)
        val.next_to(lab, DOWN, buff=0.12)
        group.add(VGroup(lab, val))
    group.arrange(DOWN, buff=row_buff, aligned_edge=LEFT)
    group.move_to(anchor)
    group.set_z_index(Z_CHROME)
    return group


def span_line(panel_: Panel, vec, *, color: str = GHOST, dashed: bool = True,
              reach: float = 9.0, stroke_width: float = 2.4,
              opacity: float = 0.9):
    """The infinite line through the origin along ``vec`` (drawn long enough
    to leave the panel; the matte clips it)."""
    v = np.asarray(vec, dtype=float).flatten()[:2]
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        v = np.array([1.0, 0.0])
        n = 1.0
    d = np.array([v[0] / n, v[1] / n, 0.0])
    a = panel_.origin - reach * d
    b = panel_.origin + reach * d
    cls = DashedLine if dashed else Line
    kw = {"stroke_width": stroke_width, "color": color}
    if dashed:
        kw["dash_length"] = 0.14
    ln = cls(a, b, **kw)
    ln.set_stroke(opacity=opacity)
    ln.set_z_index(Z_OVERLAY - 1)
    return ln


def foot_on_line(origin: np.ndarray, direction, point: np.ndarray) -> np.ndarray:
    """Perpendicular foot of ``point`` on the line origin + t*direction."""
    d = np.asarray(direction, dtype=float).flatten()[:3]
    if d.size == 2:
        d = np.array([d[0], d[1], 0.0])
    n = float(np.linalg.norm(d))
    if n < 1e-9:
        return origin.copy()
    d = d / n
    return origin + float(np.dot(point - origin, d)) * d


def residual(p: np.ndarray, q: np.ndarray, *, label: str | None = None,
             color: str = PROBE, font_size: int = 19,
             away_from: np.ndarray | None = None, side: int | None = None,
             label_buff: float = 0.46) -> VGroup:
    """Dashed gap between two points, plus an optional label beside it.

    The label is pushed off the segment on the side AWAY from ``away_from``
    (normally the panel origin), because the interesting gap is always right
    next to the arrow it is measuring and a centred label lands on top of it.
    """
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)
    g = VGroup()
    if float(np.linalg.norm(q - p)) < 0.02:
        q = q + np.array([0.02, 0.0, 0.0])
    ln = DashedLine(p, q, color=color, stroke_width=3.4, dash_length=0.1)
    g.add(ln)
    if label:
        t = T(label, font_size=font_size, color=color)
        mid = (p + q) / 2
        d = q - p
        perp = np.array([-d[1], d[0], 0.0])
        n = float(np.linalg.norm(perp))
        perp = perp / n if n > 1e-9 else np.array([0.0, 1.0, 0.0])
        if side is not None:
            perp = perp * (1 if side >= 0 else -1)
        elif away_from is not None:
            if float(np.dot(mid + perp - np.asarray(away_from),
                            mid + perp - np.asarray(away_from))) < \
               float(np.dot(mid - perp - np.asarray(away_from),
                            mid - perp - np.asarray(away_from))):
                perp = -perp
        t.move_to(mid + (label_buff + 0.5 * t.width) * perp)
        g.add(t)
    g.set_z_index(Z_FLASH)
    return g


def side_label(text: str, anchor: np.ndarray, direction, *, color: str = GHOST,
               font_size: int = 18, buff: float = 0.34, side: int = 1) -> Text:
    """A small caption placed clear of a line/arrow, perpendicular to it."""
    d = np.asarray(direction, dtype=float).flatten()
    d = np.array([d[0], d[1], 0.0])
    n = float(np.linalg.norm(d))
    perp = np.array([-d[1], d[0], 0.0]) / n if n > 1e-9 else np.array([0.0, 1.0, 0.0])
    perp = perp * (1 if side >= 0 else -1)
    t = T(text, font_size=font_size, color=color)
    t.move_to(np.asarray(anchor, dtype=float) + (buff + 0.5 * t.width) * perp)
    t.set_z_index(Z_CHROME)
    return t


def right_angle_marker(corner: np.ndarray, d1, d2, *, size: float = 0.24,
                       color: str = CORRECT, stroke_width: float = 3.0) -> VMobject:
    """A small square corner marker. Hand-built rather than manim's
    ``RightAngle`` so it never depends on line objects that later move."""
    def unit_of(d):
        d = np.asarray(d, dtype=float).flatten()
        d = np.array([d[0], d[1], 0.0])
        n = float(np.linalg.norm(d))
        return d / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
    u1, u2 = unit_of(d1), unit_of(d2)
    m = VMobject(stroke_color=color, stroke_width=stroke_width)
    m.set_points_as_corners([
        corner + size * u1,
        corner + size * u1 + size * u2,
        corner + size * u2,
    ])
    m.set_z_index(Z_FLASH)
    return m


def ghost_of(mobj: VMobject) -> VMobject:
    g = mobj.copy()
    g.set_color(GHOST)
    g.set_stroke(color=GHOST, opacity=0.45)
    try:
        g.set_fill(GHOST, opacity=0.18)
    except Exception:  # noqa: BLE001
        pass
    g.set_z_index(Z_PLANE + 1)
    return g


def fit_unit(vectors: Iterable, *, box: float = BOX, unit: float = UNIT,
             margin: float = 0.86, floor: float = 0.12,
             allow_grow: bool = False, ceiling: float = 2.4) -> float:
    """Shrink UNIT until every supplied vector's tip stays inside the box.

    ``allow_grow`` also ENLARGES the unit when everything is small -- what the
    unit-circle framing needs, where the whole story happens within one math
    unit of the origin and the default scale would draw it as a dot.
    """
    m = 0.0
    for v in vectors:
        if v is None:
            continue
        arr = np.asarray(v, dtype=float).flatten()
        if arr.size == 0:
            continue
        m = max(m, float(np.max(np.abs(arr))))
    if m < 1e-9:
        return unit
    allowed = (box / 2.0) * margin / m
    if allow_grow:
        return max(floor, min(ceiling, allowed))
    return max(floor, min(unit, allowed))


def hint_beat(scene: Scene, layout: Layout, run_time: float = 1.0) -> None:
    scene.play(Write(layout.hint), run_time=run_time)


# ---------------------------------------------------------------------------
# 3D without ThreeDScene
# ---------------------------------------------------------------------------

_ISO = np.array([[0.866, -0.866, 0.0],
                 [0.5, 0.5, 1.0]])


def iso_project(v3) -> np.ndarray:
    """Fixed axonometric R^3 -> R^2 (as a 3D scene point with z=0).

    ThreeDScene is slower, fights the matte-based panel clipping, and adds a
    camera to tune at 4am. Consequence: a 3x3 matrix cannot go through
    ApplyMatrix (which acts on scene coordinates), so 3D modes animate with a
    ValueTracker and always_redraw instead.
    """
    v = np.asarray(v3, dtype=float).flatten()
    if v.size == 2:
        v = np.array([v[0], v[1], 0.0])
    p = _ISO @ v
    return np.array([p[0], p[1], 0.0])


def iso_point(panel_: Panel, v3) -> np.ndarray:
    return panel_.origin + panel_.unit * iso_project(v3)


# ---------------------------------------------------------------------------
# ParamScene -- the base every template extends
# ---------------------------------------------------------------------------

class ParamScene(Scene):
    """Reads its parameters, in priority order, from:

      1. ``cls.P``          -- set by the backend for in-process rendering
      2. ``$SCENE_PARAMS``  -- path to a JSON file (or inline JSON)
      3. ``cls.DEFAULTS``   -- so the file renders standalone for testing

    One class attribute holds the whole validated dict, because manim.config
    and class attributes are global and not thread-safe: one assignment is
    one thing to serialize behind the render lock.
    """

    TEMPLATE = "ParamScene"
    DEFAULTS: dict = {}
    P: dict | None = None
    DURATION = 0.0

    @classmethod
    def validate(cls, params: dict) -> dict:
        return dict(params)

    @classmethod
    def resolve(cls) -> dict:
        if cls.P is not None:
            return cls.P
        return cls.validate(load_raw_params(cls.DEFAULTS))

    def construct(self) -> None:
        self.camera.background_color = BG
        self.p = self.resolve()
        self.build_scene(self.p)

    def build_scene(self, p: dict) -> None:  # pragma: no cover - overridden
        raise NotImplementedError
