"""De-risk test scene: proves Manim renders a side-by-side linear-transformation
comparison in this container WITHOUT any LaTeX installed.

Everything here is LaTeX-free on purpose:
  * All glyphs come from ``Text`` (Pango) -- never ``Tex`` / ``MathTex``.
  * Matrices are hand-built from ``Text`` in a ``VGroup`` plus bracket
    ``VMobject``s, because manim's ``Matrix`` family ALWAYS builds its brackets
    with ``MathTex`` (see ``Matrix._add_brackets``) and therefore always needs
    a TeX install -- including ``IntegerMatrix``, ``DecimalMatrix`` and
    ``MobjectMatrix``.
  * ``NumberPlane`` is created WITHOUT ``include_numbers`` (axis numbers are
    ``DecimalNumber``, whose ``mob_class`` defaults to ``MathTex``).

Render:
    .venv/bin/manim -ql --disable_caching backend/scenes/_derisk_test.py DeriskSideBySide

The helpers at the top (``text_matrix``, ``basis_arrow``, ``panel_matte``) are
written to be lifted straight into the real parameterized scene templates.
"""

from __future__ import annotations

import numpy as np
from manim import (
    BLACK,
    GREEN,
    GREY_B,
    RED,
    WHITE,
    YELLOW,
    Arrow,
    ApplyMatrix,
    Create,
    Difference,
    FadeIn,
    GrowArrow,
    Rectangle,
    Scene,
    Text,
    Transform,
    VGroup,
    VMobject,
    Write,
    config,
)
from manim.mobject.graphing.coordinate_systems import NumberPlane

# --------------------------------------------------------------------------
# Tunables the real templates will take as parameters
# --------------------------------------------------------------------------

# How far the plane is DRAWN in each direction, in math units. Deliberately
# much larger than the visible box: the matte clips the overflow, so the box
# stays full of grid lines even after a shear stretches them apart.
PLANE_RADIUS = 5
# Scene units per math unit. Keep x and y identical, otherwise ApplyMatrix in
# scene space no longer corresponds to the matrix in plane coordinates.
UNIT = 0.78
PANEL_DX = 3.6  # horizontal offset of each panel centre
PANEL_DY = -1.0  # vertical offset of each panel centre
BOX = 4.6  # side length of the visible (matted) box, in scene units

STUDENT_M = np.array([[2.0, 1.0], [0.0, 1.0]])
CORRECT_M = np.array([[2.0, -1.0], [0.0, 1.0]])


# --------------------------------------------------------------------------
# LaTeX-free helpers
# --------------------------------------------------------------------------


def text_matrix(
    rows: list[list[str]],
    *,
    font_size: int = 26,
    color=WHITE,
    h_buff: float = 0.62,
    v_buff: float = 0.46,
    bracket_pad: float = 0.14,
    bracket_lip: float = 0.10,
    stroke_width: float = 2.0,
) -> VGroup:
    """A bracketed matrix built only from ``Text`` -- no LaTeX anywhere.

    This is the drop-in replacement for manim's ``Matrix``, which cannot be
    used without a TeX distribution.
    """
    entries = VGroup()
    n_rows = len(rows)
    n_cols = len(rows[0])
    for i, row in enumerate(rows):
        for j, item in enumerate(row):
            t = Text(str(item), font_size=font_size, color=color)
            # Centre each entry on its grid slot so columns stay aligned even
            # when entries have different widths (e.g. "-1" vs "1").
            t.move_to(
                np.array(
                    [
                        (j - (n_cols - 1) / 2) * h_buff,
                        -(i - (n_rows - 1) / 2) * v_buff,
                        0.0,
                    ]
                )
            )
            entries.add(t)

    half_w = (n_cols - 1) / 2 * h_buff + bracket_pad + 0.14
    half_h = (n_rows - 1) / 2 * v_buff + bracket_pad

    def bracket(sign: int) -> VMobject:
        x = sign * half_w
        lip = sign * bracket_lip
        m = VMobject(stroke_color=color, stroke_width=stroke_width)
        m.set_points_as_corners(
            [
                np.array([x - lip, half_h, 0.0]),
                np.array([x, half_h, 0.0]),
                np.array([x, -half_h, 0.0]),
                np.array([x - lip, -half_h, 0.0]),
            ]
        )
        return m

    return VGroup(entries, bracket(-1), bracket(1))


def basis_arrow(origin: np.ndarray, vec, color) -> Arrow:
    """An arrow from the panel origin along ``vec`` (in math units)."""
    end = origin + np.array([vec[0] * UNIT, vec[1] * UNIT, 0.0])
    return Arrow(
        origin,
        end,
        buff=0,
        color=color,
        stroke_width=6,
        max_tip_length_to_length_ratio=0.28,
        max_stroke_width_to_length_ratio=9,
    )


def panel_matte(*panel_rects: Rectangle) -> VMobject:
    """A full-frame black mask with a rectangular hole per panel.

    Needed because ``ApplyMatrix`` on a ``NumberPlane`` pushes grid lines well
    outside the panel (a shear can double the extent), and manim's cairo
    renderer has no clipping. Painting an opaque matte on top with a high
    ``z_index`` is the reliable way to keep two panels visually separate.
    Uses ``Difference`` (skia-pathops), which ships with manim.
    """
    full = Rectangle(width=config.frame_width + 1, height=config.frame_height + 1)
    matte: VMobject = full
    for r in panel_rects:
        matte = Difference(matte, r)
    matte.set_fill(BLACK, opacity=1).set_stroke(width=0)
    return matte


def make_panel(dx: float):
    """Build one panel: plane + basis vectors, centred at ``dx``."""
    centre = np.array([dx, PANEL_DY, 0.0])
    length = 2 * PLANE_RADIUS * UNIT
    plane = NumberPlane(
        x_range=[-PLANE_RADIUS, PLANE_RADIUS, 1],
        y_range=[-PLANE_RADIUS, PLANE_RADIUS, 1],
        x_length=length,
        y_length=length,
        # No include_numbers: axis numbers are DecimalNumber -> MathTex -> LaTeX.
        background_line_style={
            "stroke_color": "#3B6CB7",
            "stroke_width": 1.6,
            "stroke_opacity": 0.65,
        },
        axis_config={"stroke_color": GREY_B, "stroke_width": 2.4},
    )
    plane.move_to(centre)
    origin = plane.get_origin()
    i_hat = basis_arrow(origin, (1, 0), GREEN)
    j_hat = basis_arrow(origin, (0, 1), RED)
    return plane, i_hat, j_hat, origin, centre


class DeriskSideBySide(Scene):
    def construct(self) -> None:
        self.camera.background_color = BLACK

        l_plane, l_i, l_j, l_origin, l_centre = make_panel(-PANEL_DX)
        r_plane, r_i, r_j, r_origin, r_centre = make_panel(+PANEL_DX)

        # --- mattes keep each panel's transformed grid inside its own box ---
        l_box = Rectangle(width=BOX, height=BOX).move_to(l_centre)
        r_box = Rectangle(width=BOX, height=BOX).move_to(r_centre)
        matte = panel_matte(l_box, r_box).set_z_index(10)
        borders = VGroup(
            l_box.copy().set_stroke(GREY_B, 1.6, opacity=0.55),
            r_box.copy().set_stroke(GREY_B, 1.6, opacity=0.55),
        ).set_z_index(11)

        # --- headings (z_index above the matte) ---
        title = Text(
            "Your step 3, applied to the plane", font_size=32, color=WHITE
        ).move_to(np.array([0.0, 3.58, 0.0]))
        l_head = Text("WHAT YOU WROTE", font_size=22, color=YELLOW).move_to(
            np.array([-PANEL_DX, 2.82, 0.0])
        )
        # The reference side is the TARGET, not an answer key: no heading and
        # no numbers that hand the student the correction. See
        # REVEAL_CORRECT_VALUES in common.py -- the real templates gate this.
        r_head = Text("WHAT THE PROBLEM ASKS FOR", font_size=22, color=GREEN).move_to(
            np.array([PANEL_DX, 2.82, 0.0])
        )
        l_mat = text_matrix([["2", "1"], ["0", "1"]], color=YELLOW).move_to(
            np.array([-PANEL_DX, 2.02, 0.0])
        )
        r_mat = text_matrix([["?", "?"], ["?", "?"]], color=GREY_B).move_to(
            np.array([PANEL_DX, 2.02, 0.0])
        )
        hint = Text(
            "watch the second basis vector",
            font_size=24,
            color=RED,
        ).move_to(np.array([0.0, -3.66, 0.0]))
        for m in (title, l_head, r_head, l_mat, r_mat, hint):
            m.set_z_index(12)

        # ------------------------------------------------------------------
        # Timeline (~8s)
        # ------------------------------------------------------------------
        self.add(matte, borders)
        self.play(
            Create(l_plane), Create(r_plane), FadeIn(title), run_time=1.2
        )
        self.play(
            GrowArrow(l_i),
            GrowArrow(l_j),
            GrowArrow(r_i),
            GrowArrow(r_j),
            FadeIn(l_head),
            FadeIn(r_head),
            FadeIn(l_mat),
            FadeIn(r_mat),
            run_time=1.0,
        )
        self.wait(0.4)

        # The transform. ApplyMatrix moves the grid; the basis vectors are
        # animated with Transform onto a freshly built Arrow so their tips stay
        # crisp instead of being sheared into a wedge. This is exactly
        # consistent with ApplyMatrix: under p_t = (1-t)p + t*Mp the arrow tip
        # travels a straight line, which is what Transform interpolates.
        l_i_t = basis_arrow(l_origin, STUDENT_M @ np.array([1.0, 0.0]), GREEN)
        l_j_t = basis_arrow(l_origin, STUDENT_M @ np.array([0.0, 1.0]), RED)
        r_i_t = basis_arrow(r_origin, CORRECT_M @ np.array([1.0, 0.0]), GREEN)
        r_j_t = basis_arrow(r_origin, CORRECT_M @ np.array([0.0, 1.0]), RED)

        self.play(
            ApplyMatrix(STUDENT_M, l_plane, about_point=l_origin),
            Transform(l_i, l_i_t),
            Transform(l_j, l_j_t),
            ApplyMatrix(CORRECT_M, r_plane, about_point=r_origin),
            Transform(r_i, r_i_t),
            Transform(r_j, r_j_t),
            run_time=3.0,
        )
        self.wait(0.6)
        self.play(Write(hint), run_time=1.0)
        self.wait(0.8)
