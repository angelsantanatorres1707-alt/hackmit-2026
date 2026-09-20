"""Exercise the OpenAI vision path against a local mock of the real API.

The OpenAI path cannot be tested against api.openai.com from the dev container
(the egress policy rejects it), so the request we build and the response we
parse are checked here instead. The mock ASSERTS the payload matches what
OpenAI's chat-completions vision API actually requires, so a malformed request
fails here rather than on stage.

    .venv/bin/python backend/tests/test_openai_provider.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

RECEIVED: list[dict] = []
REPLY: dict = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        RECEIVED.append(
            {"path": self.path, "headers": dict(self.headers), "json": json.loads(body)}
        )
        payload = json.dumps(REPLY).encode()
        self.send_response(REPLY.pop("_status", 200) if "_status" in REPLY else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        payload = json.dumps(
            {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}, {"id": "whisper-1"}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):  # keep test output readable
        pass


def _completion(content: str) -> dict:
    """The shape api.openai.com actually returns."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 300},
    }


EXTRACTION_JSON = json.dumps(
    {
        "document": {"page_count": 1, "legibility": "usable"},
        "problem": {"present": True, "statement": "Compute proj_a(b).", "topic": "projection"},
        "steps": [
            {
                "id": "s1",
                "student_label": "1)",
                "raw_text": "b.a = 3(1) + 1(2) = 5",
                "claimed_operation": "dot_product",
                "value": {"kind": "scalar", "scalars": [5.0]},
                "confidence": 0.9,
            },
            {
                "id": "s2",
                "student_label": "2)",
                "raw_text": "proj_a(b) = 5(1,2) = (5,10)",
                "claimed_operation": "projection",
                "value": {"kind": "vector", "rows": [[5.0, 10.0]]},
                "is_final_answer": True,
                "confidence": 0.85,
            },
        ],
    }
)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{'' if cond else '  <- ' + detail}")
    if not cond:
        failures.append(label)


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()

    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
              "OPENROUTER_API_KEY", "VISION_PROVIDER", "USE_FIXTURE"):
        os.environ.pop(k, None)
    os.environ["OPENAI_API_KEY"] = "sk-mock"
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"

    import importlib
    from backend import vision_providers as vp
    importlib.reload(vp)
    from backend import extract as ex
    importlib.reload(ex)

    img = (REPO / "samples" / "la_multiply.jpg").read_bytes()

    print("\n1. request shape sent to OpenAI")
    RECEIVED.clear()
    REPLY.clear()
    REPLY.update(_completion(EXTRACTION_JSON))
    parsed, meta = vp.extract_json([img], "SYSTEM PROMPT", "USER PROMPT", "openai")
    req = RECEIVED[0]
    body = req["json"]
    check("posts to /v1/chat/completions", req["path"].endswith("/chat/completions"), req["path"])
    check("sends bearer auth", req["headers"].get("Authorization") == "Bearer sk-mock")
    check("sends the configured model", body.get("model") == vp.OPENAI_MODEL,
          f"{body.get('model')} != {vp.OPENAI_MODEL}")
    check("asks for a json object", body.get("response_format") == {"type": "json_object"})
    check("sends temperature for a chat model", body.get("temperature") == 0)
    check("system message present", body["messages"][0]["role"] == "system")
    parts = body["messages"][1]["content"]
    img_parts = [p for p in parts if p.get("type") == "image_url"]
    check("exactly one image attached", len(img_parts) == 1, str(len(img_parts)))
    url = img_parts[0]["image_url"]["url"]
    check("image is a base64 data URI", url.startswith("data:image/jpeg;base64,"), url[:40])
    check(
        "image bytes round-trip intact",
        base64.b64decode(url.split(",", 1)[1]) == img,
    )
    check("text part follows the image", parts[-1]["type"] == "text")

    print("\n2. response parsing")
    check("usage recorded", meta.get("input_tokens") == 1200 and meta.get("output_tokens") == 300)
    check("provider tagged", meta.get("provider") == "openai")
    check("json parsed", parsed["problem"]["topic"] == "projection")
    obj = ex.Extraction.model_validate(parsed)
    check("validates as an Extraction", len(obj.steps) == 2)
    check("student's wrong answer preserved", obj.steps[1].value.rows == [[5.0, 10.0]])

    print("\n3. replies that are not clean json")
    for label, content in [
        ("fenced in ```json", f"```json\n{EXTRACTION_JSON}\n```"),
        ("wrapped in prose", f"Here you go:\n{EXTRACTION_JSON}\nHope that helps!"),
    ]:
        RECEIVED.clear(); REPLY.clear(); REPLY.update(_completion(content))
        got, _ = vp.extract_json([img], "S", "U", "openai")
        check(label, got["problem"]["topic"] == "projection")

    print("\n4. failure modes")
    RECEIVED.clear(); REPLY.clear(); REPLY.update(_completion("not json at all"))
    try:
        vp.extract_json([img], "S", "U", "openai")
        check("non-json raises ProviderError", False, "no error raised")
    except vp.ProviderError as exc:
        check("non-json raises ProviderError", True)
        check("error quotes the reply", "not json" in str(exc), str(exc)[:80])

    RECEIVED.clear(); REPLY.clear()
    truncated = _completion(EXTRACTION_JSON)
    truncated["choices"][0]["finish_reason"] = "length"
    REPLY.update(truncated)
    try:
        vp.extract_json([img], "S", "U", "openai")
        check("truncation is caught", False, "no error raised")
    except vp.ProviderError as exc:
        check("truncation is caught", "cut off" in str(exc), str(exc)[:80])

    print("\n5. reasoning models omit temperature")
    os.environ["OPENAI_MODEL"] = "o3"
    importlib.reload(vp)
    RECEIVED.clear(); REPLY.clear(); REPLY.update(_completion(EXTRACTION_JSON))
    vp.extract_json([img], "S", "U", "openai")
    check("no temperature for o3", "temperature" not in RECEIVED[0]["json"])
    os.environ.pop("OPENAI_MODEL", None)
    importlib.reload(vp)

    print("\n6. key checker lists vision models")
    check("check() succeeds against the mock", vp.check() == 0)

    print("\n7. full extract() path, as the API calls it")
    RECEIVED.clear(); REPLY.clear(); REPLY.update(_completion(EXTRACTION_JSON))
    importlib.reload(ex)
    result, meta2 = ex.extract([img], filenames=["work.jpg"])
    check("source is the live api, not a fixture", meta2.get("source") != "fixture", str(meta2))
    check("steps came from the model", len(result.steps) == 2)
    check("no fixture substitution flagged", not meta2.get("substituted_for_photo"))

    server.shutdown()
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
