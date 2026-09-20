# StepReplay: end-to-end status

Verified **2026-09-20, ~02:4x**, branch `claude/sleepy-shannon-me91wd`, by rendering
through the real API and **looking at 20 extracted frames**, not by exit codes.

Verdict: **it works.** On the user's own homework the video walks their two steps in
order, one at a time, on one canvas, driven entirely by the numbers they wrote, and
the error is visible without being stated. The two defects found were in the *other*
projection fixture; both are fixed. Open items are listed at the bottom and none of
them block the demo.

---

## 1. What was verified, and how

```bash
cd /home/user/hackmit-2026
fuser -k 8099/tcp                       # NOT pkill -f uvicorn: it kills your own shell
nohup env USE_FIXTURE=1 .venv/bin/python -m uvicorn backend.app:app --port 8099 \
      > /tmp/srv.log 2>&1 &
sleep 6

curl -s -X POST localhost:8099/api/analyze -H 'content-type: application/json' \
     -d '{"fixture":"projection_scaling","wait":true}' > /tmp/pj.json
python -c "import json;d=json.load(open('/tmp/pj.json'));print(d['rendered_template'],d['video_status'],d['video_url'])"
# -> StepReplay ready /api/video/<id>

curl -s localhost:8099/api/video/<id> -o /tmp/pj.mp4
for t in 0 2.2 4.8 6 8 10 12.5 15.5; do
  ffmpeg -v error -y -ss $t -i /tmp/pj.mp4 -frames:v 1 /tmp/f_$t.png; done
# then OPEN the pngs. Exit code 0 proves a render happened, not that it says anything.
```

Route: `projection_scaling` -> first error at `s2` -> no taxonomy `error_id` ->
`StepReplay`. `notes` records the demotion: *"StepReplay: replaying 2 of the student's
own steps (2 with geometry); StaticStepHighlight demoted to fallback"*. Render 13.4 s,
video 16.5 s at 1280x720/30.

---

## 2. The five questions, answered from the pixels

| Question | Answer |
|---|---|
| Walks the steps **in order, one at a time**? | **Yes.** Step 1's line types into the rail, plays, gets a ✓; only then does step 2's line appear, play, and get a caret. |
| Each step's geometry from the **student's own numbers**? | **Yes.** `a=(1,2)` and `b=(3,1)` are drawn from the givens; step 1 lights the legs `1`,`2`,`3`,`1` and a bar strip built from *their* terms `3(1)` and `1(2)` summing to *their* `5`; step 2 scales by *their* `5`. Nothing is preset. |
| Does the `(5,10)` arrow **visibly overshoot b**? | **Yes, unmistakably.** Orange `5a` leaves the `\|b\|` disc ("every shadow of b lands in here") far behind and the camera has to zoom out ~2.6x to contain it. This is the money shot. |
| Everything stays in frame? | **Yes.** Automated check: no pixel brighter than 60 in the outer 3 px of any frame, on **all six** fixtures. |
| Any correct answer printed? | **No.** `scene_params` carries no correct value; `leak_guard: ["project"]` stops the dot-product beat drawing the perpendicular whose foot *is* the answer. See the caveat in §5. |

Frames worth re-checking by eye if you change anything: **t=4.8 s** (the arithmetic
strip) and **t=15.5 s** (the held final frame with the hint).

---

## 3. Defects found and fixed

Both were on `la19_projection`, which now also routes to StepReplay. The hero fixture
`projection_scaling` was unaffected — its video is **byte-identical** before and after
(`md5 b788ec2981bc65fe24d74527c941437f`), so nothing about the motivating example
regressed.

**(a) The student's own claimed value was cut off the rail.**
`EXPR_CHARS = 34` in `backend/step_compiler.py` clipped step 3 to
`proj = (10/sqrt(5))(2,1) = (4 sqr…`. The one thing the rail exists to do is show
their work faithfully, and it was truncating it.
Fix: `EXPR_CHARS = 48`; the wrong step's `= <value>` tail may now wrap to two lines;
and `_build_ledger` gained `_fit_ledger`, which scales the whole rail as one group if
it would stack below `LEDGER_FLOOR = -3.05` and collide with the hint. Now reads
`= (4 sqrt5, 2 sqrt5)` in full.

**(b) Two labels overprinted into nonsense.**
u's green component tick `3` landed exactly on the Cauchy–Schwarz bound label and the
pair read as `|u||3|`. Fix, in `_k_dot_product`: `_clear_strip` pushes any component
label out of the arithmetic card's known footprint, and `_spread` slides overlapping
labels apart **horizontally only** (a vertical nudge is what would push one back into
the card). Now reads `|u||v|` with `2`, `3`, `1` separated.

---

## 4. Regression pass — all six fixtures, after the fix

Every one 200, video ready, `video_error: null`, `degraded: false`, no edge overflow,
no near-blank frame mid-video.

| fixture | template | duration |
|---|---|---|
| `la02_order` | GridTransformCompare | 12.1 s |
| `la07_inverse` | GridTransformCompare | 12.1 s |
| `la09_eigen` | EigenRayTest | 9.4 s |
| `la19_projection` | **StepReplay** | 16.7 s |
| `la_multiply` | GridTransformCompare | 8.7 s |
| `projection_scaling` | **StepReplay** | 16.5 s |

`backend/tests/test_step_compiler.py` 11/11, `test_openai_provider.py` ALL PASS,
`pyflakes` clean on both changed files, `node --check frontend/app.js` clean.

Reproduce:

```bash
for f in la02_order la07_inverse la09_eigen la19_projection la_multiply projection_scaling; do
  curl -s -o /tmp/$f.json -w "$f %{http_code}\n" -X POST localhost:8099/api/analyze \
       -H 'content-type: application/json' -d "{\"fixture\":\"$f\",\"wait\":true}"
done
.venv/bin/python backend/tests/test_step_compiler.py
```

---

## 5. What a human should check first

1. **The frontend never reads `replay`.** `frontend/app.js` uses `video_url`,
   `video_status`, `hint` and `steps` only. The replay metadata block
   (`replay.motion_steps`, `first_wrong_label`, …) is API-only. Nothing is broken —
   just do not promise it on stage.
2. **`correct_value` is still in the `/api/analyze` JSON** (pre-existing; already in
   CLAUDE.md's open items). The *video* is clean; devtools is not.
3. **Answer/given coincidence on the hero fixture.** The correct projection of `b`
   onto `a` happens to be `(1,2)`, which *is* the given `a`. `a` is on screen because
   the problem states it, and it is never marked as the answer — but a sharp judge may
   notice the arrow whose tip is the answer is already drawn. This is a property of
   the problem, not a leak in the code.
4. **The first frame is a bare grid** (title and vectors animate in). The `<video>` is
   `autoplay loop`, so it flashes near-empty on every loop. Same known item as the
   other templates; a scene-side fix would mean drawing the title + givens at t=0
   instead of animating them.
5. **Legibility of the arithmetic strip.** `3(1)` / `1(2)` / `|b||a|` render at
   font_size 19–20 in grey and team colors at the bottom-left. Fine on a laptop;
   shrink the frame to ~380 px and decide for yourself whether it survives a
   projector. Everything load-bearing (the arrows, the disc, the ledger, the hint) is
   much larger.
6. **On `la19_projection` the three component digits `2 3 1` sit close together** at
   the foot of the vectors. They are separated and color-coded to their vectors, but
   it is the densest spot in either video.

---

## 6. Honest limits

- Two fixtures exercise StepReplay. The compiler handles more kinds
  (`matrix_apply`, `row_op`, `normalize`, `add_vectors`, …) than any fixture reaches,
  so those paths are **unverified by eye**. A live photo of a different topic may
  route to StepReplay and hit a handler nobody has watched run.
- `_fit_ledger` is exercised only by construction, not by a fixture: no sample
  produces a rail long enough to trip `LEDGER_FLOOR`. It is a guard, not a tested path.
- `backend/scenes/step_replay.py` also carries **another agent's uncommitted edits**
  (the per-step framing/hysteresis block). Everything above was rendered from the
  working tree as it stands, so the results describe the combined state.

---

## 7. Files

- `backend/scenes/step_replay.py` — the scene. Changed: `LEDGER_FLOOR`,
  `_fit_ledger`, the tail's `max_lines`, `_clear_strip` + `_spread` in `_k_dot_product`.
- `backend/step_compiler.py` — steps -> params. Changed: `EXPR_CHARS` 34 -> 48.
- `samples/projection_scaling.json` — the user's homework, as a fixture.
- `docs/RENDERING.md` — the manim/LaTeX minefield. Read it before touching a scene.
