"""The project reads photographs with OpenAI, and nothing else.

This test exists because provider selection already drifted once: an
ANTHROPIC_API_KEY left in a shell outranked the OpenAI key set for this app, and
/api/health then reported a model nobody had configured. Several agents edit this
repo, so the rule is pinned in code and guarded here -- reordering providers, or
deleting the pin, fails this test instead of the demo.

    .venv/bin/python backend/tests/test_provider_pin.py
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
        "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "VISION_PROVIDER",
        "UNPIN_VISION_PROVIDER", "USE_FIXTURE", "OPENAI_MODEL")

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{'' if cond else '  <- ' + detail}")
    if not cond:
        failures.append(label)


def fresh(**env):
    for k in KEYS:
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    import backend.vision_providers as vp
    importlib.reload(vp)
    return vp


def main() -> int:
    print("\n1. the pin itself")
    vp = fresh(OPENAI_API_KEY="sk-x")
    check("PINNED_PROVIDER is openai", vp.PINNED_PROVIDER == "openai",
          repr(vp.PINNED_PROVIDER))
    check("openai key alone -> openai", vp.active_provider() == "openai")
    check("health reports the pin", vp.describe().get("pinned_to") == "openai")

    print("\n2. other providers cannot win")
    vp = fresh(OPENAI_API_KEY="sk-x", ANTHROPIC_API_KEY="sk-ant-x",
               GEMINI_API_KEY="AIza-x", OPENROUTER_API_KEY="sk-or-x")
    check("every key set -> still openai", vp.active_provider() == "openai",
          str(vp.active_provider()))
    check("model is an openai model", (vp.active_model() or "").startswith("gpt"),
          str(vp.active_model()))

    print("\n3. VISION_PROVIDER cannot override the pin")
    for other in ("anthropic", "gemini", "openrouter"):
        vp = fresh(OPENAI_API_KEY="sk-x", ANTHROPIC_API_KEY="sk-ant-x",
                   GEMINI_API_KEY="AIza-x", OPENROUTER_API_KEY="sk-or-x",
                   VISION_PROVIDER=other)
        check(f"VISION_PROVIDER={other} is ignored", vp.active_provider() == "openai",
              str(vp.active_provider()))

    print("\n4. a missing OpenAI key is an error, not a silent fallback")
    vp = fresh(ANTHROPIC_API_KEY="sk-ant-x", GEMINI_API_KEY="AIza-x")
    try:
        got = vp.active_provider()
        check("no openai key raises", False, f"returned {got!r} instead of raising")
    except vp.ProviderError as exc:
        msg = str(exc)
        check("no openai key raises", True)
        check("error names the key", "OPENAI_API_KEY" in msg, msg[:90])
        check("error names the fix", "setkey.sh" in msg, msg[:90])
        check("error says the others are ignored", "ignoring" in msg, msg[:90])

    print("\n5. the escape hatch still works, and only via the environment")
    vp = fresh(GEMINI_API_KEY="AIza-x", UNPIN_VISION_PROVIDER="1",
               VISION_PROVIDER="gemini")
    check("unpinned + forced -> gemini", vp.active_provider() == "gemini",
          str(vp.active_provider()))
    check("unpinned health drops the pin", vp.describe().get("pinned_to") is None)

    print("\n6. no keys at all")
    vp = fresh()
    try:
        vp.active_provider()
        check("no keys raises", False, "did not raise")
    except vp.ProviderError:
        check("no keys raises", True)
    check("active_model() is None", vp.active_model() is None, str(vp.active_model()))

    for k in KEYS:
        os.environ.pop(k, None)
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
