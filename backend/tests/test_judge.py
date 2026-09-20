"""The judge layer, and the two vetoes that keep it honest.

Needs a running server in LIVE mode (it makes a real model call) and skips
itself otherwise:

    bash scripts/run.sh --live          # in one terminal
    .venv/bin/python backend/tests/test_judge.py [--port 8000]

The cases that matter most are the CORRECT ones. A miss is a video we do not
make; a false accusation is a red mark on work that was right, which is the
one thing this product must never do. Asked whether a conclusion is wrong, a
model will happily recite the misconception it was just shown -- it called a
genuine rotation a failure to preserve angles -- so every code with a decidable
test is confirmed against sympy before it reaches the student.
"""

import json
import sys
import urllib.error
import urllib.request

PORT = 8000
for i, a in enumerate(sys.argv):
    if a == "--port" and i + 1 < len(sys.argv):
        PORT = int(sys.argv[i + 1])
BASE = f"http://127.0.0.1:{PORT}"

def vec(*x): return {"kind":"vector","shape":[1,len(x)],"rows":[list(x)]}
def mat(r):  return {"kind":"matrix","shape":[len(r),len(r[0])],"rows":r}
def txt(t):  return {"kind":"text","text":t}
def st(n,t,v,f=False,op="unknown"):
    return {"id":f"s{n}","student_label":f"{n})","page":1,"reading_order":n,"raw_text":t,
            "claimed_operation":op,"value":v,"is_final_answer":f,"parse_ok":True,"confidence":0.95}
def g(sym,o): return {"symbol":sym,"object":o,"source":"printed","confidence":0.97}
def ex(stm,topic,asks,givens,steps):
    return {"problem":{"present":True,"statement":stm,"topic":topic,"asks_for":asks,
            "confidence":0.95,"givens":givens},"steps":steps,"notes":[],"page_count":1}

CASES = [
 ("WRONG: shear called a rotation (no regex for this)", True,
  ex("T(e1)=(2,1), T(e2)=(1,2). Describe T.","Linear Algebra","description",
     [g("T(e1)",vec(2,1)), g("T(e2)",vec(1,2))],
     [st(1,"Both images have length sqrt(5), the same as each other.",txt("both length sqrt5")),
      st(2,"A map that sends the basis to vectors of equal length must be a rotation, so T is a rotation of the plane.",
         txt("T is a rotation of the plane"),True)])),

 ("WRONG: two vectors called a basis for R^3", True,
  ex("Do u and v form a basis for R^3?","Linear Algebra","conclusion",
     [g("u",vec(1,0,0)), g("v",vec(0,1,0))],
     [st(1,"u = (1,0,0), v = (0,1,0)",vec(1,0,0)),
      st(2,"These two are independent, and independent vectors form a basis, so u and v are a basis for R^3.",
         txt("u and v are a basis for R^3"),True)])),

 ("CORRECT: must NOT be accused", False,
  ex("Compute AB.","matrix_multiply","AB",
     [g("A",mat([[2,-1],[3,1]])), g("B",mat([[4,0],[2,5]]))],
     [st(1,"A = [2 -1; 3 1]  B = [4 0; 2 5]",mat([[2,-1],[3,1]])),
      st(2,"AB = [6 -5; 14 5]",mat([[6,-5],[14,5]]),True,"matrix_multiply")])),

 ("CORRECT: rotation really does preserve angles", False,
  ex("T(e1)=(0,1), T(e2)=(-1,0). Does T preserve angles?","Linear Algebra","conclusion",
     [g("T(e1)",vec(0,1)), g("T(e2)",vec(-1,0))],
     [st(1,"Both images are unit length and perpendicular.",txt("unit and perpendicular")),
      st(2,"So T is a rotation and it preserves angles.",txt("T preserves angles"),True)])),

 ("CORRECT: valid but unusual method", False,
  ex("Find det A.","determinant","det A",
     [g("A",mat([[3,5],[2,4]]))],
     [st(1,"Row reduce: R2 <- R2 - (2/3)R1 gives [3 5; 0 2/3]",mat([[3,5],[0,0.6666666667]])),
      st(2,"det = 3 * (2/3) = 2",{"kind":"scalar","scalars":[2.0]},True,"determinant")])),
]

ok = 0
for name, expect_wrong, e in CASES:
    req = urllib.request.Request(f"{BASE}/api/analyze?wait=false",
        data=json.dumps({"extraction": e}).encode(),
        headers={"Content-Type":"application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=180))
    except (urllib.error.URLError, OSError) as exc:
        print(f"SKIP: no server on {BASE} ({exc})")
        sys.exit(0)
    got = d.get("first_error_step_id")
    hit = bool(got) == expect_wrong
    ok += hit
    note = [n for n in (d.get("notes") or []) if n.startswith("judged")]
    print(f"  {'PASS' if hit else 'FAIL'}  {name}")
    print(f"        -> step={got} id={d.get('error_id')} flags={d.get('flags')}")
    if note: print(f"        -> {note[0][:130]}")
print(f"\n{ok}/{len(CASES)} passed")
sys.exit(0 if ok == len(CASES) else 1)
