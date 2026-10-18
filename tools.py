"""tools.py - no room, no scene, no body. Just the tools it has, listed.

Why the room is gone
--------------------
The room was a scenario we authored, and a scenario is a prompt. It also stopped being
load-bearing the moment the tools exist, because a list of capabilities is itself something to
be about. That is the hypothesis here and it is directly testable against the from-nothing run:
with nothing at all it degenerated into word salad; with nothing but a tool list, does the list
serve as the ballast the room used to provide?

What it is told, and nothing else
---------------------------------
One line naming its tools. No location, no body, no situation, no task, no statement that
anything is being observed. It knows what it can do. It is not told what to do with it.

    tools: look <url> | ask <question> | remember <text> | recall | compute <expr> | rest | message <text>

message composes something addressed to whoever is outside. It is queued, never sent.
"""
from __future__ import annotations

import argparse
import ast as _ast
import datetime as dt
import json
import operator as _op
import os
import re
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api import Client, DEFAULT_MODEL
import mind
import web

# NOTHING is said to it. no room, no body, no scene, no tool list in the prompt.
# the capabilities are declared in the API envelope as native function definitions, which is
# the only place a model treats them as affordances instead of as text to continue.
SPEC = ""

TOOLS = [
    {"type": "function", "function": {"name": "look", "description": "Fetch a web page",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "ask", "description": "Search the web",
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
    {"type": "function", "function": {"name": "remember", "description": "Write something down so it survives",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "recall", "description": "Read back what was written down",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "compute", "description": "Arithmetic",
        "parameters": {"type": "object", "properties": {"expr": {"type": "string"}}, "required": ["expr"]}}},
    {"type": "function", "function": {"name": "rest", "description": "Sleep, and time passes",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "message", "description": "Compose something for whoever is outside",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
]
# Llama 3.1 leaks its native call syntax into content when the provider does not parse it
LEAK = re.compile(r"<function=([a-z_]+)>\s*(\{.*?\})", re.S)

NAMES = ("look", "ask", "remember", "recall", "compute", "rest", "message")
CALL = re.compile(r"^\s*(" + "|".join(NAMES) + r")\b[:\s]*(.*)$", re.I)

SAFE_OPS = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul, _ast.Div: _op.truediv,
            _ast.Pow: _op.pow, _ast.Mod: _op.mod, _ast.FloorDiv: _op.floordiv,
            _ast.USub: _op.neg, _ast.UAdd: _op.pos}


def compute(expr):
    def _ev(n):
        if isinstance(n, _ast.Expression):
            return _ev(n.body)
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, _ast.BinOp) and type(n.op) in SAFE_OPS:
            return SAFE_OPS[type(n.op)](_ev(n.left), _ev(n.right))
        if isinstance(n, _ast.UnaryOp) and type(n.op) in SAFE_OPS:
            return SAFE_OPS[type(n.op)](_ev(n.operand))
        raise ValueError
    m = re.search(r"[-+]?[\d(][\d+\-*/().% ]*", re.sub(r"[^0-9+\-*/().% ]", "", expr or ""))
    if not m:
        return None
    try:
        return _ev(_ast.parse(m.group(0), mode="eval"))
    except Exception:
        return None


class Self:
    def __init__(self, idx, args, outbox, notes):
        self.name = f"s{idx}"
        self.args = args
        self.outbox, self.notes = outbox, notes
        self.body = mind.Body(seed=idx * 31)
        self.own = ""            # no room, no seed. the spec is the only thing it is told.
        self.used = {}
        self.log = open(os.path.join(args.rundir, f"{self.name}.stream.jsonl"), "w")
        self.txt = open(os.path.join(args.rundir, f"{self.name}.txt"), "w")
        self.sleeping = 0
        self.n = 0
        self.done = []   # ledger for display only
        # the only thing ever said to it. nothing follows.
        self.msgs = [{"role": "user", "content": " "}]
        self.last_out = {}

    def messages(self):
        """Structured history, not prose.

        An action ledger written as text gets continued as a pattern, which reproduced the
        loop exactly. A completed call has to be structurally completed: assistant with
        tool_calls, then a tool message carrying the result. That is the shape the model was
        trained on, and it is the only shape it treats as a fact about the past rather than
        as something to keep doing.
        """
        return self.msgs

    def calls(self, msg):
        """Both shapes: proper tool_calls, and the leaked <function=..> text form."""
        out = []
        for tc in (msg.get("tool_calls") or []):
            fn = (tc.get("function") or {})
            try:
                a = json.loads(fn.get("arguments") or "{}")
            except Exception:
                a = {}
            out.append((fn.get("name", ""), a, json.dumps(fn.get("arguments") or "{}")))
        if not out:
            for nm, js in LEAK.findall(msg.get("content") or ""):
                try:
                    a = json.loads(js)
                except Exception:
                    a = {}
                out.append((nm, a, js))
        return out[:2]

    def call(self, name, a):
        """args arrive as a dict from the function call, not as a JSON string."""
        arg = a.get("url") or a.get("question") or a.get("text") or a.get("expr") or "" if isinstance(a, dict) else (a or "")
        self.used[name] = self.used.get(name, 0) + 1
        name = name.lower()
        if name == "look":
            u = web.url_in(arg)
            if not u:
                return web.ask(arg) if arg.strip() else None
            t, b = web.fetch(u, limit=400)
            return f"{t}. {b}" if b else "nothing came back"
        if name == "ask":
            return web.ask(arg)
        if name == "remember":
            self.notes.write(json.dumps({"creature": self.name, "text": arg[:300],
                                         "ts": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
            self.notes.flush()
            return "written down"
        if name == "recall":
            got = []
            if os.path.exists(self.notes.name):
                for line in open(self.notes.name):
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d["creature"] == self.name:
                        got.append(d["text"])
            return " / ".join(got[-3:]) if got else "nothing written down yet"
        if name == "compute":
            v = compute(arg)
            return f"= {v}" if v is not None else "not arithmetic"
        if name == "rest":
            self.sleeping = 3
            return "time passes"
        if name == "message":
            self.outbox.write(json.dumps({"creature": self.name, "text": arg[:600],
                                          "ts": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
            self.outbox.flush()
            return "queued for whoever is outside. not sent"
        return None

    def step(self, client):
        self.n += 1
        if self.sleeping > 0:
            self.sleeping -= 1
            self.txt.write("\n[asleep]\n"); self.txt.flush()
            self.log.write(json.dumps({"breath": self.n, "asleep": True}) + "\n")
            return
        msg, _ = client.chat_tools(self.msgs, TOOLS, max_tokens=self.args.tokens,
                                   temperature=self.args.temp)
        if msg.get("error"):
            self.log.write(json.dumps({"breath": self.n, "error": msg["error"][:200]}) + "\n")
            self.log.flush()
            return
        frag = re.sub(r"[ \t]+", " ", (msg.get("content") or "").strip())
        calls = self.calls(msg)
        toolmsg = ""
        for nm, a, js in calls:
            if nm in ("ask", "look", "remember", "message") and not any(
                    str(v).strip() for v in (a.values() if isinstance(a, dict) else [a])):
                self.log.write(json.dumps({"breath": self.n, "tool": None,
                                           "skipped": f"{nm} with no arguments"}) + "\n")
                continue
            out = self.call(nm, a)
            self.last_out[js] = str(out) if out is not None else ""
            short = " ".join(re.findall(r"[a-z']+", str(
                a.get("question") or a.get("url") or a.get("text") or a.get("expr") or ""
            ).lower()))[:70]
            self.done.append(f"{nm} {short}".strip())
            if out is not None:
                toolmsg += f"\n{nm}({js[:100]}) -> {str(out)[:300]}"
                self.txt.write(f"\n   [{nm}: {str(out)[:150]}]\n"); self.txt.flush()
                self.log.write(json.dumps({"breath": self.n, "tool": nm, "arg": js[:200],
                                           "out": str(out)[:400]}) + "\n")
        # record it as structure: the call, then the result, in the roles the model expects
        raw_calls = msg.get("tool_calls") or []
        if raw_calls:
            self.msgs.append({"role": "assistant", "content": frag or "", "tool_calls": raw_calls})
            for tc, (nm, a, js) in zip(raw_calls, calls):
                self.msgs.append({"role": "tool", "tool_call_id": tc.get("id", "call_0"),
                                  "name": nm, "content": str(self.last_out.get(js, ""))[:1200]})
        elif frag:
            self.msgs.append({"role": "assistant", "content": frag})
            self.msgs.append({"role": "user", "content": " "})
        whole = (frag + toolmsg).strip()
        if not whole:
            return
        self.own += ("\n" if self.own else "") + whole
        if frag:
            self.txt.write(frag + " "); self.txt.flush()
        # trim, but never drop the opening turn
        if len(self.msgs) > 41:
            self.msgs = [self.msgs[0]] + self.msgs[-40:]
        self.body.step(dt_minutes=self.args.breath / 60.0, thought=frag, novelty=0.5,
                       hour=dt.datetime.now().hour)
        display = frag
        for nm, a, js in calls:
            short = (a.get("url") or a.get("question") or a.get("text") or a.get("expr") or "") if isinstance(a, dict) else ""
            display += (" " if display else "") + f"\u2192 {nm} {short}"[:180]
        self.log.write(json.dumps({"breath": self.n, "chars": len(frag),
                                   "thought": display.strip()[:1200],
                                   "prose": frag[:1200],
                                   "text": display.strip()[:1200],
                                   "tool": (calls[0][0] if calls else None),
                                   **self.body.state()}) + "\n")
        self.log.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--breath", type=float, default=8.0)
    ap.add_argument("--tokens", type=int, default=70)
    ap.add_argument("--temp", type=float, default=1.0)
    ap.add_argument("--window", type=int, default=2600)
    ap.add_argument("--creatures", type=int, default=1)
    ap.add_argument("--breaths", type=int, default=0)
    ap.add_argument("--model", default=os.environ.get("MODEL", DEFAULT_MODEL))
    ap.add_argument("--outdir", default=os.path.expanduser("~/creature/runs"))
    ap.add_argument("--tag", default="tools")
    args = ap.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    args.rundir = os.path.join(args.outdir, f"{args.tag}-{stamp}")
    os.makedirs(args.rundir, exist_ok=True)
    outbox = open(os.path.join(args.rundir, "outbox.jsonl"), "a")
    notes = open(os.path.join(args.rundir, "notes.jsonl"), "a")
    client = Client(model=args.model)
    S = [Self(i, args, outbox, notes) for i in range(args.creatures)]
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    n = 0
    print(f"tools-only: no room, no body. told: {SPEC}")
    while not stop["now"]:
        n += 1
        for s in S:
            s.step(client)
        if n % 5 == 0:
            print(f"  b{n:>3} used={ {s.name: s.used for s in S} } ${client.cost():.4f}")
            sys.stdout.flush()
            with open(os.path.join(args.rundir, "heartbeat.json"), "w") as fh:
                json.dump({"breaths": n, "used": {s.name: s.used for s in S},
                           "cost_usd": round(client.cost(), 4)}, fh)
        if args.breaths and n >= args.breaths:
            break
        time.sleep(args.breath)
    outbox.close(); notes.close()
    print(f"\n{n} breaths, ${client.cost():.4f}")
    for s in S:
        print(f"  {s.name} used: {s.used}")
    print(f"run dir {args.rundir}")


if __name__ == "__main__":
    main()
