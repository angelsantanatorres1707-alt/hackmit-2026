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
import sys
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
# The grid was #3B6CB7 at 0.65 opacity: a 1px line of a dark blue on black
# antialiases to roughly #26466f, which a projector renders as nothing at
# all. Brighter + fatter + fewer lines (see ``panel``'s step) is the whole
# legibility fix -- density is controlled by spacing, not by dimness.
GRID = "#5E8FD8"
AXIS = "#DCE0E6"      # was GREY_B (#BBBBBB) -- the axes ARE the structure
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
UNIT = 0.95           # scene units per math unit (x and y MUST share it)
                      # (was 0.78 for a 4.6 box; the panels are bigger now,
                      #  so the mathematics gets the extra room, not the
                      #  margins -- a basis vector is now ~85px, not ~70px)
PLANE_RADIUS = 7      # draw the plane far past the box; the matte clips

# The frame is 14.222 x 8.0 and this is judged across a room, so the panels
# are pushed out to the gutters: 0.28 of margin at the sides, 0.82 between
# them. The old 4.6 squares at dx=3.6 left 5 units -- 35% of the width --
# empty. Panels are WIDER than tall because the frame is 16:9; ``fit_unit``
# still measures against BOX (the height), which is the binding dimension.
PANEL_DX = 3.62
BOX_W = 6.42          # panel width
BOX = 4.44            # panel height == the reference every fit_unit uses
PANEL_DY = -0.74      # -> panel spans y in [-2.96, 1.48]

TITLE_Y, HEAD_Y, MAT_Y, HINT_Y = 3.62, 2.90, 2.04, -3.66

# The hint is anchored by its BOTTOM edge, not its centre, so that a hint
# which wrapped to two lines grows upward into the gap instead of off the
# bottom of the frame.
HINT_BOTTOM_Y = -3.82   # 0.18 of clearance at the bottom of the frame
HINT_MAX_H = 0.76       # two lines max, and the block grows upward

# Font sizes, all in one place. Everything went up: a 22pt panel heading is
# ~25px tall at 720p, which is a squint from the back of a room.
FS_TITLE = 34
FS_HEAD = 24
FS_MAT = 29
FS_HINT = 27

Z_PLANE, Z_OVERLAY, Z_MATTE, Z_BORDER, Z_CHROME, Z_FLASH = 0, 5, 10, 11, 12, 13

# Nothing may ever be wider than this. config.frame_width is 14.222; the
# remaining ~0.45 per side is deliberate gutter, because a projector's
# overscan eats the edge of the frame and a caption cut off mid-word is the
# single worst thing that can be on screen.
FRAME_SAFE_W = 13.3
MAX_TITLE_W = 13.0
MAX_HINT_W = 12.6

# Aim for this many grid cells across the widest panel dimension. More than
# this and the lattice aliases into a grey wash at 720p; fewer and a shear
# has nothing legible to act on.
GRID_TARGET_CELLS = 10


class SceneParamError(Exception):
    """Raised by ``validate`` -- the backend catches it and degrades down the
    fallback ladder: chosen template -> StaticStepHighlight -> PNG + text."""


# ---------------------------------------------------------------------------
# Answer hiding -- the product promise, enforced in one place
#
# The whole premise is that the student SEES the divergence and works out the
# fix themselves. So the reference side of every template shows its GEOMETRY
# (transformed grid, basis vectors, unit square, eigenray, span, hinge) and
# never the numbers that CONSTITUTE the answer:
#
#   the correct matrix, det(M), the true eigenvalue, the solution
#   coordinates, the true span dimension, a projection's components, an
#   invariant readout computed for the correct object.
#
# Numbers that are NOT the answer stay on screen, always:
#   * the problem's own given matrix (``M_display``, the student's lines),
#   * everything the student themselves claimed -- that is their work.
#
# The flag lives here and is re-exported by ``common.py`` (one module, two
# names), so ``from common import REVEAL_CORRECT_VALUES`` works too.
# Flip it to True -- or export ``REVEAL_CORRECT_VALUES=1`` -- to put the
# numbers back for debugging or a future "show me the answer" escalation.
#
# THE DEFAULT MUST STAY False. It is the product, not a style choice.
# ---------------------------------------------------------------------------
REVEAL_CORRECT_VALUES = False

MASK = "?"                 # what a withheld number is drawn as
MASK_COLOR = GHOST         # grey: "deliberately not shown", not "missing"

_TRUTHY = ("1", "true", "yes", "on")


def reveal_correct_values() -> bool:
    """The single gate every template asks before drawing a correct value.

    Priority: ``$REVEAL_CORRECT_VALUES`` (so the flag can be flipped for one
    render without touching code), then this module's flag, then a runtime
    override on the ``common`` alias module.
    """
    env = os.environ.get("REVEAL_CORRECT_VALUES")
    if env is not None and env.strip():
        return env.strip().lower() in _TRUTHY
    if REVEAL_CORRECT_VALUES:
        return True
    common = sys.modules.get("common")
    return bool(common is not None
                and getattr(common, "REVEAL_CORRECT_VALUES", False))


def mask_rows(rows) -> list[list[str]]:
    """Same SHAPE as ``rows``, every entry replaced by the mask glyph.

    Keeping the shape matters: "the target is a 2x2 you have not worked out
    yet" is information the student is entitled to, the entries are not.
    """
    out: list[list[str]] = []
    for row in (rows or [[""]]):
        cells = row if isinstance(row, (list, tuple)) else [row]
        out.append([MASK for _ in cells] or [MASK])
    return out or [[MASK]]


def reference_value(value: Any) -> tuple[str, str]:
    """``(text, color)`` for a number belonging to the correct answer."""
    if reveal_correct_values():
        return str(value), CORRECT
    return MASK, MASK_COLOR


# Phrasings that turn a panel heading into an answer key. The planner is an
# LLM and its first instinct is literally "WHAT THE STEP SHOULD DO", so this
# is checked at render time and not merely fixed in the DEFAULTS.
ANSWER_KEY_LABEL_WORDS = (
    "correct", "should", "right answer", "the answer", "actual",
    "true ", "truth", "wrong", "answer key", "fix",
)

REFERENCE_LABEL_DEFAULT = "WHAT THE PROBLEM ASKS FOR"


def reference_label(label: Any,
                    default: str = REFERENCE_LABEL_DEFAULT) -> str:
    """Heading for the non-student panel: the TARGET, never the correction.

    "WHAT YOU WROTE" stays on the student's side; this side has to read as
    the goal the student is aiming at, so that the comparison is an
    invitation rather than a solution.
    """
    s = str(label or "").strip()
    if not s:
        return default
    low = s.lower()
    if any(w in low for w in ANSWER_KEY_LABEL_WORDS):
        return default
    return s


def is_student_row(label: Any, index: int = 1) -> bool:
    """Is this scoreboard row the student's own claim (so: safe to show)?

    Row 0 is the student's by construction in every template that has a
    scoreboard; after that the wording decides, because a template like the
    cross product puts two student readouts above one reference readout.
    """
    if index == 0:
        return True
    low = str(label or "").lower()
    return "your" in low or "you " in low


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


def wrap_words(s: str, max_chars: int) -> str:
    """Greedy word wrap. Never splits a word -- a word broken across lines
    reads as the clipping bug we are fixing."""
    words = str(s).split()
    if not words:
        return str(s)
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = w if not cur else cur + " " + w
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return "\n".join(lines)


def stack_lines(lines: Sequence[str], *, line_spacing: float = 0.2,
                **kw) -> VGroup:
    """Centre-aligned multi-line text on a uniform pitch.

    manim's ``Text`` accepts "\\n" but Pango left-aligns the result, which
    under a centred title reads as a ragged paragraph dumped in the frame.
    Building the lines separately also lets the pitch come from one reference
    glyph pair, so a line with no descender is not pulled closer to the next.
    """
    ref = T("Ag", **kw)
    pitch = ref.height * (1.0 + float(line_spacing))
    g = VGroup()
    for i, ln in enumerate(lines):
        m = T(ln if ln.strip() else " ", **kw)
        m.move_to(np.array([0.0, -i * pitch, 0.0]))
        g.add(m)
    g.move_to(np.array([0.0, 0.0, 0.0]))
    return g


def fit_text(t: VMobject, max_width: float,
             max_height: float | None = None) -> VMobject:
    """HARD GUARANTEE: after this returns, ``t`` fits the box.

    ``max_width`` is additionally clamped to ``FRAME_SAFE_W`` whatever the
    caller asks for. An LLM writes the hints and nobody proofreads them, so
    the one thing that must be impossible is a caption running off the edge
    of the frame.
    """
    w = min(float(max_width), FRAME_SAFE_W)
    if w > 0 and t.width > w:
        t.scale(w / t.width)
    if max_height is not None and max_height > 0 and t.height > max_height:
        t.scale(max_height / t.height)
    return t


def label_text(s: str, *, font_size: int = 24, color: str = CORRECT,
               max_width: float = MAX_TITLE_W, weight=None,
               max_lines: int = 1, max_height: float | None = None,
               line_spacing: float = 0.2) -> Text:
    """Build a Text that is guaranteed to fit, WRAPPING before it shrinks.

    Shrinking alone is what produced a hint rendered at a size nobody could
    read (or, worse, a 16-unit one-liner in a 14.2-unit frame). With
    ``max_lines > 1`` the string is wrapped to the available width first and
    scaling is only the backstop.
    """
    s = str(s)
    kw: dict[str, Any] = {"font_size": font_size, "color": color}
    if weight is not None:
        kw["weight"] = weight
    t = T(s, **kw)
    w = min(float(max_width), FRAME_SAFE_W)
    if max_lines > 1 and t.width > w > 0 and len(s.split()) > 1:
        # Estimate the character budget from the measured single-line width
        # -- one extra Text build instead of one per candidate break.
        per_char = t.width / max(len(s), 1)
        budget = max(6, int(w / per_char))
        lines = wrap_words(s, budget).split("\n")
        # Greedy wrapping does not hit an exact line count (words do not
        # divide evenly), so widen the budget until it does rather than
        # computing it once and getting an orphan last word.
        guard = 0
        while len(lines) > max_lines and guard < 60:
            budget = int(budget * 1.08) + 2
            lines = wrap_words(s, budget).split("\n")
            guard += 1
        t = stack_lines(lines, line_spacing=line_spacing, **kw)
    return fit_text(t, w, max_height)


def title_text(s: str, *, color: str = CORRECT) -> Text:
    """The scene title: one line, bold, as big as the frame allows.

    Deliberately NOT wrapped: a second title line would land on the panel
    headings. A title long enough to need one gets scaled instead, and the
    planner already caps titles at 70 characters.
    """
    t = label_text(s, font_size=FS_TITLE, color=color, max_width=MAX_TITLE_W,
                   weight="BOLD", max_lines=1, max_height=0.52)
    t.move_to(np.array([0.0, TITLE_Y, 0.0]))
    t.set_z_index(Z_CHROME)
    return t


def hint_text(s: str, *, color: str = STUDENT) -> Text:
    """The positional hint, anchored by its BOTTOM edge.

    Two lines are allowed and the block grows UPWARD, so a long hint can stay
    at a readable size without ever reaching the bottom of the frame.
    """
    t = label_text(s, font_size=FS_HINT, color=color, max_width=MAX_HINT_W,
                   weight="BOLD", max_lines=2, max_height=HINT_MAX_H)
    t.move_to(np.array([0.0, HINT_BOTTOM_Y + t.height / 2.0, 0.0]))
    t.set_z_index(Z_CHROME)
    return t


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
    radius: float = PLANE_RADIUS      # x half-extent, in math units
    radius_y: float = PLANE_RADIUS    # y half-extent, in math units
    step: int = 1         # math units between MAJOR grid lines

    def pt(self, vec) -> np.ndarray:
        """Math coordinates -> scene coordinates inside this panel."""
        v = np.asarray(vec, dtype=float).flatten()
        return self.origin + np.array([v[0] * self.unit, v[1] * self.unit, 0.0])


def grid_step(box: float, unit: float, target: int = GRID_TARGET_CELLS) -> int:
    """Math units between MAJOR grid lines, so the panel shows ~``target``
    cells whatever ``fit_unit`` did to the scale.

    This is the anti-moire knob. At 720p a cell narrower than about 45px is
    two antialiased lines and a sliver of black, and a panel full of those
    reads as flat grey -- the lattice stops being a lattice exactly when the
    viewer needs to see what the transform did to it.
    """
    cells = float(box) / max(float(unit), 1e-6)
    return max(1, int(math.ceil(cells / float(target))))


def min_stretch(*mats, floor: float = 0.1, ceiling: float = 12.0) -> float:
    """Smallest singular value over the given matrices.

    That is exactly the factor by which a transform rescales the spacing of
    the TIGHTEST family of grid lines, and it cuts both ways:

      * [[3,4],[1,2]] has sigma_min = 0.37, so its image of a unit lattice is
        2.7x tighter than what we drew -- at 720p that is the hairball of
        near-parallel lines that made the determinant panel unreadable;
      * [[6,-5],[2,5]] has sigma_min = 5.3, so a lattice chosen to look right
        at the start ends the scene with one line in the panel.

    Feeding it to ``grid_shrink`` picks the step for the state the scene ENDS
    in -- the held frame, the one with the hint on it -- and ``panel`` then
    refuses any step that would leave the opening frame with fewer than
    about three cells.
    """
    m: float | None = None
    for M in mats:
        if M is None:
            continue
        A = np.asarray(M, dtype=float)
        if A.ndim != 2 or A.shape[0] < 2 or A.shape[1] < 2:
            continue
        try:
            sv = np.linalg.svd(A[:2, :2], compute_uv=False)
        except Exception:  # noqa: BLE001
            continue
        if sv.size:
            v = float(sv[-1])
            m = v if m is None else min(m, v)
    if m is None:
        return 1.0
    return float(max(floor, min(ceiling, m)))


def lattice_weight(cells: float) -> tuple[float, float]:
    """(stroke_width, stroke_opacity) for a panel showing ``cells`` cells.

    Ink per unit area is what decides whether a lattice reads or turns into
    grey fog, so the line weight tracks the density instead of being a
    constant: 4 big cells get a fat bright line, 20 small ones get a thin
    dim one. Both still read as a grid; neither reads as a wash.
    """
    c = max(float(cells), 1.0)
    width = float(np.clip(2.8 - 0.075 * c, 1.5, 2.8))
    opacity = float(np.clip(1.05 - 0.026 * c, 0.62, 0.95))
    return width, opacity


def make_plane(center: np.ndarray, *, radius: float = PLANE_RADIUS,
               unit: float = UNIT, grid_color: str = GRID,
               stroke_opacity: float = 0.9, step: int = 1,
               stroke_width: float = 2.0, axis_color: str = AXIS,
               axis_width: float = 3.4, radius_y: float | None = None):
    from manim.mobject.graphing.coordinate_systems import NumberPlane

    # x and y may cover DIFFERENT numbers of units, but they must share one
    # scene-units-per-math-unit or ApplyMatrix animates a conjugated matrix
    # (RENDERING.md #2). That is why both lengths are built from ``unit``.
    radius_y = radius if radius_y is None else radius_y
    length = 2 * radius * unit
    length_y = 2 * radius_y * unit
    # freq = step, faded_line_ratio = step  =>  lines are drawn every 1 math
    # unit but only every step-th one is at full strength. The unit lattice
    # survives as a whisper under a lattice you can actually see. step == 1
    # (the common case) produces no faded lines at all.
    ratio = int(step) if 1 <= step <= 2 else 1
    plane = NumberPlane(
        x_range=[-radius, radius, step],
        y_range=[-radius_y, radius_y, step],
        x_length=length,
        y_length=length_y,
        # No include_numbers / add_coordinates: axis labels are DecimalNumber
        # -> MathTex -> LaTeX. Unreadable at panel size anyway.
        background_line_style={
            "stroke_color": grid_color,
            "stroke_width": stroke_width,
            "stroke_opacity": stroke_opacity,
        },
        faded_line_style={
            "stroke_color": grid_color,
            "stroke_width": stroke_width * 0.7,
            "stroke_opacity": stroke_opacity * 0.3,
        },
        faded_line_ratio=ratio,
        axis_config={"stroke_color": axis_color, "stroke_width": axis_width},
    )
    plane.move_to(center)
    return plane


def panel(dx: float, *, radius: float | None = None, unit: float = UNIT,
          dy: float = PANEL_DY, box: float = BOX_W,
          box_h: float | None = None, step: int | None = None,
          max_reach: float | None = None, grid_shrink: float = 1.0) -> Panel:
    """``box`` is the panel WIDTH, ``box_h`` its height (default: square).

    ``max_reach`` caps how far, IN SCENE UNITS, the plane may be drawn to
    either side of its centre. In a two-panel layout that cap is the distance
    to the other panel's near edge: the matte has a hole over each panel, so
    a plane drawn wide enough to reach the neighbour draws straight through
    it and the two lattices superimpose.
    """
    center = np.array([dx, dy, 0.0])
    bw = float(box)
    bh = float(box_h if box_h is not None else box)
    if step is None:
        span_ = max(bw, bh)
        # Size the lattice for the SQUEEZED state (see ``min_stretch``)...
        step = grid_step(span_, unit * max(float(grid_shrink), 1e-3))
        # ...but never so coarse that the untransformed panel starts out with
        # fewer than ~3 cells across it and stops reading as a grid at all.
        step = max(1, min(step, int(math.floor(span_ / max(3.0 * unit, 1e-6))) or 1))

    def _snap(reach: float) -> int:
        """Scene-unit reach -> whole math radius, rounded DOWN onto ``step``
        so the lattice stays symmetric about the origin."""
        n = int(math.floor(max(reach, 0.0) / max(unit, 1e-6)))
        n = int(step * math.floor(n / float(step)))
        return max(step, min(24, n))

    if radius is not None:
        rx = ry = int(radius)
    else:
        # Draw the plane PAST the visible box -- the matte clips it -- or a
        # shear pulls the grid lines apart and leaves the box with four
        # lonely lines in it. Vertically there is no neighbour to bleed into,
        # so y gets the generous radius; x is capped by ``max_reach``.
        # (rx/ry below.)
        ry = _snap(bh / 2 + 3.4)
        rx = _snap(bw / 2 + 3.4)
        if max_reach is not None:
            rx = min(rx, _snap(max_reach))
        # ...but never so small that the panel starts out half empty.
        rx = max(rx, int(step * math.ceil(((bw / 2 + 0.15) / unit) / float(step))))
    # Line weight follows the density the panel will actually show. The
    # scene spends time in BOTH states, so split the difference between the
    # opening lattice and the transformed one.
    span2 = max(bw, bh)
    cells_open = span2 / max(unit * step, 1e-6)
    cells_end = cells_open / max(float(grid_shrink), 1e-3)
    gw, go = lattice_weight(math.sqrt(max(cells_open, 1.0) * max(cells_end, 1.0)))
    plane = make_plane(center, radius=rx, radius_y=ry, unit=unit, step=step,
                       stroke_width=gw, stroke_opacity=go)
    plane.set_z_index(Z_PLANE)
    rect = Rectangle(width=bw, height=bh).move_to(center)
    return Panel(plane=plane, origin=plane.get_origin(), center=center, box=rect,
                 unit=unit, radius=rx, radius_y=ry, step=step)


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
    g = make_plane(p.center, radius=p.radius, radius_y=p.radius_y,
                   unit=p.unit, step=p.step,
                   grid_color=GHOST, stroke_opacity=0.45, stroke_width=1.8,
                   axis_color=GHOST, axis_width=2.2)
    g.set_z_index(Z_PLANE - 1)
    for m in g.get_family():
        m.set_stroke(opacity=min(0.45, m.get_stroke_opacity()))
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
                     box: float = BOX_W, box_h: float = BOX,
                     grid_shrink: float = 1.0) -> Layout:
    """Build + z-index + add the chrome shared by five templates.

    Adds the matte and the borders to the scene (they must be present from
    frame 0). Everything else is returned for the template to animate in. The
    hint is created but NOT added -- templates ``Write`` it in the last beat.

    ``correct_rows`` is the ANSWER, so it is masked here rather than in each
    template: whatever the planner sends, the reference panel cannot print
    the numbers. ``student_rows`` is the student's own work and is always
    shown. See ``reveal_correct_values``.
    """
    # How far either plane may be drawn sideways before it reaches the other
    # panel's hole in the matte.
    reach = 2 * dx - box / 2 - 0.08
    L = panel(-dx, unit=unit, dy=dy, box=box, box_h=box_h, max_reach=reach,
              grid_shrink=grid_shrink)
    R = panel(+dx, unit=unit, dy=dy, box=box, box_h=box_h, max_reach=reach,
              grid_shrink=grid_shrink)

    # ---- cross-panel bleed ------------------------------------------------
    # The matte has a HOLE over each panel and cairo cannot clip, so once
    # ApplyMatrix carries the student's lattice across the frame it draws
    # straight through the reference panel. (Verified: with an IDENTITY
    # reference, the right panel came out full of the left panel's
    # diagonals.) ``max_reach`` above fixes the untransformed case; this
    # opaque shield, slipped BETWEEN the two planes, fixes the transformed
    # one. Painter's algorithm cannot break both directions of the tie -- a
    # mask that hides plane_R inside the left box also hides plane_L -- so
    # the REFERENCE panel is the one kept clean, because it is the thing
    # being compared against and it has to be unambiguous.
    L.plane.set_z_index(Z_PLANE - 2)
    shield = Rectangle(width=box, height=box_h).move_to(R.center)
    shield.set_fill(BLACK, opacity=1).set_stroke(width=0)
    shield.set_z_index(Z_PLANE - 1)
    R.plane.set_z_index(Z_PLANE)

    matte = panel_matte(L.box, R.box).set_z_index(Z_MATTE)
    borders = VGroup(
        L.box.copy().set_stroke(STUDENT, 3.0, opacity=0.9),
        R.box.copy().set_stroke(CORRECT, 3.0, opacity=0.75),
    ).set_z_index(Z_BORDER)

    title_m = title_text(title)
    # With a matrix parked at x = 0 the headings must not reach the centre,
    # or "WHAT AN EIGENVECTOR DOES" runs straight into its right bracket.
    head_w = box - 0.25 if center_rows is None else min(box - 0.25, 2 * dx - 1.9)
    l_head = label_text(student_label, font_size=FS_HEAD, color=STUDENT,
                        max_width=head_w, weight="BOLD")
    l_head.move_to(np.array([-dx, HEAD_Y, 0.0]))
    r_head = label_text(reference_label(correct_label), font_size=FS_HEAD,
                        color=CORRECT, max_width=head_w, weight="BOLD")
    r_head.move_to(np.array([dx, HEAD_Y, 0.0]))

    l_mat = r_mat = center_mat = None
    if center_rows is not None:
        # The GIVEN matrix, not an answer: the student is allowed to read it.
        center_mat = TextMatrix(center_rows, color=CORRECT, font_size=FS_MAT)
        # Same row as the per-panel matrices when there are none to clash
        # with, so it clears the heading row above it.
        center_mat.move_to(np.array([
            0.0, MAT_Y + (0.42 if (student_rows or correct_rows) else 0.12), 0.0]))
    if student_rows is not None:
        l_mat = TextMatrix(student_rows, color=STUDENT, font_size=FS_MAT)
        l_mat.move_to(np.array([-dx, MAT_Y, 0.0]))
    if correct_rows is not None:
        if reveal_correct_values():
            r_mat = TextMatrix(correct_rows, color=CORRECT, font_size=FS_MAT)
        else:
            r_mat = TextMatrix(mask_rows(correct_rows), color=MASK_COLOR,
                               font_size=FS_MAT)
        r_mat.move_to(np.array([dx, MAT_Y, 0.0]))

    hint_m = hint_text(hint)

    for m in (title_m, l_head, r_head, l_mat, r_mat, center_mat, hint_m):
        if m is not None:
            m.set_z_index(Z_CHROME)

    ghosts = None
    if ghost_reference:
        g_l, g_r = ghost_plane(L), ghost_plane(R)
        g_l.set_z_index(Z_PLANE - 3)      # under the left plane
        g_r.set_z_index(Z_PLANE - 0.5)    # over the shield, under the right plane
        ghosts = VGroup(g_l, g_r)

    scene.add(matte, borders, shield)
    return Layout(left=L, right=R, panels=[L, R], matte=matte, borders=borders,
                  title=title_m, l_head=l_head, r_head=r_head, l_mat=l_mat,
                  r_mat=r_mat, center_mat=center_mat, hint=hint_m, ghosts=ghosts)


def one_panel_layout(scene: Scene, *, title: str, hint: str, dx: float = -3.58,
                     dy: float = 0.10, box: float = 6.4,
                     box_h: float | None = 6.0, unit: float = UNIT,
                     border_color: str = GHOST,
                     grid_shrink: float = 1.0) -> Layout:
    """Single plane on the left, room for a scoreboard on the right.

    Used by the templates whose comparison is number-vs-number or
    same-space (T4, T5, T6 solution mode, T7) rather than panel-vs-panel.
    ``box`` is the WIDTH, ``box_h`` the height -- with no second panel the
    plane can take the full height between the title and the hint.
    """
    P = panel(dx, unit=unit, dy=dy, box=box, box_h=box_h,
              grid_shrink=grid_shrink)
    matte = panel_matte(P.box).set_z_index(Z_MATTE)
    borders = VGroup(P.box.copy().set_stroke(border_color, 3.0, opacity=0.75))
    borders.set_z_index(Z_BORDER)

    title_m = title_text(title)
    hint_m = hint_text(hint)

    scene.add(matte, borders)
    return Layout(left=P, panels=[P], matte=matte, borders=borders,
                  title=title_m, hint=hint_m)


# ---------------------------------------------------------------------------
# Arrows and the ApplyMatrix dance
# ---------------------------------------------------------------------------

def arrow_at(origin: np.ndarray, vec, color: str, *, unit: float = UNIT,
             stroke_width: float = 8.0) -> Arrow:
    """Arrow from a panel origin along ``vec`` (math units)."""
    v = np.asarray(vec, dtype=float).flatten()
    end = origin + np.array([v[0] * unit, v[1] * unit, 0.0])
    if float(np.linalg.norm(end - origin)) < 0.06:
        # A zero-length Arrow divides by zero while scaling its tip.
        d = np.array([v[0], v[1], 0.0])
        n = float(np.linalg.norm(d))
        d = d / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        end = origin + 0.06 * d
    # A heavily zoomed-out panel draws i-hat only ~30px long, and manim's
    # default ratios then thin it to a hairline. Keep short arrows FAT: they
    # are the one thing in the frame the student is told to watch.
    return Arrow(origin, end, buff=0, color=color, stroke_width=stroke_width,
                 max_tip_length_to_length_ratio=0.34,
                 max_stroke_width_to_length_ratio=18)


class VecArrow:
    """An arrow that remembers the math vector it currently represents, so a
    multi-stage template can keep composing transforms on it."""

    def __init__(self, panel_: Panel, vec, color: str, *, stroke_width: float = 8.0):
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


def scoreboard(rows: Sequence[tuple], *, anchor, label_size: int = 22,
               value_size: int = 42, row_buff: float = 0.56,
               max_width: float = 5.3) -> VGroup:
    """[(label, value, color)] -> a stacked two-line-per-row readout block.

    How "student's claim vs true value" appears in the single-plane
    templates, where there is no second panel to carry the comparison.
    """
    group = VGroup()
    for label, value, color in rows:
        lab = fit_text(T(label, font_size=label_size, color=GHOST,
                         weight="BOLD"), max_width)
        val = fit_text(T(value, font_size=value_size, color=color), max_width)
        val.next_to(lab, DOWN, buff=0.14)
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
             color: str = PROBE, font_size: int = 22,
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
               font_size: int = 22, buff: float = 0.34, side: int = 1) -> Text:
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
