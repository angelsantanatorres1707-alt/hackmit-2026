"""Manim rendering: params in, mp4 path out.

Runs each render in a SUBPROCESS (`python -m backend.render --worker`) with the
payload in the ``SCENE_PARAMS`` environment variable. Subprocess rather than
in-process because:

  * ``manim.config`` is global and class attributes are not thread-safe
    (RENDERING.md), and a child process is the cheapest possible lock;
  * a scene that raises, segfaults or hangs cannot take the API down with it,
    which matters when the scene templates are being written in parallel;
  * the API process never imports manim, so it starts in milliseconds.

Everything is cached by a hash of (template, params, quality, scene source
version), so re-rendering the rehearsed demo is instant and editing a scene
template correctly invalidates the old video.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENES_DIR = REPO_ROOT / "backend" / "scenes"
CACHE_DIR = Path(os.environ.get("RENDER_CACHE_DIR", "/tmp/manimhint/cache"))
WORK_DIR = Path(os.environ.get("RENDER_WORK_DIR", "/tmp/manimhint/jobs"))
QUALITY = os.environ.get("RENDER_QUALITY", "medium_quality")  # -qm: 1280x720@30
TIMEOUT = float(os.environ.get("RENDER_TIMEOUT", "180"))
PYTHON = os.environ.get("RENDER_PYTHON", sys.executable)

QUALITY_DIRS = {
    "low_quality": "480p15",
    "medium_quality": "720p30",
    "high_quality": "1080p60",
    "production_quality": "1440p60",
    "fourk_quality": "2160p60",
}


class RenderError(RuntimeError):
    def __init__(self, message: str, *, detail: str = "", timed_out: bool = False):
        super().__init__(message)
        self.detail = detail
        self.timed_out = timed_out


# --------------------------------------------------------------------------
# Template discovery. The scenes package is owned by another agent and may not
# exist yet, so every lookup here is defensive and reports rather than raises.
# --------------------------------------------------------------------------

def _registry_dicts() -> list[dict]:
    found: list[dict] = []
    for modname in ("backend.scenes.registry", "backend.scenes"):
        try:
            mod = __import__(modname, fromlist=["*"])
        except Exception:
            continue
        for attr in ("TEMPLATES", "REGISTRY", "SCENES", "SCHEMAS", "PARAM_SCHEMAS"):
            obj = getattr(mod, attr, None)
            if isinstance(obj, dict) and obj:
                found.append(obj)
    return found


_CLASS_DEF = re.compile(r"^class\s+([A-Za-z_]\w*)\s*\(", re.M)
_DICT_KEY = re.compile(r"^\s*[\"']([A-Za-z_]\w*)[\"']\s*:", re.M)


def available_templates() -> list[str]:
    """Template ids we could render right now.

    Deliberately a TEXT scan, not an import: the API process must never import
    manim (it is slow, and a scene module that is mid-edit would otherwise make
    this raise inside a request). Actually loading the class happens in the
    worker, where a failure is just a step down the fallback ladder.
    """
    names: set[str] = set()
    if not SCENES_DIR.is_dir():
        return []
    for path in SCENES_DIR.glob("*.py"):
        # helpers/common hold shared chrome (TextMatrix, SceneParamError), not templates
        if path.name.startswith("_") or path.name in ("helpers.py", "common.py"):
            continue
        try:
            src = path.read_text()
        except Exception:
            continue
        names.update(_CLASS_DEF.findall(src))
        if path.name in ("__init__.py", "registry.py"):
            names.update(_registry_keys(src))
    names.discard("ParamScene")
    return sorted(names)


_REGISTRY_NAMES = ("TEMPLATES", "REGISTRY", "SCENES", "SCHEMAS", "PARAM_SCHEMAS")


def _registry_keys(src: str) -> set[str]:
    """Top-level keys of the registry mappings, and nothing else.

    A flat regex over every quoted dict key also picks up the keys *inside* each
    entry - "quality", "media_dir", "module", "file" - and every param name in a
    nested schema, so /api/health advertised 'quality' and 'actual_det' as
    renderable templates. Parse instead, and descend exactly one level. Still no
    import, so this stays safe against a scene module that is mid-edit.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()

    keys: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not any(t in _REGISTRY_NAMES for t in targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _scan_scene_classes() -> dict[str, Any]:
    """Last resort: import every module in backend/scenes and collect Scene classes."""
    import importlib.util
    import inspect

    out: dict[str, Any] = {}
    if not SCENES_DIR.is_dir():
        return out
    try:
        from manim import Scene
    except Exception:
        return out
    for path in sorted(SCENES_DIR.glob("*.py")):
        if path.name in ("__init__.py", "common.py"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"_scenes_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
        except Exception:
            continue
        for name, obj in vars(mod).items():
            if inspect.isclass(obj) and issubclass(obj, Scene) and obj is not Scene:
                out.setdefault(name, obj)
    return out


def resolve_template(name: str):
    """-> a manim Scene subclass for this template id."""
    import inspect

    for d in _registry_dicts():
        entry = d.get(name)
        if entry is None:
            continue
        if inspect.isclass(entry):
            return entry
        for key in ("scene", "cls", "class", "template"):
            cand = entry.get(key) if isinstance(entry, dict) else None
            if inspect.isclass(cand):
                return cand
    scanned = _scan_scene_classes()
    if name in scanned:
        return scanned[name]
    raise RenderError(
        f"no scene template named {name!r}",
        detail=f"available: {', '.join(available_templates()) or '(none yet)'}",
    )


# --------------------------------------------------------------------------
# Cache key
# --------------------------------------------------------------------------

def _scene_version() -> str:
    """Changes whenever a scene file changes, so edits invalidate old videos."""
    if not SCENES_DIR.is_dir():
        return "0"
    stamps = sorted(
        f"{p.name}:{int(p.stat().st_mtime)}" for p in SCENES_DIR.glob("*.py")
    )
    return hashlib.sha256("|".join(stamps).encode()).hexdigest()[:8]


def cache_key(template: str, params: dict, quality: str = QUALITY) -> str:
    blob = json.dumps(
        {"t": template, "p": params, "q": quality, "v": _scene_version()},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def cached_path(video_id: str) -> Optional[Path]:
    path = CACHE_DIR / f"{video_id}.mp4"
    return path if path.is_file() and path.stat().st_size > 0 else None


# --------------------------------------------------------------------------
# Parent side
# --------------------------------------------------------------------------

def render(
    template: str,
    params: dict,
    *,
    quality: str = QUALITY,
    timeout: float = TIMEOUT,
    force: bool = False,
) -> dict[str, Any]:
    """Render one scene. -> {video_id, path, cached, seconds, template}."""
    started = time.time()
    video_id = cache_key(template, params, quality)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    hit = cached_path(video_id)
    if hit and not force:
        return {
            "video_id": video_id, "path": str(hit), "cached": True,
            "seconds": 0.0, "template": template,
        }

    job_dir = WORK_DIR / video_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    job_dir.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"{video_id}.mp4"

    payload = {
        "template": template,
        "params": params,
        "quality": quality,
        "media_dir": str(job_dir),
        "output_file": video_id,
        "out_path": str(out_path),
    }
    # Two files on purpose. params.json is the plain param dict the scene templates
    # document reading from $SCENE_PARAMS; job.json is this module's envelope.
    params_file = job_dir / "params.json"
    params_file.write_text(json.dumps(params, indent=2, default=str))
    job_file = job_dir / "job.json"
    job_file.write_text(json.dumps(payload, indent=2, default=str))

    env = dict(os.environ)
    env["SCENE_PARAMS"] = str(params_file)   # scenes accept a path or inline JSON
    env["SCENE_PARAMS_FILE"] = str(params_file)
    env["SCENE_JOB"] = json.dumps(payload, default=str)
    env["SCENE_JOB_FILE"] = str(job_file)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    try:
        proc = subprocess.run(
            [PYTHON, "-m", "backend.render", "--worker"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(
            f"render of {template} timed out after {timeout:.0f}s",
            detail=_tail(getattr(exc, "stderr", "") or ""),
            timed_out=True,
        ) from exc

    if proc.returncode != 0:
        raise RenderError(
            f"render of {template} failed (exit {proc.returncode})",
            detail=_tail(proc.stderr or proc.stdout),
        )

    result = _worker_result(proc.stdout)
    mp4 = Path(result.get("mp4", "")) if result else None
    if not mp4 or not mp4.is_file():
        raise RenderError(
            f"render of {template} produced no video", detail=_tail(proc.stderr or proc.stdout)
        )
    shutil.rmtree(job_dir, ignore_errors=True)
    return {
        "video_id": video_id,
        "path": str(mp4),
        "cached": False,
        "seconds": round(time.time() - started, 2),
        "template": template,
    }


def render_with_fallback(plan: dict, *, quality: str = QUALITY, timeout: float = TIMEOUT) -> dict[str, Any]:
    """The §1.3 ladder: chosen template -> StaticStepHighlight -> an honest failure.

    ``plan`` is {"template", "params", "fallback": {"template","params"} | None}.
    Never raises: a render problem must never reach the demo as a stack trace.
    """
    plan = plan or {}
    attempts: list[dict[str, Any]] = [
        {"template": plan.get("template"), "params": plan.get("params") or {}}
    ]
    # ``fallback`` is the next rung; ``fallbacks`` is the rest of the ladder
    # below it, which a StepReplay plan uses to keep StaticStepHighlight as the
    # never-raises bottom under the comparison template it demoted.
    rungs = [plan.get("fallback")] + list(plan.get("fallbacks") or [])
    for fb in rungs:
        if not isinstance(fb, dict) or not fb.get("template"):
            continue
        if any(fb["template"] == a["template"] for a in attempts):
            continue
        attempts.append({"template": fb["template"], "params": fb.get("params") or {}})

    errors: list[str] = []
    try:
        have = set(available_templates())
    except Exception as exc:           # a mid-edit scene file must not stop us
        errors.append(f"template scan failed: {type(exc).__name__}: {exc}")
        have = set()
    for attempt in attempts:
        if not attempt.get("template") or attempt.get("params") is None:
            errors.append("a fallback plan was incomplete")
            continue
        if have and attempt["template"] not in have:
            errors.append(f"{attempt['template']}: not implemented yet")
            continue
        try:
            out = render(attempt["template"], attempt["params"], quality=quality, timeout=timeout)
            out["degraded"] = attempt is not attempts[0]
            out["errors"] = errors
            out["ok"] = True
            return out
        except RenderError as exc:
            errors.append(f"{attempt['template']}: {exc} {exc.detail}".strip())
        except Exception as exc:
            # OSError from the cache dir, a JSON that will not serialize, an
            # unpickleable param -- none of these are RenderError, and all of
            # them used to come out of here as an exception instead of a step
            # down the ladder.
            errors.append(f"{attempt['template']}: {type(exc).__name__}: {exc}")
    return {"ok": False, "video_id": None, "path": None, "errors": errors,
            "template": plan.get("template"), "degraded": True}


def _tail(text: str, lines: int = 12) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _worker_result(stdout: str) -> Optional[dict]:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and "mp4" in line:
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


# --------------------------------------------------------------------------
# Worker side: this is the only place that imports manim.
# --------------------------------------------------------------------------

def _worker() -> int:
    raw = os.environ.get("SCENE_JOB")
    if not raw and os.environ.get("SCENE_JOB_FILE"):
        raw = Path(os.environ["SCENE_JOB_FILE"]).read_text()
    if not raw:
        print("SCENE_JOB is not set", file=sys.stderr)
        return 2
    payload = json.loads(raw)
    template = payload["template"]
    params = payload.get("params") or {}
    quality = payload.get("quality", QUALITY)
    media_dir = payload.get("media_dir") or str(WORK_DIR / "adhoc")
    output_file = payload.get("output_file", "scene")

    cls = resolve_template(template)

    # SCENE_CATALOG.md §1.3: every template exposes validate(); it raises
    # SceneParamError, which the parent turns into a step down the ladder.
    validated = params
    validate = getattr(cls, "validate", None)
    if callable(validate):
        try:
            validated = validate(params) or params
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 3

    # One class attribute, not a dozen: one thing to serialize (RENDERING.md).
    setattr(cls, "P", validated)
    for key, value in validated.items():
        upper = key.upper()
        if hasattr(cls, upper):
            setattr(cls, upper, value)

    from manim import tempconfig

    with tempconfig(
        {
            "quality": quality,
            "disable_caching": True,
            "media_dir": media_dir,
            "output_file": output_file,
            "verbosity": "ERROR",
            "progress_bar": "none",
        }
    ):
        cls().render()

    mp4 = _find_output(Path(media_dir), quality, output_file)
    if mp4 is None:
        print(f"no mp4 under {media_dir}", file=sys.stderr)
        return 4
    out_path = payload.get("out_path")
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        _publish(mp4, Path(out_path))
        mp4 = Path(out_path)
    print(json.dumps({"mp4": str(mp4)}))
    return 0


def _publish(src: Path, dest: Path) -> None:
    """Move the render into the cache with its moov atom up front.

    Manim leaves moov at the end of the file, so a browser has to download the
    whole thing before it can show frame one. The remux is a stream copy - no
    re-encode, no quality loss, well under a second - and it is what lets the
    video start playing while it is still arriving. Falls back to a plain copy
    if ffmpeg is missing or unhappy; a non-faststart video still plays.
    """
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-c", "copy", "-movflags", "+faststart", str(dest)],
            capture_output=True, timeout=60,
        )
        if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
            return
        print(f"faststart remux failed ({proc.returncode}), copying as-is",
              file=sys.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"faststart remux unavailable ({exc}), copying as-is", file=sys.stderr)
    shutil.copyfile(src, dest)


def _find_output(media_dir: Path, quality: str, output_file: str) -> Optional[Path]:
    """In-process renders write to <media_dir>/videos/<H>p<FPS>/<output_file>.mp4 -
    note there is NO script-stem directory, which is the classic path bug here."""
    sub = QUALITY_DIRS.get(quality, "720p30")
    direct = media_dir / "videos" / sub / f"{output_file}.mp4"
    if direct.is_file():
        return direct
    candidates = sorted(media_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


if __name__ == "__main__":
    if "--worker" in sys.argv:
        sys.exit(_worker())
    print(json.dumps({"templates": available_templates(), "cache": str(CACHE_DIR)}, indent=2))
