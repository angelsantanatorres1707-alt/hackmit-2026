# See your mistake

Photograph your handwritten linear algebra. We find the **first step that is actually
wrong**, then animate **your own claimed result** applied to the plane — the grid and the
basis vectors — right beside what the problem asked for.

We never tell you the answer. We point at the step and let you watch the two pictures
come apart.

```
      WHAT YOU WROTE                   WHAT THE PROBLEM ASKS FOR
      ┌────────────────┐               ┌────────────────┐
      │   [ 6  -5 ]    │               │   [ ?   ? ]    │  ← the reference panel is
      │   [ 2   5 ]    │               │   [ ?   ? ]    │    masked on purpose
      │                │               │        ↑  î    │
      │  ĵ ↖           │               │  ĵ ↖   │       │
      │     ╲___→  î   │               │     ╲  │       │
      └────────────────┘               └────────────────┘
          ĵ lands in the same place. î does not. That is the whole error,
          and it is a shape, not a number.

                    watch the first basis vector
```

That last line is the hint. It names a **location** and a **thing to watch**, and it is
lint-enforced never to contain the correction.

---

## Setup — one command

```bash
bash scripts/setup.sh
```

~60s cold, ~5s warm, idempotent. It installs ffmpeg + cairo/pango (macOS via Homebrew,
Linux via apt), builds `.venv` on Python 3.11, installs Manim Community 0.21.0 and
`backend/requirements.txt`, then proves the install by rendering a throwaway scene and
running all five bundled samples through extract → verify → hint.

**It deliberately does not install LaTeX.** Every Manim `Matrix`/`Tex`/`MathTex` class
shells out to `latex`; our scenes build matrices out of `Text` in `VGroup`s with drawn
brackets instead (`text_matrix()` in `backend/scenes/helpers.py`). That saves a
multi-gigabyte TeX install and is a hard constraint on any new scene — see
[`docs/RENDERING.md`](docs/RENDERING.md).

## Run it

```bash
bash scripts/run.sh                 # fixture mode: no API key, no network
bash scripts/run.sh --live          # read real photographs (needs OPENAI_API_KEY)
bash scripts/run.sh --dev           # + uvicorn auto-reload (never during a demo)
PORT=9000 bash scripts/run.sh       # somewhere else
```

Then open **http://localhost:8000**.

The server boots in under a second (the API process never imports Manim). The first
render of a given scene takes 6–9 seconds; every repeat is served from cache in
milliseconds.

## Check it before you trust it

```bash
bash scripts/smoke.sh               # starts its own server on a free port
BASE=http://localhost:8000 bash scripts/smoke.sh   # or test one that is running
```

Every bundled sample must reach a video **and** a non-empty hint; the leak lint is
self-tested in the same run. ~45s cold, ~2s once the render cache is warm. Non-zero exit,
loudly, if anything fails.

---

## How the pipeline works

```
   photo (JPEG/PNG/HEIC)
        │
        ▼
 ┌──────────────────┐   backend/extract.py
 │ 1. EXTRACT       │   Vision model as a TRANSCRIBER, not a solver. Returns typed
 │                  │   steps: raw text, parsed value, bbox, confidence, ambiguities,
 │                  │   crossed-out flag. It is forbidden to fix anything it sees.
 └────────┬─────────┘
          ▼
 ┌──────────────────┐   backend/verify.py  (sympy — no LLM in this step)
 │ 2. VERIFY        │   Layer 1: is this step wrong? ONE invariant check of the claim
 │    step by step  │   against the ORIGINAL GIVEN DATA — not against our own solution
 │                  │   path, because the student's route is legitimately different.
 │                  │   Layer 2: WHICH of the 19 taxonomy errors is it? Signature match.
 └────────┬─────────┘   Layer 1 alone decides the verdict, so a mistake that is nowhere
          │             in the taxonomy is still caught.
          ▼
 ┌──────────────────┐   the FIRST failing step, not every failing step. Downstream
 │ 3. LOCATE        │   arithmetic that faithfully carries a bad number is not blamed.
 │    first error   │   Charity: a step is wrong only if EVERY candidate reading of it
 │                  │   against EVERY candidate reading of the givens is wrong.
 └────────┬─────────┘   Unparseable ≠ wrong. Crossed-out work is never blamed.
          ▼             0.71 for 1/√2 is a rounding, not a linear algebra mistake.
 ┌──────────────────┐   backend/hints.py
 │ 4. PLAN          │   Picks a scene template and fills a small typed params dict —
 │  scene + hint    │   the LLM never writes Manim. Every number in params is computed
 │                  │   here from sympy values. Falls down a ladder on any failure:
 └────────┬─────────┘   geometric scene → StaticStepHighlight → _minimal().
          ▼
 ┌──────────────────┐   backend/render.py
 │ 5. RENDER        │   Manim in a SUBPROCESS (config is global and not thread-safe; a
 │                  │   scene that hangs or segfaults cannot take the API down).
 │                  │   -qm = 1280×720@30. Cached on (template, params, quality, scene
 └────────┬─────────┘   source hash), so editing a template invalidates its video.
          ▼
 ┌──────────────────┐   The hint names a location and a thing to watch. `lint_hint()`
 │ 6. POSITIONAL    │   rejects digits, spelled-out numbers, fractions, percentages,
 │    HINT          │   scientific notation, ~24 banned phrases, and even differences
 └──────────────────┘   or ratios between the student's value and the right one.
                        `plan()` lints its own output — the sentence AND the caption
                        burned into the video — before returning.
```

The render is fired **speculatively**, the moment the analysis is done, in a background
thread. The student spends that time on the read-back screen confirming what the camera
saw, so the render's dead time is not theirs.

### The reference panel is masked on purpose

`REVEAL_CORRECT_VALUES` (in `backend/scenes/helpers.py`) is `False` and is enforced at
**render** time, not just in template defaults. The right-hand panel shows `[? ?]` in
grey and its heading reads "WHAT THE PROBLEM ASKS FOR", never "what it should be". The
geometry is the whole message. Set `REVEAL_CORRECT_VALUES=1` in the environment to
un-mask it while developing.

---

## Architecture

```
frontend/            static, no build step, no framework
  index.html         4 stages: input → working → read-back → result
  app.js             upload / fixture chips / read-back editing / polls /api/job
  lib.js             rebuilds an Extraction from the student's corrections
      │  POST /api/analyze          (multipart photo, or JSON extraction/fixture)
      │  GET  /api/job/{id}         (poll: render status)
      │  GET  /api/video/{id}       (the mp4; 202 while still rendering)
      ▼
backend/
  app.py             FastAPI. Serves frontend/ at /. Jobs in memory. Nothing here
                     is allowed to 500: verify() and plan() are each wrapped, and a
                     crash degrades to a 200 with the reason in `warnings`.
  extract.py         photo → typed steps (Anthropic vision), or a bundled fixture
  verify.py          sympy. Layer 1 invariant + Layer 2 signatures. Timeout-guarded.
  hints.py           verdict → (scene template, params) + the lint-enforced hint
  render.py          subprocess Manim + content-addressed cache
  scenes/
    helpers.py       shared layout: panels, text_matrix(), grid density, masking
    common.py        20-line alias that re-exports helpers.py
    registry.py      18 template ids → 7 Scene classes (the rest are presets/aliases)
    grid_transform.py  eigen_ray.py  determinant_area.py  vector_op.py
    span_compare.py    line_system.py  step_focus.py
samples/             5 canned extractions + the sample photo (la_multiply.jpg)
docs/                the design record — see below
scripts/             setup.sh  run.sh  smoke.sh
Dockerfile, fly.toml, deploy/   container deploy (Manim needs real system libs;
                                Vercel/Netlify/Lambda cannot run this)
```

**Seven hand-written Manim `Scene` classes**, registered under 18 ids because several
are the same animation with different parameters (`CompositionOrderCompare` and
`InverseRoundTrip` are both `GridTransformCompare` with a two-element stage list).
`backend/scenes/registry.py` is the source of truth; `GET /api/health` lists what is
loadable right now.

### API

| route | what |
|---|---|
| `POST /api/analyze` | multipart photo(s), **or** JSON `{fixture}` / `{extraction}` / `{steps}`. `?wait=true` blocks until the video is rendered (curl and the smoke test use it); the browser does not. |
| `GET /api/job/{id}` | the whole analysis again, plus live render status |
| `GET /api/video/{id}` | the mp4. `202` while rendering, `204` if nothing was wrong, `503` with the reason if the render failed |
| `GET /api/fixtures` | the bundled samples, for the chips on the input screen |
| `GET /api/health` | fixture mode, key present, model, loadable templates, cache dir, job count |

```bash
curl -s -X POST "localhost:8000/api/analyze?wait=true" \
     -H 'Content-Type: application/json' -d '{"fixture":"la_multiply"}' | jq .hint
# "Watch where the first basis vector lands in your step 2."
```

---

## What needs `OPENAI_API_KEY`, and what does not

**Needs the key — exactly one thing:** turning a photograph of handwriting into
structured steps (`backend/extract.py`, model `claude-opus-5`, ~10–20s for a full page).

**Works with no key, no network, nothing:**

- every bundled sample, end to end
- all of sympy verification and first-error location
- template selection, parameter filling, the hint and its lint
- every Manim render
- the whole frontend, including the read-back editor

`scripts/run.sh` sets `USE_FIXTURE=1` by default, so a fresh clone with no key is fully
demoable. `GET /api/health` reports `fixture_mode` and the header shows a **Fixture
mode** pill.

**If you upload a photo with no key**, the app hands back a bundled sample and says so
in an unmissable banner: *"This is not your photo."* It will not quietly show you
someone else's mistake. Set the key and use `--live` to read real work.

---

## Known limitations — stated honestly

**Scope**

- **Linear algebra only**, and deliberately so. The 19-entry taxonomy in
  [`docs/ERROR_TAXONOMY.md`](docs/ERROR_TAXONOMY.md) covers matrix multiply, transpose,
  determinant, inverse, eigen, rref, span, projection, dot/cross. Layer 1 catches a
  wrong step whether or not it matches a taxonomy entry, but a match is what buys the
  good scene and the good hint. Hand it calculus and it has nothing to say.
- Errors with no geometry (dimension mismatch, dot product written as a vector) route to
  a static slide, not an animation. That is the honest answer, not a bug.

**Not fully proven**

- **The live vision path has not been exercised end to end** — the build container has
  no API key. Everything up to the network call is tested (missing key, corrupt upload,
  SDK missing), but the real response parsing is unverified. Fixture mode is the tested
  path.
- Single-page reads only; a multi-problem page reads the first problem and warns.

**Visual quality** (measured in [`docs/TEMPLATE_AUDIT.md`](docs/TEMPLATE_AUDIT.md) —
36 renders, 0 crashes)

- 4 of 18 template configurations render fine but are **not convincing**:
  `DeterminantAreaCompare` on its LA04 example, `EigenRayTest(mode=eigenvalue)`,
  `SpanCompare3D`, `DeterminantVolume3D`. The 3-D scenes in particular read as grey
  slabs. The audit ranks all 18; demo from the top of that list.
- Residual one-direction cross-panel grid bleed: after a strongly expanding transform
  the student's panel can pick up a few of the reference panel's lattice lines. The
  reference panel is kept clean. Fixing it properly needs per-frame clipping of one
  plane instead of `ApplyMatrix`.
- Scenes with a large matrix open zoomed out, so the basis vectors start as hairlines.
  The *end* frame — the one held under the hint — is clean. A proper fix is a camera
  move, not a grid tweak.

**Known leaks and sharp edges**

- **The answer is withheld from the video but not from the JSON.** `/api/analyze` still
  returns `correct_value` and `scene_params.correct_display`, and `hints.py` still sets
  `correct_label="WHAT THE STEP SHOULD DO"` before `reference_label()` rewrites it at
  render time. A student with devtools open reads the answer off the network tab.
- Jobs live in memory, capped at `MAX_JOBS=200` and evicted by insertion age, not last
  access. A server restart invalidates every video URL on screen — which is why
  `run.sh` no longer defaults to `--reload`.
- No auth and `allow_origins=["*"]`. This is a localhost demo, not a deployment.
- PDFs are not accepted (uploads go through PIL). JPEG, PNG and HEIC all work.
- `StaticStepHighlight`'s free-text `annotation` is not run through the hint leak lint;
  the `hint` is.

---

## Docs

| file | what is in it |
|---|---|
| [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) | minute-by-minute demo script, judge Q&A, failure drill, 9:30 checklist |
| [`docs/TEMPLATE_AUDIT.md`](docs/TEMPLATE_AUDIT.md) | all 18 templates rendered and ranked: which are demo-grade, which are duds |
| [`docs/ERROR_TAXONOMY.md`](docs/ERROR_TAXONOMY.md) | the 19 errors, their sympy checks, and the verification strategy |
| [`docs/SCENE_CATALOG.md`](docs/SCENE_CATALOG.md) | the 7 scene classes and their exact param contracts |
| [`docs/RENDERING.md`](docs/RENDERING.md) | Manim facts for this container, and the LaTeX minefield — **read before writing a scene** |
| [`docs/EXTRACTION.md`](docs/EXTRACTION.md) | the vision prompt, the schema, and the silent-correction guard |
| [`docs/STEP_REPLAY.md`](docs/STEP_REPLAY.md) | spec for an eighth template (`StepReplay`) — **not built**, post-deadline work |

Built at HackMIT 2026.
