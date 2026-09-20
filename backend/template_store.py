"""Every rendered video, kept as a REUSABLE template rather than a one-off.

A video is already a registered scene plus a parameter set -- the numbers ARE
the parameters. What was missing is that the parameter sets were thrown away
after the render, so nothing recorded what shape a given kind of problem
produces, and nothing could replay one with different numbers.

This writes each successful render down as {template, params}, filed by the
misconception it was made for. Feed a stored entry back to render() with the
numbers changed and you get the same film about a different problem, which is
what makes it a template and not a recording.

Deliberately dumb: JSON files in a directory, newest variant first, capped.
No database, nothing to start, nothing to go wrong at 10am. Set
NOEMA_TEMPLATE_DIR to move it.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

MAX_VARIANTS = 6          # per (error_id, template): enough to see the shape vary
_DEFAULT = Path(__file__).resolve().parents[1] / "generated_templates"

# Parameters that describe THIS student's page rather than the shape of the
# problem. They are kept for reference but are the first things you replace.
_PER_PAGE = ("hint", "title", "student_label", "correct_label")


def directory() -> Path:
    return Path(os.environ.get("NOEMA_TEMPLATE_DIR") or _DEFAULT)


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(s or "unknown")).strip("-")[:48] or "unknown"


def key_for(error_id: Optional[str], template: str) -> str:
    return f"{_slug(error_id or 'unclassified')}__{_slug(template)}"


def record(*, template: str, params: dict, error_id: Optional[str] = None,
           topic: str = "", asks_for: str = "", video_seconds: Optional[float] = None,
           digest: str = "") -> Optional[Path]:
    """Add this render to the template for its (error_id, template) pair.

    Never raises: failing to file a template must not cost a student their
    video. Returns the path written, or None.
    """
    try:
        d = directory()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{key_for(error_id, template)}.json"

        doc: dict[str, Any] = {"error_id": error_id, "template": template,
                               "variants": []}
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                if isinstance(loaded, dict) and isinstance(loaded.get("variants"), list):
                    doc = loaded
            except Exception:  # noqa: BLE001
                pass

        variant = {
            "params": params,
            "topic": topic,
            "asks_for": asks_for,
            "video_seconds": video_seconds,
            "digest": digest,
            "per_page_params": [k for k in _PER_PAGE if k in (params or {})],
        }
        # Same numbers rendered twice is the same variant, not a new one.
        sig = json.dumps(params, sort_keys=True, default=str)
        rest = [v for v in doc["variants"]
                if json.dumps(v.get("params"), sort_keys=True, default=str) != sig]
        doc["error_id"] = error_id
        doc["template"] = template
        doc["variants"] = ([variant] + rest)[:MAX_VARIANTS]

        # Atomic: a half-written template file read by the next request would
        # look like a corrupt one forever.
        fd, tmp = tempfile.mkstemp(dir=str(d), suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, indent=2, default=str)
        os.replace(tmp, path)
        return path
    except Exception:  # noqa: BLE001
        return None


def load(error_id: Optional[str], template: str) -> Optional[dict]:
    try:
        path = directory() / f"{key_for(error_id, template)}.json"
        return json.loads(path.read_text()) if path.exists() else None
    except Exception:  # noqa: BLE001
        return None


def catalogue() -> list[dict]:
    """Every template captured so far, with how many variants each has seen."""
    out: list[dict] = []
    try:
        for path in sorted(directory().glob("*.json")):
            try:
                doc = json.loads(path.read_text())
            except Exception:  # noqa: BLE001
                continue
            variants = doc.get("variants") or []
            out.append({
                "key": path.stem,
                "error_id": doc.get("error_id"),
                "template": doc.get("template"),
                "variants": len(variants),
                "latest_params": (variants[0] or {}).get("params") if variants else None,
                "per_page_params": (variants[0] or {}).get("per_page_params") if variants else [],
            })
    except Exception:  # noqa: BLE001
        pass
    return out
