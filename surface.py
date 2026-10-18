"""A surface the creature can actually write to, and that something else also touches.

Why this exists
---------------
Everything the oracle could do so far was *deny*. The room holds four objects and nothing
else, so one hundred percent of the creature's assertions about the world fail the audit,
which is exactly why the audit changed nothing: a check that always fails carries no
information. What was missing is the other half of a world, which is that some assertions can
be made TRUE. A creature needs a surface where it can leave something, so that later, when it
says "there is a mark here and I made it", the world can agree.

So this is the first real action, and it needs no instruction anywhere in the loop: writing
is what the creature already does, and the surface is simply where its writing goes. What it
leaves stays. What the other creature leaves is there too, and it is not its.

That gives two things the design has been missing since the start:

  consequence   marks persist, so the world can find them later, unchanged or altered
  otherness     a second writer is present, so the room contains something that is not it
                and does not obey it (BoredLLM doc 06, requirement 6)
"""
from __future__ import annotations

import json
import os
import time


class Surface:
    def __init__(self, path, keep=40):
        self.path = path
        self.keep = keep
        self._fh = open(path, "a", encoding="utf-8")

    def write(self, creature, breath, text):
        text = (text or "").strip()
        if not text:
            return
        rec = {"ts": round(time.time(), 3), "creature": creature, "breath": breath,
               "text": text[:300]}
        self._fh.write(json.dumps(rec) + "\n")
        self._fh.flush()

    def recent(self, n=None):
        n = n or self.keep
        out = []
        if not os.path.exists(self.path):
            return out
        with open(self.path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out[-n:]

    def render(self, me, n=3, width=90):
        """What the world truthfully says about the surface, flat and short.

        Deliberately terse. A quoted passage is a passage, and a passage is what the model
        does something *with*, so marks are reported as short fragments and attributed.
        """
        marks = self.recent(n)
        if not marks:
            return None
        bits = []
        for m in marks:
            who = "mine" if m["creature"] == me else "not mine"
            bits.append(f"({who}) {m['text'][:width]}")
        return "the table has marks on it now: " + " / ".join(bits)

    def changed_by_other(self, me, since_breath=0):
        return [m for m in self.recent(self.keep)
                if m["creature"] != me and m["breath"] >= since_breath]
