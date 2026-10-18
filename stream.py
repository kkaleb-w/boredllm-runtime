"""BoredLLM stream mode: one continuous stream of thought, not a sequence of thoughts.

Why this exists
---------------
The tick mode produced discrete, self-contained paragraphs, each a response to a freshly
rendered room. A person's thinking is not like that. It does not reset every ten minutes, it
does not get the whole scene re-described to it, and it does not emit tidy paragraphs. It runs,
and the world occasionally interrupts.

So the units change:

  tick mode    world speaks every tick -> creature answers -> world speaks again
  stream mode  the creature never stops -> the world speaks only when it CHANGES

The world keeps a clock. The mind does not have ticks, it has breaths. The stream is one
continuous text that is appended to forever, and the creature's own prior text is the only
thing carrying it forward. That makes "the mind is its own input" literal rather than a design
principle.

The world's lines stay in the readable record but are dropped from the model's context as the
window slides, so the stream is not polluted by near-identical re-descriptions (a measured
self-similarity attractor). Only the most recent intrusion is visible, and only until it falls
out of the window.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api import Client, DEFAULT_MODEL
import mind
import web
import world as W

COMMENT = re.compile(
    r"\b(the (text|passage|poem|story|narrator|writer|author|speaker|protagonist|character|"
    r"scene|piece|line|phrase)|it'?s like|this is like|suggests|represents|symboli|metaphor|"
    r"reads as|evokes|imagery|in terms of|the theme|narrative|(refine|rewrite|revise|edit) "
    r"(it|this)|to be more|in \d+-\d+ lines)\b", re.I)
TEMPLATE = re.compile(
    r"\b(option[s]?\s*[a-d]\)|choose one|multiple.choice|answer the question|what (is|are) the "
    r"correct|could you|would you like|the question is|as an ai|i'?ll (help|assist)|let me know)\b",
    re.I)


def elapsed(sec):
    h = int(sec // 3600)
    return (f"{h}h{int(sec % 3600 // 60):02d}m" if h else f"{int(sec // 60)}m{int(sec % 60):02d}s")


class Stream:
    def __init__(self, idx, args):
        self.idx, self.args = idx, args
        self.name = f"s{idx}"
        self.world = W.World(seed=idx * 17)
        self.body = mind.Body(seed=idx * 31)
        self.dir = args.rundir
        self.mem = mind.Memory(os.path.join(self.dir, f"{self.name}.db"))
        self.own = ""                 # the creature's text only: this is the context
        self.last_world = ""          # most recent intrusion, dropped as the window slides
        self.log = open(os.path.join(self.dir, f"{self.name}.stream.jsonl"), "w")
        self.readable = open(os.path.join(self.dir, f"{self.name}.txt"), "w")
        self.text_log = open(os.path.join(self.dir, f"{self.name}.stream.log"), "w")
        self.breaths = 0
        self.sessions = 0             # world intrusions
        self.prev_obs = ""
        self.world_novelty = 0.5
        self.last_rep = 0.0
        self.looks = 0
        self.rows = []

    # -------------------------------------------------------------- the world

    def world_speaks(self, now):
        """Only on change. The world is not a narrator, it is an interruption."""
        obs = self.world.observe(self.body)
        if obs == self.prev_obs:
            return None
        # novelty is against the world, and it is applied once, on the intrusion
        self.world_novelty = (1.0 - mind.overlap(self.prev_obs, obs)) if self.prev_obs else 0.5
        self.prev_obs = obs
        self.sessions += 1
        self.world.offset = 0.0
        return f"[{dt.datetime.now().strftime('%H:%M')}] {obs}"

    # -------------------------------------------------------------- the mind

    def context(self):
        """The stream's context.

        Measured lesson: removing the per-tick observation did not free the stream, it
        unmoored it. With only one world line and its own long prior text in view, the
        model did what language models do with text: it criticised it. Sixty breaths
        produced a dissertation on Nabokov, Kundera and Robinson Crusoe, none of whom
        are in the room.

        So the anchor has to be CONTINUOUS, and the shape of it is interoception:
        you always feel your body, and you only notice the room when it changes. The
        body speaks every breath, in flat first person, graded so it varies. The world
        still speaks only on change. And the self-window is short, so there is a
        fragment to continue rather than a passage to analyse.
        """
        tail = self.own[-self.args.window:] if self.own else ""
        anchor = self.body.say()
        parts = [p for p in (self.last_world, tail, anchor) if p]
        return "\n".join(parts)

    def breathe(self, client):
        self.breaths += 1
        prompt = self.context()
        if not prompt.strip():
            return None
        raw, usage = client.generate(prompt, max_tokens=self.args.tokens,
                                     temperature=self.args.temp)
        frag = re.sub(r"\s+", " ", re.split(r"\[", raw)[0]).strip()
        rep = mind.overlap(self.own[-400:], frag) if self.own else 0.0
        self.last_rep = rep
        stance = ("empty" if not frag else
                  "comment" if COMMENT.search(frag) else
                  "template" if TEMPLATE.search(frag) else "other")
        if frag:
            self.own += " " + frag
            self.readable.write(frag + " ")
            self.readable.flush()
            self.text_log.write(" " + frag)
            self.text_log.flush()
        audit = self.world.audit(frag) if frag else {"n_invented_refs": 0, "invented_refs": []}
        # if it produced a URL, the world honours it. That is the creature directing its
        # own attention with no instruction anywhere in the loop.
        if self.args.web and frag:
            u = web.url_in(frag)
            if u:
                looked = web.as_looked(u)
                if looked:
                    self.last_world = looked
                    self.readable.write("\n" + looked + "\n"); self.readable.flush()
                    self.log.write(json.dumps({"breath": self.breaths, "creature": self.name,
                                               "world": looked, "looked": u,
                                               **self.body.state()}) + "\n"); self.log.flush()
                    self.looks += 1
        hits = []
        if self.body.bored and self.args.memory:
            hits = self.mem.recall(self.own[-200:], limit=2)
            if hits:
                frag = (frag + " " + " ".join(hits)[:160]).strip()
                self.own += " " + " ".join(hits)[:160]
                self.text_log.write(" |" + " ".join(hits)[:160])
        self.mem.retain(self.breaths, frag, salience=None) if frag else None
        # the body is driven by the world, never by its own text. Between intrusions the
        # world supplies nothing, so stimulation falls; an intrusion pays a little back.
        nov, self.world_novelty = self.world_novelty, 0.0
        self.body.step(dt_minutes=self.args.breath / 60.0, thought=frag,
                       novelty=nov, hour=dt.datetime.now().hour)
        row = {"breath": self.breaths, "creature": self.name, "ts": dt.datetime.now().isoformat(timespec="seconds"),
               "model": client.model, "chars": len(frag), "stance": stance,
               "rep": round(rep, 3), "invented": audit["n_invented_refs"],
               "recall": len(hits), "context_chars": len(prompt),
               "text": frag, **self.body.state()}
        self.log.write(json.dumps(row) + "\n"); self.log.flush()
        self.rows.append(row)
        return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--breath", type=float, default=8.0, help="seconds between continuations")
    ap.add_argument("--tokens", type=int, default=45, help="tokens per breath: a fragment, not a paragraph")
    ap.add_argument("--temp", type=float, default=0.95)
    ap.add_argument("--window", type=int, default=1200, help="chars of its own text kept in context")
    ap.add_argument("--creatures", type=int, default=1)
    ap.add_argument("--minutes", type=float, default=0, help="stop after N minutes (0 = forever)")
    ap.add_argument("--breaths", type=int, default=0, help="stop after N breaths (0 = forever)")
    ap.add_argument("--world-interval", type=float, default=600,
                    help="minimum seconds between world intrusions")
    ap.add_argument("--model", default=os.environ.get("MODEL", DEFAULT_MODEL))
    ap.add_argument("--outdir", default=os.path.expanduser("~/creature/runs"))
    ap.add_argument("--memory", dest="memory", action="store_true", default=True)
    ap.add_argument("--no-memory", dest="memory", action="store_false")
    ap.add_argument("--web", dest="web", action="store_true", default=False,
                    help="the window also opens onto the real, live web. read-only, no write "
                         "path anywhere. See web.py for why this is legitimate as a condition.")
    ap.add_argument("--web-every", type=float, default=90,
                    help="seconds between real-web intrusions when --web is on")
    ap.add_argument("--tag", default="stream")
    args = ap.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    args.rundir = os.path.join(args.outdir, f"{args.tag}-{stamp}")
    os.makedirs(args.rundir, exist_ok=True)

    client = Client(model=args.model)
    streams = [Stream(i, args) for i in range(args.creatures)]
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))

    print(f"model    {client.model}")
    print(f"run      {args.rundir}")
    print(f"breath   {args.breath}s   world speaks at most every {args.world_interval}s")
    sys.stdout.flush()

    t0 = time.time()
    last_world = 0.0
    last_web = 0.0
    try:
        while not stop["now"]:
            # the world interrupts only when it has actually changed, and not too often
            if args.web and time.time() - last_web >= args.web_every:
                for s in streams:
                    line = web.as_noticed()
                    if line:
                        s.last_world = line
                        s.readable.write("\n" + line + "\n"); s.readable.flush()
                        s.text_log.write("\n" + line + "\n"); s.text_log.flush()
                        s.log.write(json.dumps({"breath": s.breaths, "creature": s.name,
                                                "world": line, "source": "web",
                                                **s.body.state()}) + "\n"); s.log.flush()
                last_web = time.time()
            if time.time() - last_world >= args.world_interval:
                for s in streams:
                    line = s.world_speaks(time.time())
                    if line:
                        s.last_world = line
                        s.readable.write("\n\n" + line + "\n")
                        s.readable.flush()
                        s.text_log.write("\n" + line + "\n")
                        s.text_log.flush()
                        s.log.write(json.dumps({"breath": s.breaths, "creature": s.name,
                                                "world": line, **s.body.state()}) + "\n")
                        s.log.flush()
                last_world = time.time()
            for s in streams:
                s.breathe(client)
            b0 = streams[0].breaths
            if b0 % 10 == 0:
                s = streams[0]
                print(f"breath {b0:>5}  {elapsed(time.time()-t0):>6}  stim={s.body.stimulation:.2f} "
                      f"rep={s.last_rep:.2f}  tok={client.tok_in}/{client.tok_out}  "
                      f"${client.cost():.4f}  err={client.errors}")
                sys.stdout.flush()
                with open(os.path.join(args.rundir, "heartbeat.json"), "w") as fh:
                    json.dump({"breaths": b0, "ts": dt.datetime.now().isoformat(timespec="seconds"),
                               "elapsed_s": round(time.time() - t0, 1),
                               "cost_usd": round(client.cost(), 4)}, fh)
            if args.breaths and streams[0].breaths >= args.breaths:
                break
            if args.minutes and (time.time() - t0) / 60.0 >= args.minutes:
                break
            time.sleep(args.breath)
    finally:
        for s in streams:
            for fh in (s.log, s.readable, s.text_log):
                try: fh.close()
                except Exception: pass
    print(f"\nstopped after {streams[0].breaths} breaths, {elapsed(time.time()-t0)}, "
          f"${client.cost():.4f}, errors {client.errors}")
    print(f"run dir {args.rundir}")


if __name__ == "__main__":
    main()
