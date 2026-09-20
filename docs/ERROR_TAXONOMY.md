# Error Taxonomy & Symbolic Verification Strategy

Linear algebra only. Every matrix, determinant, and claimed-wrong value below was
executed through sympy 1.14 before being written down — the numbers are safe to paste
into demo samples and unit tests.

**Design rule that governs this whole document:** an error earns its place only if the
student's *wrong answer*, applied geometrically, looks visibly different from the right
one. Three entries here fail that test. They are kept and labelled, because knowing
which errors we cannot dramatize is as operationally important as knowing which we can —
those route to a fallback scene instead of burning render time on a non-event.

---

## 1. Scene template catalog

Nine hand-written `Scene` classes. The LLM never writes Manim; it picks a template id and
fills a small typed parameter dict. Build priority is a cut list — P0 gets you a demo,
P1 makes it impressive, P2 is gravy.

| id | params | what it shows | priority |
|---|---|---|---|
| `GridTransformCompare` | `M_student`, `M_correct`, `labels` | Two copies of the plane side by side. Same grid, same î/ĵ. Apply each matrix. The workhorse — most errors reduce to "your matrix sends the basis vectors somewhere else." | **P0** |
| `InverseRoundTrip` | `M`, `M_inv_claimed` | Apply `M`, then apply the student's claimed inverse. Does the grid come home to the identity? The single most legible animation in the app. | **P0** |
| `EigenRayTest` | `M`, `v_claimed`, `v_correct`, `lambda_claimed` | Draw the infinite line spanned by the claimed vector. Apply `M`. Watch whether the image vector stays glued to that line or lifts off it. | **P0** |
| `DeterminantAreaCompare` | `M`, `claimed_det` | Unit square (or cube) morphs under `M` with a live area/volume readout, next to the student's claimed number. Orientation flip is rendered as the square physically turning over, with the fill color swapping. | **P1** |
| `VectorOpCompare` | `u`, `v`, `w_claimed`, `w_correct`, `op` | One plane/space, both result vectors drawn. Carries an op-specific invariant overlay (perpendicularity mark, unit circle, projection foot). | **P1** |
| `SpanCompare` | `vectors`, `claimed_dim`, `actual_dim`, `probe` | Sweep all linear combinations to fill in the actual span (line / plane / space), then try and fail to reach a probe vector outside it. | **P1** |
| `CompositionOrderCompare` | `A`, `B`, `order_student` | Two-stage: apply the first matrix, *pause on the intermediate grid*, apply the second. Run both orders. The pause is the whole point — it's where AB vs BA becomes obvious. | **P1** |
| `RowOpLinePivot` | `rows_before`, `rows_after`, `op_label` | Each equation is a line in the plane. A **legal** row operation produces a new line that still passes through the common intersection point; an illegal one swings the line off that point. This is the correct geometry of row reduction and almost nobody teaches it. | **P2** |
| `StaticStepHighlight` | `step_latex`, `focus_span`, `annotation` | No animation. The student's own handwriting re-typeset, with a region pulsed. The honest fallback for errors with no geometry, and the safety net when parsing degrades. | **P0** |

`GridTransformCompare`, `InverseRoundTrip`, `EigenRayTest`, and `StaticStepHighlight`
cover 13 of 18 errors between them. If the clock runs out, build exactly those four.

---

## 2. The errors

Scored on `visual_strength`: **strong** (obvious at a glance, no narration needed),
**medium** (visible, needs an on-screen label), **none** (do not animate).

| id | topic | error | visual |
|---|---|---|---|
| LA01 | matrix_multiply | row-by-row pairing (computes ABᵀ) | medium |
| LA02 | matrix_multiply | order reversed, BA for AB | **strong** |
| LA03 | matrix_multiply | incompatible shapes multiplied anyway | **none** |
| LA04 | determinant | 2×2 as ad+bc | **strong** |
| LA05 | determinant | 3×3 cofactor signs all + | **strong** |
| LA06 | determinant | row swap, sign not flipped | **strong** |
| LA07 | inverse | adjugate written without 1/det | **strong** |
| LA08 | inverse | negated off-diagonal, forgot to swap a and d | medium |
| LA09 | eigen | claimed vector is not an eigenvector | **strong** |
| LA10 | eigen | characteristic polynomial sign slip | medium |
| LA11 | eigen | normalized by the wrong divisor | **strong** |
| LA12 | rref | arithmetic slip inside a row operation | **strong** |
| LA13 | rref | row scaled but augmented column missed | **strong** |
| LA14 | span | dependent set called independent | **strong** |
| LA15 | span | span dimension overclaimed | **strong** |
| LA16 | transpose | (AB)ᵀ expanded as AᵀBᵀ | **strong** |
| LA17 | cross_product | j-component sign dropped | **strong** |
| LA18 | dot_product | dot product returned as a vector | **none** |

Plus LA19 (projection denominator) below — 19 total, one over the brief, because the
projection error is both very common and visually excellent.

---

### LA01 — row-by-row pairing in matrix multiplication
**Topic:** matrix_multiply · **Visual:** medium

The student walks row *i* of A against **row** *j* of B instead of column *j*. Done
consistently, that is exactly `A·Bᵀ`.

- **Student writes:** `A = [[2,1],[1,3]], B = [[1,2],[0,1]]`, `AB = [[4,1],[7,3]]`
- **Correct:** `[[2,5],[1,5]]`
- **Check:** `eq(S, G['A']*G['B'].T) and not eq(S, G['A']*G['B'])`
- **Visual consequence:** *Honest caveat:* for 2×2 this error **always preserves the
  determinant** (det Bᵀ = det B), so the area of the transformed square is identical in
  both panels — do not build the story around area. What does change is destination:
  their matrix throws î to (2,1)·ᵀ→(4,7) while the real one sends it to (2,1); ĵ goes to
  (1,3) instead of (5,5). Side by side the two grids shear in visibly different
  directions with the same amount of stretch. Label the panels or the viewer may read it
  as the same animation twice.
- **Scene:** `GridTransformCompare`
- **Hint:** "Both grids stretch by the same amount — watch *where* your first column
  sends î compared to the other panel. Which row of B did that number come from?"

---

### LA02 — multiplication order reversed  ⭐ hero demo
**Topic:** matrix_multiply · **Visual:** strong

Asked for AB, computes BA. The canonical non-commutativity failure.

- **Student writes:** `A = [[0,-1],[1,0]]` (rotate 90°), `B = [[3,0],[0,1]]` (stretch x by 3),
  `AB = [[0,-3],[1,0]]`
- **Correct:** `[[0,-1],[3,0]]`
- **Check:** `eq(S, G['B']*G['A']) and not eq(S, G['A']*G['B'])`
- **Visual consequence:** The best animation in the app. Stretch-then-rotate leaves the
  long axis of the unit square pointing **vertically**; rotate-then-stretch leaves it
  pointing **horizontally**. Same det (3) in both, same amount of stretch, same rotation —
  the rectangle just ends up lying on its side in one panel and standing up in the other.
  Run it with `CompositionOrderCompare` so the viewer sees the identical intermediate
  grids diverge only at the second step.
- **Scene:** `CompositionOrderCompare`
- **Hint:** "Freeze both panels halfway through. The intermediate grids are the same
  shape — which one did you stretch first?"

---

### LA03 — incompatible shapes multiplied anyway
**Topic:** matrix_multiply · **Visual:** **none**

Student multiplies a 2×3 by a 2×2, pairing entries positionally until they run out.

- **Student writes:** `A` is 2×3, `B` is 2×2, "`AB = [[...]]`" (2×2)
- **Correct:** undefined; `AB` does not exist
- **Check:** `G['A'].shape[1] != G['B'].shape[0]` — structural, runs before any value comparison
- **Visual consequence:** **There is none, and we should not fake one.** The composition
  the student wrote is not a map, so there is no grid to deform and no "their version" to
  animate. Any animation here would be invented rather than derived, which breaks the
  contract of the whole product. Route to `StaticStepHighlight`: re-typeset the two
  matrices with the inner dimensions boxed and mismatched, and let the shapes speak. This
  is a **P0 correctness requirement** — a shape error must never reach the Manim renderer,
  because sympy will raise `ShapeError` and kill the job mid-demo.
- **Scene:** `StaticStepHighlight`
- **Hint:** "Count the numbers across one row of your left matrix, then count down one
  column of your right one. Those two counts decide whether this product exists at all."

---

### LA04 — 2×2 determinant computed as ad + bc
**Topic:** determinant · **Visual:** strong

- **Student writes:** `M = [[3,4],[1,2]]`, `det = (3)(2) + (4)(1) = 10`
- **Correct:** `2`
- **Check:** `eq(S, M[0,0]*M[1,1] + M[0,1]*M[1,0]) and not eq(S, M.det())`
- **Visual consequence:** The unit square morphs into a parallelogram while a live area
  counter ticks up. It stops at **2.00**. Their `10` sits frozen next to it as a static
  label. Overlay ten copies of the unit square as a ghost outline to show what an
  area-10 answer would have to look like — it dwarfs the actual parallelogram. The gap is
  a factor of five and completely unmissable.
- **Scene:** `DeterminantAreaCompare`
- **Hint:** "The area counter stops well before your number. Both products you formed are
  in the right place — check what you did *between* them."

---

### LA05 — 3×3 cofactor expansion with all-plus signs
**Topic:** determinant · **Visual:** strong

Expands along the top row but never applies the (+, −, +) checkerboard.

- **Student writes:** `M = [[1,2,3],[0,1,4],[5,6,0]]`, `det = 1(-24) + 2(-20) + 3(-5) = -79`
- **Correct:** `1`
- **Check:** `eq(S, sum(M[0,j]*M.minor(0,j) for j in range(3))) and not eq(S, M.det())`
- **Visual consequence:** Chosen specifically so the two answers disagree on **magnitude
  and sign**. The unit cube maps to a sliver of volume exactly 1 — it stays about the same
  size, just badly skewed. Their answer claims volume 79 *and* an orientation flip. Animate
  the real transformation (cube deforms, volume readout holds at 1.00, handedness
  preserved) against a ghost of what −79 would demand (a cube swelling past the frame and
  turning inside out). The claim is off by a factor of 79 in a picture where nothing much
  happens.
- **Scene:** `DeterminantAreaCompare` (3D mode)
- **Hint:** "Your three minors are all correct. Look at what sits in front of the second
  one — the volume barely changes in the animation."

---

### LA06 — row swapped during reduction, sign not flipped
**Topic:** determinant · **Visual:** strong

- **Student writes:** `M = [[0,2],[3,1]]`, swaps to `[[3,1],[0,2]]`, reads `det = 6`
- **Correct:** `-6`
- **Check:** `eq(S, -M.det()) and not eq(S, M.det())`, with `n_row_swaps % 2 == 1`
- **Visual consequence:** Sign of the determinant is genuinely geometric and almost never
  taught that way. Shade the unit square with a two-tone fill (one color per side of the
  sheet). Under the real matrix the square **turns over** — î and ĵ trade handedness and
  the reverse color comes up. Their positive answer asserts the sheet never flipped. Play
  both: one panel flips, the other doesn't. Nothing else in the taxonomy makes "negative
  determinant" this concrete.
- **Scene:** `DeterminantAreaCompare`
- **Hint:** "Watch which color the square is showing when it lands. Your answer says it
  never turned over."

---

### LA07 — inverse written as the adjugate, 1/det dropped  ⭐ hero demo
**Topic:** inverse · **Visual:** strong

Swaps a and d, negates b and c — then forgets to divide.

- **Student writes:** `M = [[3,1],[2,4]]`, `M⁻¹ = [[4,-1],[-2,3]]`
- **Correct:** `(1/10)·[[4,-1],[-2,3]] = [[2/5,-1/10],[-1/5,3/10]]`
- **Check:** `eq(S, M.adjugate()) and not eq(S, M.inv())`
- **Visual consequence:** The cleanest story available. Apply `M`, then apply their claimed
  inverse, and ask one question: *does the grid come home?* It does not — `M · S = 10·I`
  exactly, so the grid returns perfectly square, perfectly un-rotated, and **ten times too
  large**, spilling past the frame. Every other property is right, which makes the one
  wrong property impossible to misread. Put the identity grid on screen as a faint
  reference so the overshoot is measurable.
- **Scene:** `InverseRoundTrip`
- **Hint:** "The grid comes back square and pointing the right way — it just doesn't come
  back the right *size*. Everything about your matrix is right except one factor."

---

### LA08 — off-diagonal negated, diagonal not swapped
**Topic:** inverse · **Visual:** medium

Recalls "negate b and c, divide by det" but not "swap a and d."

- **Student writes:** `M = [[3,1],[2,4]]`, `M⁻¹ = (1/10)[[3,-1],[-2,4]]`
- **Correct:** `(1/10)[[4,-1],[-2,3]]`
- **Check:** `eq(S, Matrix([[M[0,0],-M[0,1]],[-M[1,0],M[1,1]]])/M.det()) and not eq(S*M, eye(2))`
- **Visual consequence:** Round trip lands `(1/10)[[7,1],[-2,14]]` — *near* the identity but
  not on it. The grid comes back roughly where it started and then visibly refuses to
  settle: still slightly sheared, still slightly rotated, gridlines no longer meeting at
  right angles. Weaker than LA07 because the miss is small; zoom to a 2×2 window around
  the origin and overlay the true identity grid in a contrasting color so the drift reads.
- **Scene:** `InverseRoundTrip`
- **Hint:** "It almost comes home. Look at the two numbers on your main diagonal and where
  they sit relative to the original."

---

### LA09 — claimed eigenvector is not an eigenvector  ⭐ hero demo
**Topic:** eigen · **Visual:** strong

Typically lifts a basis vector, or a diagonal entry as the eigenvalue.

- **Student writes:** `M = [[2,1],[1,2]]`, "eigenvector `(1,0)`, λ = 2"
- **Correct:** `(1,1)` with λ=3, `(1,-1)` with λ=1
- **Check:** `not (S.norm() != 0 and Matrix.hstack(S, G['M']*S).rank() <= 1)`
- **Visual consequence:** The definitional animation, and 3Blue1Brown's own. Draw the
  infinite line through their `(1,0)` — the x-axis. Apply `M`. Their vector lands at
  `(2,1)`, which **lifts off the line** and the gap between arrow tip and line is drawn as
  a visible dashed residual. Then do the same for `(1,1)`: the line is the diagonal, the
  image is `(3,3)`, and it slides *along* its own line and stops — never leaving it. "Stays
  on its line" versus "falls off its line" is a distinction a viewer gets in under a second
  with no explanation.
- **Scene:** `EigenRayTest`
- **Hint:** "Your vector's line is drawn on screen. Play it and watch whether the arrow
  stays on that line — compare with the other one."

---

### LA10 — characteristic polynomial sign slip
**Topic:** eigen · **Visual:** medium

Sets up det(A − λI) but drops a sign, usually on the constant term.

- **Student writes:** `M = [[4,1],[2,3]]`, `λ² − 7λ − 10 = 0`, `λ ≈ 8.22, −1.22`
- **Correct:** `λ² − 7λ + 10 = 0`, `λ = 5, 2`
- **Check:** `not eq(G['M'].charpoly(lam).as_expr().subs(lam, S), 0)` — claimed λ is not a root
- **Visual consequence:** Direction is right, magnitude is wrong, so this is a length story
  rather than a shape story. Take the genuine eigenvector `(1,1)`, draw a ghost arrow out
  to `8.22·(1,1)` (their claim), then apply `M` and watch the real vector stop short at
  `5·(1,1)`. Two arrow tips on the same ray with a labelled gap between them. Medium rather
  than strong: it needs the ghost arrow and a length label to read, and a wrong λ that
  comes out complex leaves nothing at all to draw — check `im(λ) == 0` before selecting
  this scene, and fall back to `StaticStepHighlight` if not.
- **Scene:** `EigenRayTest` (with `lambda_claimed` ghost)
- **Hint:** "The direction you found is right. Play it and see how far along that line the
  vector actually travels — then look at the last term of your polynomial."

---

### LA11 — normalized by the wrong divisor
**Topic:** eigen · **Visual:** strong

Divides by the sum of components, or by ‖v‖², instead of ‖v‖.

- **Student writes:** `v = (3,4)`, `v̂ = (3/7, 4/7)`
- **Correct:** `(3/5, 4/5)`
- **Check:** `Matrix.hstack(S, G['v']).rank() == 1 and not eq(S.norm(), 1)`
- **Visual consequence:** Draw the unit circle. A unit vector, by definition, has its tip
  **on** that circle. Theirs has length 0.714 — the arrow stops visibly short, its tip
  floating inside the circle with a gap you can measure by eye. The correct one lands
  exactly on the curve. Direction is identical in both, so the picture isolates the single
  property that's wrong. Trivial to render and instantly legible.
- **Scene:** `VectorOpCompare` (op=`normalize`, unit-circle overlay)
- **Hint:** "The circle on screen is every vector of length 1. Yours points the right way —
  check where its tip lands relative to that circle."

---

### LA12 — arithmetic slip inside a row operation
**Topic:** rref · **Visual:** strong

Executes R2 ← R2 − 3R1 correctly on the coefficients but mis-subtracts the augmented entry.

- **Student writes:** `x + 2y = 5; 3x + 4y = 11` → `[0, -2 | -6]` → `y = 3, x = -1`
- **Correct:** `[0, -2 | -4]` → `y = 2, x = 1`
- **Check (final):** `not eq(G['A']*S, G['b'])`  ·  **(per-step):** `G['Aug'].rref() != S_aug.rref()`
- **Visual consequence:** Two layers, both good. **Layer 1** (`RowOpLinePivot`): each
  equation is a line. A legal row operation produces a new line that *still passes through
  the intersection point* — the line pivots about that point like a hinge. Their bad
  arithmetic swings the line **off** the hinge, and the frame shows it detaching from the
  solution. **Layer 2** (`SolutionPointCheck`): plot their `(-1,3)` against the two original
  lines — it sits on neither, and substituting back gives `(5,9)` against a required
  `(5,11)`, drawn as a residual segment. Layer 2 alone is enough for the demo; Layer 1 is
  the more beautiful idea.
- **Scene:** `RowOpLinePivot`, falling back to `SolutionPointCheck`
- **Hint:** "Your new line has come off the point where the first two cross. Everything left
  of the bar is fine — look right of it."

---

### LA13 — row scaled, augmented column missed
**Topic:** rref · **Visual:** strong

Multiplies a row to force a leading 1 but applies the factor only to the coefficients.

- **Student writes:** `[2, 4 | 6]` → `[1, 2 | 6]`
- **Correct:** `[1, 2 | 3]`
- **Check:** `S_aug[:, :-1].rref() == correct[:, :-1].rref() and S_aug.rref() != correct.rref()` —
  coefficients row-equivalent, augmented system not
- **Visual consequence:** Same hinge geometry as LA12 and, if anything, cleaner: scaling a
  row is the one operation that should leave the line **completely unmoved** (same line,
  different equation for it). Animate it: the correct scaling redraws the identical line on
  top of itself — nothing visibly happens, which is the point. Theirs slides the line
  bodily sideways, parallel to where it was. "This step should have been a no-op and your
  line moved" is a very strong frame. The downstream system is often inconsistent, so the
  lines end up parallel and the intersection vanishes entirely.
- **Scene:** `RowOpLinePivot`
- **Hint:** "Scaling a row shouldn't move its line at all — yours slid. Which entries got
  the factor?"

---

### LA14 — dependent set claimed independent
**Topic:** span · **Visual:** strong

- **Student writes:** `{(1,2,3), (2,4,6), (1,0,1)}` "are linearly independent"
- **Correct:** rank 2; `v₂ = 2v₁`, so the set is dependent
- **Check:** `S_claim == 'independent' and Matrix.hstack(*G['V']).rank() < len(G['V'])`
- **Visual consequence:** Three independent vectors in R³ span a parallelepiped with
  nonzero volume. Draw theirs and let it **collapse flat** — the solid closes up to a plane
  with zero thickness, because `det = 0` exactly. Then highlight `v₁` and `v₂` and slide one
  along the other to show they lie on the same ray, which is *why* it flattened. Independence
  is an abstract word; a solid with no volume is not.
- **Scene:** `SpanCompare`
- **Hint:** "The solid your three vectors make has no thickness. Lay the first two on top of
  each other and see what happens."

---

### LA15 — span dimension overclaimed
**Topic:** span · **Visual:** strong

- **Student writes:** `span{(1,2), (2,4)} = R²`, "dimension 2"
- **Correct:** a line through the origin; dimension 1
- **Check:** `not eq(S, Matrix.hstack(*G['V']).rank())`
- **Visual consequence:** Sweep the coefficients over a wide range and paint every point
  the combinations reach. Their claim says the plane floods with color. What actually
  happens is that every combination lands on a single line and the rest of the plane stays
  empty. Then drop a probe vector at `(0,1)` — verified unreachable, `rank([V | probe]) > rank(V)` —
  and animate a search for coefficients that hit it, scanning along the line and never
  arriving. Emptiness is a strong visual when it's supposed to be full.
- **Scene:** `SpanCompare`
- **Hint:** "Watch how much of the plane actually fills in. The marked point is one your
  combinations keep missing — try to reach it."

---

### LA16 — (AB)ᵀ expanded as AᵀBᵀ
**Topic:** transpose · **Visual:** strong

- **Student writes:** `A = [[1,2],[0,1]]`, `B = [[2,0],[1,1]]`, `(AB)ᵀ = AᵀBᵀ = [[2,1],[4,3]]`
- **Correct:** `BᵀAᵀ = [[4,1],[2,1]]`
- **Check:** `eq(S, G['A'].T*G['B'].T) and not eq(S, (G['A']*G['B']).T)`
- **Visual consequence:** Transposing is not cosmetic, and the grid proves it. `A = [[1,2],[0,1]]`
  shears the plane **horizontally** (the top of the square slides right); `Aᵀ = [[1,0],[2,1]]`
  shears it **vertically** (the right side slides up). Run the student's product and the
  correct one side by side and the two grids lean in different directions. As a second beat,
  animate the transpose itself as a reflection across the main diagonal so the order
  reversal has a reason attached to it.
- **Scene:** `GridTransformCompare`
- **Hint:** "Both panels shear by the same amount, one sideways and one upward. Reflecting
  across the diagonal does something to the order — check which matrix ends up on the left."

---

### LA17 — cross product j-component sign dropped
**Topic:** cross_product · **Visual:** strong

Expands the 3×3 determinant but writes `+j(u₁v₃ − u₃v₁)` instead of `−j(...)`.

- **Student writes:** `u = (1,2,3)`, `v = (4,5,6)`, `u×v = (-3,-6,-3)`
- **Correct:** `(-3, 6, -3)`
- **Check (invariant, preferred):** `not eq(G['u'].dot(S), 0) or not eq(G['v'].dot(S), 0)`
- **Check (signature, for hint selection):** `eq(S, G['u'].cross(G['v']).multiply_elementwise(Matrix([1,-1,1])))`
- **Visual consequence:** "Your normal isn't normal." Draw the plane spanned by u and v as a
  translucent sheet. The true cross product stands **straight up out of it** with a right-angle
  marker on both u and v. Theirs visibly **leans into and through** the sheet — `u·w = -24`,
  `v·w = -60`, both far from zero, and we can print those numbers as the animation tilts the
  camera to show the arrow piercing the plane. The one defining property of a cross product
  is the one their answer violates, and it's a property you can see from any camera angle.
- **Scene:** `VectorOpCompare` (op=`cross`, plane + right-angle overlay)
- **Hint:** "Rotate to look edge-on at the plane. The correct arrow stands straight out of
  it; watch what yours does to the middle number's sign."

---

### LA18 — dot product returned as a vector
**Topic:** dot_product · **Visual:** **none**

Multiplies componentwise and reports a vector where a scalar was required.

- **Student writes:** `u = (1,2)`, `v = (3,4)`, `u·v = (3,8)`
- **Correct:** `11`
- **Check:** `isinstance(S, Matrix) and S.shape != (1,1)` (type violation), plus signature
  `eq(S, G['u'].multiply_elementwise(G['v']))`
- **Visual consequence:** **Essentially none, and we should say so rather than stretch.** The
  honest geometric content of a dot product is a projected length times a length — a
  one-dimensional quantity. The student's answer is a point in the plane, and there is no
  principled place to draw it: putting `(3,8)` on the same axes as a projection diagram
  invites the viewer to compare two things that live in different spaces, which teaches a
  falsehood. The componentwise product is not a wrong *arrow*, it's a category error. Route
  to `StaticStepHighlight` with a type annotation ("this side is a number, that side is an
  arrow"). If there is spare time, a **medium** upgrade exists: show the projection of u onto
  v̂ with the scalar 11 rendered as a length along v's line, and leave their answer as text
  off to the side — but do **not** draw it as a vector in the same frame.
- **Scene:** `StaticStepHighlight`
- **Hint:** "Count how many numbers are on each side of your equals sign."

---

### LA20 — projections onto a non-orthogonal basis, added together
**Topic:** projection · **Visual:** strong

Computes proj onto each spanning vector correctly, adds them, and calls the sum the
projection onto the span. Only valid when the spanning vectors are perpendicular.

- **Student writes:** `u1=(1,0,1), u2=(1,1,0), b=(2,1,3)` → `proj_u1 b = (5/2,0,5/2)`,
  `proj_u2 b = (3/2,3/2,0)` → `proj_W b = (4,3/2,5/2)`
- **Correct:** `(8/3,1/3,7/3)`
- **Check (final):** `(b - S)` is not orthogonal to every spanning vector, `S` equals the
  sum of the one-vector projections, and the basis is not orthogonal
- **Why it is invisible per-step:** every individual step is arithmetically perfect. The
  mistake is the method, so nothing that checks steps one at a time can catch it.
- **Visual consequence:** their answer *does* land in the plane, so "is it in W" proves
  nothing. What fails is the property that defines an orthogonal projection: `b - proj`
  must be perpendicular to the whole plane. Theirs is not, and the right-angle marker at
  the foot does not close.
- **Scene:** the projection comparison, falling back to `StepReplay`
- **Hint:** "Your directions are not square to each other, so the shadows you added share
  part of the same ground. Watch whether what is left over meets the plane squarely."

---

### LA21 — claimed projection is not orthogonal to the subspace
**Topic:** projection · **Visual:** strong

The general case of LA20: whatever route they took, `b - proj` is not perpendicular to the
subspace, so it is not the orthogonal projection.

- **Check (final):** `(b - S).dot(u) != 0` for some spanning vector `u`
- **Scene:** the projection comparison, falling back to `StepReplay`
- **Hint:** "A projection leaves behind something square to the whole plane. Watch whether
  yours does."

---

## Property claims — the sentence is wrong, every number is right

LA22 onwards are a different species. The student computes correctly and then draws a
conclusion that does not follow. There is no wrong value to contrast and nothing to
withhold, so these are checked by `check_property_claims()` in `verify.py` — a pattern for
how the claim is written, plus the computation that settles it — and they run only when
nothing numeric is wrong. A claim we cannot settle is left alone rather than guessed at,
and a claim the student **denies** ("T does not preserve angles") is tested as the denial.

### LA22 — "it preserves angles" when it does not
**Topic:** transformations · **Visual:** strong

- **Student writes:** `T(e₁)=(2,1)`, `T(e₂)=(1,2)`, "both have length √5, so T preserves angles"
- **Why it is wrong:** equal lengths on the basis say nothing about the angle between the
  images. `(2,1)·(1,2) = 4 ≠ 0`, so the right angle is gone.
- **Check:** `AᵀA` is not a positive multiple of `I`, where the images are A's columns
- **Scene:** `AnglePreservationCheck` — the unit basis with a right-angle square between it,
  carried through the student's own map, so the square visibly collapses into an acute wedge
- **Hint:** "Equal lengths are not the same as equal angles. Watch what happens to the square
  corner between the two basis arrows."

### LA23 — "it preserves lengths" when it does not
**Topic:** transformations · **Visual:** strong

- **Check:** `AᵀA ≠ I`
- **Scene:** `AnglePreservationCheck` with `show="length"` — a ghost unit circle stays put
  while the transformed tips leave it
- **Hint:** "Watch how long the basis arrows are after the map, against how long they started."

### LA24 — "AB = BA"
**Topic:** matrix_multiply · **Visual:** strong

- **Check:** `AB - BA` is not the zero matrix
- **Scene:** `GridTransformCompare`, the two orders side by side (the LA02 picture)
- **Hint:** "Applying one map and then the other is not the same journey as applying them the
  other way round."

### LA25 — "A is invertible" (or "singular") when it is not
**Topic:** inverse · **Visual:** medium

Both directions are tested: "is invertible / has an inverse / is nonsingular" against
`det ≠ 0`, and "is singular / is not invertible / has no inverse" against `det = 0`.

- **Check:** `det(A) == 0` for the first, `det(A) != 0` for the second
- **Scene:** `StaticStepHighlight` (no bespoke picture yet — a collapsing unit square is the
  obvious one)
- **Hint:** "A map that squashes the plane flat has no way back."

### LA26 — "u and v are orthogonal" when `u·v ≠ 0`
**Topic:** vectors · **Visual:** medium

Fires only when exactly two vectors are in scope, and never on a page that mentions a
projection — "the orthogonal projection of b" is not a claim that two things are
perpendicular, and projection pages say it constantly.

- **Check:** `u.dot(v) != 0`
- **Scene:** `StaticStepHighlight`
- **Hint:** "Square to each other is a statement about the dot product, not about the lengths."

### LA27 — the wrong number of solutions
**Topic:** linear_system · **Visual:** medium

Compares `rank(A)`, `rank([A|b])` and the number of unknowns, then tests whichever of
"infinitely many solutions", "no solution" or "a unique solution" the student asserted.

- **Check:** `rank([A|b]) > rank(A)` → none; `rank = rank < n` → infinitely many; `rank = n` → one
- **Scene:** `StaticStepHighlight`
- **Hint:** "How many solutions there are is settled by how many independent conditions the
  rows really impose, against how many unknowns there are."

### LA28 — the right eigenvector, paired with the wrong eigenvalue
**Topic:** eigen · **Visual:** medium

`is_eigvec(A, v)` asks only whether `v` stays on its own line. On a symmetric
`[[3,1],[1,3]]` a student found `(1,1)` for `λ=4`, then reasoned that symmetry means
`x = y` again for `λ=2` and reused the same vector. `(1,1)` IS an eigenvector, so the
existing check said yes and the page walked free. The pairing is what is wrong.

- **Check:** an eigenvalue is in scope from an earlier line, and `Av ≠ λv` for it
- **Note:** the claim is usually prose — "so the same vector (1,1) works for both
  eigenvalues" — with no vector value on the step at all, so the vector is read out of
  the sentence
- **Scene:** `EigenRayTest` refuses this one by design (nothing lifts off the line), so
  it falls back to `StaticStepHighlight`. The bespoke picture would show the vector
  travelling the wrong distance ALONG its line.
- **Hint:** "A vector can sit on an eigen-line and still belong to a different stretch."

### LA29 — coordinates in a basis read off as the vector's own entries
**Topic:** coordinates · **Visual:** strong

`[v]_B` is the pair of weights that rebuild `v` from `b1, b2`, not `v`'s entries. The
extractor labels "[v]_B = (5,1)" as `copy_given`, so it was compared against `v` itself
and PASSED — and `[v]_B = v` is precisely the misconception, so the only wrong claim on
the page was certified correct while a later, arithmetically perfect line took the blame.

- **Check:** `c₁b₁ + c₂b₂ ≠ v`; the target is `solve([b₁ b₂], v)`
- **Scene:** `VectorOpCompare` via `_span_rebuild` — the student's weights, applied, against
  the vector they are supposed to reach
- **Hint:** "Coordinates in a basis are the amounts of each basis vector you need to
  rebuild the vector — not the vector's own entries."

### LA31 — the perpendicular part returned instead of the shadow
**Topic:** projection · **Visual:** strong

"Find the projection of v onto the x-axis" names its target subspace in WORDS. The
extractor has no vector to record for it, so `topic_target()` built nothing, the final
step went `UNCHECKED`, and a wrong answer came back as "nothing in this work disagrees".
`named_axis()` turns the wording into the basis vector it always was and hands it to the
existing projection machinery under the reserved given `axis`; nothing about projections
is special-cased and no answer is hardcoded.

The misconception itself: v splits into a part lying ALONG the axis and a part standing
away from it at a right angle. Both are honest pieces of v and they sum to v, which is
exactly why students hand back the wrong one.

- **Student writes:** `v = (3,2)`, `proj(v) = (0,2)`
- **Check:** the claim equals `v - proj`, the residual, rather than `proj`
- **Scene:** `VectorOpCompare` (`op="projection"`) — v, the axis, the dashed
  perpendicular, the shadow along the axis, and the student's arrow standing straight up
- **Hint:** "A shadow lies ALONG the thing it falls on. What you kept is the part that
  stands away from it at a right angle."
- **Deliberately literal:** one axis, named outright. Two axes in one sentence, a
  non-axis subspace ("the line y = 2x"), or a task that is not a projection ("reflect v
  across the x-axis") all leave the machinery switched off rather than guessing.

### LA32 — projected onto the other axis
**Topic:** projection · **Visual:** strong

Checked BEFORE LA31, because it is the more specific reading and much the more useful
one: "you projected onto the other axis" is something a student can see and fix, where
"you returned the residual" uses a word they may not have met yet. In R2 the two
descriptions pick out the same vector; in R3 they part company, and both codes earn
their place.

- **Student writes:** `v = (3,2)`, asked for the x-axis, answers `(0,2)` — which is the
  projection onto the y-axis
- **Check:** the claim equals the projection onto some coordinate axis OTHER than the one
  the problem named
- **Scene:** `VectorOpCompare` (`op="projection"`), with the target axis LABELLED by name
  rather than called "the axis" — that label is most of what makes the mix-up legible:
  the white shadow lies along the x-axis, the student's arrow stands up the y-axis
- **Hint:** "A shadow falls onto the line you were asked about, and lands ALONG it. Look
  at which line your own arrow is sitting on."

## The wrong-rule signatures (LA33–LA40)

Added after measuring Noema against expert reviewers who diagnosed the same 32 cases
blind. Agreement was 32/32 on whether work was wrong at all and 30/32 on which step —
but on six cases Noema found the right step and had no name for the misconception, so
the student got "watch the highlighted part". Each of these fires only when the
student's value is exactly what a specific FALSE IDENTITY produces and is not the right
answer. That precision is the point: a signature that guesses is worse than none.

| Code | The false rule | Truth |
|---|---|---|
| **LA33** | the standard matrix stores each image along a ROW | images are the COLUMNS |
| **LA34** | independent ⟹ a basis | a basis of Rⁿ needs n of them as well |
| **LA35** | the eigenvalues are the diagonal entries | true only when nothing sits below it |
| **LA36** | det(A+B) = det A + det B | det is linear in each ROW, not in the matrix |
| **LA37** | det(cA) = c·det A | det(cA) = cⁿ·det A — once per row |
| **LA38** | (AB)⁻¹ = A⁻¹B⁻¹ | (AB)⁻¹ = B⁻¹A⁻¹ — shoes before socks |
| **LA39** | ‖u‖ = Σuᵢ² | that is ‖u‖², the square of the length |
| **LA40** | a solution is a set of numbers | it is an ordered assignment; the values were right and the slots were swapped |

LA33 deliberately does nothing when the images are symmetric: rows and columns then give
the same matrix and there is no mistake to find, which is exactly why the habit survives.

**A false positive these controls caught, unrelated to any of them:** `det(A+B)` and
`det(2A)` computed CORRECTLY were being marked wrong, because the determinant branch
read only the first symbol on the line and compared against `det A`. `_det_argument()`
now evaluates what is actually inside the brackets.

**Where the experts still differ from us (2/32):** on a page whose conclusion follows
from an earlier false sentence, they blame the sentence and we blame the conclusion —
`sys-colspace` ("b is in the column space", then "so it has a solution") and
`trans-rows` ("put them in as rows", then the matrix). Both of ours are defensible, and
both of theirs point at the idea rather than its consequence. Open.

---

### LA19 — projection with the wrong denominator
**Topic:** projection · **Visual:** strong

Writes `proj_v(u) = (u·v / ‖v‖)·v` instead of `(u·v / v·v)·v`.

- **Student writes:** `u = (3,4)`, `v = (2,1)`, `proj = (10/√5)(2,1) = (4√5, 2√5) ≈ (8.94, 4.47)`
- **Correct:** `2·(2,1) = (4,2)`
- **Check (invariant, preferred):** `not eq((G['u'] - S).dot(G['v']), 0)`
- **Check (signature):** `eq(S, (G['u'].dot(G['v'])/G['v'].norm())*G['v'])`
- **Visual consequence:** The defining property of a projection is that the residual `u − p`
  meets the line at a right angle. Draw v's line, drop the segment from u's tip to the
  correct foot at `(4,2)`, and snap a right-angle marker closed. Then drop the segment to
  their point at `(8.94, 4.47)` — far down the line, well past u — and the marker visibly
  **fails to close**; the residual dot product is `-12.36`, not 0. Their point is also plainly
  further from the origin than u itself, which is absurd for a shadow. Two independent things
  wrong in one frame, both visible without narration.
- **Scene:** `VectorOpCompare` (op=`projection`, right-angle marker)
- **Hint:** "A shadow can't be longer than the thing casting it. Watch whether the corner
  marker closes."

---

## 3. Where we have no visual, and what that costs

Stated plainly, because it shapes routing:

- **LA03 (shape mismatch)** — no map exists, so no grid deforms. Any animation would be
  fabricated. Hard-route to `StaticStepHighlight`, and guard the renderer: a shape error must
  be caught before sympy raises `ShapeError` inside the render job.
- **LA18 (dot as vector)** — a category error, not a geometric one. Drawing their vector next
  to a projection diagram would actively mislead.
- **LA10 (charpoly sign)** — only medium, and **nothing at all** when the bad polynomial has
  complex roots. Gate on `im(λ) == 0`.
- **LA01 (row-by-row)** — the determinant is invariant under this error for 2×2, so the area
  story is unavailable. Use destination, not size.
- **LA08 (no diagonal swap)** — real but small; needs a zoom and a reference grid or the drift
  is lost at default framing.

Two further classes worth knowing we don't cover: **notation-only slips** (a dropped transpose
bar, a misplaced subscript) have no geometry by construction, and **conceptual claims about
infinite-dimensional or abstract vector spaces** have no R²/R³ picture. Both route to
`StaticStepHighlight`.

---

## 4. Verification strategy

### 4.1 Two-layer detection

Keep these strictly separate; conflating them is the main way this component fails.

- **Layer 1 — is the step wrong?** A single invariant check against the *given problem data*.
  Generic, and it works on errors not in this taxonomy.
- **Layer 2 — which mistake was it?** Signature match against the 19 entries above. Determines
  the scene template and the hint wording.

Layer 1 runs first and alone decides the verdict. If Layer 2 matches nothing, we still know the
step is wrong and still render `GridTransformCompare` with their claimed object against the
correct one, plus a generic positional hint. **Coverage is therefore not limited to 19 errors** —
the taxonomy buys better hints and better scene selection, not the ability to detect at all.
Note that LA17 and LA19 above already have invariant checks (perpendicularity) that are far more
robust than their signatures. Prefer invariants wherever one exists.

### 4.2 Check claims against the problem, not against our solution path

Do **not** compute our own solution and diff it step against step — the student's route is
legitimately different from ours and we would flag correct work constantly.

Instead, each step is a *claim*: `expr_i = value_i`. Evaluate `expr_i` exactly from the original
given data and compare to `value_i`. Where the student restates no expression (just writes a
matrix), fall back to step-to-step equivalence: is `value_i` reachable from `value_{i-1}` by the
operation they labelled, or by any single operation in a small legal set (row ops, scalar
multiply, transpose, one multiplication)?

### 4.3 Canonical comparison by type

Never compare LaTeX or strings. Canonicalize both sides, then compare by type:

| type | comparison |
|---|---|
| scalar | `simplify(a-b) == 0`, numeric fallback |
| matrix / vector | shape first, then entrywise `simplify` → `nsimplify` → numeric |
| eigenvector | **scale-invariant**: `Matrix.hstack(v,w).rank() <= 1`. Accept any nonzero multiple, either sign, normalized or not |
| eigenvalue list | multiset, sorted by `(re, im)` after `N()`, with multiplicity |
| basis / spanning set | **compare spans, not lists**: `rank(V) == rank(W) == rank(hstack(V,W))` |
| RREF / augmented system | `A.rref() == B.rref()`; any row-equivalent form is accepted |
| solution set | for underdetermined systems compare particular + nullspace basis as spans |

The eigenvector and span rows are what separate "wrong" from "different but equivalent form."
A student writing `(2,2)` where we computed `(1,1)`, or listing a basis in another order, or
stopping at row-echelon rather than *reduced*, is **correct** and must not be flagged. This is the
single highest-risk false-positive source in the app.

### 4.4 Float tolerance

Three tiers, in order:

1. **Exact.** Both sides rational or symbolic → `simplify(a-b) == 0`. No tolerance at all.
2. **Rationalize.** Student wrote decimals → `nsimplify(v, rational=True, tolerance=1e-4)` and
   retry exact. `0.4` must match `2/5`; `0.333` must match `1/3`.
3. **Numeric.** `abs(a-b) <= atol + rtol*max(1,abs(b))` with `atol=1e-6`, `rtol=1e-4`.

Plus a **rounding amnesty**: if a step fails tier 3 but passes at `rtol=5e-3`, mark it
`plausible_rounding` and **do not call it the first error**. A student writing `0.71` for
`1/√2 = 0.7071` is not making a linear algebra mistake, and failing them for it is the most
embarrassing possible demo outcome. Amnesty applies only to the *last* significant digit pattern —
if the sign differs, or the magnitude is off by more than 1%, it's a real error.

**Implementation trap, found while validating this document:** a naive `eq()` helper gave a false
"not equal" on two matrices that were mathematically identical, because one side was `sympy.N(...)`
(Float entries) and the other was exact (`4*sqrt(5)`). Mixed-domain matrices break entrywise
comparison in ways that look like student errors. **Canonicalize both sides into the same domain
before comparing** — rationalize-or-floatify both, never one of each. Unit-test this specifically.

### 4.5 Root cause, not first symptom

Once step *k* fails, run **forward propagation**: accept `value_k` as given and re-check
`k+1 … n`.

- All subsequent steps consistent → one error, at *k*. Report with high confidence.
- Subsequent steps also fail → report *k*, flag `multiple_errors`, and still animate *k* only.

Also require the flagged step to be **load-bearing**. If propagating from *k* does not reproduce
their final answer, *k* was abandoned scratch work — demote it and keep searching. Students cross
things out and restart; blaming a discarded line is a bad experience.

Ordering is by `(page, line)` from the OCR bounding boxes, not by the order the model happens to
emit steps.

### 4.6 Unparseable steps

**Never treat "cannot parse" as "wrong."** Policy, in order:

1. Mark `parse_ok=False`, status `SKIPPED_UNPARSED`, carry the last known-good value forward.
2. **Bridge the gap.** If `i-1` and `i+1` both parse and `i+1` is consistent with `i-1`, the
   unreadable line was harmless — continue.
3. **Bracket the error.** If `i+1` is *inconsistent* with `i-1`, the error is inside the unreadable
   region. Report at the unparsed step with a region-level hint ("something between line 2 and
   line 4") and **still render the animation** from `value_{i+1}` — the animation needs only their
   claimed *object*, never a successful parse of the reasoning.
4. **One retry.** Re-ask the vision model for just that line's LaTeX at higher crop resolution
   before giving up. Budget-capped at one retry per step, two per image.
5. **Final-answer fallback.** If nothing intermediate parses but the final answer does and is
   wrong, animate their final object against the correct one with a generic hint. This is the
   safety net that guarantees the demo always produces *something* — wire it up early.

### 4.7 Charitable reading of OCR ambiguity

Handwriting OCR should emit up to **K=3 candidate parses** per step (4 vs 9, minus sign vs fraction
bar, 1 vs 7). A step is wrong only if **all** candidates are wrong. If any candidate makes the step
correct, adopt it and continue.

This prevents the single most likely demo failure: confidently accusing a student of an error the
camera invented. Bias hard toward charity — a missed error costs nothing on stage, a fabricated one
kills the pitch.

### 4.8 Performance guards

`sympy.simplify` can hang on ugly expressions and will take the whole request with it. Use fast
paths first (`cancel`, `expand`, `together`), wrap each step check in a **2-second timeout**, and
fall back to numeric comparison on expiry. Budget the whole verification pass at under 3 seconds so
the time goes to rendering, which is the actual bottleneck.

### 4.9 Output contract

```
{
  "first_error_index": 3,
  "confidence": "high",              # high | medium | low(bracketed/unparsed)
  "error_id": "LA07",                # null if Layer 2 found no signature
  "student_value": <Matrix|scalar>,  # drives the animation
  "correct_value": <Matrix|scalar>,
  "scene_template": "InverseRoundTrip",
  "scene_params": { ... },
  "positional_hint": "...",          # points, never corrects
  "flags": ["load_bearing", "single_error"]
}
```

Hint discipline: name a **location** and a **thing to watch**, never a correction. "Check the
second column of your step 3" and "watch whether the corner marker closes" are fine. "You forgot
the 1/det" is a failure of the product.

---

## 5. Helper contract for `sympy_check`

Every check above is an expression evaluated with this scope:

```python
S        # the student's claimed value at this step (Matrix or scalar)
G        # dict of given problem objects: G['A'], G['B'], G['M'], G['u'], G['v'], G['b'], G['V']
eq(a, b) # tolerance-aware equality per 4.3/4.4
lam      # sympy symbol for the eigenvalue variable
Matrix, eye, simplify, nsimplify   # from sympy
```

Verified helper implementations:

```python
def is_eigvec(M, v):
    v = Matrix(v)
    return v.norm() != 0 and Matrix.hstack(v, M * v).rank() <= 1

def span_eq(V, W):
    MV, MW = Matrix.hstack(*V), Matrix.hstack(*W)
    return MV.rank() == MW.rank() == Matrix.hstack(MV, MW).rank()
```

## 6. Demo picks

Strongest three in order, all verified end to end:

1. **LA02** — rotate-then-stretch vs stretch-then-rotate. Two panels, same pieces, visibly
   different result. Best opener.
2. **LA07** — the grid doesn't come home, and misses by exactly 10×. Best single frame.
3. **LA09** — the vector falls off its own line. Best concept.

All three use P0 templates only (`CompositionOrderCompare` is P1 — LA02 degrades acceptably to
`GridTransformCompare` if you run out of time).
