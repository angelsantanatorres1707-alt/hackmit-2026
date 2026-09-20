# Demo runbook — 2-3 minutes, live

Everything below was executed against this repo and the timings are measured, not
estimated. Follow it literally. If you are reading this at 9:45 with four hours of sleep,
read the **Card** and the **9:30 checklist**, and nothing else.

---

## The card

| | |
|---|---|
| **Start** | `bash scripts/run.sh` → http://localhost:8000 |
| **Mode** | Fixture (no key, no network). The header pill says **Fixture mode**. |
| **Demo this** | The **last** sample chip: *Compute AB · one dot product cut short* |
| **Template** | `GridTransformCompare` — rank 1 in `docs/TEMPLATE_AUDIT.md` |
| **The peak** | 2.6s–5.6s into the 8.7s video. Two grids shear apart. Stop talking. |
| **The hint** | "Watch where the first basis vector lands in your step 2." |
| **Never say** | The corrected number. The whole thesis is that we don't. |
| **Backups** | `~/demo-backup/*.mp4`, created by step 4 of the 9:30 checklist |

---

## T-30 minutes: start everything

Run these in order. Total: about **90 seconds**, dominated by the warm-up render.

### 1. Start the server — 2 seconds

```bash
cd /home/user/hackmit-2026
bash scripts/run.sh
```

Leave this terminal open and untouched. It prints:

```
==> FIXTURE mode: bundled samples only, no API key or network needed.
    Open  ->  http://localhost:8000
    Stop  ->  Ctrl-C
```

Boot to first healthy response is **0.7s** — the API process never imports Manim.
There is deliberately **no `--reload`**: a reloader restarts the process on any file
save, and every rendered job lives in memory, so a teammate editing a file mid-demo
would 404 the video the judge is watching.

### 2. Prove it is alive — 1 second

In a **second** terminal:

```bash
curl -s localhost:8000/api/health | python3 -m json.tool
```

You want to see `"ok": true`, `"fixture_mode": true`, and **18** entries under
`scene_templates`. Anything else, jump to the failure drill.

### 3. Warm the render cache — 40 seconds. **Do not skip this.**

```bash
cd /home/user/hackmit-2026
time (for f in la_multiply la02_order la07_inverse la09_eigen la19_projection; do
  curl -s -o /dev/null -X POST "http://localhost:8000/api/analyze?wait=true" \
       -H 'Content-Type: application/json' -d "{\"fixture\":\"$f\"}"
done)
```

Measured: **39.4s cold, 0.08s warm.** After this, every sample's video is served from
`/tmp/manimhint/cache` in milliseconds. Cold, the hero render alone is **8.1s** of
silence in front of a judge.

### 4. Make the fallback assets — 3 seconds once the cache is warm

```bash
mkdir -p ~/demo-backup
cd /home/user/hackmit-2026
for f in la_multiply la02_order la09_eigen la19_projection la07_inverse; do
  ID=$(curl -s -X POST "http://localhost:8000/api/analyze?wait=true" \
        -H 'Content-Type: application/json' -d "{\"fixture\":\"$f\"}" \
      | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')
  curl -s -o "$HOME/demo-backup/$f.mp4" "http://localhost:8000/api/video/$ID"
  echo "$f -> $(stat -c%s "$HOME/demo-backup/$f.mp4") bytes"
done
```

Expect five files, **la_multiply.mp4 at ~1.77 MB** being the hero. Open
`~/demo-backup/la_multiply.mp4` once now, in the browser, so you know it plays. This is
the asset you fall back to if anything at all goes wrong.

### 5. Open the browser — and leave it open

Chrome, **http://localhost:8000**, one tab, full screen, zoom 100%.

- Close devtools. Keep them closed. The `/api/analyze` JSON still contains
  `correct_value` — the video withholds the answer, the network tab does not.
- Do a full silent dry run now: click the last chip, click through, watch the video
  play. Then press **Start over**. The second run is the one the judge sees, and it is
  entirely cached.

---

## The demo — minute by minute

Two people is better than one: one drives, one talks. One person works if you rehearse
the two clicks.

### 0:00 – 0:25 · The problem (stay on the input screen)

**DO:** Nothing. The input screen is up: the headline reads *"Watch your own work
actually happen"*, with a dropzone that says *"Drop a photo here."*

**SAY:**

> "Here's a linear algebra problem set at 1am. You get it back, and there's a red X on
> problem 4. You know the answer is wrong. You have no idea *which line* went wrong, and
> the answer key just prints the right matrix — which teaches you nothing, because you
> can already see you didn't get that.
>
> So: photograph your work. We find the first step that actually breaks, and then we
> show you what *your* answer does to space."

### 0:25 – 0:40 · Start it

**DO:** Point at the dropzone. Then scroll to the sample chips at the bottom and click
the **last** one: **Compute AB · one dot product cut short**.

**SAY:**

> "You'd drop the photo here. I shot this page earlier and it's already read, because I'd
> rather not demo the conference wifi."

**WHAT HAPPENS:** The working screen flashes for well under a second, then the read-back
screen. The render has *already started*, server-side, in a background thread.

### 0:40 – 1:00 · The read-back screen. **Slow down here.**

This screen is a feature, not a loading step. Give it fifteen seconds. Note that it
says nothing about what is *wrong* — that is deliberate, and it is the point.

**DO:** Point at the four lines in *Your steps*, top to bottom. The badges you will see,
in order: line 1 *camera unsure — check this* and *read "4" — could be 9*; line 2
*crossed out*; line 3 *couldn't read this line*; line 4 *final answer*.

**SAY:**

> "Before we say anything at all, here's every line we read, exactly as written. Mistakes
> included — the model is a transcriber, it is not allowed to fix anything it sees, and
> nothing on this screen is accusing her of anything yet.
>
> Line one is the given matrices. Line two she crossed out — we never blame crossed-out
> work. Line three is scratch arithmetic we couldn't parse, and *couldn't parse is not
> wrong*; we skip it, we don't accuse it. Line four is her final answer.
>
> And see this badge — the top-left of B could be a 4 or a 9. We're not sure, so we say
> so. Every number on this screen is click-to-edit; if the camera misread you, you fix it
> and we re-check the whole page against your correction. That's why an OCR miss here is
> a five-second fix instead of a confident, wrong accusation."

**DO:** Click **"That's my work — show me"**.

### 1:00 – 1:35 · The animation. This is the demo.

The video is 8.7 seconds and **loops automatically**. Let it run. Time your sentences to
the loop — it repeats, so you get a second pass for free.

| in-loop | what is on screen | what you say |
|---|---|---|
| 0.0 – 1.4s | Two panels fade in. Left, amber border: **WHAT YOU WROTE**, with her matrix `[6 -5 ; 2 5]` above it. Right, white: **WHAT THE PROBLEM ASKS FOR**, with a grey `[? ?; ? ?]`. | "Left is her answer. Right is what the problem asked for — and notice we're **not showing it**. Grey question marks." |
| 1.4 – 2.6s | Both grids sit still and **identical**. Same unit lattice, same î and ĵ at the origin. | "Same plane, twice. Same grid, same two basis vectors." |
| **2.6 – 5.6s** | **Both grids shear, and they shear differently.** Peak motion at ~3.3s. | ***Say nothing.*** Let it play. |
| 5.6 – 6.2s | Dead still, and the two panels are now different shapes. The **red** arrow (ĵ) points up-left in *both* panels — same direction. The **green** arrow (î) lies shallow, pointing right, on the left; it stands steep, nearly vertical, on the right. | "Look at the red arrow: it lands in the same place in both. That column she got right. Now look at the green one — that's the first basis vector, and her matrix sends it *there*, while the problem sends it *there*." |
| 6.2 – 8.7s | The first basis vector pulses. Amber caption fades in at the bottom: **watch the first basis vector**. | "That's the whole error, and it's a shape, not a number. You can see it from the back of the room." |

**The single most important instruction in this document: do not talk over 2.6s–5.6s.**
The divergence is the product. Narrating it is the most common way to kill it.

### 1:35 – 1:50 · The hint

**DO:** Point at the hint card under the video. It reads:

> **Look here** — Watch where the first basis vector lands in your step 2.

Then point at the **Your work** rail on the right: the last line now carries an amber
**Look here** badge, and the foot of the rail says *"Checked 4 lines. The highlighted one
is the first that disagrees with the problem."*

**SAY:**

> "And that's all we say. A location and a thing to watch. Not 'you forgot to carry the
> 3', not the corrected matrix — we still haven't shown her the right answer, and we're
> not going to. She has to go back to her own page and find it. That's deliberate, and
> it's the part we'd defend hardest."

### 1:50 – 2:15 · How it knows (do this, or the second example, not both)

**SAY:**

> "Nothing about that was an LLM guessing. The model's only job was to read handwriting.
> Everything after that is sympy: each line is a *claim*, we evaluate it against the
> original given data, and the first claim that fails is the one we animate.
>
> And here's the part I like — this particular mistake isn't in our error taxonomy. We
> have nineteen catalogued errors with hand-tuned animations; this one matched none of
> them. It got caught anyway, and it still got the right animation, because the generic
> check is 'is this claim true of the given data', not 'is this one of our nineteen'."

### 1:50 – 2:15 (alternative) · A second example — only if you are at or under 1:45

**DO:** Click **New problem**, then the **first** chip: *Compute AB · multiplication
order reversed*. Cached, so the video is up instantly.

**SAY:**

> "Different error, same idea: she computed BA instead of AB. Two stages, with a pause on
> the intermediate grid — the intermediate is *identical*, which is exactly why the
> mistake feels invisible on paper. Then the second stage runs and the two panels end
> somewhere completely different."

Cut this the moment you are over 2:15.

### 2:15 – 2:30 · Close

**SAY:**

> "Photograph the page, we find the first line that breaks, and you watch your own
> mistake happen to the plane. No correction, no answer key. Linear algebra, seven
> animation templates, runs on a laptop with no LaTeX and no GPU."

---

## Judge questions, answered

**"How do you know which step is wrong — is the LLM just guessing?"**

> No. The model transcribes; sympy decides. Every step is a claim, `expr = value`. We
> evaluate `expr` exactly from the *original given problem data* and compare — we
> deliberately do **not** compute our own solution and diff it line against line, because
> the student's route is legitimately different from ours and we'd flag correct work all
> day. Where they restate no expression, we check step-to-step equivalence against a
> small set of legal operations. That's Layer 1, and it alone decides the verdict. Layer
> 2 is a signature match against nineteen catalogued errors, and all it buys is a better
> animation and better hint wording. Coverage is not capped at nineteen.
>
> Three things in there we're proud of: **charity** — a step is wrong only if *every*
> candidate reading of it, against *every* candidate reading of the givens, is wrong;
> **unparseable is never wrong**; and **rounding amnesty** — writing 0.71 for 1/√2 is not
> a linear algebra mistake.

**"Why not just tell them the answer? Wouldn't that be faster?"**

> Faster, and it doesn't work. Being shown a correct answer produces recognition —
> "yeah, that looks right" — and recognition is not retrieval. The student has to
> generate the correction themselves for it to stick; that's the testing effect, and it's
> one of the most replicated results in learning science. An answer key also teaches
> nothing about *where* you went wrong, which is the only thing you actually need.
>
> So the hint names a location and a thing to watch, and never states the correction.
> That's not a style guide, it's enforced: `lint_hint()` in `backend/hints.py` rejects
> digits, spelled-out numbers, fractions, percentages, scientific notation, about
> twenty-four banned phrases, and even *differences and ratios* between their value and
> the right one — so "you're twelve short" and "it's ten times too big" both get blocked.
> `plan()` lints its own output before returning it, including the caption burned into
> the video. And the reference panel in the animation is masked to grey question marks at
> render time, not just in the template defaults.

**"What happens when the OCR misreads the handwriting?"**

> You just saw it. That's the read-back screen, and it's the feature we'd cut last. We
> show every line we read, exactly as read, and every number is click-to-edit. On this
> very sample we flagged the top-left of B as possibly a 4 or a 9 — and the verdict still
> came back high-confidence, because under *both* readings that step is wrong. That's the
> charity rule doing its job: ambiguity never manufactures an accusation.
>
> When you do correct something, we re-run the whole pipeline on your corrected
> transcription. The alternative — silently guessing and confidently animating the wrong
> mistake — is the single most damaging thing this app could do.

**"What if I photograph calculus? Or chemistry?"**

> It's scoped to linear algebra and we'd rather say so than pretend. That's not a
> shortcut, it's the premise: the reason this works at all is that linear algebra
> operations *are* geometric transformations, so a wrong matrix is a visibly wrong
> picture. There is no equivalent picture for a mis-integrated polynomial.
>
> Within linear algebra we cover matrix multiply, transpose, determinant, inverse,
> eigenvectors and eigenvalues, row reduction, span and independence, projection, dot and
> cross products. Errors with genuinely no geometry — a dimension mismatch, a dot product
> written as a vector — fall through to a static annotated slide rather than a fake
> animation. We'd rather be honest about the ones we can't dramatize.

**"Does it need an API key / does it work offline?"**

> Exactly one thing needs the key: turning a photograph into structured steps. Everything
> else — verification, error location, template choice, hint generation, every Manim
> render, the whole UI — runs offline. What's on screen right now has no network
> connection at all.

**"How long does a render take?"**

> Six to nine seconds at 720p30, and it's cached on a hash of the template, the params
> and the scene source — so editing a template correctly invalidates its video and
> nothing else. The render starts speculatively the moment analysis finishes, while the
> student is still on the confirm screen, so most of it is hidden from them. And it runs
> in a subprocess: a scene that hangs or segfaults cannot take the API down.

**"Why does the animation look like that — no LaTeX?"**

> There is no LaTeX installed and none needed. Every Manim `Matrix`, `Tex` and `MathTex`
> class shells out to `latex`, so we build matrices out of `Text` in groups with drawn
> brackets. It saves a multi-gigabyte install, and it means this runs anywhere Python and
> ffmpeg run.

**"What's broken?"** (answer it straight — they will respect it)

> Three things. The live photo path is the least-tested code we have, because our build
> container has no API key. Four of our eighteen template configurations render fine but
> aren't convincing enough to show anyone — the 3-D ones especially — and they're ranked
> and written down in `docs/TEMPLATE_AUDIT.md`. And the API response still carries the
> correct value in JSON: the video withholds the answer, the network tab doesn't. That's
> a ten-minute fix we chose not to make at 4am with the render path in flux.

---

## Failure drill

Rehearse the first two at least once. They are the ones that actually happen.

### The video never appears / spinner keeps spinning

The overlay says "Rendering your animation" with a ticking counter. It gives up at 180s.

1. **Wait 10 seconds.** A cold render is 6–9s; if you skipped the warm-up, this is normal.
2. **Do not reload the page.** Jobs live in memory but the page state does not survive a
   reload cleanly — you would have to re-click everything.
3. **After ~15s: switch to the backup.** Say *"the render's taking its time, here's the
   one I made this morning"* and play it. Second terminal:
   ```bash
   xdg-open ~/demo-backup/la_multiply.mp4   # macOS: open ~/demo-backup/la_multiply.mp4
   ```
   Or drag the file onto a new Chrome tab. **Keep talking over it** — the hint card is
   still on screen behind you, and the hint is the product.
4. Diagnose later, not on stage:
   ```bash
   curl -s localhost:8000/api/job/<job_id> | python3 -m json.tool | grep -A3 video_
   ```

### The video plays black, or the frame is empty

The frontend detects this itself and swaps in a panel saying *"The animation didn't
render"* with the hint still below it — so you are never looking at a silent black
rectangle. If it happens anyway:

1. Click **Play it again** once. A stalled first load usually recovers.
2. If still black: **play the backup** (command above). Say *"browser's not decoding it —
   here's the same render."*
3. Genuinely last resort, no server needed at all, renders in **5.8 seconds**:
   ```bash
   cd /home/user/hackmit-2026
   .venv/bin/manim -qm --disable_caching backend/scenes/grid_transform.py GridTransformCompare
   # writes media/videos/grid_transform/720p30/GridTransformCompare.mp4
   ```

### The OCR misread something (live mode only)

This is a **feature demo**, not a failure. Do not apologise.

1. Stay on the read-back screen. Click the wrong number. Type the right one.
2. The button changes to **"Re-check with my corrections"**. Click it.
3. Say: *"This is the confirm screen doing exactly what it's for. It read a 9 as a 4; I
   fix it, and it re-checks the whole page against my correction rather than guessing."*
4. It re-runs in well under a second and usually hits the same cached video.

If the misread is bad enough that it flags the **wrong step**: say *"and that's why you
get to correct it before we accuse you of anything"*, fix it, re-check. If it is still
wrong, press **New problem** and click the last sample chip — you are back on the
rehearsed path in two clicks.

### The network dies

**Nothing happens.** Fixture mode makes no network calls. The server is on localhost, the
samples are on disk, Manim renders locally. If you are in `--live` mode and the network
dies, the app falls back to a bundled sample and shows a loud *"This is not your photo"*
banner — at which point say:

> "We just lost the network, so it's refusing to pretend it read my page and it's showing
> you a bundled sample instead. That banner is deliberate — showing one student another
> student's mistake is the worst thing this app could do."

Then finish the demo on the sample. It is the same animation.

### The server is dead / the terminal got closed

```bash
cd /home/user/hackmit-2026
bash scripts/run.sh
```
Back in 2 seconds, and the render cache in `/tmp/manimhint/cache` survives a restart, so
everything is still instant. Reload the browser tab and re-click. **Note: the jobs are
in-memory, so any video URL from before the restart is dead — you must click through
again from the input screen.**

If it refuses with *"port 8000 is already in use"*, a zombie is holding it:

```bash
# Find it WITHOUT killing your own shell. Do NOT use `pkill -f uvicorn` —
# the pattern matches your own command line and kills your terminal.
ps -eo pid,args | awk '/uvicor[n] backend.app:app/ {print $1, $NF}'
kill <that pid>
```
Or just move: `PORT=8001 bash scripts/run.sh`, and open http://localhost:8001.

### Everything is on fire

Full reset, ~45 seconds:

```bash
cd /home/user/hackmit-2026
rm -rf /tmp/manimhint            # drop the render cache
bash scripts/smoke.sh            # starts its own server, renders all 5, asserts each
```
`PASS - 5 fixtures, all reached a video or an explained fallback.` means the whole
pipeline is healthy. Then restart `run.sh`. You do **not** need to re-run the warm-up:
`smoke.sh` renders into the same `/tmp/manimhint/cache` that `run.sh` reads, so it left
you warm. Re-do step 4 if you wiped `~/demo-backup` too.

If even that fails, present `~/demo-backup/la_multiply.mp4` and the read-back screenshot
and talk through it. The idea survives without the live server; it does not survive you
debugging on stage.

---

## 9:30am pre-demo checklist

Tick every line. Twenty minutes is enough; ten is tight.

**Machine**

- [ ] Laptop plugged in. Battery saver **off** (it throttles the CPU and Manim is
      CPU-bound).
- [ ] Do Not Disturb on. Slack, mail, calendar alerts quit.
- [ ] Screen sleep and screensaver disabled.
- [ ] Display resolution set and **tested on the actual projector/HDMI** if you can get
      to it. Browser zoom 100%.

**App**

- [ ] `cd /home/user/hackmit-2026 && git status` — clean, or you know exactly what is
      uncommitted. **No one edits `backend/` after this point.**
- [ ] `bash scripts/smoke.sh` → **PASS - 5 fixtures**. (~45s cold, ~2s warm.)
- [ ] `bash scripts/run.sh` in a dedicated terminal. Leave it alone.
- [ ] `curl -s localhost:8000/api/health | python3 -m json.tool` → `"ok": true`,
      `"fixture_mode": true`, 18 scene templates.
- [ ] **Warm-up loop** (step 3 above). Watch it take ~39s. If it takes 0.1s the cache was
      already warm — good.
- [ ] **Backup assets** (step 4 above). Five mp4s in `~/demo-backup/`, hero ~1.77 MB.
- [ ] Open `~/demo-backup/la_multiply.mp4` once and confirm it plays.

**Browser**

- [ ] Chrome, one window, one tab, http://localhost:8000, full screen.
- [ ] Header pill reads **Fixture mode**.
- [ ] Five sample chips visible at the bottom of the input screen.
- [ ] **Devtools closed.** (`correct_value` is in the JSON.)
- [ ] Bookmarks bar hidden, no personal tabs, no notifications extension.

**Dry run — do this twice**

- [ ] Click the **last** chip → read-back appears in under a second, with 4 lines.
- [ ] Badges read, top to bottom: *camera unsure — check this* + *read "4" — could be 9*
      · *crossed out* · *couldn't read this line* · *final answer*. Nothing is marked
      wrong yet — correct.
- [ ] Click **"That's my work — show me"** → the video is there immediately, playing and
      looping; the rail on the right puts an amber **Look here** on the last line.
- [ ] At about 5 seconds in, the two green arrows clearly point in **different
      directions**. If they don't, you are on the wrong sample — press **Start over** and
      click the **last** chip.
- [ ] The hint card reads *"Watch where the first basis vector lands in your step 2."*
- [ ] Press **Start over**. You are staged.

**Decision gate — live mode?**

Only if you have a working `ANTHROPIC_API_KEY` **and** both rehearsals below pass. The
live vision path is our least-tested code. If either fails, stay in fixture mode; it is
the rehearsed path and nothing in the story depends on the photo being read live.

- [ ] `export ANTHROPIC_API_KEY=sk-ant-...` then `bash scripts/run.sh --live`.
- [ ] Upload `samples/la_multiply.jpg` via **"Load the sample photo"**. It must come back
      in 10–20s, with **no** *"This is not your photo"* banner, and flag the same last
      step.
- [ ] Do it a second time. Both passes clean → demo live, and add the photo thumbnail
      beat at 0:40 ("that's the page, this is what we read off it"). Any failure →
      `Ctrl-C`, `bash scripts/run.sh`, warm up again, demo from the chip.

**Human**

- [ ] Whoever is talking has said the 2.6s–5.6s rule out loud: **stop talking during the
      shear**.
- [ ] Whoever is driving knows the two clicks: last chip → "That's my work — show me".
- [ ] Both of you know where `~/demo-backup/la_multiply.mp4` is.
- [ ] Nobody says the corrected number. Not once.
