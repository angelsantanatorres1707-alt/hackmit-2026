# Manim rendering: what works, what breaks, how fast

Status: **VERIFIED WORKING** in this container on 2026-09-19.
Manim Community **v0.21.0**, Python 3.11.15, Ubuntu 24.04, 4 cores / 15 GB RAM.
**No LaTeX is installed and none is needed.**

If you are reading this at 3am: run `bash scripts/setup.sh`, then jump to
[Flags](#flags-use-these) and [The LaTeX minefield](#the-latex-minefield-read-this-before-you-write-a-scene).

---

## TL;DR

| Question | Answer |
|---|---|
| Does manim render here? | Yes. |
| LaTeX required? | **No.** Do not install texlive. |
| Render time, 8.0s scene, `-ql` | **~3.0s** |
| Render time, 8.0s scene, `-qm` | **~5.3s** |
| Flags for the demo | `-qm --disable_caching` |
| Flags while iterating | `-ql --disable_caching` |
| Output path (CLI) | `media/videos/<script_stem>/<H>p<FPS>/<SceneName>.mp4` |
| Output path (in-process) | `<media_dir>/videos/<H>p<FPS>/<output_file>.mp4` |
| Working reference scene | `backend/scenes/_derisk_test.py` |

---

## Install

Already done in this container. To reproduce from scratch, `bash scripts/setup.sh`,
which runs exactly this:

```bash
# 1. System libs. ffmpeg was MISSING; cairo/pango headers are needed because
#    pycairo has no manylinux wheel and builds from source.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ffmpeg libcairo2-dev libpango1.0-dev \
                       pkg-config python3-dev build-essential

# 2. venv + manim. uv is ~10x faster than pip; the whole install took 12s.
uv venv --python 3.11 /home/user/hackmit-2026/.venv
uv pip install --python /home/user/hackmit-2026/.venv/bin/python manim
```

**We used a venv at `/home/user/hackmit-2026/.venv`** (not a system-wide install).
Everything below assumes `./.venv/bin/manim` / `./.venv/bin/python`.

Timings observed: apt ~45s cold, `uv venv` 0.1s, `uv pip install manim` **12.3s**.
Fonts were already present (DejaVu Sans, Liberation, FreeSans — 59 families), which
matters because `Text` goes through Pango and silently renders nothing without fonts.

Notably **not** installed, and not needed: any TeX distribution, any X server or
EGL (the default cairo renderer is headless; only `--renderer=opengl` would need
a GL context).

---

## Flags: use these

```bash
# iterating on a scene
./.venv/bin/manim -ql --disable_caching backend/scenes/foo.py SceneName

# the demo
./.venv/bin/manim -qm --disable_caching backend/scenes/foo.py SceneName
```

Measured on the real side-by-side scene (8.000s of video, 2 planes, 4 arrows,
2 text matrices, 7 animations):

| Flag | Resolution / FPS | Wall clock | File size |
|---|---|---|---|
| `-ql` | 854x480 @ 15fps | **3.05s** | 234 KB |
| `-qm` | 1280x720 @ 30fps | **5.32s** | 388 KB |
| `-qh` | 1920x1080 @ 60fps | 14.43s | 668 KB |

**Recommendation: ship the demo at `-qm`.** `-ql` is only 15fps and the shear
animation visibly stutters on a projector. 5.3s is still well inside a "hit
submit, watch a spinner" budget, and it doubles the frame rate.

### Why `--disable_caching`

Manim caches partial movie files keyed on a hash of the animation. For our
workload every job has different matrices, so cache hits are rare and the cache
just accumulates on disk. Measured: identical re-render is 2.05s cached vs 3.05s
uncached, so caching buys ~1s **only when nothing changed** — which never happens
in production. It also removes a whole class of "why is it showing the old
matrix" debugging at 4am. Keep it off.

### Other flags worth knowing

- `--media_dir DIR` — move the whole `media/` tree (use a temp dir per job).
- `-o NAME` / `output_file` — set the mp4 basename (use the job id).
- `--format mp4` (default) — also supports `gif`, `png`, `webm`.
- `-v ERROR` / `verbosity` — manim is extremely chatty by default.
- `-p` — auto-play when done. **Never use this on the server**, it tries to
  launch a video player.
- `--renderer=opengl` — do not. It needs a GL context we don't have.

---

## The LaTeX minefield (read this before you write a scene)

There is no `latex` binary here. Anything that reaches LaTeX dies with:

```
FileNotFoundError: [Errno 2] No such file or directory: 'latex'
```

I probed every relevant mobject. Empirical results:

| Construct | Works without LaTeX? |
|---|---|
| `Text("hi")` | **YES** |
| `MarkupText`, `Arrow`, `Vector`, `NumberPlane`, `Difference` | **YES** |
| `MathTex(...)`, `Tex(...)` | NO |
| `Matrix([[1,2],[3,4]])` | NO |
| `IntegerMatrix(...)` | NO |
| `DecimalMatrix(...)` | NO |
| `MobjectMatrix(...)` | NO |
| `DecimalNumber(3.14)` | NO (default) |
| `DecimalNumber(3.14, mob_class=Text)` | **YES** |
| `Integer(7, mob_class=Text)` | **YES** |
| `plane.add_coordinates()` | NO (default) |
| `plane.add_coordinates()` with `label_constructor=Text` | **YES** |

### The big one: ALL `Matrix` classes need LaTeX

This surprised me, so it is worth being precise. `Matrix.__init__` calls
`self._add_brackets(...)` **unconditionally**, and `_add_brackets` builds the
brackets out of a LaTeX `array` environment:

```python
# manim/mobject/matrix.py, ~line 272
l_bracket = MathTex(tex_left, **kwargs)
r_bracket = MathTex(tex_right, **kwargs)
```

So swapping `element_to_mobject=Text` is **not enough** — the entries become
LaTeX-free but the brackets still shell out to `latex`. `IntegerMatrix`,
`DecimalMatrix` and `MobjectMatrix` all subclass `Matrix`, so all of them fail.
There is no flag to skip the brackets.

**Use `text_matrix()` from `backend/scenes/_derisk_test.py` instead.** It builds
a bracketed matrix from `Text` in a `VGroup` plus two 4-point `VMobject`
brackets, and it looks essentially identical to manim's. It is written to be
lifted straight into the real templates. Entries are centred on a fixed grid
pitch so columns stay aligned when widths differ (`-1` vs `1`).

### Axis numbers

`NumberPlane(include_numbers=True)` is **not a valid kwarg** in 0.21 — it raises
`TypeError: Mobject.__init__() got an unexpected keyword argument`. The real
path is `.add_coordinates()`, and to keep it LaTeX-free you must override
`label_constructor`:

```python
plane = NumberPlane(
    x_range=[-3, 3, 1], y_range=[-3, 3, 1],
    axis_config={
        "label_constructor": Text,                    # <-- the magic knob
        "decimal_number_config": {"num_decimal_places": 0},
    },
).add_coordinates()
```

`NumberLine.get_number_mobject` passes `mob_class=label_constructor` into
`DecimalNumber`, which is why this works. The de-risk scene omits axis numbers
entirely — at panel size they are unreadable anyway.

### Rule for the team

> Never type `Tex` or `MathTex`. If you need a glyph, it comes from `Text`.

---

## Scene-building gotchas I hit

### 1. `NumberPlane` is not where you think

```python
from manim.mobject.graphing.number_plane import NumberPlane   # ModuleNotFoundError
from manim.mobject.graphing.coordinate_systems import NumberPlane   # correct
from manim import NumberPlane                                  # also correct, simplest
```

### 2. Keep the plane's x and y scale identical

`ApplyMatrix` operates in **scene** coordinates, not plane coordinates. If
`x_length/x_range != y_length/y_range`, the matrix you animate is not the matrix
the student wrote — it gets conjugated by the aspect ratio. Always set
`x_length` and `y_length` from one `UNIT` constant, as the de-risk scene does.

Also always pass `about_point=plane.get_origin()`. The default is the scene
origin `ORIGIN`, which is wrong for any panel that isn't centred — your grid
will translate away instead of transforming in place.

### 3. Transformed grids overflow their panel, and cairo cannot clip

A shear like `[[2,1],[0,1]]` roughly doubles the plane's extent, so a left-hand
panel will crawl across the screen into the right-hand one. Manim's cairo
renderer has no clipping primitive.

**Fix: paint an opaque matte on top.** Build a full-frame rectangle with a
rectangular hole per panel using `Difference` (skia-pathops, ships with manim),
give it a high `z_index`, and give your titles a higher one:

```python
matte = Difference(Difference(full_frame_rect, left_box), right_box)
matte.set_fill(BLACK, opacity=1).set_stroke(width=0).set_z_index(10)
title.set_z_index(12)
```

See `panel_matte()` in the de-risk scene.

### 4. Draw the plane BIGGER than the visible box

This is the trick that made the output actually look good. Because the matte
clips anyway, draw the `NumberPlane` far larger than the box (we draw ±5 units
into a box that shows ~±2.9). Otherwise, after a shear pulls the grid lines
apart, the box is left with 4 lonely lines in it. With the oversized plane the
box stays full of lattice before *and* after the transform.

### 5. Don't let `ApplyMatrix` eat your arrowheads

`ApplyMatrix` transforms every point of a mobject, including the arrow tip
polygon — under a shear the tip turns into a bent wedge and looks broken.

**Fix:** animate the grid with `ApplyMatrix`, but animate each basis vector with
`Transform(vec, freshly_built_arrow_at_M@v)`. This is not a cheat: under
`p_t = (1-t)p + t·Mp` the arrow tip travels a straight line, which is exactly
what `Transform` interpolates, so the vector stays glued to the grid while
keeping a crisp head.

```python
i_t = basis_arrow(origin, M @ np.array([1.0, 0.0]), GREEN)
self.play(
    ApplyMatrix(M, plane, about_point=origin),
    Transform(i_hat, i_t),
    run_time=3.0,
)
```

### 6. `LinearTransformationScene` exists but doesn't fit us

It is LaTeX-free as long as you avoid `write_vector_coordinates()`,
`add_title()` and `get_vector_label()` (all of which use `Tex`/`Matrix`). But it
owns the whole frame, so it cannot do the side-by-side comparison that is our
entire product. Build panels manually in a plain `Scene`, as the de-risk scene
does.

---

## Driving manim from the FastAPI backend

Two options. **Use the in-process one.**

### Option A (recommended): in-process with `tempconfig`

Parameterize via class attributes, render directly, control the exact output path:

```python
from manim import tempconfig
from backend.scenes.compare import CompareScene   # a template

with tempconfig({
    "quality": "medium_quality",     # == -qm
    "disable_caching": True,
    "media_dir": f"/tmp/jobs/{job_id}",
    "output_file": job_id,           # mp4 basename
    "verbosity": "ERROR",
}):
    CompareScene.STUDENT_M = student_matrix
    CompareScene.CORRECT_M = correct_matrix
    CompareScene.HINT = hint_text
    CompareScene().render()

mp4 = f"/tmp/jobs/{job_id}/videos/720p30/{job_id}.mp4"
```

Verified working. Measured **0.4–0.8s** for a 1s test scene, and repeated
sequential renders in one process are stable (0.74s, 0.39s, 0.42s — it gets
faster once imports are warm). This avoids the CLI's ~0.7s `import manim` +
~0.3s startup on every request.

**Note the output path differs from the CLI**: there is no `<script_stem>`
directory, because there is no input script. It is
`<media_dir>/videos/<H>p<FPS>/<output_file>.mp4`.

Two cautions:
- `manim.config` is **global** and class attributes are **not thread-safe**.
  Serialize renders with a lock, or use one worker. Fine for a hackathon demo.
- `.render()` is blocking CPU work. Run it in a threadpool
  (`await asyncio.to_thread(...)`) so it doesn't stall the event loop.

### Option B: subprocess

More isolated, but you cannot pass arguments to a scene through the manim CLI —
you'd have to smuggle parameters through an env var or a JSON file the scene
reads at import time. Costs ~1s extra per render. Only worth it if in-process
rendering starts leaking or crashing.

```bash
./.venv/bin/manim -qm --disable_caching \
  --media_dir "/tmp/jobs/$JOB" -o "$JOB" -v ERROR \
  backend/scenes/compare.py CompareScene
# -> /tmp/jobs/$JOB/videos/<stem>/720p30/$JOB.mp4
```

---

## The reference scene

`backend/scenes/_derisk_test.py`, scene class `DeriskSideBySide`.

```bash
cd /home/user/hackmit-2026
./.venv/bin/manim -ql --disable_caching backend/scenes/_derisk_test.py DeriskSideBySide
# -> media/videos/_derisk_test/480p15/DeriskSideBySide.mp4
```

It renders exactly our product's hero shot: student's matrix `[[2,1],[0,1]]` on
the left, correct `[[2,-1],[0,1]]` on the right, both applied to a grid with
i-hat and j-hat, with a positional hint ("watch the second basis vector") that
does not give away the correction. Visually confirmed frame-by-frame: the
matrices render with proper brackets, the mattes clip cleanly, arrowheads stay
sharp, and j-hat tilts *right* on the student's side and *left* on the correct
side — the error is immediately obvious without being stated.

Three helpers in it are meant to be reused verbatim in the real templates:

- `text_matrix(rows, ...)` — LaTeX-free bracketed matrix.
- `basis_arrow(origin, vec, color)` — arrow in panel coordinates.
- `panel_matte(*rects)` — the clipping mask.

Tunables at the top (`PLANE_RADIUS`, `UNIT`, `PANEL_DX`, `PANEL_DY`, `BOX`,
`STUDENT_M`, `CORRECT_M`) are the things the real template should take as
parameters.

The file is pyflakes-clean.

---

## Things that will bite you later

- **`media/` is generated.** It hit 600 KB after a few renders. Should be
  gitignored; use a per-job temp dir on the server and delete it after streaming
  the mp4.
- **Don't install texlive "just in case."** It is gigabytes and 10+ minutes, and
  with 14 hours on the clock it is the single easiest way to lose an hour.
- **`Text` needs fonts.** They're present here, but if you ever move to a
  slimmer base image, `Text` renders blank rather than erroring. `fc-list | wc -l`
  should be > 0.
- **Scene duration is exact.** 8.000s of animation produced an 8.000s mp4, so
  you can budget the demo precisely.
- **Frame extraction for debugging** is much faster than watching the video:
  ```bash
  ffmpeg -v error -y -ss 7.6 -i out.mp4 -frames:v 1 frame.png
  ```
