# Template audit — does the error actually SHOW?

Audited 2026-09-20 ~01:00–01:10 UTC by the scene-sweep agent.
Every template in `backend/scenes/registry.py` (7 canonical + 5 aliases) plus the
11 named presets that subclass them was rendered at `-qm` (1280x720@30), frames
were pulled with ffmpeg and looked at, including downscaled to 384px wide as an
"across the room" test.

**36 renders, 0 crashes, 0 exceptions, 0 fallbacks.** Nothing here is broken in
the "it dies" sense. The problem, where there is one, is that some templates
produce two pictures a judge cannot tell apart.

## How it was tested

```
in-process:  registry.render(name, params, quality="medium_quality")
params:      backend/scenes/example_params/*.json, and <Preset>.DEFAULTS for the
             presets that have no example file
frames:      ffmpeg -ss {20,50,75,97}% of duration, viewed at 1280x720 and 384px
reveal:      REVEAL_CORRECT_VALUES left at its default False (demo behaviour)
```

Timing caveat: `determinant_area.py`, `line_system.py`, `span_compare.py`,
`step_focus.py`, `vector_op.py` and `helpers.py` were edited by another agent at
01:02–01:05 while this sweep was running. Everything in the table below is the
**second** pass, rendered after 01:05, so it reflects that code. Panels got
bigger and several hint/border overlaps were fixed between the two passes — if
those files move again, re-check the four rows marked with a dagger.

## The table

Rank is demo order: 1 is the animation to put in front of the judge.

| # | Template (preset) | Covers | Renders | Sec | MB | Convincing | What is wrong | Rank |
|---|---|---|---|---|---|---|---|---|
| 1 | **GridTransformCompare** (defaults) | LA01/16, unmatched | yes | 6.4 | 0.49 | **YES** | Nothing that matters. Grid is busy but the two red j-hats lean opposite ways — survives 384px. | **1** |
| 2 | **CompositionOrderCompare** → GridTransform | LA02 | yes | 9.1 | 0.90 | **YES** | Stage label ("then rotate") is drawn in the gutter with no backing plate and the left panel's border + grid lines strike through the glyphs. | **2** |
| 3 | **EigenRayTest** (`mode=vector`) | LA09 | yes | 7.0 | 0.71 | **YES** | Dashed reference line on the right panel is grey-on-dark and nearly invisible at distance; "off the line" tag is small. Geometry still carries it. | **3** |
| 4 | LineSystemCompare (`mode=row_op`) = **RowOpLinePivot** | LA12/13 | yes | 5.0 | 0.37 | **YES** | ~120px dead band between titles and panels. Result lines don't span the panel width. | **4** |
| 5 | LineSystemScaleNoOp (`row_op` preset) | LA13 | yes | 5.2 | 0.34 | **YES** | † "off the crossing" label overlaps the left panel's top border; "unchanged" label collides with the hint line at the bottom. | **5** |
| 6 | **SpanCompare** (2-D, la15) | LA15 | yes | 5.3 | 0.31 | **YES** | † "gap" label sits on top of the green arrow. "REACHED ?" adds nothing (masked). | **6** |
| 7 | LineSystemCompare (`mode=solution`) = **SolutionPointCheck** | LA12 | yes | 3.8 | 0.25 | marginal→yes | Geometry lives in the top-left quadrant only; half the panel is empty grid. The "9 vs 11" readout does more work than the picture. | **7** |
| 8 | **VectorOpCompare** (`op=projection`, la19) | LA19 | yes | 4.6 | 0.26 | marginal | † Correct (white) arrow is short and lies under the orange one; right-angle marker is ~15px. Overshoot is visible, the "corner doesn't close" story is not. | 8 |
| 9 | DeterminantAreaFlip (`DeterminantAreaCompare` preset) | LA06 | yes | 5.9 | 0.65 | marginal | † Sign error is conveyed only by a grey→purple fill change plus a text label. Miss the transition and the end frame says nothing. | 9 |
| 10 | **InverseRoundTrip** → GridTransform | LA07 | yes | 8.9 | 1.03 | marginal | Plane is scaled for the student's 10x blow-up, so the CORRECT panel ends with basis vectors about 4px long — the "good" answer looks like an empty box. Stage label struck through by the panel border, as in #2. | 10 |
| 11 | VectorOpNormalize (`VectorOpCompare` preset) | LA11 | yes | 5.1 | 0.27 | marginal | Claimed tip and true tip are ~25px apart. You must already be looking at the circle to see it. Dies at 384px. | 11 |
| 12 | **StaticStepHighlight** (la03 shape mismatch) | LA03/18, fallback | yes | 3.8 | 0.20 | marginal | Static slide, no motion at all. Orange focus box is mis-sized: it cuts the trailing "..." in half. Reads fine; it is not a demo animation. | 12 (fallback only) |
| 13 | VectorOpCross (`VectorOpCompare` preset) | LA17 (P2) | yes | 5.3 | 0.31 | marginal | Fake 3-D. Orange arrow does visibly pierce the sheet, but "every arrow in here is a combination of u and v" is printed over the sheet and the arrows. | 13 |
| 14 | StaticStepHighlightPairing (`StaticStepHighlight` preset) | LA01 pairing | yes | 3.8 | 0.20 | **NO** | **Glitch:** the dashed focus box is ~2x the cell height, sticks out above the matrix bracket, and encloses a stray grey "?" that never clears. Travelling dots are 8px and easy to miss. | 14 |
| 15 | **DeterminantAreaCompare** (la04, M=[[3,4],[1,2]]) | LA04 | yes | 6.1 | 0.97 | **NO** | The landed parallelogram (det 2) is a thin grey sliver inside a field of ~40 near-parallel blue lines. Readout says "YOUR ANSWER 10 / AREA ON SCREEN **?**". Nothing on screen says 2. The example file's hint ("watch the counter as the square lands") points at a counter that is permanently "?" — the class DEFAULTS hint was already updated to mention the grey tiles, `example_params/la04_determinant_area.json` was not. | 15 |
| 16 | **EigenRayTest** (`mode=eigenvalue`) | LA10 | yes | 7.6 | 0.81 | **NO** | Textbook failure mode: two near-identical panels. The whole error is a dark-grey ghost arrow on the left panel with a 4-letter "gap" tag. Invisible at 384px. | 16 |
| 17 | SpanCompare3D (`SpanCompare` preset) | LA14 (P2) | yes | 4.1 | 0.23 | **NO** | Flat grey quad plus a thin "V" of axes and no depth cue. Reads as a rendering artefact, not as "your three vectors only reach a plane". | 17 |
| 18 | DeterminantVolume3D (`DeterminantAreaCompare` preset) | LA05 (P2) | yes | 6.9 | 0.25 | **NO** | Unrecognisable dark slab with stray line stubs at its base, barely changes across the whole 10.2s, bottom 40% of the panel is empty, readout is "-79 / **?**". Worst frame in the set. | 18 |

† = row most exposed to the concurrent edits in `determinant_area.py` /
`line_system.py` / `span_compare.py` / `vector_op.py`.

## Verdict

**Demo-grade (ranks 1–6).** Put these in front of a judge. In each one the two
panels are different *shapes*, not different numbers, and the difference
survives being shrunk to a thumbnail:

- **GridTransformCompare** — the hero. The student's j-hat leans one way, the
  correct one leans the other; mirror image, instantly readable. It is also
  where the flagship sample routes: `samples/index.json` says `la_multiply`
  ("first_error at s4, no taxonomy signature") lands on GridTransformCompare via
  Layer 1. Lead with this.
- **CompositionOrderCompare** — ends with a tall green arrow on the left and a
  long red arrow pointing left on the right. "Order matters" in one frame.
- **EigenRayTest (vector)** — the orange arrow visibly lifts off its own dashed
  line while the reference arrow slides along its own. This is the best
  *explanation* in the set even if it is #3 on pure punch.
- **RowOpLinePivot / LineSystemScaleNoOp** — one horizontal line misses the
  circled crossing point, the other goes straight through it. Cheap, fast (5s),
  and unambiguous.
- **SpanCompare 2-D** — the panel stays black except for a dotted line while the
  readout says "YOUR CLAIM: a plane". Good punchline.

**Duds (ranks 15–18). Do not demo these, and prefer falling back over showing
them.** `DeterminantAreaCompare` in its main LA04 configuration,
`EigenRayTest(eigenvalue)`, `SpanCompare3D`, `DeterminantVolume3D`. All four
render fine and all four fail the only test that matters: a judge watching once
cannot see what the student got wrong. Three of them end on a readout of the
form "YOUR ANSWER <number> / …ON SCREEN **?**", which reads as a broken counter
rather than as a deliberately withheld answer.

**One real glitch worth a fix if anyone has spare minutes**, in priority order:

1. `StaticStepHighlightPairing` — oversized dashed focus box with a stray "?"
   trapped in it, above the matrix. This is the only frame in the sweep that
   looks like a bug rather than a design tradeoff.
2. GridTransformCompare stage labels — drawn in the gutter with no backing
   plate, so the panel border and grid lines cut through the text. Hits the #2
   and #10 templates. A small opaque rectangle behind the label fixes it.
3. `StaticStepHighlight` focus box width — clips the last character of the
   focused line ("A B = .|.").
4. `InverseRoundTrip` panel scale — the correct panel's basis vectors end up
   ~4px. Either clamp the plane scale or drop a marker at the origin so the
   "came home" panel does not read as empty.

**Risk note for 10:00.** Nothing in the ladder is load-bearing on the duds:
every template that fails validation or rendering degrades to
`StaticStepHighlight`, which rendered in 3.8s and is legible. The danger is not
a crash, it is picking rank 15–18 for the one animation the judge watches.
