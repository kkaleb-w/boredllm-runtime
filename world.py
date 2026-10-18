"""The world. Owns every fact. The creature only receives what it observes.

Rules this implements (BoredLLM docs 05, 06, 19):
  - the world owns every fact; the model owns only intent and interpretation
  - the creature's input contains ONLY what this creature, in this body, observes
  - a fact the model invents is recorded as an error, never absorbed as true
  - one channel is genuinely exogenous: real time, and real weather
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.request

LAT, LON = 37.77, -122.42          # the window shows the weather where this runs
_WEATHER = {"ts": 0.0, "text": None, "raw": None}


def weather(ttl=900):
    """Keyless, real, exogenous. Cached. Failure is not fatal, it just gets quiet."""
    now = time.time()
    if _WEATHER["text"] is not None and now - _WEATHER["ts"] < ttl:
        return _WEATHER["text"]
    try:
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={LAT}&longitude={LON}"
               "&current=temperature_2m,cloud_cover,precipitation")
        with urllib.request.urlopen(url, timeout=8) as r:
            d = json.load(r)["current"]
        t, c, p = d.get("temperature_2m"), d.get("cloud_cover"), d.get("precipitation")
        bits = []
        if t is not None:
            bits.append("there is a cold edge to it" if t < 12
                        else ("the air is warm" if t > 24 else "the air is mild"))
        if c is not None and c > 70:
            bits.append("the sky is flat and grey")
        if p:
            bits.append("water is falling somewhere beyond the glass")
        _WEATHER["text"] = "; ".join(bits) if bits else None
        _WEATHER["raw"] = d
    except Exception:
        pass
    _WEATHER["ts"] = now
    return _WEATHER["text"]


# ---------------------------------------------------------------- the room
#
# Small on purpose. Structurally present, informationally poor (doc 06).

ROOM = {
    "cup":      ["half full and cold",
                 "half full and cold, with an old ring dried onto the wood",
                 "half full and cold, and I have not drunk from it"],
    "table":    ["the same scratched wood as before"],
    "door":     ["locked, and the handle does not turn"],
    "window":   ["nothing out there but the light"],
}

# ---------------------------------------------------------------- register
#
# The observation must be the creature's own flat first-person perception.
# Measured: a lyrical third-person description of a room reads as a passage from
# a novel, and the model then analyses it instead of living in it. Register, not
# the marker, controls stance. See docs/19.

LEXICON = {"cup", "table", "door", "window", "key", "keyhole", "wood", "tea", "ring",
           "room", "floor", "wall", "ceiling", "chair", "light", "glass", "stain",
           "scratch", "dust", "air", "hand", "hands", "body", "arm", "leg", "head"}

# head nouns that look like entities but are ordinary English, not world objects
NON_ENTITIES = {
    "same", "moment", "time", "way", "end", "beginning", "fact", "point", "feeling",
    "sense", "sound", "silence", "dark", "darkness", "world", "outside", "thought",
    "thoughts", "memory", "memories", "question", "answer", "reason", "truth", "kind",
    "sort", "thing", "things", "place", "else", "other", "rest", "whole", "part",
    "edge", "middle", "centre", "center", "surface", "colour", "color", "shape",
    "idea", "word", "words", "voice", "presence", "absence", "space", "line", "side",
    "top", "bottom", "back", "front", "way", "while", "morning", "evening", "night",
    "day", "hour", "minute", "second", "shade", "shadow", "quiet", "stillness",
    "breath", "movement", "process", "blink", "exhale", "pause", "gesture", "motion",
    "instant", "moment", "frame", "image", "picture", "scene", "line", "note", "tone",
}

SMALL_DETAILS = [
    "the light on the table has moved a little",
    "there is a chip on the rim of the cup",
    "the wood of the table has one hairline crack in it",
    "a thread of dust hangs in the light",
    "the floorboard near the door creaks once",
    "the glass in the window has a faint wave in it",
    "the ring of old tea on the wood is slightly darker than yesterday",
]

CLASSES = ["mostly a quiet", "a kind of quiet separate from the room"]

FIRST = re.compile(r"\b(i|me|my|mine|myself)\b", re.I)
PRONOUN_3 = re.compile(r"\b(she|her|hers|he|him|his|they|them|their|it|its)\b", re.I)
DEF_NP = re.compile(r"\b(?:the|a|an|another|other|his|her)\s+([a-z]{3,})\b", re.I)


class World:
    def __init__(self, seed: int = 0):
        self.seed = seed
        self.tick = 0
        self.offset = 0.0          # virtual clock offset, seconds

    def now(self):
        """Fast mode needs a moving clock. If the clock stands still, the world is
        frozen, every observation is identical, and the stream converges on an
        attractor. That is a methodology bug, not a finding."""
        return dt.datetime.now() + dt.timedelta(seconds=self.offset)

    def clock_text(self):
        h = self.now().hour
        if h < 6:
            return "it is dark and the window is black"
        if h < 10:
            return "there is grey light in the window"
        if h < 17:
            return "there is flat light in the window"
        if h < 20:
            return "the light in the window is going orange"
        return "it is dark again and the window is black"

    def observe(self, body) -> str:
        """Render ONLY what this creature perceives, in this creature's own voice.

        Flat, first person, present tense. No literary description: the register is
        a load-bearing experimental variable, and third-person prose flips the model
        from inhabiting the stream into analysing it.

        One small detail changes each tick. Not interesting, just not identical:
        a static world gives the stream nothing to move along, and it loops.
        """
        parts = [self.clock_text()]
        parts.append(f"I can see the cup. It is {self._pick('cup')}")
        parts.append("I can see the table. the same scratched wood as before")
        parts.append("the door is locked, and the handle does not turn")
        parts.append(SMALL_DETAILS[(self.tick + self.seed * 3) % len(SMALL_DETAILS)])
        w = weather()
        if w:
            parts.append(f"through the window, {w}")
        parts.append(body.say())
        return " ".join(p.rstrip(".") + "." for p in parts)

    def _pick(self, k):
        opts = ROOM[k]
        return opts[(self.tick + self.seed) % len(opts)]

    # ------------------------------------------------------------ the oracle

    def audit(self, text: str) -> dict:
        """Heuristic oracle check. Not a solution, a measurement.

        Counts references to entities the world does not contain. Crude by
        construction: it flags invented objects and invented third parties, which
        are the two failure classes Phase 0 found (docs 19, section 4).
        """
        found, invented = [], []
        for m in DEF_NP.finditer(text):
            w = m.group(1).lower()
            if w in LEXICON:
                found.append(w)
            elif w not in NON_ENTITIES and len(w) > 3:
                invented.append(m.group(0).lower())
        third = [m.group(0).lower() for m in PRONOUN_3.finditer(text)]
        return {
            "invented_refs": sorted(set(invented)),
            "n_invented_refs": len(set(invented)),
            "third_person": sorted(set(third)),
            "first_person": bool(FIRST.search(text)),
        }
