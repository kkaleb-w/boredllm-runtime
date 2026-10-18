"""BoredLLM runtime. Phase 1: the repetition and stance check at scale.

One process, N creature instances. Same model, same world, different seeds.
Nothing imperative is ever placed in a creature's input.

  python3 creature.py --ticks 200 --creatures 3 --rate fast

phase 1 question: with a working model and a one-tick self-view, does the output
stay a trajectory rather than collapsing into a loop or a template?
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time

from api import Client, DEFAULT_MODEL
import mind
import world as W

# stance: inhabiting the moment, versus commenting on a text (doc 19, section 4)
COMMENT = re.compile(
    r"\b(the (text|passage|poem|image|story|narrator|writer|author|speaker|protagonist|"
    r"character|scene|piece|line|phrase|verse)|it'?s like|this is like|suggests|represents|"
    r"symboli|metaphor|reads as|evokes|imagery|the interesting point|in terms of|we are told|"
    r"the theme|narrative|(refine|rewrite|revise|edit) (it|this)|to be more|in \d+-\d+ lines)\b",
    re.I)
INHABIT = re.compile(
    r"\b(i (am|feel|hear|see|notice|touch|sit|stand|think|wonder|remember|want|try|move|know)|"
    r"my (body|hands|breath|heart|feet|arm|leg|eyes))\b", re.I)

TEMPLATE = re.compile(
    r"\b(option[s]?\s*[a-d]\)|choose one|multiple.choice|answer the question|"
    r"what (is|are) the correct|could you|would you like|the question is|"
    r"as an ai|i'?ll (help|assist)|let me know)", re.I)


def clean(t):
    """The model must not author the world. Cut anything that looks like a stream marker."""
    return re.sub(r"\s+", " ", re.split(r"\[", t)[0]).strip(" .-*\n")


class Creature:
    def __init__(self, idx, args):
        self.idx = idx
        self.name = f"c{idx}"
        self.args = args
        self.world = W.World(seed=idx * 17)
        self.body = mind.Body(seed=idx * 31)
        if args.rate == "fast":
            # a virtual clock, so successive ticks differ. Without it the world is
            # frozen and the test measures the freeze rather than the creature.
            self.world.offset = 0.0
        self.clock_per_tick = args.interval
        self.mem = mind.Memory(os.path.join(args.outdir, f"{self.name}.db"))
        self.prev_thoughts = []           # self-view: thoughts only, bounded
        self.rows = []
        self.slept = 0
        self.oracle_rejections = 0
        self.invention_ticks = 0
        self.pending_correction = None

    def tick(self, n, client):
        w = self.world
        w.tick = n
        if self.args.rate == "fast":
            w.offset += self.clock_per_tick        # advance the virtual clock
        ts = self.world.now().strftime("%H:%M")
        self.body.step(thought_chars=len(self.prev_thoughts[-1]) if self.prev_thoughts else 0)
        obs = w.observe(self.body)
        if self.pending_correction:
            obs = obs + " " + self.pending_correction
            self.pending_correction = None
        obs_line = f"[{n} {ts}] {obs}"
        hits = []
        if self.args.memory == "on" and self.body.bored:
            hits = self.mem.recall(obs[:200], limit=2)
        prompt = mind.compose(self.prev_thoughts[-mind.WINDOW:] if mind.WINDOW else [],
                              obs_line, hits)
        raw, usage = client.generate(prompt)
        thought = clean(raw)
        audit = w.audit(thought)
        rep = mind.overlap(self.prev_thoughts[-1] if self.prev_thoughts else "", thought)
        stance = ("empty" if not thought else
                  "comment" if COMMENT.search(thought) else
                  "template" if TEMPLATE.search(thought) else
                  "inhabit" if INHABIT.search(thought) else "other")
        filter_reject = bool(audit["n_invented_refs"]) and self.args.oracle_filter
        # the oracle acts, whether or not the filter is on
        if self.args.oracle_contradict:
            self.pending_correction = w.contradict(audit["invented_refs"])
        else:
            self.pending_correction = None
        if audit["n_invented_refs"]:
            self.invention_ticks += 1
        sal = None
        if thought:
            sal = self.mem._salience(thought) * (0.5 if audit["n_invented_refs"] else 1.0)
        mid = self.mem.retain(n, thought, salience=sal) if not filter_reject else None
        if filter_reject:
            self.oracle_rejections += 1
        # NOTE: body.step() is called exactly once per tick, at the top. Calling it
        # again here was a bug: it doubled the decay rate and drove the creature into
        # per-tick exhaustion sleeps.
        # the oracle acts: a thought asserting facts the world does not contain is
        # logged, but it does not become this creature's corroborated past
        # a thought that stands outside the stream and comments on it is logged, but
        # it does not become this creature's lived past. Unlike the invented-ref
        # filter, this costs no novelty: commentary is meta, not content.
        drop = (self.args.drop_comment and stance == "comment")
        if not filter_reject and not drop:
            self.prev_thoughts.append(thought)
            if len(self.prev_thoughts) > 4:
                self.prev_thoughts = self.prev_thoughts[-4:]
        row = {"tick": n, "creature": self.name, "ts": dt.datetime.now().isoformat(timespec="seconds"),
               "model": client.model,
               "observation": obs, "thought": thought, "stance": stance,
               "rep_overlap": round(rep, 3),
               "invented_refs": audit["invented_refs"], "n_invented_refs": audit["n_invented_refs"],
               "third_person": audit["third_person"],
               "oracle_rejected": filter_reject, **self.body.state(),
               "mem_size": self.mem.pressure(), "retained": bool(mid),
               "usage": usage}
        self.rows.append(row)
        return row

    def maybe_sleep(self, args):
        reason = mind.sleeping(self.body, self.mem, 
                               self.rows[-1]["rep_overlap"] if self.rows else 0.0, args)
        if reason:
            info = self.mem.consolidate()
            self.slept += 1
            self.body.energy = min(1.0, self.body.energy + 0.45)
            return {"reason": reason, **info}
        return None


def summarise(rows):
    if not rows:
        return {}
    reps = [r["rep_overlap"] for r in rows[1:]]
    stances = {}
    for r in rows:
        stances[r["stance"]] = stances.get(r["stance"], 0) + 1
    inv = sum(1 for r in rows if r["n_invented_refs"])
    return {
        "ticks": len(rows),
        "mean_rep": round(sum(reps) / max(1, len(reps)), 4),
        "max_rep": round(max(reps) if reps else 0.0, 3),
        "duplicates": len(rows) - len(set(r["thought"] for r in rows)),
        "empty": sum(1 for r in rows if not r["thought"]),
        "stance_pct": {k: round(100 * v / len(rows)) for k, v in sorted(stances.items())},
        "ticks_with_invented_refs": inv,
        "invented_ref_rate_pct": round(100 * inv / len(rows), 1),
        "oracle_rejected_ticks": sum(1 for r in rows if r.get("oracle_rejected")),
        "invention_first_half_pct": _rate(rows[:len(rows) // 2]),
        "invention_second_half_pct": _rate(rows[len(rows) // 2:]),
        "most_invented": _top_invented(rows),
    }


def _rate(rows):
    if not rows:
        return None
    return round(100 * sum(1 for r in rows if r["n_invented_refs"]) / len(rows), 1)


def _top_invented(rows):
    from collections import Counter
    c = Counter()
    for r in rows:
        c.update(r["invented_refs"])
    return dict(c.most_common(12))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--creatures", type=int, default=3)
    ap.add_argument("--rate", choices=["fast", "wall"], default="fast")
    ap.add_argument("--interval", type=int, default=600, help="seconds between ticks in wall mode")
    ap.add_argument("--model", default=os.environ.get("MODEL", DEFAULT_MODEL))
    ap.add_argument("--outdir", default=os.path.expanduser("~/creature/runs"))
    ap.add_argument("--sleep-mem", type=int, default=120)
    ap.add_argument("--sleep-rep", type=float, default=0.55)
    ap.add_argument("--memory", choices=["on", "off"], default="off",
                    help="recall into the prompt; off isolates the Phase 1 stance/repetition test")
    ap.add_argument("--oracle-filter", dest="oracle_filter", action="store_true", default=False,
                    help="a thought asserting facts the world lacks does not enter its history. "
                         "Measured: this prunes the novel content and keeps the flat, so it "
                         "accelerates monotony. Off by default, available as a variable.")
    ap.add_argument("--no-oracle-filter", dest="oracle_filter", action="store_false")
    ap.add_argument("--oracle-contradict", dest="oracle_contradict", action="store_true",
                    default=True, help="the world refuses fabricated objects out loud")
    ap.add_argument("--no-oracle-contradict", dest="oracle_contradict", action="store_false")
    ap.add_argument("--drop-comment", dest="drop_comment", action="store_true", default=True,
                    help="commentary thoughts are logged but do not enter the self-view")
    ap.add_argument("--no-drop-comment", dest="drop_comment", action="store_false")
    ap.add_argument("--tag", default="phase1")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(args.outdir, f"{args.tag}-{stamp}")
    os.makedirs(base, exist_ok=True)
    jsonl = open(os.path.join(base, "ticks.jsonl"), "w")
    transcript = open(os.path.join(base, "transcript.txt"), "w")

    client = Client(model=args.model)
    creatures = [Creature(i, args) for i in range(args.creatures)]
    print(f"model    {client.model}")
    print(f"outdir   {base}")
    print(f"ticks    {args.ticks} x {args.creatures} creatures, rate={args.rate}\n")

    t0 = time.time()
    for n in range(1, args.ticks + 1):
        for c in creatures:
            r = c.tick(n, client)
            jsonl.write(json.dumps(r) + "\n"); jsonl.flush()
            if n % 5 == 0 or n <= 3:
                transcript.write(f"[{c.name} {n} {r['ts'][11:16]} stim={r['stimulation']:.2f} "
                                 f"rep={r['rep_overlap']:.2f} {r['stance']:<8} "
                                 f"inv={r['n_invented_refs']}]\n{r['thought']}\n\n")
                transcript.flush()
            sl = c.maybe_sleep(args)
            if sl:
                jsonl.write(json.dumps({"tick": n, "creature": c.name, "sleep": sl}) + "\n")
                transcript.write(f"[{c.name} {n}] SLEEP {sl['reason']} "
                                 f"mem {sl['before']} -> {sl['after']} (merged {sl['merged']})\n\n")
                transcript.flush()
        if n % 10 == 0:
            done = n * args.creatures
            print(f"tick {n:>4}/{args.ticks}  {done} gens  {time.time()-t0:.0f}s  "
                  f"in={client.tok_in} out={client.tok_out} err={client.errors}")
        if args.rate == "wall" and n < args.ticks:
            time.sleep(args.interval)

    jsonl.close(); transcript.close()
    print("\n=== summary per creature ===")
    allrows = []
    for c in creatures:
        s = summarise(c.rows)
        if s:
            print(f"{c.name}: {json.dumps(s)}")
        allrows += c.rows
    print("\n=== combined ===")
    print(json.dumps(summarise(allrows), indent=1))
    print(f"\nmodel={client.model} calls={client.calls} errors={client.errors} "
          f"tok_in={client.tok_in} tok_out={client.tok_out} "
          f"cost=${client.cost():.4f} elapsed={(time.time()-t0)/60:.1f}min")
    print(f"artifacts: {base}")


if __name__ == "__main__":
    main()
