# StepReplay — replaying the student's reasoning, one step at a time

Status: **SPEC**, with the load-bearing mechanics verified on real pixels
(2026-09-20 ~01:40 UTC, manim 0.21.0, `-qm`). Prototype renders and the frames
they were judged on are referenced inline.

Implement as **one new file, `backend/scenes/step_replay.py`, class `StepReplay`**,
plus a new `TEMPLATES` entry and one new builder in `hints.py`. Nothing in the
seven existing templates changes.

---

## 0. Why this exists

Today the pipeline finds the first wrong step and then shows a *summary*: one of
seven pre-made comparisons, driven by `student_value` / `correct_value` — the
endpoints of the reasoning, never the reasoning. Two consequences the user named
exactly:

> "the video doesn't actually walk through each step of the logic"
> "it doesn't actually read the work, it just auto defaults to a template"

Both are true and they are the same bug. `VectorOpCompare` receives `w_claimed`
and `w_correct` and draws two arrows; it never sees that the student computed
`b·a = 5` correctly and then multiplied by it. The student's middle is thrown
away before the scene is chosen.

**StepReplay keeps the middle.** It takes the ordered extracted steps *with the
student's own numbers*, and plays each one as a geometric action on a single
shared canvas. The state on screen after step *i* is exactly what the student's
step *i* implies — including when that is absurd. The product promise ("a
visualization of what following MY logic would actually imply") is literal here:
the scene has no notion of a correct answer to draw, only the student's
operations applied in order.

### The one-sentence difference

| | Today | StepReplay |
|---|---|---|
| Input | `student_value`, `correct_value` | the ordered `steps[]`, each with its own args and result |
| Canvas | two panels, one before/after | one canvas, state carried across steps |
| Correct answer | drawn in the right panel (masked) | **never computed, never drawn** |
| "wrong" is shown by | comparing to the right panel | the claim missing an **invariant region** derived from the givens |
| Length | 8s | 12–18s |

---

## 1. The core model: a register file

This is the single idea another agent needs before anything else. StepReplay is
a **tiny interpreter with a graphics backend**.

- The scene owns a **register file**: `env: dict[str, Reg]`, symbol → current
  value *and its live mobject on the canvas*.
- It is seeded from `givens` (`a`, `b`, `A`, `M`, …).
- Each step **reads** registers named in its `args`, performs its geometric
  action, and **writes** its `result` into the register named by `bind`.
- Step *i+1*'s input arrow is literally the mobject step *i* left on screen.
  That continuity *is* the replay. A step that rebuilds its inputs from scratch
  has broken the contract.

```python
@dataclass
class Reg:
    value: np.ndarray | float      # the student's number, verbatim
    display: str                   # fmt_num'd, for the ledger
    mob: VMobject | None           # arrow / point / nothing (scalars)
    color: str
    label: str                     # "a", "5a", "p" -- REWRITTEN on each write
```

Two rules that fall straight out of the model and are not negotiable:

1. **Everything drawn is a function of the givens and the student's own claimed
   numbers.** `verdict.correct_value` is never passed into the scene. If a
   quantity cannot be derived from what is already on the canvas, it does not
   get drawn.
2. **A register's label is rewritten when it is written.** After
   `scale_vector(k=5, v=a) -> p`, the arrow is no longer labelled `a`; it is
   labelled `5a`. In prototype 2 this was missed and the final frame showed a
   `(5,10)` arrow captioned `a`, which is simply a lie about the student's work.

---

## 2. Step kinds

Eleven kinds. Each has a genuine geometric action; the two that do not
(`scalar_value`, `state_answer`) say so and degrade honestly rather than
inventing a picture.

`detects` is evaluated against a `backend.extract.Step` plus the register file.
The primary signal is `claimed_operation` (the enum in `docs/EXTRACTION.md`
line 162); `op_args.source_symbols` and the shape of `step.value` disambiguate.

---

### 2.1 `define_vector`

- **Detects** — `claimed_operation == "copy_given"`, or a given that no step
  produced but a later step's `args` names. Also synthesised for every entry in
  `problem.givens` whose object is `kind == "vector"`.
- **Geometry** — `GrowArrow` from the origin, plus a `Text` label offset
  perpendicular to the arrow. Colour from the palette rota (`I_HAT`, `J_HAT`,
  then `PROBE`).
- **Params** — `{"value": [1,2], "label": "a", "color": "i_hat"}`
- **Wrong step** — a mis-copied given: draw the arrow the student wrote, and
  hold a `GHOST` arrow at the *printed* given alongside it. This is the one kind
  where a second arrow is allowed, because the problem statement is public — it
  is not the answer.

### 2.2 `define_matrix`

- **Detects** — `copy_given` with `value.kind == "matrix"`, or a given matrix.
- **Geometry** — no arrow. A `TextMatrix` docks into the ledger rail and the
  grid pulses once (`Indicate` on the plane) to say "this is a map, it will act
  on this grid". Registers a value with `mob=None`.
- **Params** — `{"rows": [[2,1],[0,1]], "label": "A"}`
- **Wrong step** — a transcription slip; circle the differing cell in the ledger
  matrix (reuse `step_focus.py`'s focus box), no grid action.

### 2.3 `dot_product`

- **Detects** — `claimed_operation == "dot"`, or `claimed_expression` matching
  `u . v` / `u·v`, with `value.kind == "scalar"`.
- **Geometry** — **component decomposition, not the projection picture.**
  Light up `u`'s components on the axes, then `v`'s; slide the two products
  (`3·1`, `1·2`) out as short horizontal bars; they concatenate into a sum bar
  that lands on the claimed scalar. The scalar docks into the ledger.
- **Params** — `{"u": "b", "v": "a", "result": 5, "terms": ["3(1)", "1(2)"]}`
- **Wrong step** — the sum bar lands somewhere the two term bars do not reach:
  the bars and the total visibly disagree in length. Plus the Cauchy–Schwarz
  bound `|u||v|` drawn as a capped track — a claimed `|u·v|` past the cap is
  impossible for *any* pair, which is an absurdity the viewer can check.

> **Trap, found while storyboarding — read this.**
> The textbook geometry for a dot product is "drop a perpendicular from `b` to
> `a`'s line and multiply the foot's length by `|a|`". In a **projection**
> problem that foot *is the correct final answer*. Drawing it would leak the
> answer from a step that was correct. Hence the component-decomposition
> rendering above. Generalised:
>
> **A step that is CORRECT must still be replayed without drawing any
> construction that gives away a later step's answer.** The builder passes
> `"leak_guard": ["project"]` when a downstream step of that kind exists, and
> `dot_product` switches rendering accordingly.

### 2.4 `scale_vector`

- **Detects** — `claimed_operation == "scalar_multiply"`, or
  `claimed_expression` of the form `k * v` / `k(v)` where `k` resolves to a
  scalar register or `op_args.scalar`, and `v` to a vector register.
- **Geometry** — the hero action. `|k|` ghost copies of `v` are laid **end to
  end** along `v`'s line, one every `0.28s`, while the live arrow stretches to
  follow the last one. Negative `k` lays them the other way and the arrow
  crosses the origin. This is the literal meaning of "times k", built from
  nothing but the student's own `k`.
- **Params** — `{"k": 5, "k_display": "5", "v": "a", "result": [5,10]}`
- **Wrong step** — nothing about the *action* is wrong; the action is what makes
  it wrong. The tiles march straight out of the invariant region (§6) and keep
  going. The frame is forced to zoom out to hold them (§5), and the zoom itself
  is the statement: the world had to shrink to contain this answer.
- **Degradation** — `|k| > 8`: draw 3 tiles, then an ellipsis tile and a single
  continuous stretch. 40 tiles is a smear.

### 2.5 `add_vectors`

- **Detects** — `claimed_operation in ("add", "subtract")` with two vector args.
- **Geometry** — tail-to-head: a `GHOST` copy of `v` translates so its tail sits
  on `u`'s tip, then the resultant grows from the origin to the far corner. The
  completing parallelogram is stroked faintly. Subtraction flips `v` first, and
  the flip is animated (`Rotate` through 180°) so the sign is visible.
- **Params** — `{"u": "p", "v": "q", "sign": "+", "result": [4,3]}`
- **Wrong step** — the resultant arrow lands **off the parallelogram's far
  corner**, and the corner stays stroked. A gap between an arrow's tip and a
  corner that is drawn right next to it needs no caption.

### 2.6 `matrix_apply`

- **Detects** — `claimed_operation == "multiply"` where one arg is a matrix
  register and the other a vector register; or `A v` in `claimed_expression`.
- **Geometry** — `apply_matrix_anims(panel, M, arrows, run_time=...)` from
  `helpers.py` — `ApplyMatrix` on the plane, `Transform` on each tracked arrow
  (never feed arrows to `ApplyMatrix`; RENDERING.md #5). `about_point` **must**
  be `panel.origin`.
- **Params** — `{"M": "A", "v": "x", "result": [3,-1]}`
- **Wrong step** — the grid carries the lattice point under `v` to one place and
  the student's claimed arrow sits somewhere else. Hold both: the transported
  lattice intersection is a visible dot, and the claimed tip is not on it. The
  lattice is the witness, and the lattice is derived from `M`, which the student
  wrote.

### 2.7 `matrix_product`

- **Detects** — `claimed_operation == "multiply"` with two matrix args, or
  `topic == "matrix_multiply"`.
- **Geometry** — the product is a *composition*, so replay it as one: apply the
  right factor to the grid, hold `pause_between_stages` (0.6s) on the
  intermediate, then apply the left factor. Then apply the student's claimed
  single matrix to a **ghost grid** started from the original.
- **Params** — `{"factors": ["A","B"], "order": ["B","A"], "result": [[...]]}`
- **Wrong step** — the two grids end in different places. Order errors (LA02)
  are exactly this and it is the strongest picture in the existing catalog; here
  it gains the intermediate state, which is the part the student actually got
  wrong in their head.

### 2.8 `row_op`

- **Detects** — `claimed_operation in ("row_swap","row_scale","row_add_multiple")`;
  `op_args.rows` names which, `op_args.scalar` the multiplier.
- **Geometry** — equations as lines (as `line_system.py` does), but replayed:
  the operated row's line **sweeps continuously** from its old position to its
  new one while the intersection point of the system is circled and held.
- **Params** — `{"rows": [2,1], "scalar": "-3", "op_label": "R2 - 3R1", "result_line": [0,-5,-10]}`
- **Wrong step** — the swept line **lets go of the circled crossing point**. A
  legal row operation pivots about it; an illegal one does not. The circle is
  drawn from the original system, so it is a given, not an answer.

### 2.9 `normalize`

- **Detects** — `claimed_operation == "normalize"`, or `claimed_expression`
  containing `v/||v||`.
- **Geometry** — draw the unit circle **first** (the invariant), then shrink the
  arrow along its own line toward it.
- **Params** — `{"v": "a", "divisor_display": "sqrt(5)", "result": [0.447,0.894]}`
- **Wrong step** — the tip stops short of, or shoots past, the unit circle and
  parks there. The circle is radius 1 — the definition, not the answer.
  **Framing note:** this kind needs `allow_grow=True` framing (everything
  happens within one unit of the origin), which is why §5's unit solver takes a
  `grow` flag.

### 2.10 `project`

- **Detects** — `claimed_operation == "project"`, or `proj_v(u)` in
  `claimed_expression`.
- **Geometry** — draw `v`'s line (dashed, `GHOST`, `span_line`), then the
  invariant disc of radius `|u|` (§6), then land the claimed point.
- **Params** — `{"u": "b", "v": "a", "result": [5,10]}`
- **Wrong step** — three independent failures, all derivable from the givens:
  the claimed point is outside the disc; the residual from `u`'s tip to the
  claimed point is not perpendicular to `v` (the corner marker will not close);
  and the claimed point is further from the origin than `u` is.
- **Note** — when the projection is *assembled* by the student as
  `dot` → `scale` (the motivating example), the builder emits the two kinds, not
  this one. This kind is for a student who wrote the projection in one line.

### 2.11 `scalar_value` and `state_answer`

- **Detects** — `determinant_expand`, `cofactor`, `char_poly`,
  `solve_char_poly`, `back_substitute`, `state_answer`, `unknown`, or any step
  whose value is a scalar with no vector args.
- **Geometry** — **none, and it says so.** The line docks into the ledger and
  is marked; the canvas holds. `determinant_expand` is the one exception: it
  may draw the unit square's image and read off the signed area, since that is
  honest geometry.
- **Rationale** — `ERROR_TAXONOMY.md §3` is explicit that LA03 and LA18 have no
  geometry and that drawing one "would actively mislead". A replay that invents
  a picture for an arithmetic line is the exact failure mode we are fixing.
  A replay in which two of six steps are ledger-only is fine; the *canvas* is
  still continuous.
- **Guard** — if **every** step resolves to `scalar_value`, `StepReplay.validate`
  raises `SceneParamError` and the ladder degrades to `StaticStepHighlight`.

---

## 3. SCENE_PARAMS: the exact JSON

Consumed by `StepReplay` via `ParamScene.resolve()` (class attr `P`, else
`$SCENE_PARAMS`, else `DEFAULTS`) — identical to every other template.

```jsonc
{
  "title": "Your steps, replayed",
  "hint": "a shadow can't be longer than the thing casting it",
  "student_label": "YOUR WORK",

  "canvas": {
    "box":        [9.5, 6.05],     // width, height -- verified to fit title+hint
    "box_center": [-1.85, -0.30],
    "ledger_x":   4.95,            // centre of the right rail
    "zoom_max":   2.6,             // see 5.3 -- VERIFIED bound
    "pad":        0.9,             // math units of air around the bbox
    "margin":     0.55,            // scene units kept clear inside the box
    "grow":       false            // true only for unit-circle stories
  },

  "givens": {
    "a": {"kind":"vector","value":[1,2],"display":"(1, 2)","color":"i_hat"},
    "b": {"kind":"vector","value":[3,1],"display":"(3, 1)","color":"j_hat"}
  },

  "leak_guard": ["project"],       // kinds present downstream; see 2.3

  "steps": [
    {
      "id": "s1",
      "student_label": "1)",
      "kind": "dot_product",
      "expr": "b.a = 3(1) + 1(2) = 5",   // the student's OWN raw_text, trimmed
      "args": {"u": "b", "v": "a"},
      "terms": ["3(1)", "1(2)"],
      "result": {"kind":"scalar","value":5,"display":"5"},
      "bind": "k",
      "status": "ok",                     // "ok" | "wrong" | "unchecked" | "crossed_out"
      "first_wrong": false,
      "run_time": 2.4,
      "invariant": null,
      "divergence": null
    },
    {
      "id": "s2",
      "student_label": "2)",
      "kind": "scale_vector",
      "expr": "proj_a(b) = 5(1,2) = (5,10)",
      "args": {"k": "k", "v": "a"},
      "result": {"kind":"vector","value":[5,10],"display":"(5, 10)"},
      "bind": "p",
      "status": "wrong",
      "first_wrong": true,
      "run_time": 3.0,
      "invariant": {
        "kind": "disc",                   // disc | unit_circle | line | point | parallelogram | band
        "radius_of": "b",                 // a SYMBOL in scope -- never a literal answer
        "caption": "every shadow of b lands in here"
      },
      "divergence": {
        "absurdity": "length",            // length | corner | offlattice | offcorner | offpivot | none
        "compare_to": "b",
        "residual_from": "b",
        "right_angle_at": "result"
      }
    }
  ]
}
```

### Field contract

| field | who fills it | rule |
|---|---|---|
| `givens[*].value` | backend (sympy) | verbatim from `problem.givens` |
| `steps[*].kind` | backend | §2 detection table, never an LLM guess |
| `steps[*].args` | backend | **symbol names**, resolved against the register file |
| `steps[*].result.value` | backend | the student's claim, verbatim from `step.value` |
| `steps[*].expr` | backend | the student's `raw_text`, whitespace-normalised, ≤ 34 chars |
| `steps[*].status` | backend | straight from `verify.StepResult.status` |
| `steps[*].first_wrong` | backend | exactly one step may be `true` |
| `steps[*].invariant.*_of` | backend | **must name a symbol already in scope** |
| `title`, `hint`, `caption`s | planner | linted by `check_hint` / `lint_hint` as today |
| `run_time` | backend | seconds; auto-fitted by §4.2 if the total overruns |

### Validation (`StepReplay.validate`) — raise `SceneParamError` on any of

1. `len(steps) < 2` → not a replay; degrade.
2. every step is `scalar_value` → no geometry; degrade.
3. any `args` symbol unresolvable at its point in the sequence (forward
   reference, or a register never bound).
4. more than one `first_wrong`.
5. any `invariant` field carrying a **literal** rather than a symbol name.
6. `as_vector` / `as_matrix` rejects any value (non-finite, magnitude > 50).
7. computed `zoom` ratio > 40 — the claim is so far out that no framing holds
   both ends. Degrade to the existing two-panel comparison, which does not care
   about scale.

---

## 4. Timing

### 4.1 Per-kind defaults (seconds)

| kind | run_time | + settle |
|---|---|---|
| `define_vector` | 0.6 | 0.15 |
| `define_matrix` | 0.7 | 0.2 |
| `dot_product` | 2.4 | 0.3 |
| `scale_vector` | 0.28·min(\|k\|,5) + 1.2 | 0.5 |
| `add_vectors` | 1.8 | 0.3 |
| `matrix_apply` | 2.2 | 0.4 |
| `matrix_product` | 2.0 per factor + 0.6 hold | 0.5 |
| `row_op` | 2.0 | 0.4 |
| `normalize` | 1.6 | 0.3 |
| `project` | 2.2 | 0.4 |
| `scalar_value` | 0.5 (ledger only) | 0.1 |

Fixed overhead: title + givens 1.6s, invariant beat 1.0s, divergence beat 1.2s,
hint 1.2s, final hold 1.8s.

### 4.2 Budget

Target **12–18s**, hard ceiling 20s. If the sum overruns, scale every
*non-`first_wrong`* step's `run_time` by `(budget − fixed − wrong_step) / rest`,
floored at 0.4s each. **The first wrong step's beat is never compressed** — it
is the only beat the video exists for. If it still overruns at the floor, drop
`scalar_value` steps to ledger-instant (0.0s) and, past that, elide the middle
of a long run of `ok` steps behind a single "…3 more steps checked" ledger line.

---

## 5. Canvas strategy

**One shared canvas.** A replay whose frame is cut apart cannot show continuity,
and continuity is the whole product. There is exactly one `NumberPlane`, one
origin, and one set of arrows for the entire video. Comparison happens against
**invariant regions on that canvas** (§6), not against a second panel.

Layout, verified at `-qm`:

```
 title          y = +3.4      (title_text)
 box            9.5 x 6.05 centred at (-1.85, -0.30)   ->  x in [-6.6, 2.90]
 ledger rail    x in [3.10, 7.00], anchor x = 4.95
 hint           y = -3.82     (hint_text, HINT_BOTTOM_Y)
```

The rail carries the student's own lines, re-typeset, appearing as they are
played — it is the "it read my work" evidence, and it is where a `scalar_value`
step lives when it has no geometry.

### 5.1 The framing solver

The problem: `(5,10)` has 2.5× the extent of `a=(1,2)` and `b=(3,1)`, so no
single scale serves both the opening and the end.

```python
PAD, MARGIN = 0.9, 0.55

def frame_for(points, box, box_center, grow=False):
    """bbox of every point visited so far -> (unit, origin_scene_position)."""
    P  = np.array([[0.0, 0.0]] + [list(p) for p in points], float)
    lo, hi = P.min(axis=0) - PAD, P.max(axis=0) + PAD
    span   = np.maximum(hi - lo, 1e-6)
    unit   = min((box[0] - 2*MARGIN) / span[0],
                 (box[1] - 2*MARGIN) / span[1])
    mid    = (lo + hi) / 2
    origin = box_center - unit * np.array([mid[0], mid[1], 0.0])
    return unit, origin
```

Two things it does that a plain `fit_unit` does not, both necessary:

- It includes the **origin** in the bbox (every arrow starts there).
- It **anchors the origin off-centre**. The projection example lives entirely in
  the first quadrant; centring the origin wastes three quadrants and forces the
  scale down by ~2×. Anchoring by bbox bought a 0.419 final unit instead of
  ~0.26 — the difference between readable arrows and the `InverseRoundTrip`
  4-pixel-basis-vector failure in `TEMPLATE_AUDIT.md` row 10.

### 5.2 Re-framing: a Transform between two planes

**Verified mechanism.** Build the replacement plane with the *same* `radius`,
`radius_y` and `step` and only a different `unit` (hence `x_length`/`y_length`),
then:

```python
self.play(Transform(plane, plane_at(new_unit, new_origin)),
          *[Transform(a.mob, arrow_at(new_origin, a.vec, a.color, unit=new_unit))
            for a in arrows],
          <the step's own animation>,
          run_time=step.run_time)
```

Because the two planes have identical submobject structure, `Transform` is a
straight linear interpolation of every line's endpoints — i.e. exactly a smooth
zoom. Arrows are rebuilt rather than scaled, so arrowheads stay crisp
(RENDERING.md #5 again). Confirmed on frames at t=1.2/2.8/3.8 of
`ZoomTest.mp4`: the lattice densifies smoothly and no arrowhead deforms.

**The re-frame is played *inside the same `play()` as the step's action.** Never
as its own beat. The frame chasing the arrow as it shoots out is the drama; a
separate "and now we zoom out" beat throws it away.

### 5.3 Two constants, both set by evidence

**`zoom_max = 2.6`.** `grid_step` is fixed for the whole scene (it must be — a
different `step` changes the submobject count and breaks the `Transform`), so
one step value has to read at both ends of the zoom. Measured: the box shows
`BOX_W/unit` cells, and at **22.6 cells** with `step=1` the lattice is still
clearly a lattice at 720p (frame `g_9.2.png`), while below ~4 cells it stops
reading as a grid at all. That bounds the ratio at ≈2.6. So:

```python
u_end,   org_end   = frame_for(all_points)            # most zoomed out
u_start, org_start = frame_for(points_of_beat_0)
u_start = min(u_start, zoom_max * u_end)              # clamp
```

When the clamp binds, the opening is a little wider than ideal — the safe
degradation, since zooming out only ever shrinks things that already fit. For
the projection example this gives `u0 = 1.091`, `u1 = 0.419`, ratio 2.60,
8.7 cells → 22.6 cells. Both ends verified legible.

`step = 1` while `BOX_W/u_end <= 24`, else `2` (`make_plane`'s
`faded_line_ratio` keeps the unit lattice as a whisper at `step == 2`; at
`step >= 3` it does not, so never exceed 2).

**Plane radius** — fixed, and large enough that the *most zoomed-out* state
still fills the box:

```python
radius = min(26, ceil((max(BOX_W, BOX_H)/2 + 1.6) / u_end))
```

For the example: 15. At the opening unit the plane spans ~33 scene units and is
mostly outside the frame; the matte clips it (RENDERING.md #4), and the
submobject count never changes, which is what keeps `Transform` clean.

### 5.4 Intermediate re-frames and hysteresis

Compute `u_i = frame_for(points visited through step i)` for every `i`. Only
actually re-frame when `u_i < 0.88 * u_current` — otherwise the canvas breathes
on every step and the viewer loses the thread. In the motivating example this
fires exactly once, on the wrong step, which is precisely where it should.

### 5.5 The z-index rule — this one bit, hard

`panel_matte` is at `Z_MATTE = 10`. Several helpers default **above** it:
`residual` and `right_angle_marker` at `Z_FLASH = 13`, `side_label` at
`Z_CHROME = 12`. In prototype 1 the residual line and its label were drawn
**outside the box, floating in the black gutter**, because the matte could not
clip them (frame `f_6.5.png`).

> **Every mobject expressed in panel coordinates must be given
> `z_index = Z_MATTE - 1` (call it `Z_GEO = 9`).** Arrows, labels, invariant
> regions, residuals, corner markers, ghost tiles, span lines — all of it.
> Only the title, the ledger, the hint and the border sit above the matte,
> and none of those are in panel coordinates.

Re-verified in prototype 2: with `Z_GEO`, every overlay clips cleanly at the box
edge (`g_3.2.png`, `g_9.2.png`).

### 5.6 The arrowhead-margin bug

In prototype 1 the `(5,10)` arrow reached the box edge and the matte ate its
head — a headless amber stick (`f_3.8.png`). `MARGIN = 0.55` scene units in
`frame_for` is sized for `Arrow`'s tip length at these stroke widths. Do not
reduce it, and do not compute the unit from the tips alone: compute it from the
bbox *plus* `MARGIN`, as the solver above does.

---

## 6. Divergence: showing "it broke here" without printing the answer

`REVEAL_CORRECT_VALUES` stays `False` (`common.py`). StepReplay is stricter than
the existing templates: it does not even *receive* the correct value, so there
is nothing to leak. The question is then how a viewer sees that a step is wrong
when no correct answer is on screen.

### 6.1 The principle

> **Every operation has an invariant its result must satisfy. The invariant is
> computable from the givens alone. Draw the invariant BEFORE the claim lands,
> then let the claim miss it.**

An invariant is a **region or a property**, never a point, so it constrains the
answer without being the answer. It is derived from symbols already on the
canvas — the `*_of` fields in §3 name symbols for exactly this reason.

### 6.2 The table

| kind | invariant (answer-free) | miss looks like |
|---|---|---|
| `project` | the disc of radius `\|u\|` (a shadow is never longer than the object), intersected with `v`'s line | claim lands outside the disc; corner marker will not close |
| `normalize` | the unit circle | tip stops short of it / shoots past it |
| `scale_vector` | `v`'s line, and `\|k\|` tiles of `v` laid end to end | inherits the downstream invariant; the tiles march out of the region |
| `dot_product` | the Cauchy–Schwarz track, length `\|u\|\|v\|`, with a sign gate set by the angle wedge | the total bar overruns the track, or falls on the wrong side of zero |
| `add_vectors` | the completing parallelogram | resultant tip misses the far corner |
| `matrix_apply` | the transported lattice point under `M` | claimed tip is not on the lattice intersection |
| `matrix_product` | the composite grid from applying the factors in sequence | claimed grid ends elsewhere |
| `row_op` | the circled intersection of the original system | the swept line lets go of the circle |

### 6.3 The three escalating cues, in order

Play them in this order, each about 0.4–0.6s apart. They are independent, so a
viewer who misses one still gets it.

1. **The region is missed.** Already on screen, drawn before the claim. Nothing
   is said; the claim simply lands outside it. This is the honest cue and it
   does most of the work.
2. **Absurdity of scale.** For `absurdity: "length"`, swing an arc of radius
   `|u|` (the object's own length) up to the claim's line and let it fall
   visibly short. "The shadow is 3.5× the object" is a statement about two
   things both already on screen.
3. **The property fails.** The residual from `u`'s tip to the claimed point,
   dashed in `PROBE`, and a right-angle marker at the claimed tip that does not
   close — with a small `Wiggle` on the marker so the failure is *animated*
   rather than merely small.

**On the corner marker specifically:** `TEMPLATE_AUDIT.md` row 8 already
complains it is ~15px and reads as nothing, and prototype 2 reproduced that
(`g_9.2.png` — the marker at the tip is invisible against the arrow). So it is
the **third** cue, never the first, and it must be drawn at `size >= 0.30` with
the residual offset clear of the arrow. The disc and the length arc carry the
frame.

### 6.4 Marking the steps as they play

- `status == "ok"` → a small `CORRECT`-coloured tick next to the ledger line,
  and the geometry settles with no fuss. **Correct steps must visibly check
  out**; that is what makes the wrong one mean something, and it is the part
  that proves the app read the work.
- `status == "unchecked" / "crossed_out"` → the ledger line is dimmed to `GHOST`
  with no mark. Never blamed (taxonomy §4.5).
- `first_wrong` → the ledger line turns `STUDENT` amber with a caret, the
  invariant region is already up, and the divergence cues fire. **No red X, no
  "WRONG".** The geometry says it.
- Steps *after* the first wrong one are still played, in `GHOST`, because the
  student's later work followed honestly from a bad input and showing it is the
  point. They are never marked.

---

## 7. Storyboard — the motivating example

```
a = (1,2)   b = (3,1)   "proj_a(b) = (b.a)a"
  1)  b.a = 3(1) + 1(2) = 5           <- correct
  2)  proj_a(b) = 5(1,2) = (5,10)     <- first wrong: never divided by a.a = 5
```

Framing from §5: `u0 = 1.091`, `u1 = 0.419`, ratio 2.60, origin anchored at the
bbox of `{0, a, b, (5,10)}`. Total **15.4s**.

| # | t | dur | Beat |
|---|---|---|---|
| **B1** | 0.0 | 1.6 | Title "Your steps, replayed" writes. Plane in at `u0`. `a` grows green, labelled `a`; `b` grows red, labelled `b`. Ledger rail empty. |
| **B2** | 1.6 | 1.0 | Ledger line 1 types in, in the student's own hand-numbering: `1)  b·a = 3(1) + 1(2) = 5`. |
| **B3** | 2.6 | 2.4 | **dot_product, leak-guarded.** `b`'s components flash on the axes, then `a`'s. Two term bars slide out (`3(1)`, `1(2)`) and concatenate into a sum bar landing on `5`. The Cauchy–Schwarz track is behind it; the bar sits comfortably inside. A `CORRECT` tick lands on ledger line 1. The scalar `5` docks into the rail as register `k`. **No perpendicular is drawn** (§2.3). |
| **B4** | 5.0 | 1.0 | Ledger line 2 types in, amber: `2)  proj = 5(1,2)`. The result is *not* shown yet. |
| **B5** | 6.0 | 1.0 | **The invariant.** A `PROBE` circle of radius `\|b\| = √10` is drawn about the origin, caption "every shadow of b lands in here". `a`'s line goes in dashed `GHOST`. Nothing has moved yet — the viewer is shown the target zone before the shot. |
| **B6** | 7.0 | 3.0 | **THE WRONG STEP.** `a` re-tints to `STUDENT` amber. Five ghost tiles of `a` lay end to end along its line, one every 0.28s — **tile 2 crosses the circle and keeps going**. The live arrow stretches to follow. *Concurrently*, in the same `play()`, the plane and every arrow `Transform` to `u1`: the world shrinks 2.6× to hold what the student wrote. Arrow lands at `(5,10)`, label rewritten to `5a`. |
| **B7** | 10.0 | 1.2 | **Absurdity.** An arc of radius `\|b\|` swings from `b`'s tip up to the claim's line and falls visibly short — the claimed shadow is 3.5× the object. The tiny circle, now far below the amber tip, does the rest. |
| **B8** | 11.2 | 1.2 | **The property.** Dashed `PROBE` residual from `b`'s tip to `(5,10)`; right-angle marker at the tip, drawn at size 0.30, then `Wiggle` — it does not close. Ledger line 2 gets its amber caret. |
| **B9** | 12.4 | 1.2 | Hint writes at the bottom: *"a shadow can't be longer than the thing casting it"*. (Positional only; passes `check_hint` — it names no value.) |
| **B10** | 13.6 | 1.8 | Hold. Final frame: amber `5a` towering over red `b`, the little purple disc near the origin, the ledger reading the student's two lines with a tick and a caret. |

Verified end-state composition in `g_9.2.png`: amber arrow ≈4× `b`, disc small
and clearly missed, everything inside the box, arrowhead intact.

---

## 8. Wiring

### 8.1 Registry

Append to `TEMPLATES` in `backend/scenes/registry.py` (surgical addition — the
file is being edited concurrently, so re-read it immediately before touching it
and add only this key):

```python
"StepReplay": {
    "class": StepReplay, "module": "step_replay",
    "file": os.path.join(_HERE, "step_replay.py"), "scene": "StepReplay",
    "priority": "P0", "duration": 15.4,
    "covers": ["any multi-step solution", "LA11", "LA19", "LA02", "LA12"],
    "summary": "Replay the student's own steps, in order, on one canvas.",
    "param_schema": {
        "givens": (_S, "symbol -> {kind,value,display,color}"),
        "steps":  (_S, "ordered list; see docs/STEP_REPLAY.md §3"),
        "canvas": (_S, "framing block; solver fills it"),
        "leak_guard": (_S, "list[str] of downstream kinds"),
        "title": (_L, "str"), "hint": (_L, "str, positional only"),
        "student_label": (_L, "str"),
    },
},
```

### 8.2 Planner

New builder `_step_replay(verdict, ext, env, S, C)` in `backend/hints.py`, and
`plan()` tries it **first** whenever

```
len([s for s in ext.steps if s.parse_ok and not s.crossed_out]) >= 2
and at least two of those map to a non-scalar_value kind
```

falling through to the existing `builder` dict on `SceneUnavailable`. The
existing seven templates become the fallback tier, unchanged. The `_static`
fallback stays the bottom of the ladder exactly as today.

The builder walks `ext.steps` in `(page, reading_order)` order alongside
`verdict.step_results` (same ordering, so zip by index), maps
`claimed_operation` → `kind` via §2, resolves `op_args.source_symbols` against
the register file, and copies `step.value` through verbatim. It sets
`first_wrong` on the single index equal to `verdict.first_error_index`.
It never reads `verdict.correct_value`.

### 8.3 Hint linting

Unchanged. `params["hint"]` still goes through `lint_hint` against
`_forbidden(C)` in `plan()`. Additionally, **every `invariant.caption` and every
in-canvas caption must be linted the same way** — they are burned into the frame
and are every bit as public as the hint.

---

## 9. Pitfalls, with the evidence

Each of these was hit in a prototype, not theorised.

1. **The matte does not clip `Z_FLASH`/`Z_CHROME`.** Overlays escape the box and
   float in the gutter. Use `Z_GEO = Z_MATTE - 1` for everything in panel
   coordinates. (§5.5, `f_6.5.png`)
2. **Arrowheads get eaten at the box edge.** Frame from the bbox + `MARGIN`,
   not from the tips. (§5.6, `f_3.8.png`)
3. **`Transform` between planes only zooms cleanly if `radius`/`radius_y`/`step`
   are identical.** Change `unit` alone. Changing `step` mid-scene changes the
   submobject count and manim null-pads, which looks like lines being born at a
   point. (§5.2, §5.3)
4. **A correct step can leak a later answer.** The perpendicular-foot picture for
   `b·a` *is* the projection answer. `leak_guard`. (§2.3)
5. **Labels must be rewritten on every register write**, or the final frame
   captions a `(5,10)` arrow as `a`. (§1)
6. **Never re-frame in its own beat.** Zoom inside the step's `play()`.  (§5.2)
7. **Never compress the first wrong step's beat** when fitting the budget. (§4.2)
8. Reuse `helpers.py` wholesale — `make_plane`, `panel_matte`, `arrow_at`,
   `apply_matrix_anims`, `span_line`, `residual`, `right_angle_marker`,
   `foot_on_line`, `TextMatrix`, `fmt_num`, `title_text`, `hint_text`,
   `label_text`, `ParamScene`. Write no new geometry primitives.
9. **No `Tex`/`MathTex`/`Matrix`/`IntegerMatrix`/`DecimalMatrix`/`MobjectMatrix`.**
   There is no `latex` binary. `TextMatrix` and `T()` only. (RENDERING.md)
10. `ApplyMatrix` needs `about_point=panel.origin`; arrows are `Transform`ed to
    freshly built arrows, never fed to `ApplyMatrix`. (RENDERING.md #5)

---

## 10. Acceptance — how the implementer knows it is done

Exit code 0 is not evidence. Render, pull frames with `ffmpeg -ss`, and **look
at them**:

```bash
cd /home/user/hackmit-2026
.venv/bin/manim -qm --disable_caching -v ERROR --media_dir /tmp/sr \
    backend/scenes/step_replay.py StepReplay
ffmpeg -v error -y -ss 8.5 -i /tmp/sr/videos/step_replay/720p30/StepReplay.mp4 \
    -frames:v 1 /tmp/sr/mid.png          # then Read it
```

Checks, on pixels:

- [ ] At t ≈ 4.0 the dot-product beat is visibly *doing arithmetic on the axes*,
      and there is **no perpendicular from `b` to `a`'s line** anywhere.
- [ ] At t ≈ 6.5 the invariant disc is on screen **before** the amber arrow moves.
- [ ] Between t = 7 and t = 10 the grid visibly densifies (the zoom) while the
      amber arrow grows. Both are legible throughout.
- [ ] At t ≈ 9.5 the amber arrowhead is **present and sharp**, inside the box.
- [ ] Nothing is drawn outside the box at any time.
- [ ] Final frame: `5a` is obviously several times longer than `b`; the disc is
      obviously missed; the ledger shows the student's two lines with a tick on
      line 1 and a caret on line 2.
- [ ] `(1,2)`, `(5/5)`, `a·a`, and the string `5/5` appear **nowhere**.
- [ ] Downscale the final frame to 384px wide and it still reads.
- [ ] Duration is 12–18s; render at `-qm` is under 12s wall clock.
- [ ] `registry.validate_params("StepReplay", ...)` raises `SceneParamError` for
      each of the seven §3 validation cases, and `render_with_fallback` lands on
      `StaticStepHighlight` rather than propagating.

---

## Appendix: prototypes

Throwaway, in the scratchpad, not in the repo — rebuild from this document
rather than from them:

```
/tmp/claude-0/-home-user-hackmit-2026/ec5fcd38-b034-5601-9d96-e8734979a5e8/scratchpad/zoomtest.py
/tmp/claude-0/-home-user-hackmit-2026/ec5fcd38-b034-5601-9d96-e8734979a5e8/scratchpad/replay2.py
```

`zoomtest.py` established that the plane-to-plane `Transform` zoom works and
exposed pitfalls 1 and 2. `replay2.py` is the corrected framing + z-index +
invariant-disc version whose frames back §5 and §6; it prints the solved
`u0/u1/ratio/cells` for the projection example.
