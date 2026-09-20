"""Read a photograph of handwritten work with whichever vision API you have a key for.

The app was written against Anthropic, but whoever is running it may have
credits somewhere else, or none at all. Everything here speaks raw HTTPS through
``urllib`` rather than a vendor SDK: one endpoint per provider is not worth a
dependency, and ``bash scripts/setup.sh`` stays fast.

Selection is automatic - set a key and it is used::

    export OPENAI_API_KEY=sk-...              # if you already have credits
    export GEMINI_API_KEY=...                 # free, no card: aistudio.google.com
    export ANTHROPIC_API_KEY=sk-ant-...       # backend/extract.py's own path
    export OPENROUTER_API_KEY=sk-or-...       # free tier, many models

With several set the order above decides, OpenAI first -- an ANTHROPIC_API_KEY
left in a shell for unrelated reasons must not outrank the key someone set for
this app. Force one with
``VISION_PROVIDER=openai|gemini|anthropic|openrouter``, and check what a key can
actually reach with::

    python -m backend.vision_providers

These providers are asked for raw JSON via the prompt rather than a formal
response schema. Gemini's ``responseSchema`` is an OpenAPI subset that rejects
the ``$ref``/``$defs`` pydantic emits, and flattening it by hand is a liability
at 3am. Asking for JSON and parsing defensively is what actually survives.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

TIMEOUT = float(os.environ.get("VISION_TIMEOUT", "90"))

# A 429 is a wait, not a failure: the provider tells us how long.
RETRY_429_MAX = int(os.environ.get("VISION_RETRY_429", "3"))
RETRY_429_CAP = float(os.environ.get("VISION_RETRY_CAP", "40"))

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# gpt-4o-mini rather than gpt-4o. Both read handwriting well, but a new OpenAI
# account gets a far larger tokens-per-minute allowance on the mini models, and
# gpt-4o's 10,000/min was the whole reason a second photo inside a minute came
# back as a rate-limit error instead of an animation. It is also several times
# cheaper per photo.
#
# Override with OPENAI_MODEL if an account has room for the larger model:
#     echo "OPENAI_MODEL=gpt-4o" >> .env
# `python -m backend.vision_providers` lists what a given key can reach.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# Overridable so the request/response path can be exercised against a local
# mock, and so an Azure/proxy/compatible endpoint works without a code change.
OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_URL = f"{OPENAI_BASE}/chat/completions"
OPENAI_MODELS_URL = f"{OPENAI_BASE}/models"

# Only so describe() can name the model for EVERY provider. The Anthropic call
# itself lives in backend/extract.py and reads the same variable.
ANTHROPIC_MODEL = os.environ.get("EXTRACTION_MODEL", "claude-opus-5")


# ---------------------------------------------------------------------------
# THE PIN
#
# This project reads photographs with OpenAI. Full stop.
#
# It is pinned in code, not left to whichever key happens to be exported,
# because several agents edit this repo and provider selection had already
# drifted once: an ANTHROPIC_API_KEY sitting in a shell silently outranked the
# OpenAI key that was set for this app, and /api/health then named a model
# nobody had configured.
#
# While pinned, every other provider's key is IGNORED -- not ranked lower,
# ignored -- and a missing OPENAI_API_KEY is an error that names the fix rather
# than a quiet fallback to some other API.
#
# The one escape hatch is deliberately awkward to reach by accident and exists
# for one situation: OpenAI is down mid-demo and you need Gemini's free tier
# right now. It is an environment variable, so no code edit can flip it:
#
#     UNPIN_VISION_PROVIDER=1 VISION_PROVIDER=gemini bash scripts/run.sh --live
#
# backend/tests/test_provider_pin.py fails if this constant changes, so an
# agent that "helpfully" reorders providers breaks a test instead of the demo.
# ---------------------------------------------------------------------------
PINNED_PROVIDER = "openai"


def pin_released() -> bool:
    return (os.environ.get("UNPIN_VISION_PROVIDER") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


class ProviderError(RuntimeError):
    """A vision call failed in a way worth showing a human."""


# ---------------------------------------------------------------- selection

def available_providers() -> list[str]:
    """Providers with a key, best first.

    OpenAI leads deliberately. ANTHROPIC_API_KEY is commonly already exported in
    a shell for unrelated reasons, and when it silently outranked the key
    someone had just set for this app, the app used a provider they never chose
    and /api/health named a model they had not configured.
    """
    out = []
    if os.environ.get("OPENAI_API_KEY"):
        out.append("openai")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        out.append("gemini")
    if os.environ.get("ANTHROPIC_API_KEY"):
        out.append("anthropic")
    if os.environ.get("OPENROUTER_API_KEY"):
        out.append("openrouter")
    return out


def active_model() -> str | None:
    """The model a photo would actually be sent to right now."""
    try:
        provider = active_provider()
    except ProviderError:
        return None
    return {
        "openai": OPENAI_MODEL,
        "gemini": GEMINI_MODEL,
        "anthropic": ANTHROPIC_MODEL,
        "openrouter": OPENROUTER_MODEL,
    }.get(provider)


def active_provider() -> str | None:
    """Which provider a photo would actually go to right now, or None.

    Pinned to OpenAI unless UNPIN_VISION_PROVIDER is set -- see THE PIN above.
    """
    have = available_providers()

    if PINNED_PROVIDER and not pin_released():
        if PINNED_PROVIDER in have:
            return PINNED_PROVIDER
        others = [p for p in have if p != PINNED_PROVIDER]
        raise ProviderError(
            f"{_key_name(PINNED_PROVIDER)} is not set, and this project is "
            f"pinned to {PINNED_PROVIDER}. Run: bash scripts/setkey.sh"
            + (
                f"  (ignoring the key(s) for {', '.join(others)} -- the pin is "
                "deliberate; set UNPIN_VISION_PROVIDER=1 only if OpenAI is down)"
                if others else ""
            )
        )

    forced = (os.environ.get("VISION_PROVIDER") or "").strip().lower()
    if forced:
        if forced not in ("anthropic", "openai", "gemini", "openrouter"):
            raise ProviderError(
                f"VISION_PROVIDER={forced!r} is not one of: "
                "anthropic, openai, gemini, openrouter"
            )
        if forced not in have:
            raise ProviderError(
                f"VISION_PROVIDER={forced} but no key for it. Set "
                f"{_key_name(forced)} (or unset VISION_PROVIDER to use: "
                f"{', '.join(have) or 'nothing - no keys are set'})."
            )
        return forced
    return have[0] if have else None


def _key_name(provider: str) -> str:
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }[provider]


def describe() -> dict[str, Any]:
    """For /api/health, so a stuck demo can be diagnosed without reading code."""
    try:
        active = active_provider()
        problem = None
    except ProviderError as exc:
        active, problem = None, str(exc)
    return {
        "active": active,
        "available": available_providers(),
        "model": active_model(),
        "problem": problem,
        "pinned_to": None if pin_released() else PINNED_PROVIDER,
    }


# ---------------------------------------------------------------- transport

_RETRY_AFTER = re.compile(r"try again in ([\d.]+)\s*s", re.I)


def _post(url: str, payload: dict, headers: dict, _attempt: int = 0) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode()[:600]
        except Exception:
            pass
        # 429 is the one a real account actually hits: a new OpenAI org starts at
        # 10k tokens per MINUTE, and one photo plus this prompt is most of that,
        # so two uploads in a row trip it. The reply says exactly how long to
        # wait ("Please try again in 25.494s") -- so wait that long and retry
        # instead of handing the student a wall of JSON.
        if exc.code == 429 and _attempt < RETRY_429_MAX:
            hinted = _RETRY_AFTER.search(detail)
            header = exc.headers.get("retry-after") if exc.headers else None
            try:
                wait = float(hinted.group(1)) if hinted else float(header or 0)
            except (TypeError, ValueError):
                wait = 0.0
            # A little margin: the window is measured server-side and a retry
            # landing on the same second just fails again.
            wait = min(max(wait, 2.0) + 1.0, RETRY_429_CAP)
            time.sleep(wait)
            return _post(url, payload, headers, _attempt + 1)
        if exc.code == 429:
            raise ProviderError(
                "rate limited by the provider (HTTP 429), and still limited after "
                f"{RETRY_429_MAX} retries. A new OpenAI account is capped at 10,000 "
                "tokens per minute; adding a payment method raises it. "
                f"{detail}"
            ) from exc
        if exc.code in (401, 403):
            raise ProviderError(
                f"the API key was rejected (HTTP {exc.code}). Check it is set "
                f"correctly and still active. {detail}"
            ) from exc
        raise ProviderError(f"vision call failed (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"could not reach the vision API: {exc.reason}") from exc


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _json_from_text(text: str) -> dict:
    """Pull an object out of a model reply that may be fenced or prose-wrapped."""
    text = (text or "").strip()
    if not text:
        raise ProviderError("the model returned an empty response")
    fenced = _JSON_BLOCK.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"the model did not return valid JSON: {text[:300]}"
            ) from exc
    raise ProviderError(f"the model did not return JSON at all: {text[:300]}")


def _mime(blob: bytes) -> str:
    if blob[:8].startswith(b"\x89PNG"):
        return "image/png"
    if blob[:3] == b"GIF":
        return "image/gif"
    if blob[4:12] in (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypmif1"):
        return "image/heic"
    return "image/jpeg"


# ---------------------------------------------------------------- providers

def _gemini(images: list[bytes], system: str, user: str) -> tuple[dict, dict]:
    key = os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"]
    parts: list[dict] = [
        {"inline_data": {"mime_type": _mime(b), "data": base64.b64encode(b).decode()}}
        for b in images
    ]
    parts.append({"text": user})
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    data = _post(GEMINI_URL.format(model=GEMINI_MODEL) + f"?key={key}", payload, {})

    candidates = data.get("candidates") or []
    if not candidates:
        # A blocked prompt returns 200 with no candidates and a reason here.
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise ProviderError(f"the model returned no answer{f' ({reason})' if reason else ''}")
    cand = candidates[0]
    if cand.get("finishReason") == "MAX_TOKENS":
        raise ProviderError("the reply was cut off; try a smaller image or fewer steps")
    text = "".join(
        p.get("text", "") for p in (cand.get("content") or {}).get("parts") or []
    )
    usage = data.get("usageMetadata") or {}
    return _json_from_text(text), {
        "provider": "gemini",
        "model": GEMINI_MODEL,
        "input_tokens": usage.get("promptTokenCount"),
        "output_tokens": usage.get("candidatesTokenCount"),
    }


def _openai_compatible(
    images: list[bytes], system: str, user: str, *, url: str, key: str,
    model: str, provider: str, extra_headers: dict | None = None,
) -> tuple[dict, dict]:
    """OpenAI's chat-completions shape, which OpenRouter also speaks."""
    content: list[dict] = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{_mime(b)};base64,{base64.b64encode(b).decode()}"
            },
        }
        for b in images
    ]
    content.append({"type": "text", "text": user})
    payload: dict[str, Any] = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    }
    # The reasoning models reject temperature outright, so only send it to the
    # models that accept it rather than sniffing model-name prefixes.
    if not re.match(r"^(o\d|gpt-5|gpt-6)", model):
        payload["temperature"] = 0

    data = _post(url, payload, {"Authorization": f"Bearer {key}", **(extra_headers or {})})
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError(f"the model returned no answer: {str(data)[:300]}")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise ProviderError("the reply was cut off; try a smaller image")
    text = (choice.get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return _json_from_text(text), {
        "provider": provider,
        "model": model,
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
    }


def _openai(images: list[bytes], system: str, user: str) -> tuple[dict, dict]:
    return _openai_compatible(
        images, system, user,
        url=OPENAI_URL, key=os.environ["OPENAI_API_KEY"],
        model=OPENAI_MODEL, provider="openai",
    )


def _openrouter(images: list[bytes], system: str, user: str) -> tuple[dict, dict]:
    return _openai_compatible(
        images, system, user,
        url=OPENROUTER_URL, key=os.environ["OPENROUTER_API_KEY"],
        model=OPENROUTER_MODEL, provider="openrouter",
    )


def extract_json(
    images: list[bytes], system: str, user: str, provider: str | None = None
) -> tuple[dict, dict]:
    """Send the photo(s) to a non-Anthropic provider; return (parsed json, meta).

    Anthropic is handled by backend/extract.py's own code path, which uses the
    SDK's structured-output support. This covers the free-tier alternatives.
    """
    provider = provider or active_provider()
    if provider == "openai":
        return _openai(images, system, user)
    if provider == "gemini":
        return _gemini(images, system, user)
    if provider == "openrouter":
        return _openrouter(images, system, user)
    raise ProviderError(
        f"no non-Anthropic provider selected (got {provider!r}). Set one of "
        "OPENAI_API_KEY, GEMINI_API_KEY (free, no card, aistudio.google.com) "
        "or OPENROUTER_API_KEY."
    )


def check() -> int:
    """`python -m backend.vision_providers` - say what a key can actually reach.

    Worth its few lines: "which model name works with my key" is otherwise
    answered by a failed demo.
    """
    info = describe()
    print(f"available providers : {', '.join(info['available']) or '(none - no keys set)'}")
    print(f"active provider     : {info['active']}")
    print(f"model               : {info['model']}")
    if info["problem"]:
        print(f"PROBLEM             : {info['problem']}")
        return 1
    if not info["active"]:
        print("\nSet one of: OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, "
              "OPENROUTER_API_KEY")
        return 1
    if info["active"] == "openai":
        try:
            data = _post_get(OPENAI_MODELS_URL, {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        except ProviderError as exc:
            print(f"\nkey check FAILED: {exc}")
            return 1
        names = sorted(m.get("id", "") for m in data.get("data") or [])
        vision = [n for n in names if re.match(r"^(gpt-4o|gpt-4\.1|gpt-5|gpt-6|o[1-9])", n)]
        print(f"\nkey works. {len(names)} models visible.")
        print("vision-capable models you can use with OPENAI_MODEL=:")
        for n in vision[:25]:
            print(f"  {n}{'   <- current default' if n == OPENAI_MODEL else ''}")
        if OPENAI_MODEL not in names:
            print(f"\nWARNING: OPENAI_MODEL={OPENAI_MODEL} is NOT in your account's "
                  "model list. Pick one from above.")
    else:
        print("\n(no model listing for this provider; a real photo is the test)")
    return 0


def _post_get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"HTTP {exc.code}: {exc.read().decode()[:300]}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"could not reach {url}: {exc.reason}") from exc


if __name__ == "__main__":
    raise SystemExit(check())
