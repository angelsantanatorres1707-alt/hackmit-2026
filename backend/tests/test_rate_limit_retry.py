"""Prove the 429 retry actually retries, and gives up cleanly."""
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, '/home/user/hackmit-2026')

STATE = {'calls': 0, 'fail_times': 2}

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        STATE['calls'] += 1
        if STATE['calls'] <= STATE['fail_times']:
            body = json.dumps({"error": {"message":
                "Rate limit reached for gpt-4o on tokens per min (TPM): Limit 10000, "
                "Used 7160, Requested 7089. Please try again in 2.5s.",
                "code": "rate_limit_exceeded"}}).encode()
            self.send_response(429)
        else:
            body = json.dumps({"choices":[{"message":{"content":'{"steps":[]}'},
                               "finish_reason":"stop"}],"usage":{}}).encode()
            self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass

srv = HTTPServer(('127.0.0.1',0), H); port = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()

for k in ('ANTHROPIC_API_KEY','GEMINI_API_KEY','OPENROUTER_API_KEY','VISION_PROVIDER'):
    os.environ.pop(k, None)
os.environ['OPENAI_API_KEY']='sk-x'
os.environ['OPENAI_BASE_URL']=f'http://127.0.0.1:{port}/v1'
import importlib
from backend import vision_providers as vp
importlib.reload(vp)

img = open('/home/user/hackmit-2026/samples/la_multiply.jpg','rb').read()

print("A. two 429s then success -> must succeed")
STATE.update(calls=0, fail_times=2)
t0=time.time()
out,_ = vp.extract_json([img], "S", "U", "openai")
print("   calls made :", STATE['calls'], "(1 real + 2 retried)")
print("   waited     : %.1fs (server said 2.5s each)" % (time.time()-t0))
print("   result     :", out)

print("\nB. never recovers -> clean error, not a JSON wall")
STATE.update(calls=0, fail_times=99)
try:
    vp.extract_json([img], "S", "U", "openai")
    print("   ** should have raised **")
except vp.ProviderError as e:
    msg=str(e)
    print("   calls made :", STATE['calls'], f"(gave up after {vp.RETRY_429_MAX} retries)")
    print("   says why   :", 'tokens per minute' in msg)
    print("   says fix   :", 'payment method' in msg)
srv.shutdown()
