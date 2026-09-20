"""FastAPI app: photo (or JSON steps) -> read-back, located error, hint, video.

    POST /api/analyze      multipart image(s), or JSON {fixture|extraction|steps}
    GET  /api/video/{id}   the mp4 (202 while it is still rendering)
    GET  /api/job/{id}     the full analysis again, plus live render status
    GET  /api/fixtures     canned extractions for fixture mode
    GET  /api/health       what is wired up right now
    GET  /                 the frontend, served straight from frontend/

The render is fired speculatively the moment the analysis is done and runs in a
background thread (EXTRACTION.md §7.4), so the confirm screen is the render's
dead time rather than the student's. Pass ``wait=true`` to block instead, which
is what curl and the smoke test use.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile

from . import extract as extract_mod
from . import hints as hints_mod
from . import render as render_mod
from . import verify as verify_mod
from .extract import Extraction

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"

app = FastAPI(title="See your mistake", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # localhost demo; no cookies, no credentials
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One render at a time: manim is CPU-bound and four parallel jobs make every one
# of them slow. The subprocess boundary already gives us isolation.
_RENDER_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render")
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()

# Jobs are held so /api/job and /api/video can answer later. Nothing ever
# removed them, so a long demo session grew the dict forever; 200 is far more
# than a demo needs and keeps every video that is still on screen reachable.
MAX_JOBS = int(os.environ.get("MAX_JOBS", "200"))


def _evict_old_jobs() -> None:
    """Caller holds _LOCK. Drops the oldest jobs past the cap."""
    if len(_JOBS) <= MAX_JOBS:
        return
    for jid, _ in sorted(_JOBS.items(), key=lambda kv: kv[1].get("created", 0))[
        : len(_JOBS) - MAX_JOBS
    ]:
        _JOBS.pop(jid, None)


# --------------------------------------------------------------------------
# Shaping for the confirm screen
# --------------------------------------------------------------------------

def _obj_view(obj) -> Optional[dict]:
    if obj is None:
        return None
    rows = obj.rows
    display = None
    if rows:
        display = [[hints_mod.fmt_num(x) for x in row] for row in rows]
    if obj.exact:
        display = [[str(x) for x in row] for row in obj.exact]
    scalars = obj.exact_scalars or (
        [hints_mod.fmt_num(s) for s in obj.scalars] if obj.scalars else None
    )
    return {
        "kind": obj.kind,
        "shape": obj.shape,
        "orientation": obj.orientation,
        "rows": rows,
        "display": display,
        "scalars": scalars,
        "var": obj.var,
        "text": obj.text,
    }


def _steps_view(ext: Extraction, verdict: verify_mod.Verdict) -> list[dict]:
    by_id = {r.step_id: r for r in verdict.step_results}
    out = []
    for step in sorted(ext.steps, key=lambda s: (s.page, s.reading_order)):
        res = by_id.get(step.id)
        status = res.status if res else "UNCHECKED"
        out.append(
            {
                "id": step.id,
                "label": step.student_label,
                "page": step.page,
                "reading_order": step.reading_order,
                "raw_text": step.raw_text,
                "claimed_expression": step.claimed_expression,
                "claimed_operation": step.claimed_operation,
                "bbox": step.bbox.model_dump() if step.bbox else None,
                "value": _obj_view(step.value),
                "alternates": [_obj_view(a) for a in step.alternates],
                "ambiguities": [a.model_dump() for a in step.ambiguities],
                "crossed_out": step.crossed_out,
                "parse_ok": step.parse_ok,
                "is_final_answer": step.is_final_answer,
                "needs_review": step.confidence < 0.55 or bool(step.ambiguities),
                "status": status,
                "is_first_error": verdict.step_id == step.id,
            }
        )
    return out


def _givens_view(ext: Extraction) -> list[dict]:
    return [
        {
            "symbol": g.symbol,
            "source": g.source,
            "object": _obj_view(g.object),
            "alternates": [_obj_view(a) for a in g.alternates],
            "ambiguities": [a.model_dump() for a in g.ambiguities],
            "needs_review": g.confidence < 0.8 or bool(g.ambiguities),
        }
        for g in ext.problem.givens
    ]


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------

def _empty_verdict() -> verify_mod.Verdict:
    """A verdict that accuses nobody, for when the checker itself falls over."""
    return verify_mod.Verdict(first_error_index=None, confidence="low")


def analyze_extraction(ext: Extraction, meta: dict, *, wait: bool, quality: Optional[str]) -> dict:
    t0 = time.time()
    crashes: list[str] = []

    # verify and plan are pure functions over student-supplied data, and the
    # student supplies it by photographing a page. Neither one gets to 500 the
    # request: a page we cannot check still has to come back as a read-back the
    # student can look at and correct.
    try:
        verdict = verify_mod.verify(ext)
    except Exception as exc:
        crashes.append(f"could not check this work ({type(exc).__name__}: {exc})")
        verdict = _empty_verdict()

    try:
        plan = hints_mod.plan(verdict, ext)
    except Exception as exc:
        crashes.append(f"could not build a hint ({type(exc).__name__}: {exc})")
        template, params = hints_mod._minimal(verdict)
        plan = hints_mod.Plan(
            template=template,
            params={**params, "hint": "watch the highlighted part",
                    "title": "Your work"},
            hint="Watch the highlighted part of your work.",
        )
    verify_seconds = round(time.time() - t0, 3)

    job_id = uuid.uuid4().hex[:12]
    job: dict[str, Any] = {
        "job_id": job_id,
        "created": time.time(),
        "digest": extract_mod.extraction_digest(ext),
        "source": meta.get("source"),
        "fixture": meta.get("fixture"),
        "extraction_seconds": meta.get("seconds"),
        "verify_seconds": verify_seconds,
        "problem": {
            "present": ext.problem.present,
            "statement": ext.problem.statement,
            "topic": ext.problem.topic,
            "asks_for": ext.problem.asks_for,
            "givens": _givens_view(ext),
        },
        "document": ext.document.model_dump(),
        "steps": _steps_view(ext, verdict),
        "first_error_index": verdict.first_error_index,
        "first_error_step_id": verdict.step_id,
        "student_label": verdict.student_label,
        "error_id": verdict.error_id,
        "confidence": verdict.confidence,
        "flags": verdict.flags,
        "student_value": verify_mod.val_json(verdict.student_value),
        "correct_value": verify_mod.val_json(verdict.correct_value),
        "hint": plan.hint,
        "scene_template": plan.template,
        "scene_params": plan.params,
        # Present when the scene replays the student's own steps: the ordered
        # step list with a time window each, so the player can highlight the
        # line the video is currently on. None means a comparison template.
        "replay": getattr(plan, "replay", None),
        "warnings": list(ext.extraction.warnings) + list(meta.get("notes") or []),
        "notes": plan.notes + verdict.notes,
        "video_url": f"/api/video/{job_id}",
        "video_status": "pending",
        "video_error": None,
        "video_path": None,
        "video_seconds": None,
        "rendered_template": None,
    }
    # Surfaced as its own field, not just another warning row: showing one
    # student another student's mistake is the single most misleading thing
    # this app can do, and it needs to be unmissable on screen.
    job["photo_substituted"] = bool(meta.get("substituted_for_photo"))
    if meta.get("fell_back_because"):
        job["warnings"].append(meta["fell_back_because"])
    job["warnings"].extend(crashes)
    job["degraded"] = bool(crashes)

    # The hint is the product. An empty one is a blank panel on the projector,
    # so it is replaced here rather than anywhere downstream.
    if not (job.get("hint") or "").strip():
        job["hint"] = f"Watch the highlighted part of {hints_mod.step_ref(verdict)}."
        job["notes"] = list(job.get("notes") or []) + ["hint was empty; used the positional wording"]

    with _LOCK:
        _JOBS[job_id] = job
        _evict_old_jobs()

    if verdict.first_error_index is None:
        job["video_status"] = "not_needed"
        job["hint"] = (
            "Could not check this work, so nothing is marked wrong. The read-back "
            "below is what was seen on the page."
            if crashes else
            "Nothing in this work disagrees with the problem as it was read."
        )
        return job

    plan_payload = plan.json()
    if wait:
        _do_render(job_id, plan_payload, quality)
    else:
        job["video_status"] = "rendering"
        _RENDER_POOL.submit(_do_render, job_id, plan_payload, quality)
    return job


def _do_render(job_id: str, plan_payload: dict, quality: Optional[str]) -> None:
    job = _JOBS.get(job_id)
    if job is None:
        return
    job["video_status"] = "rendering"
    try:
        result = render_mod.render_with_fallback(
            plan_payload, quality=quality or render_mod.QUALITY
        )
    except Exception as exc:  # a render problem must never reach the student
        job["video_status"] = "failed"
        job["video_error"] = f"{type(exc).__name__}: {exc}"
        return
    if result.get("ok"):
        job["video_status"] = "ready"
        job["video_path"] = result["path"]
        job["video_id"] = result["video_id"]
        job["video_seconds"] = result.get("seconds")
        job["rendered_template"] = result.get("template")
        job["video_degraded"] = bool(result.get("degraded"))
        if result.get("errors"):
            job["notes"] = list(job.get("notes") or []) + result["errors"]
    else:
        job["video_status"] = "failed"
        job["video_error"] = "; ".join(result.get("errors") or ["render failed"])


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in ("video_path", "created")}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@app.post("/api/analyze")
async def analyze(
    request: Request,
    wait_q: Optional[bool] = Query(default=None, alias="wait"),
    quality_q: Optional[str] = Query(default=None, alias="quality"),
) -> JSONResponse:
    """Photo(s), or JSON, in. Read-back + located error + hint + video URL out.

    Dispatches on Content-Type by hand rather than declaring File/Form and Body
    parameters together: FastAPI reads a JSON body as a *form field* once any
    File/Form parameter is declared, which silently drops the whole payload.
    """
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    body: dict[str, Any] = {}
    blobs: list[bytes] = []
    names: list[str] = []

    if ctype in ("multipart/form-data", "application/x-www-form-urlencoded"):
        form = await request.form()
        for key in ("image", "images", "file", "files", "photo"):
            for item in form.getlist(key):
                if isinstance(item, StarletteUploadFile):
                    data = await item.read()
                    if data:
                        blobs.append(data)
                        names.append(item.filename or "upload")
        for key in ("fixture", "wait", "quality"):
            if key in form:
                body[key] = form[key]
        if "extraction" in form:
            try:
                body["extraction"] = json.loads(str(form["extraction"]))
            except Exception:
                raise HTTPException(status_code=422, detail="extraction field is not valid JSON")
    elif ctype == "application/json":
        try:
            parsed = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="body is not valid JSON")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=422, detail="body must be a JSON object")
        body = parsed
    elif ctype.startswith("image/"):
        raw = await request.body()
        if raw:
            blobs.append(raw)
            names.append("upload")

    do_wait = _truthy(wait_q if wait_q is not None else body.get("wait", False))
    quality = quality_q or body.get("quality")
    fixture_name = body.get("fixture")

    # JSON path: a caller (or the confirm screen, after an edit) hands us the
    # structured work directly. No vision call at all.
    raw_extraction = body.get("extraction")
    if raw_extraction is None and body.get("steps") is not None:
        raw_extraction = {
            "document": body.get("document", {}),
            "problem": body.get("problem", {}),
            "steps": body["steps"],
            "final_answer": body.get("final_answer", {}),
            "extraction": body.get("meta", {"unreadable_regions": [], "warnings": []}),
        }
    if raw_extraction is not None:
        try:
            ext = Extraction.model_validate(raw_extraction)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"bad extraction payload: {exc}")
        meta = {"source": "client", "seconds": 0.0, "notes": extract_mod.audit(ext)}
        return JSONResponse(_public(analyze_extraction(ext, meta, wait=do_wait, quality=quality)))

    if not blobs and not fixture_name and not extract_mod.use_fixture_mode():
        raise HTTPException(
            status_code=400,
            detail="send an image file, a fixture name, or an extraction object",
        )

    try:
        ext, meta = extract_mod.extract(blobs or None, filenames=names, fixture=fixture_name)
    except extract_mod.ExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return JSONResponse(_public(analyze_extraction(ext, meta, wait=do_wait, quality=quality)))


@app.get("/api/job/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return JSONResponse(_public(job))


@app.get("/api/video/{video_id}")
def get_video(video_id: str):
    """The mp4. 202 while it is still rendering, so the frontend can just poll."""
    job = _JOBS.get(video_id)
    if job is not None:
        status = job.get("video_status")
        if status == "ready" and job.get("video_path") and Path(job["video_path"]).is_file():
            return FileResponse(job["video_path"], media_type="video/mp4",
                                filename=f"{video_id}.mp4")
        if status in ("pending", "rendering"):
            return JSONResponse({"status": status, "job_id": video_id}, status_code=202)
        if status == "not_needed":
            return JSONResponse({"status": status, "reason": "no error was found"}, status_code=204)
        return JSONResponse(
            {"status": status or "unknown", "error": job.get("video_error"),
             "notes": job.get("notes")},
            status_code=503,
        )
    direct = render_mod.cached_path(video_id)   # also serve raw cache keys
    if direct:
        return FileResponse(str(direct), media_type="video/mp4", filename=f"{video_id}.mp4")
    raise HTTPException(status_code=404, detail="no such video")


@app.get("/api/fixtures")
def get_fixtures() -> dict:
    return {"fixtures": extract_mod.list_fixtures(), "fixture_mode": extract_mod.use_fixture_mode()}


def _vision_health() -> dict:
    """Never let a health check be the thing that raises."""
    try:
        from . import vision_providers

        return vision_providers.describe()
    except Exception as exc:  # pragma: no cover
        return {"active": None, "available": [], "problem": str(exc)}


@app.get("/api/health")
def health() -> dict:
    templates = render_mod.available_templates()
    return {
        "ok": True,
        "fixture_mode": extract_mod.use_fixture_mode(),
        "api_key_present": extract_mod.have_api_key(),
        "model": extract_mod.MODEL,
        # Which vision API a photo would actually reach, and why not, if not.
        # "it silently used a fixture" is the failure this answers in one curl.
        "vision": _vision_health(),
        "fixtures": [f["name"] for f in extract_mod.list_fixtures()],
        "scene_templates": templates,
        "render_quality": render_mod.QUALITY,
        "cache_dir": str(render_mod.CACHE_DIR),
        "jobs": len(_JOBS),
        "frontend": FRONTEND_DIR.is_dir() and (FRONTEND_DIR / "index.html").is_file(),
    }


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:  # pragma: no cover
    @app.get("/")
    def root() -> dict:
        return {"ok": True, "note": "frontend/ is empty; the API is at /api/*"}
