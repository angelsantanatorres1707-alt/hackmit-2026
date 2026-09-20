# hackmit-2026 — working agreement

Photograph handwritten linear algebra → the app extracts the steps, finds the
**first** one that is mathematically wrong, and renders a Manim animation that
replays the student's own reasoning until it visibly breaks. A short hint points
at the step **without stating the correction**.

**Demo is 10:00 EDT. Keep `main` runnable at every commit.** A broken branch at
9am costs more than any feature is worth.

---

## Who is editing what

Two agents work on this repo at once. Stay in your lane and neither of us loses
work.

| Area | Owner |
|---|---|
| `frontend/` — logo, CSS, layout, copy | **UI agent** |
| `backend/`, `backend/scenes/`, `scripts/`, `samples/`, `docs/` | **backend agent** |

`frontend/app.js` is shared and is the one real collision risk. The backend agent
touches it only for wiring (video fallback, warning banners). If you must change
it, **re-read the file immediately before editing**, keep the edit surgical, and
never revert a change you did not make.

**Pull before you start and before every push.** `git pull --rebase` if you have
local commits.

---

## Run it

```bash
bash scripts/setup.sh    # once, ~60s (macOS or Debian)
bash scripts/run.sh      # http://localhost:8000, fixture mode, no API key
```

Fixture mode runs the whole pipeline offline on bundled samples — that is how you
develop and it is the demo's insurance. `--live` reads real photos and needs a
key (`.env`, see `.env.example`). `.env` is gitignored; **never commit a key**.

Before you push:

```bash
bash scripts/smoke.sh                                  # if present
curl -s localhost:8000/api/health | python -m json.tool
```

---

## Things that break silently

These cost hours to diagnose and give no error. Read this section before touching
the relevant area.

### Manim (scenes)

- **Never use `Tex`, `MathTex`, `Matrix`, `IntegerMatrix`, `DecimalMatrix` or
  `MobjectMatrix`.** All of them shell out to `latex`, which is deliberately not
  installed. `Matrix` builds even its *brackets* from LaTeX, so
  `element_to_mobject=Text` is not enough. Use `text_matrix()` in
  `backend/scenes/common.py`.
- **A missing font makes `Text()` render blank and raises nothing.**
  `fonts-dejavu-core` is in `setup.sh` for this reason.
- `ApplyMatrix` needs `about_point=plane.get_origin()` or the grid translates
  away instead of transforming in place.
- Full list of traps: `docs/RENDERING.md`.

### The product rules

- **The animation must not print the correct answer.** Numbers on the reference
  side are masked to `?` unless `REVEAL_CORRECT_VALUES=1`. That includes
  determinants, eigenvalues, solution coordinates — anything computed *from* the
  problem. The student's own values always stay visible; they are their work.
- **Hints point, they do not correct.** "Watch where the first basis vector
  lands in your step 2" — never the right value. `backend/hints.py` lints for
  this; do not weaken it.

### Frontend

- **No build step. No npm. No CDN.** Vanilla HTML/CSS/JS served statically by
  FastAPI. Venue wifi will fail; everything must be local.
- **Dark theme and large type are deliberate** — this is judged on a projector
  from across a room. Test by shrinking a screenshot to ~380px wide: if you
  cannot read it, neither can the judges.
- `frontend/app.js` reads **41 element IDs** out of `index.html`. Renaming or
  removing one breaks that feature with no console error. Before restyling the
  markup, check the id is unused:

  ```bash
  grep -n "my-id" frontend/app.js
  ```

  The load-bearing ones: `video`, `video-frame`, `video-overlay`,
  `video-fallback`, `fallback-reason`, `hint-text`, `hint-card`, `warnings`,
  `result-steps`, `readback-steps`, `step-count`, `problem-statement`,
  `dropzone`, `file-input`, `analyze-btn`, `confirm-btn`, `sample-photo-btn`.
- These CSS classes are created from JS, so they must keep working even though
  they appear nowhere in `index.html`: `warn-row`, `warn-loud`, `step`,
  `step-label`, `step-raw`, `step-flags`, `flag`, `crossed`, `mobj`,
  `mobj-grid`, `bracket`, `cell`, `chip`, `thumb`, `look-here`, `given`.
- Keep `<video>` as `muted playsinline autoplay loop` — autoplay is blocked
  without `muted`.

---

## Checks that matter

```bash
node --check frontend/app.js                 # JS parses
bash -n scripts/run.sh                       # shell parses
.venv/bin/python backend/tests/test_openai_provider.py
```

Then load the page, click **use sample**, and confirm you get: the read-back
screen → a playing animation → a hint. If the video is a black rectangle, read
the fallback message; it names the cause.

**Look at the pixels.** Exit code 0 proves a render happened, not that it shows
anything. Extract frames and view them:

```bash
ffmpeg -i out.mp4 -vf "select='eq(n\,120)'" -fps_mode passthrough frame.png
```

---

## Known open items

- Every render now opens with a title beat and a concept beat
  (`backend/scenes/prologue.py`) before the student's work. Act 2 is chosen by
  `concept_for()` from the template name and params; an unrecognised topic
  skips it rather than showing a beat that explains the wrong idea.
  Concept beats use HARD-CODED example values, never the student's, so they
  cannot leak the answer to the problem on screen.
- `/api/analyze` still returns `correct_value` and `scene_params.correct_display`
  in JSON. The video is clean, but devtools reveals the answer.
- `docs/TEMPLATE_AUDIT.md` ranks the scene templates by whether the error is
  actually *visible*. Demo ranks 1–6; **ranks 14–18 render fine and communicate
  nothing.**
