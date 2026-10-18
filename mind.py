"""Drives, memory, sleep, and prompt composition.

Implements BoredLLM docs 02 (boredom as a drive), 07 (sleep), 08 (memory), 18 (self-view).

The self-view is deliberately level 0 or 1 only: the last thought, and a bounded
window. The full log never enters context (HANDOFF non-negotiable 9).
"""
from __future__ import annotations

import math
import os
import random
import re
import sqlite3
import time

WINDOW = int(os.environ.get("SELF_WINDOW", "1"))       # how many past thoughts
CAP_CHARS = int(os.environ.get("SELF_CAP", "600"))     # hard cap on the self-view


class Body:
    """Homeostatic variables. Nothing here is an instruction (doc 05).

    v2, after review. v1 decayed on a metronome: energy fell by a constant per
    tick no matter what happened, comfort wobbled randomly, and the boredom
    variable was computed and then used for nothing. It was a clock, not a
    metabolism, and its only report was one of four fixed phrases, so the creature
    could not feel a gradient.

    Now:
    - energy falls with time awake and faster when thinking a lot
    - comfort is pulled by the time of day, so night is cold
    - **stimulation is coupled to what the creature actually does.** Novel thought
      relieves boredom; repeating itself deepens it. That is the causal loop the
      design always claimed, and it was missing.
    - interoception is graded, so the body reports a value rather than a mood
    """

    def __init__(self, seed=0):
        self.rng = random.Random(seed)
        self.energy = 0.72
        self.comfort = 0.68
        self.stimulation = 0.55
        self.awake_minutes = 0.0
        self.deficits_met = 0

    @staticmethod
    def _clamp(v, lo=0.02, hi=1.0):
        return max(lo, min(hi, v))

    def step(self, dt_minutes=10.0, thought="", novelty=0.5, hour=12):
        self.awake_minutes += dt_minutes
        # energy: time awake, plus a small extra cost for producing a lot of thought
        self.energy = self._clamp(self.energy
                                  - 0.0085 * (dt_minutes / 10.0)
                                  - min(0.004, len(thought) / 30000.0))
        # comfort: the room is comfortable, the night is not. pulled toward a
        # target set by the real hour rather than random-walked.
        target = 0.55 if (hour < 6 or hour >= 21) else 0.72
        self.comfort = self._clamp(self.comfort + 0.06 * (target - self.comfort)
                                   + self.rng.uniform(-0.012, 0.012))
        # stimulation: the room gives nothing, so it falls. Novel thought is the
        # only thing that pays it back, and repeating yourself costs extra.
        base = -0.016 * (dt_minutes / 10.0)
        reward = 0.030 * (novelty - 0.5)
        self.stimulation = self._clamp(self.stimulation + base + reward)

    # -------------------------------------------------------- interoception

    @property
    def bored(self):
        return self.stimulation < 0.28

    @property
    def tired(self):
        return self.energy < 0.35

    def say(self):
        """Graded, first person, flat. A value, not a mood."""
        b = []
        e = self.energy
        b.append("I am very tired" if e < 0.25 else
                 "I am tired" if e < 0.45 else
                 "I am a little tired" if e < 0.62 else "I am not tired")
        c = self.comfort
        b.append("the cold is in my hands" if c < 0.4 else
                 "there is a chill in the room" if c < 0.55 else
                 "I am neither warm nor cold" if c < 0.75 else "the room is warm")
        s = self.stimulation
        b.append("there is nothing here that wants anything from me" if s < 0.15 else
                 "I have run out of things to look at" if s < 0.3 else
                 "I have looked at all of this before" if s < 0.45 else
                 "something in the room still holds me" if s < 0.65 else
                 "the room still has my attention")
        return ". ".join(b) + "."

    def state(self):
        return {"energy": round(self.energy, 3), "comfort": round(self.comfort, 3),
                "stimulation": round(self.stimulation, 3),
                "awake_minutes": round(self.awake_minutes, 1),
                "bored": self.bored, "tired": self.tired}


WORDS = re.compile(r"[a-z']+")


def _grams(t):
    w = WORDS.findall(t.lower())
    return set(zip(w, w[1:]))


def overlap(a, b):
    if not a or not b:
        return 0.0
    A, B = _grams(a), _grams(b)
    return len(A & B) / max(1, len(A | B))


class Memory:
    """Small, and only the properties that are actually load bearing (doc 08)."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS mem(
            id INTEGER PRIMARY KEY, tick INTEGER, ts REAL, text TEXT,
            salience REAL, strength REAL, kind TEXT, hits INTEGER DEFAULT 0)""")
        self.db.commit()

    def retain(self, tick, text, salience=None, kind="episodic"):
        if not text.strip():
            return None
        s = salience if salience is not None else self._salience(text)
        if s < 0.18:                       # attention gate: the dull majority is dropped
            return None
        cur = self.db.execute(
            "INSERT INTO mem(tick,ts,text,salience,strength,kind) VALUES(?,?,?,?,?,?)",
            (tick, time.time(), text, s, 1.0, kind))
        self.db.commit()
        return cur.lastrowid

    @staticmethod
    def _salience(text):
        t = text.lower()
        s = 0.25
        if re.search(r"\b(i (feel|hear|notice|realise|realize|remember|want|wonder))\b", t):
            s += 0.25
        if len(text) > 120:
            s += 0.10
        if re.search(r"\b(cup|table|door|window|cold|light)\b", t):
            s += 0.15
        if re.search(r"^(i|my)\b", t.strip()):
            s += 0.15
        return min(1.0, s)

    def decay(self, factor=0.97):
        self.db.execute("UPDATE mem SET strength = strength * ?", (factor,))
        self.db.execute("DELETE FROM mem WHERE strength < 0.05")
        self.db.commit()

    def recall(self, cue, limit=3, exclude_last=True):
        rows = self.db.execute(
            "SELECT id,tick,text,strength FROM mem ORDER BY strength DESC, tick DESC LIMIT 200"
        ).fetchall()
        scored = []
        for mid, tick, text, strength in rows:
            ov = overlap(cue, text) if cue else 0.0
            scored.append((ov * 0.6 + strength * 0.4, mid, text))
        scored.sort(reverse=True)
        picked = scored[:limit]
        for _, mid, _ in picked:            # retrieval strengthens
            self.db.execute("UPDATE mem SET hits = hits + 1, strength = MIN(1.5, strength + 0.06) WHERE id=?", (mid,))
        self.db.commit()
        return [t for _, _, t in picked]

    def pressure(self):
        return self.db.execute("SELECT COUNT(*) FROM mem").fetchone()[0]

    def consolidate(self):
        """The sleep pass. Merges near-duplicates, decays, prunes (doc 07)."""
        rows = self.db.execute("SELECT id,text FROM mem ORDER BY tick").fetchall()
        seen, merged = [], 0
        for mid, text in rows:
            if any(overlap(text, s) > 0.6 for s in seen):
                self.db.execute("DELETE FROM mem WHERE id=?", (mid,))
                merged += 1
            else:
                seen.append(text)
        before = self.pressure()
        self.decay(0.90)
        after = self.pressure()
        self.db.commit()
        return {"merged": merged, "before": before, "after": after}


def compose(prev_thoughts, observation, memory_hits=None):
    """The creature's input. A STATE, never an instruction (doc 05 commitment 1).

    Shape: previous thoughts, then the current observation, and the model continues.
    Three measured constraints, each from a run that failed without it:

    - **Thoughts only, no prior observations.** Repeating the world's own observation
      lines into the stream is a self-similarity attractor: repetition goes from
      about 0.01 to about 0.32 when prior observations are included.
    - **No labelled history** (`just now: ...`). A label is structural, so the model
      continues the *label* and starts answering it, which seeds a quiz template.
    - Level 0/1 self-view only, hard capped. Never the full log (HANDOFF rule 9).
    """
    mem_line = ""
    if memory_hits:
        mem_line = ("something surfaces, and I do not know from where: "
                    + " ".join(memory_hits)[:240])
    hist = [t for t in prev_thoughts if t]
    # Budget the parts explicitly. Clipping the tail of the whole thing silently
    # deleted the memory line, because it is assembled first and the observation
    # alone can be 400 characters. The self-view is what gets shortened, never the
    # recall and never the observation.
    budget = max(160, CAP_CHARS - len(mem_line) - len(observation) - 40)
    hist_txt = "\n".join(hist)[-budget:] if hist else ""
    parts = [p for p in (mem_line, hist_txt, observation) if p]
    return "\n".join(parts)


def sleeping(body, mem, recent_overlap, args):
    """Sleep fires on internal state, never on the clock (doc 07)."""
    if mem.pressure() >= args.sleep_mem:
        return "memory pressure"
    if recent_overlap >= args.sleep_rep:
        return "repetition"
    if body.energy < 0.08:
        return "exhaustion"
    return None
