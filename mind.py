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
    """Homeostatic variables. Nothing here is an instruction (doc 05)."""

    def __init__(self, seed=0):
        self.rng = random.Random(seed)
        self.energy = 0.72
        self.comfort = 0.68
        self.stimulation = 0.55        # the boredom variable

    def step(self, thought_chars=0):
        self.energy = max(0.02, self.energy - 0.010 - thought_chars / 40000.0)
        self.comfort = min(1.0, max(0.05, self.comfort + self.rng.uniform(-0.03, 0.03)))
        # a dull world erodes stimulation; producing a thought is itself mildly stimulating
        self.stimulation = max(0.02, self.stimulation - 0.020 + min(0.010, thought_chars / 8000.0))

    @property
    def bored(self):
        return self.stimulation < 0.25

    def say(self):
        p = []
        p.append("my body is heavy and slow" if self.energy < 0.4 else "my body is fine, not tired")
        p.append("the cold is in my hands" if self.comfort < 0.45
                 else "the room is a comfortable temperature")
        if self.stimulation < 0.15:
            p.append("there is nothing here that wants anything from me")
        elif self.stimulation < 0.35:
            p.append("I have run out of things to look at")
        return ". ".join(p) + "."

    def state(self):
        return {"energy": round(self.energy, 3), "comfort": round(self.comfort, 3),
                "stimulation": round(self.stimulation, 3), "bored": self.bored}


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
    lines = []
    if memory_hits:
        lines.append("something surfaces, and I do not know from where: "
                     + " ".join(memory_hits)[:240])
    lines.extend(t for t in prev_thoughts if t)
    lines.append(observation)
    joined = "\n".join(lines)
    return joined[-CAP_CHARS - 400:] if len(joined) > CAP_CHARS + 400 else joined


def sleeping(body, mem, recent_overlap, args):
    """Sleep fires on internal state, never on the clock (doc 07)."""
    if mem.pressure() >= args.sleep_mem:
        return "memory pressure"
    if recent_overlap >= args.sleep_rep:
        return "repetition"
    if body.energy < 0.08:
        return "exhaustion"
    return None
