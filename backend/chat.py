"""A tutor you can actually talk to, inside the same rules as the hint.

The composer used to answer from a lookup table: it could ask for an upload
and little else, so a student who did not like the video, or did not follow
it, had nowhere to go. This gives it a model -- with the one rule that makes
this product what it is still enforced in code rather than requested in a
prompt.

The reply is linted exactly as a hint is. If the model states the correct
value, the reply is thrown away and replaced. A chatbot that leaks the answer
is worse than no chatbot, because the whole promise is that it will not.

It may also propose a DIFFERENT visualisation of the same error, chosen from
the templates the registry says can carry it -- so "show me another way" does
something instead of apologising.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import re

MAX_MESSAGE = 600
MAX_REPLY = 420

# What counts as asking for a different picture, as opposed to asking a
# question about the one on screen.
_ASKED_FOR_ANOTHER = re.compile(
    r"\b(?:different|another|other|again|instead|re-?do|redo|re-?make|remake|"
    r"new\s+(?:video|animation)|another\s+way|other\s+way|show\s+me\s+\w+\s+way|"
    r"visuali[sz]e\s+it|try\s+again|alternative)\b", re.I)

SYSTEM = """\
You are Noema, a linear algebra tutor. A student has uploaded work, it has been
checked exactly, and they are now talking to you about it.

THE ONE RULE: never state the correct answer, or any number derived from it. Not
the value, not the difference from theirs, not "it should be twice as big". You
point at the place to look and the idea to think about. This is enforced after
you reply -- a reply that leaks is discarded and the student sees a canned line
instead, so leaking costs them your answer.

You may: explain the concept, say what the animation is showing, say which step
you are pointing at and why that kind of step goes wrong, suggest what to try
next, and offer a different visualisation.

You may not: give the corrected value, do the arithmetic for them, or claim the
checker was wrong -- it is exact, and it is right.

Keep it to two or three sentences. Talk like a person, not a textbook.

Return ONLY this JSON:
{"reply": "what you say to the student",
 "want": "rerender" | "upload" | null,
 "template": "<one of alternate_templates>" or null}

"want":"rerender" with a template asks for that visualisation to be built. Only
use it if they asked for something different, and only name a template from
alternate_templates. "want":"upload" if you genuinely need to see more of their
work before you can help.
"""


def _alternates(error_id: Optional[str], current: str) -> list[str]:
    """Other registered templates that say they can carry this error."""
    try:
        from .scenes import registry
    except Exception:  # noqa: BLE001
        try:
            from scenes import registry  # type: ignore
        except Exception:  # noqa: BLE001
            return []
    out = []
    for name, spec in (getattr(registry, "TEMPLATES", {}) or {}).items():
        if name == current:
            continue
        covers = [str(c).split("(")[0] for c in (spec.get("covers") or [])]
        if error_id and error_id in covers:
            out.append(name)
    return sorted(out)


def _context(job: dict) -> dict:
    steps = []
    for s in (job.get("steps") or [])[:14]:
        steps.append({"id": s.get("id"), "wrote": s.get("raw_text"),
                      "status": s.get("status"),
                      "blamed": bool(s.get("is_first_error"))})
    return {
        "problem": (job.get("problem") or {}).get("statement"),
        "asks_for": (job.get("problem") or {}).get("asks_for"),
        "steps": steps,
        "blamed_step": job.get("first_error_step_id"),
        "error_id": job.get("error_id"),
        "hint_already_shown": job.get("hint"),
        "current_template": job.get("rendered_template") or job.get("scene_template"),
        "alternate_templates": _alternates(
            job.get("error_id"), job.get("rendered_template") or job.get("scene_template") or ""),
        "video_status": job.get("video_status"),
    }


def _forbidden(job: dict) -> tuple[list[str], list[str]]:
    """(values the reply must not contain, values it may)."""
    from .hints import _forbidden as forb, derived_values
    from .verify import to_sympy

    def as_val(raw):
        try:
            return to_sympy(raw) if raw else None
        except Exception:  # noqa: BLE001
            return None

    allowed = forb(as_val(job.get("student_value")))
    bad = forb(as_val(job.get("correct_value")))
    return bad + derived_values(allowed, bad), allowed


FALLBACK = ("I would rather not say more than the hint here -- that is the point "
            "of it. Tell me which part of the animation is not landing and I will "
            "come at it another way.")


def respond(job: dict, message: str) -> dict:
    """-> {"reply", "want", "template"}. Never raises."""
    text = (message or "").strip()[:MAX_MESSAGE]
    if not text:
        return {"reply": "", "want": None, "template": None}

    payload = json.dumps({"student_says": text, "analysis": _context(job)},
                         ensure_ascii=False)
    try:
        from . import vision_providers

        raw, _meta = vision_providers.extract_json([], SYSTEM, payload)
    except Exception as exc:  # noqa: BLE001
        return {"reply": "I could not reach the tutor just now. The hint above still "
                         "stands, and the animation is the argument behind it.",
                "want": None, "template": None, "error": str(exc)[:120]}

    if not isinstance(raw, dict):
        return {"reply": FALLBACK, "want": None, "template": None}

    reply = str(raw.get("reply") or "").strip()[:MAX_REPLY]
    leaked: list[str] = []
    if reply:
        try:
            from .hints import lint_hint

            bad, allowed = _forbidden(job)
            # Only the VALUE findings discard a reply. lint_hint also rejects
            # corrective phrasing, which is tuned for an eight-word caption
            # burned into a frame -- in three sentences of conversation "try"
            # and "instead" are ordinary English, and letting that rule run
            # here wiped two replies out of three and left the student with a
            # canned line. The leak that matters is a number.
            leaked = [p for p in lint_hint(reply, bad, allowed) if "leaks the value" in p]
        except Exception:  # noqa: BLE001
            leaked = []
    if not reply or leaked:
        reply = FALLBACK

    want = raw.get("want") if raw.get("want") in ("rerender", "upload") else None
    template = raw.get("template")
    if want == "rerender":
        # The model offered a new picture on almost every turn, including
        # "I do not understand" -- which wants an explanation, not a different
        # film, and swapping the animation under someone mid-question is worse
        # than useless. Rebuild only when they actually asked for something
        # else, and never sideways into the template already on screen.
        current = _context(job)["current_template"]
        if not _ASKED_FOR_ANOTHER.search(text) or template == current:
            template, want = None, None
        elif template not in _context(job)["alternate_templates"]:
            template, want = None, None
    else:
        template = None

    out = {"reply": reply, "want": want, "template": template}
    if leaked:
        out["leaked"] = leaked          # developer-visible only
    return out
