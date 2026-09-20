# Manim Scene Template Catalog

**Seven hand-written `Scene` classes.** The LLM never writes Manim code — it picks a
`template` id and fills a small typed `params` dict. Every template puts the student's
**claimed** object next to the **true** one so the difference is self-evident, and closes
on a positional hint that never states the correction.

Companion docs: [`ERROR_TAXONOMY.md`](ERROR_TAXONOMY.md) (which error routes where),
[`RENDERING.md`](RENDERING.md) (how to render, and the LaTeX minefield).

**Hard constraint, enforced throughout: there is no LaTeX in this container.** No `Tex`,
no `MathTex`, no `Matrix`/`IntegerMatrix`/`DecimalMatrix`/`MobjectMatrix`, no bare
`DecimalNumber`. Every glyph comes from `Text` or `MarkupText`. Matrices are `VGroup`s of
`Text` inside two hand-drawn bracket `VMobject`s — see [`text_matrix`](#1-text_matrix--the-latex-free-matrix).

---

## 0. Reconciliation with ERROR_TAXONOMY.md

`ERROR_TAXONOMY.md` was written first and names **nine** template ids across its 19 error
entries. This catalog consolidates those to **seven classes**, because three of them are
the same animation with different parameters. The taxonomy's ids all still resolve — keep
using them in routing code, they are registered as aliases so **no edit to
`ERROR_TAXONOMY.md` is required**.

| Taxonomy id | Resolves to | How |
|---|---|---|
| `GridTransformCompare` | `GridTransformCompare` | identity |
| `CompositionOrderCompare` | `GridTransformCompare` | `stages` = 2 matrices, `pause_between_stages` > 0 |
| `InverseRoundTrip` | `GridTransformCompare` | `stages` = `[M, S_claimed]` vs `[M, M_inv]`, `ghost_reference=True` |
| `EigenRayTest` | `EigenRayTest` | identity |
| `DeterminantAreaCompare` | `DeterminantAreaCompare` | identity |
| `VectorOpCompare` | `VectorOpCompare` | identity |
| `SpanCompare` | `SpanCompare` | identity |
| `RowOpLinePivot` | `LineSystemCompare` | `mode="row_op"` |
| `SolutionPointCheck` | `LineSystemCompare` | `mode="solution"` |
| `StaticStepHighlight` | `StaticStepHighlight` | identity (`pairing=None`) |

Two notes on the reconciliation:

- **`SolutionPointCheck` was dangling.** `ERROR_TAXONOMY.md` §LA12 routes to it as a
  fallback, but it is absent from that doc's own catalog table. It exists here as
  `LineSystemCompare(mode="solution")`.
- **Why the three-into-one merge is principled, not just budget-cutting.**
  `GridTransformCompare`, `CompositionOrderCompare` and `InverseRoundTrip` are all
  *"apply an ordered sequence of linear maps to a grid; student's sequence in the left
  panel, correct sequence in the right."* A one-element sequence is the plain compare; a
  two-element sequence with a pause is the composition-order story; a two-element sequence
  whose second element is the claimed inverse is the round trip. One implementation, one
  set of bugs to fix, three behaviours. This is the single biggest schedule win in the
  catalog — it turns three P0/P1 builds into one.

The brief's suggested `MatrixProductSteps` (row-by-column pairing) lives as
`StaticStepHighlight(pairing={...})`, see [T3](#t3--staticstephighlight). The name is
inherited from the taxonomy and is mildly inaccurate in pairing mode; keeping it costs one
sentence of explanation, whereas renaming costs 19 edits in a doc at 3am. Keep the name.

---

## 1. The contract

### 1.1 Param envelope

The planner emits exactly this, as JSON:

```json
{ "template": "GridTransformCompare", "params": { "...": "..." } }
```

The backend then follows `RENDERING.md` §"Option A: in-process with `tempconfig`":

```python
from backend.scenes import TEMPLATES          # {id: class}, aliases included
cls = TEMPLATES[payload["template"]]
cls.P = cls.validate(payload["params"])       # raises SceneParamError
cls().render()
```

`P` is a single class attribute holding the whole validated dict. One attribute, not a
dozen, because `manim.config` and class attributes are global and not thread-safe
(`RENDERING.md` §Option A) — one assignment is one thing to serialize behind the lock.

### 1.2 Who fills which parameter

This split matters and is easy to get wrong.

| Filled by | Parameters | Why |
|---|---|---|
| **Backend (sympy)** | every matrix, vector, scalar, determinant, eigenvalue, line coefficient, and their `*_display` string forms | These are *computed*. An LLM retyping a matrix sympy already produced is a pure opportunity to corrupt it. Format with `fmt_num`, never `str()`. |
| **LLM (planner)** | `template`, `title`, `student_label`, `correct_label`, `hint`, `op`, `mode`, `focus`, `stage_labels` | These are *editorial* — which story to tell and how to word it. |

Numbers crossing into `params` are plain JSON ints/floats/strings. **Never put a sympy
object in `params`** — `Rational` and `Matrix` do not survive JSON, and `float(Rational)`
silently loses the exactness the verifier worked for. Convert with `fmt_num` for display
and `float()` for geometry, at the boundary, deliberately.

### 1.3 Validation and the fallback ladder

Every template exposes `@classmethod validate(params) -> dict` that raises
`SceneParamError`. The backend catches it and degrades — it **never** lets a render crash
reach the demo:

```
chosen template  ->  (SceneParamError)  ->  StaticStepHighlight  ->  (still fails)  ->  still-frame PNG + hint text
```

Per-template guards are listed with each template below. The universal ones:

- every matrix is square and 2×2 or 3×3, entries finite, `abs(entry) <= 50`
- no vector is the zero vector where a direction is needed
- resulting geometry fits: `max |M @ e_i| * UNIT <= 3.5 * BOX` or the scene auto-zooms
  (`fit_unit()` in the helpers) rather than drawing off-frame
- `hint` is non-empty and passes the §1.4 check
- total scene duration lands in **8.0–14.0s**

### 1.4 Hint discipline (product requirement, not style)

The whole premise is that the student *sees* the error rather than being told it. A hint
that leaks the answer destroys the product. Hints are **positional and observational**:

- **Allowed:** name a location ("your step 3", "the second column"), direct attention
  ("watch whether the arrow stays on its line"), state an observable ("the counter stops
  before your number").
- **Forbidden:** the corrected value in any form; "should be"; "instead of"; "you forgot";
  naming the missing operation ("divide by the determinant").

Cheap enforcement, worth the ten lines — run in `validate`:

```python
BANNED = ("should be", "instead of", "you forgot", "the correct", "actually is", "is wrong because")
def check_hint(hint: str, forbidden_values: list[str]) -> None:
    low = hint.lower()
    if any(b in low for b in BANNED): raise SceneParamError(f"hint states the correction: {hint!r}")
    for v in forbidden_values:                      # the true answer's rendered entries
        if v and v in hint: raise SceneParamError(f"hint leaks the value {v!r}")
```

Pass the correct answer's `fmt_num` strings as `forbidden_values`. Good models still leak
under time pressure; this catches it for free.

---

## 2. shared_helpers — `backend/scenes/common.py`

One module every template imports. It exists so each template file stays roughly
80–140 lines: the layout chrome, the LaTeX workarounds, and the three `ApplyMatrix`
gotchas from `RENDERING.md` are written **once**.

### 2.0 Palette and layout constants

```python
BG       = "#000000"
GRID     = "#3B6CB7"   # NumberPlane background lines
AXIS     = GREY_B
I_HAT    = "#83C167"   # manim GREEN  - 3Blue1Brown convention, keep it
J_HAT    = "#FC6255"   # manim RED    - ditto
STUDENT  = "#FFB020"   # amber: everything the student claimed, AND the hint
CORRECT  = "#E9ECEF"   # near-white: the true object
GHOST    = "#6C757D"   # grey: reference overlays, "what you'd need" outlines
PROBE    = "#C77DFF"   # violet: unreachable targets, residual markers
```

> **Fix a bug inherited from the de-risk scene.** `_derisk_test.py` colors the *correct*
> panel heading `GREEN` — the same green as `i_hat`. On a projector the heading and the
> basis vector read as "the same thing," which is exactly the wrong association. Panel
> identity must ride on **amber vs near-white** and never on green or red, because green
> and red are permanently spoken for by î and ĵ. Six colors total, zero collisions.

```python
UNIT       = 0.78   # scene units per math unit. x and y MUST share it (RENDERING.md #2)
PLANE_RADIUS = 5    # draw the plane far past the box; the matte clips (RENDERING.md #4)
PANEL_DX   = 3.6
PANEL_DY   = -1.0
BOX        = 4.6
TITLE_Y, HEAD_Y, MAT_Y, HINT_Y = 3.58, 2.82, 2.02, -3.66

Z_PLANE, Z_OVERLAY, Z_MATTE, Z_BORDER, Z_CHROME, Z_FLASH = 0, 5, 10, 11, 12, 13
```

The z-index bands are load-bearing: the matte at 10 is what keeps a sheared left panel out
of the right panel, so anything that must stay readable sits above it.

### 2.1 `text_matrix` — the LaTeX-free matrix

Lifted from `_derisk_test.py`, promoted to a class so templates can address cells.
`Matrix.__init__` builds its brackets with `MathTex` unconditionally
(`RENDERING.md` §"The big one"), so this is not an optimization — it is the only way to
draw a matrix here.

```python
class TextMatrix(VGroup):
    """Bracketed matrix from Text only. Entries centred on a fixed pitch so columns
    stay aligned when widths differ ('-1' vs '1')."""
    def __init__(self, rows, *, font_size=26, color=WHITE,
                 h_buff=0.62, v_buff=0.46, bracket_pad=0.14, ...): ...
    def entry(self, i, j) -> Text: ...      # cell accessor  -> highlight/replace one entry
    def row(self, i) -> VGroup: ...         # -> sweep highlights in pairing mode
    def col(self, j) -> VGroup: ...
    def cell_center(self, i, j) -> np.ndarray: ...
```

`entry`/`row`/`col` are what make T3's pairing sweep and T1's "which column moved" flash
short. Without them each template re-derives index arithmetic over a flat `VGroup`.

### 2.2 `fmt_num` — readable numbers without `\frac`

```python
def fmt_num(x, max_den: int = 20) -> str:
    """int -> '3';  nice rational -> '2/5';  else -> '0.71'.  Never '0.4000000001'."""
```

Non-negotiable: `ERROR_TAXONOMY.md` §LA07's correct inverse is
`[[2/5,-1/10],[-1/5,3/10]]`. With no LaTeX there is no `\frac`, and `str(float)` gives
`0.4` / `0.30000000000000004`. Render rationals as `a/b` on one line. Use it for **every**
number that reaches the screen, including live readouts.

### 2.3 `panel` and `two_panel_layout` — the chrome

```python
@dataclass
class Panel:
    plane: NumberPlane; origin: np.ndarray; center: np.ndarray; box: Rectangle

def panel(dx: float, *, radius=PLANE_RADIUS, unit=UNIT, dy=PANEL_DY) -> Panel: ...

def two_panel_layout(scene, *, title, student_label, correct_label,
                     student_rows=None, correct_rows=None, hint,
                     center_rows=None, ghost_reference=False) -> Layout: ...
```

`two_panel_layout` builds, z-indexes and returns: both panels, the `panel_matte`, the two
borders (amber left / near-white right), title, both headings, the two `TextMatrix`
displays, and the hint `Text` (created but **not** added — templates `Write` it in the
final beat). `center_rows` puts a single shared matrix under the title instead of one per
panel, which is what T2 needs (one matrix `M`, two different vectors).

This one function is ~60 lines used by five templates. It is the main reason the templates
are short.

### 2.4 `panel_matte` — clipping, because cairo cannot

```python
def panel_matte(*panel_rects: Rectangle) -> VMobject:
    """Full-frame black rect with a hole per panel, via Difference (skia-pathops)."""
```

Verbatim from the de-risk scene. `RENDERING.md` §3: a shear roughly doubles the plane's
extent and the cairo renderer has no clipping primitive, so an opaque matte on top is the
only reliable separation. Combined with `PLANE_RADIUS=5` into a `BOX` showing ~±2.9, the
panel stays full of lattice before *and* after the transform.

### 2.5 `apply_matrix_anims` — the arrowhead gotcha, encapsulated

```python
def apply_matrix_anims(panel: Panel, M, arrows: dict[tuple, Arrow], *, run_time,
                       extra=()) -> list[Animation]:
    """ApplyMatrix on the plane + Transform each arrow onto a freshly built arrow at M@v.
    Returns animations (does NOT play) so both panels run inside one scene.play()."""
```

Encapsulates two `RENDERING.md` traps that will otherwise be re-hit in every template:

- `about_point=panel.origin` — the default `ORIGIN` translates any off-centre panel away
  instead of transforming it in place (§2).
- Arrows are **not** fed to `ApplyMatrix`; each is `Transform`ed onto a fresh
  `arrow_at(origin, M @ v)`. Under `p_t = (1-t)p + t·Mp` the tip travels a straight line,
  which is exactly what `Transform` interpolates — so the vector stays glued to the grid
  while keeping a crisp head instead of being sheared into a bent wedge (§5).

### 2.6 Readouts, markers, and the rest

```python
def arrow_at(origin, vec, color, *, unit=UNIT, stroke_width=6) -> Arrow
def live_text(fn, **kw) -> Mobject          # always_redraw(lambda: Text(fn(), **kw))
def signed_area(poly) -> float              # shoelace on poly.get_vertices()
def scoreboard(rows, *, anchor) -> VGroup   # [(label, value, color)] -> aligned two-column
def span_line(origin, vec, *, color, dashed=True) -> Line   # the infinite line through vec
def residual(p, q, *, label=None, color=PROBE) -> VGroup    # dashed gap + optional length
def right_angle(corner, d1, d2, *, size=0.22, color) -> VMobject
def ghost_of(mobj) -> VMobject              # grey, 35% opacity, behind
def iso_project(v3) -> np.ndarray           # fixed axonometric R^3 -> R^2, see 2.7
def fit_unit(vectors, *, box=BOX) -> float  # shrink UNIT so the result stays in frame
def hint_beat(scene, layout, run_time=1.0)  # Write(hint); identical everywhere
```

`signed_area` is verified exact: shoelace on a `Polygon`'s vertices after `apply_matrix`
equals `|det M|` to 1e-9, and it keeps the **sign**, which is how the orientation flip
(`ERROR_TAXONOMY.md` §LA06) gets rendered.

`scoreboard` is how "student's claim vs true value" appears in templates whose geometry is
one shared plane (T4, T5, T6-solution, T7) rather than two panels.

### 2.7 `iso_project` — 3D without `ThreeDScene`

3×3 determinants (LA05), R³ spans (LA14) and cross products (LA17) need a solid. **Do not
use `ThreeDScene`.** It is slower, it fights the matte-based panel clipping, and camera
orientation is one more thing to tune at 4am.

Instead project R³ to R² with a fixed axonometric matrix and draw ordinary 2D `Polygon`s:

```python
_ISO = np.array([[ 0.866, -0.866, 0.0],
                 [ 0.5  ,  0.5  , 1.0]])     # 30 degrees, classic isometric
def iso_project(v3): return np.array([*(_ISO @ np.asarray(v3, float)), 0.0])
```

Consequence for T4/T7: a 3×3 matrix cannot be handed to `ApplyMatrix` (which acts on
*scene* coordinates). Animate instead with a `ValueTracker` `t` and `always_redraw`,
rebuilding the projected solid from `M_t = (1-t)·I + t·M` each frame. The volume readout
is then `abs(det(M_t))`, which is honest at every instant. **All 3D modes are P2.**

---

## 3. The templates

Shared rhythm, so the app feels like one product rather than seven demos:

> **setup → objects → hold → the act → hold → mark the divergence → hint → hold**

The "mark the divergence" beat is the product. Without it the viewer watches two
animations and is left to spot the difference; with it the frame points at the exact place
the student's claim broke, while still never naming the fix.

### T1 — `GridTransformCompare`

`backend/scenes/grid_transform.py` · **P0, the workhorse** · aliases
`CompositionOrderCompare`, `InverseRoundTrip`

Two copies of the plane, same grid, same î/ĵ. Apply the student's sequence on the left and
the correct sequence on the right. Most linear-algebra errors reduce to *"your matrix sends
the basis vectors somewhere else."*

**Covers:** LA01, LA02, LA07, LA08, LA16 — **and every Layer-1-only detection**, i.e. any
step verified wrong whose specific signature matched nothing in the taxonomy. That
fallback role is why it is built first: it makes the app's coverage unbounded rather than
capped at 19 errors.

```jsonc
{
  "student_stages": [[[2,1],[0,1]]],        // 1-3 matrices, applied in order
  "correct_stages": [[[2,-1],[0,1]]],
  "student_display": [["2","1"],["0","1"]], // fmt_num strings, backend-filled
  "correct_display": [["2","-1"],["0","1"]],
  "stage_labels": ["apply A", "then B"],    // optional, one per stage
  "title": "Your step 3, applied to the plane",
  "student_label": "WHAT YOU WROTE",
  "correct_label": "WHAT THE STEP SHOULD DO",
  "hint": "watch the second basis vector",
  "ghost_reference": false,                 // faint original grid underneath (round trip)
  "pause_between_stages": 0.8,
  "track_vectors": [[1,0],[0,1]]            // defaults to the basis
}
```

**Storyboard — one stage, 8.0s** (matches the verified de-risk render exactly):

| t | dur | beat |
|---|---|---|
| 0.0 | 1.2 | `Create` both planes, `FadeIn` title. If `ghost_reference`, the grey reference grid is added now and never moves. |
| 1.2 | 1.0 | `GrowArrow` î/ĵ both panels; `FadeIn` headings and both `TextMatrix` displays. |
| 2.2 | 0.4 | hold — the viewer reads the two matrices. |
| 2.6 | 3.0 | **the act.** `apply_matrix_anims` on both panels simultaneously. |
| 5.6 | 0.6 | hold on the two end states. |
| 6.2 | 1.0 | **mark the divergence:** `Indicate` the one basis arrow that differs most, in both panels at once. |
| 7.2 | 0.8 | `Write` hint, then settle. |

**Storyboard — two stages, 11.6s** (composition order, and the inverse round trip):

| t | dur | beat |
|---|---|---|
| 0.0 | 1.2 | planes + title |
| 1.2 | 1.0 | arrows, headings, matrices, stage caption 1 |
| 2.2 | 0.4 | hold |
| 2.6 | 2.5 | **stage 1** both panels |
| 5.1 | 0.8 | **pause on the intermediate.** For LA02 this is the whole point — both grids are still identical here. Pulse both borders white to say "same so far". |
| 5.9 | 0.5 | swap stage caption 1 → 2 |
| 6.4 | 2.5 | **stage 2** — the panels diverge |
| 8.9 | 0.7 | hold |
| 9.6 | 1.2 | mark divergence + `Write` hint |
| 10.8 | 0.8 | settle |

Three stages only at `run_time=2.0` per stage (13.9s total); beyond that, cut stages.

**`ghost_reference` is what makes the round trip legible.** For LA07 the student's
`M · S = 10·I` exactly: the grid comes home perfectly square and perfectly un-rotated, just
ten times too large. Without the faint original grid underneath there is no ruler in frame
and "ten times too big" reads as "zoomed in". With it, the overshoot is measurable by eye.
For LA08 the miss is small — set `fit_unit` to zoom to a ±2 window or the drift is lost.

**Guards:** every stage matrix 2×2; `abs(det) >= 0.05` on any stage whose panel must stay
readable (a near-singular stage collapses the grid to a line and the next stage has
nothing to act on — route to `StaticStepHighlight`); `len(student_stages) == len(correct_stages)`.

### T2 — `EigenRayTest`

`backend/scenes/eigen_ray.py` · **P0**

Draw the infinite line spanned by a vector. Apply `M`. Watch whether the image stays glued
to that line or lifts off it. This is the definition of an eigenvector rendered as a yes/no
question a viewer answers in under a second.

**Covers:** LA09 (hero), LA10 (via `mode="eigenvalue"`), and any "is this an eigenvector"
claim.

```jsonc
{
  "M": [[2,1],[1,2]],
  "M_display": [["2","1"],["1","2"]],   // ONE matrix -> centered under the title
  "v_claimed": [1,0],
  "v_correct": [1,1],
  "lambda_claimed": 8.22,               // eigenvalue mode only; ghost arrow at lambda*v
  "lambda_correct": 5,
  "mode": "vector",                     // "vector" (LA09) | "eigenvalue" (LA10)
  "student_label": "YOUR VECTOR", "correct_label": "AN EIGENVECTOR",
  "title": "...", "hint": "..."
}
```

**Storyboard — `mode="vector"`, 9.4s:**

| t | dur | beat |
|---|---|---|
| 0.0 | 1.2 | `Create` both planes; `FadeIn` title and the shared `M` display (`center_rows`). |
| 1.2 | 0.8 | `GrowArrow` `v_claimed` (amber, left) and `v_correct` (near-white, right); headings in. |
| 2.0 | 1.0 | **`Create` the span line** through each vector, dashed, through the origin both ways. Its own beat on purpose: the viewer must register *"this is the line it has to stay on"* **before** the transform, or the payoff lands on nothing. |
| 3.0 | 0.4 | hold |
| 3.4 | 3.0 | **the act.** `apply_matrix_anims` on both panels. The span lines are added to the scene, **not** to the plane, so `ApplyMatrix` leaves them fixed — they are the reference, and a reference that moves proves nothing. |
| 6.4 | 1.0 | **mark the divergence.** Left: `residual()` draws a dashed perpendicular from the image tip to the claimed line, labelled with the gap. Right: `Indicate` the line and vector together — still welded. |
| 7.4 | 0.4 | hold |
| 7.8 | 1.6 | `Write` hint; settle. |

**`mode="eigenvalue"` (LA10)** keeps the beats but changes the content: both panels show
the *same, correct* eigenvector direction, and the left additionally carries a grey ghost
arrow out at `lambda_claimed · v`. The 6.4 beat then draws the gap between the real tip
(`lambda_correct · v`) and the ghost tip. Direction is right, distance is wrong — a length
story, not a shape story.

**Guards:** `v_claimed` and `v_correct` nonzero; in eigenvalue mode **`im(lambda) == 0` or
refuse** — a complex claimed eigenvalue has nothing to draw on a real plane, and this is
the specific gate `ERROR_TAXONOMY.md` §3 calls for. Refuse → `StaticStepHighlight`.

### T3 — `StaticStepHighlight`

`backend/scenes/step_focus.py` · **P0** · subsumes the brief's `MatrixProductSteps`

The honest fallback, and the safety net whenever parsing or verification degrades. Two
modes.

**Covers:** LA03 and LA18 (both have *no* geometry, by construction), LA01 (pairing mode),
plus every `SceneParamError` fallback in the app.

```jsonc
{
  "lines": [{"kind":"matrix","rows":[["2","1"],["1","3"]],"prefix":"A = "},
            {"kind":"text","text":"AB = ..."}],
  "focus": {"line": 1, "cell": [0,1]},        // or {"line":1,"chars":[5,9]}
  "annotation": "this side is a number, that side is an arrow",
  "pairing": null,                            // or the object below
  "title": "...", "hint": "..."
}
```

**Storyboard — static mode, 8.0s:**

| t | dur | beat |
|---|---|---|
| 0.0 | 1.0 | `FadeIn` title |
| 1.0 | 1.4 | the student's own steps write in, stacked and centred, `LaggedStart` at 0.35 stagger |
| 2.4 | 0.6 | hold |
| 3.0 | 1.2 | a `SurroundingRectangle` (amber) grows around the focused cell or character range |
| 4.2 | 1.4 | it pulses twice (`Indicate`). **For LA03 specifically:** circle the two *inner* dimensions, connect them with a dashed line, and print both counts beside it — the shapes make the argument by themselves |
| 5.6 | 0.8 | `FadeIn` annotation below |
| 6.4 | 1.6 | `Write` hint; settle |

**Storyboard — pairing mode, 9.4s** (LA01, row-by-row multiplication):

```jsonc
"pairing": {"A_rows": [["2","1"],["1","3"]], "B_rows": [["1","2"],["0","1"]],
            "target": [0,0], "student_entry": "4", "correct_entry": "2",
            "wrong_source": "row"}
```

| t | dur | beat |
|---|---|---|
| 0.0 | 1.0 | title; `A`, `B`, `=`, and a result matrix with faint placeholder entries |
| 1.0 | 1.0 | settle |
| 2.0 | 2.0 | **correct pairing.** A dot sweeps row `i` of A left→right while a second dot sweeps **column** `j` of B top→bottom; they meet and the true entry pops into cell `(i,j)` in near-white |
| 4.0 | 2.0 | **student pairing.** Replay — but the second dot sweeps **row** `j` of B, so *both* sweeps run horizontally. Their entry pops in amber over the same cell, the correct one ghosted behind |
| 6.0 | 1.0 | dashed box around cell `(i,j)`, the two candidate entries side by side |
| 7.0 | 0.6 | hold |
| 7.6 | 1.8 | `Write` hint; settle |

The tell is **the direction of the second sweep** — across instead of down. That is a
purely positional observation, so the hint can point straight at it without stating the
fix. This matters because LA01 is the one multiplication error with *no* usable geometry:
`det(Bᵀ) = det(B)`, so both grids stretch by exactly the same amount
(`ERROR_TAXONOMY.md` §LA01) and the area story is unavailable. Pairing mode is the answer.

**Guards:** none that can fail — this is the bottom of the ladder. `validate` clamps
`len(lines) <= 6` and truncates long strings rather than raising. **`StaticStepHighlight`
must never raise.**

### T4 — `DeterminantAreaCompare`

`backend/scenes/determinant_area.py` · **P1** (2×2) / **P2** (3×3)

The unit square morphs under `M` with a live area readout, next to the student's frozen
number. Orientation flip is rendered as the sheet physically turning over.

**Covers:** LA04, LA06 (sign flip), LA05 (3×3, P2).

```jsonc
{
  "M": [[3,4],[1,2]], "M_display": [["3","4"],["1","2"]],
  "claimed_det": "10", "actual_det": "2",
  "show_ghost_scale": true,
  "title": "...", "hint": "..."
}
```

Layout is **not** two panels: the comparison is number-vs-number, so the plane takes the
left ~60% and a `scoreboard` on the right holds `YOUR ANSWER 10` (amber, static, filled
from the start) above `AREA ON SCREEN 0.00` (near-white, live).

**Storyboard — 2×2, 10.2s:**

| t | dur | beat |
|---|---|---|
| 0.0 | 1.2 | `Create` the single plane; title; scoreboard with the student's number already showing |
| 1.2 | 0.8 | `FadeIn` the unit square (two-tone fill: `CORRECT` face up), `GrowArrow` î/ĵ, `M` display |
| 2.0 | 0.4 | hold |
| 2.4 | 3.5 | **the act.** `ApplyMatrix` on plane, square and arrows. The readout is `live_text(lambda: fmt_num(abs(signed_area(sq))))` so it ticks organically. An updater recolors the fill the instant `signed_area` changes sign |
| 5.9 | 0.6 | readout locks and flashes |
| 6.5 | 1.7 | **mark the divergence.** `show_ghost_scale` tiles `floor(claimed)` grey outline unit squares (plus a partial one) from the origin — *"your answer means this much area"* — dwarfing the real parallelogram |
| 8.2 | 2.0 | `Write` hint; settle |

**Verified, not assumed.** I rendered this mechanic end-to-end before specifying it. With
`M = [[0,2],[1,0]]` (det = −2) the `always_redraw` readout sampled 32 times through a 2s
`ApplyMatrix` and traced **+1.00 → 0.00 → −2.00**, final `abs` matching `|det|` exactly,
and the fill recolored on the crossing.

That middle value is worth designing around rather than hiding: **the area genuinely
passes through zero** when the determinant is negative, because the interpolated matrix
`(1-t)I + tM` is singular at some `t`. On screen the sheet turns edge-on and vanishes for
one frame before coming back the other color. That is not a glitch — it is the most
literal possible picture of "the orientation flipped", and it is the entire payoff for
LA06. Let it play; do not smooth it out.

**3×3 mode (P2):** unit cube via `iso_project`, animated with a `ValueTracker` +
`always_redraw` rebuilding from `M_t` (a 3×3 cannot go through `ApplyMatrix`, §2.7),
volume readout `abs(det(M_t))`. LA05 is chosen so the true volume is 1 and the claim is
−79: almost nothing happens on screen while the claim demands a cube swelling past the
frame and turning inside out.

**Guards:** `abs(claimed_det - actual_det) > 1e-9` — if they agree there is no story, and
some *other* step is the error; `abs(claimed_det) <= 60` or the ghost tiling is skipped
(60 squares is noise, not a message).

### T5 — `VectorOpCompare`

`backend/scenes/vector_op.py` · **P1**

One plane, both results drawn, plus the **invariant overlay** that the student's answer
violates. Unlike the grid templates this is deliberately single-panel: these results live
in the same space, so drawing them together is the honest comparison.

**Covers:** LA11 (`normalize`), LA17 (`cross`, P2), LA19 (`projection`).

```jsonc
{
  "op": "projection",                  // "normalize" | "projection" | "cross" | "generic"
  "u": [3,4], "v": [2,1],
  "w_claimed": [8.94,4.47], "w_correct": [4,2],
  "labels": {"u":"u","v":"v"},
  "readouts": [["your residual . v","-12.36"], ["correct residual . v","0.00"]],
  "title": "...", "hint": "..."
}
```

Overlay by `op`: `normalize` → unit `Circle`; `projection` → v's infinite line plus a
`right_angle` at each foot; `cross` → the iso-projected translucent sheet spanned by u,v.

**Storyboard — 10.0s:**

| t | dur | beat |
|---|---|---|
| 0.0 | 1.0 | `Create` plane; title |
| 1.0 | 1.0 | `GrowArrow` u and v with labels |
| 2.0 | 1.2 | **`Create` the invariant overlay.** Its own beat, before either answer appears — the viewer has to learn the rule before watching it break |
| 3.2 | 0.4 | hold |
| 3.6 | 1.5 | `GrowArrow` `w_correct` (near-white) — its marker **snaps closed** / its tip lands exactly on the circle, with a small `Flash` |
| 5.1 | 1.5 | `GrowArrow` `w_claimed` (amber) — its marker **fails to close**, drawn in violet and `Wiggle`d; or its tip stops short of the circle with a dashed gap |
| 6.6 | 1.2 | `FadeIn` the numeric `readouts`, amber row against near-white row |
| 7.8 | 2.2 | hold; `Write` hint; settle |

**Correct first, then student — always.** The viewer needs to see what "closing" looks
like before they can recognise a failure to close. Reversed, the first marker is
meaningless and the beat is wasted.

For LA19 the frame carries two independent absurdities at once: the right-angle marker
does not close (residual·v = −12.36, not 0) *and* their "shadow" is plainly longer than the
thing casting it. Either one alone would land.

**Guards:** `v` nonzero for projection/normalize; `u`,`v` non-parallel for `cross` (a
degenerate sheet has no normal to stand out of); `fit_unit` on all four vectors — LA19's
claimed point at `(8.94,4.47)` is well outside a default window and will silently leave
frame without it.

### T6 — `LineSystemCompare`

`backend/scenes/line_system.py` · **P1** (`solution`) / **P2** (`row_op`) · aliases
`RowOpLinePivot`, `SolutionPointCheck`

Each equation is a line. A **legal** row operation produces a new line that still passes
through the common intersection — it pivots about that point like a hinge. An illegal one
swings the line off it.

**Covers:** LA12, LA13, and any `Ax = b` solution claim.

```jsonc
{
  "mode": "row_op",                        // "row_op" | "solution"
  "equations": [[1,2,5],[3,4,11]],         // ax + by = c
  "student_result_line": [0,-2,-6], "correct_result_line": [0,-2,-4],
  "op_label": "R2 - 3R1",
  "x_claimed": [-1,3], "x_correct": [1,2], // solution mode
  "substitutions": [["5","5"],["9","11"]], // solution mode: LHS vs required RHS
  "title": "...", "hint": "..."
}
```

**Storyboard — `mode="row_op"`, 10.6s** (two panels, same two original lines in each):

| t | dur | beat |
|---|---|---|
| 0.0 | 1.2 | planes + title |
| 1.2 | 1.2 | `Create` both equation lines in both panels; a `Dot` pops in at the intersection with a ring |
| 2.4 | 0.4 | hold; `FadeIn` `op_label` centred |
| 2.8 | 0.6 | **`Indicate` the intersection dot in both panels** — establishing the hinge is the whole setup; skip it and the payoff has no anchor |
| 3.4 | 3.0 | **the act.** `Transform` line 2 → the result line. Right panel pivots about the dot, staying in contact. Left panel detaches and slides off |
| 6.4 | 1.2 | **mark the divergence.** Left: dashed perpendicular from the hinge to the student's new line, labelled with the distance. Right: flash the dot/line contact |
| 7.6 | 0.4 | hold |
| 8.0 | 2.6 | `Write` hint; settle |

**The LA13 trap, and the fix.** When the student mis-scales a row, the *correct* operation
is a genuine no-op — scaling an equation leaves its line exactly where it was. The right
panel therefore does nothing at all for 3 seconds and reads as a rendering bug. Fade an
`unchanged` tag into the right panel at t=6.4 so the stillness is legibly deliberate. This
is the strongest frame in the template — *"this step should not have moved the line, and
yours slid"* — but only if the viewer trusts that the still panel is working.

**Storyboard — `mode="solution"`, 8.8s** (single panel):

| t | dur | beat |
|---|---|---|
| 0.0 | 1.2 | plane + title |
| 1.2 | 1.4 | `Create` both lines; hollow near-white dot at the true intersection |
| 2.6 | 0.4 | hold |
| 3.0 | 1.2 | an amber dot flies in from off-frame and lands on `x_claimed` |
| 4.2 | 2.0 | **substitute.** Dashed drops from the claimed point to each line; the scoreboard fills row by row with LHS vs required RHS |
| 6.2 | 0.6 | hold |
| 6.8 | 2.0 | `Write` hint; settle |

Scoreboard rows are plain words — `5 vs 5` / `9 vs 11`, or `off by 2`. **No ✓/✗ glyphs:**
`Text` goes through Pango and renders missing glyphs as blank or tofu rather than erroring
(`RENDERING.md` §"Things that will bite you later"), and checking font coverage is not how
to spend the last hour.

**Guards:** the two original lines must actually intersect — `det([[a1,b1],[a2,b2]]) != 0`,
or there is no hinge and the template is meaningless (route to `StaticStepHighlight`);
intersection within `±4` math units or `fit_unit` rescales.

### T7 — `SpanCompare`

`backend/scenes/span_compare.py` · **P2**

Sweep the coefficients and paint every point the combinations actually reach, then drop a
probe vector outside the span and fail to reach it.

**Covers:** LA14 (R³, collapse to a flat solid), LA15 (R², line instead of plane).

```jsonc
{
  "vectors": [[1,2],[2,4]],
  "claimed_dim": 2, "actual_dim": 1,
  "probe": [0,1],
  "ambient": 2,
  "title": "...", "hint": "..."
}
```

**Storyboard — 2D, 10.4s:**

| t | dur | beat |
|---|---|---|
| 0.0 | 1.2 | `Create` plane; title; scoreboard showing `YOUR CLAIM dimension 2` |
| 1.2 | 1.0 | `GrowArrow` each input vector |
| 2.2 | 0.4 | hold |
| 2.6 | 3.5 | **the sweep.** ~600 pre-computed dots at `a·v1 + b·v2` over a coefficient grid, revealed with `LaggedStart(FadeIn, ...)`. They fill **a line**, and the rest of the plane stays black |
| 6.1 | 0.6 | **hold on the emptiness.** Counter-intuitive but essential: the message here is what *failed* to happen, and absence needs airtime to register |
| 6.7 | 1.8 | **the probe.** A violet dot appears at `probe`; a search arrow runs the filled line twice, never arriving; a dashed segment marks the permanent gap |
| 8.5 | 0.5 | scoreboard resolves: `REACHED a line` |
| 9.0 | 1.4 | `Write` hint; settle |

Use pre-computed dots plus `LaggedStart`, **not** `TracedPath`. `TracedPath` depends on
updater-vs-render ordering and gives a slightly different picture each run; an explicit dot
grid is deterministic, and "deterministic" is worth a great deal when the render happens
live in front of judges.

**3D mode (P2 of a P2):** three vectors via `iso_project` spanning a parallelepiped that
**collapses flat** — `det = 0` exactly, so the solid closes to a plane with zero thickness.
Then slide `v2` onto `v1` to show *why*. "Independence" is an abstract word; a solid with
no volume is not.

**Guards:** `1 <= len(vectors) <= 3`; `claimed_dim != actual_dim` (equal means no story);
`probe` verified unreachable — `rank([V | probe]) > rank(V)` — before rendering, because a
search animation that *could* succeed is a lie.

---

## 4. Coverage

All 19 taxonomy errors route to one of the seven, with no gaps.

| Template | Errors covered | Priority |
|---|---|---|
| `GridTransformCompare` | LA01, LA02, LA07, LA08, LA16, **+ all unmatched Layer-1 detections** | **P0** |
| `EigenRayTest` | LA09, LA10 | **P0** |
| `StaticStepHighlight` | LA03, LA18, LA01 (pairing), **+ every fallback** | **P0** |
| `DeterminantAreaCompare` | LA04, LA06, LA05 (3×3, P2) | P1 |
| `VectorOpCompare` | LA11, LA19, LA17 (3D, P2) | P1 |
| `LineSystemCompare` | LA12, LA13, generic `Ax=b` | P1 |
| `SpanCompare` | LA15, LA14 (3D, P2) | P2 |

## 5. Build order, and what to cut

Roughly 14 hours to the deadline, shared with backend, OCR, verifier and frontend. Build in
this order and stop wherever the clock stops:

| Order | Item | Est. | Rationale |
|---|---|---|---|
| 1 | `common.py` | 2.0h | Everything imports it. Lift `text_matrix`, `basis_arrow`, `panel_matte` from `_derisk_test.py` — already verified. |
| 2 | `GridTransformCompare` (1 stage) | 1.0h | The de-risk scene *is* this template with hardcoded params. Mostly parameterization. |
| 3 | `StaticStepHighlight` (static) | 0.75h | No fallback ladder = a crash in the live demo. |
| 4 | `EigenRayTest` (vector mode) | 1.0h | Highest wow-per-hour in the catalog. |
| 5 | `GridTransformCompare` (staged) | 0.5h | Unlocks LA02 and LA07 for three lines of code. |
| 6 | `DeterminantAreaCompare` (2×2) | 1.0h | Live readout mechanic already verified above. |
| — | **demo-ready line** | | 1–6 cover **11 of 19 errors** including all four hero cases. |
| 7 | `VectorOpCompare` | 1.0h | |
| 8 | `LineSystemCompare` (solution) | 0.75h | |
| 9 | `StaticStepHighlight` (pairing) | 0.75h | |
| 10 | `LineSystemCompare` (row_op) | 0.75h | |
| 11 | `SpanCompare` (2D) | 1.0h | |
| — | **cut line** | | |
| 12 | every 3D mode | 2.0h+ | `iso_project` plus `ValueTracker` rebuilds. Real work, low marginal payoff. |

**Cut 3D first and without regret.** It is the only part of this catalog that needs a
mechanic not already verified working, and LA05/LA14/LA17 all degrade to
`StaticStepHighlight` cleanly.

At `-qm` (the demo setting) a 10s scene renders in ~6.6s by `RENDERING.md`'s measured
3.05s-per-8s at `-ql` / 5.32s at `-qm`. Every template here is inside a "hit submit, watch a
spinner" budget.

## 6. API notes verified in this container

Manim Community 0.21.0, cairo renderer, no LaTeX, 2026-09-19. Everything the templates
depend on that `RENDERING.md` did not already cover was probed before being written down:

| Construct | Used by | Status |
|---|---|---|
| `always_redraw(lambda: Text(...))` | live readouts (T4, T7) | works |
| `Polygon.get_vertices()` → shoelace | `signed_area` (T4) | works; `== abs(det M)` to 1e-9, sign preserved |
| live readout tracking through `ApplyMatrix` | T4 | works; 32 samples across a 2s animation, +1.00 → 0.00 → −2.00 |
| fill recolor on sign flip via updater | T4 / LA06 | works |
| `RightAngle(Line, Line)` | T5 | works, LaTeX-free |
| `Indicate` / `Wiggle` / `Flash` / `Circumscribe` / `LaggedStart` | all | work |
| `SurroundingRectangle(Text(...))` | T3 | works |
| `DashedLine`, `Line.rotate(about_point=...)` | T2, T6 | work |
| `MarkupText` with `<span foreground=...>` | mixed-color labels | works |
| `Circle.point_at_angle` | T5 normalize overlay | works |
| `DecimalNumber(x, mob_class=Text)` | numeric labels | works (per `RENDERING.md`) |
| `TracedPath` | — | works, but **rejected** for T7: non-deterministic under updater ordering |

Probe scripts were scratch files and are not in the repo; re-derive from this table if a
claim ever looks wrong.
