"""Build a compact snapshot for the live view from a run directory.

The view is derived data only. It never writes back, so the observer cannot perturb
the creature (BoredLLM doc 18). One direction, enforced by architecture.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time

TARGET = 20.0        # the pre-registered target for internally directed ticks
HUMAN = 46.9         # Killingsworth & Gilbert, 2010


def mtime_of(rundir, rows=None):
    """Newest mtime among whatever files this run actually has."""
    best = 0.0
    for pat in ("ticks.jsonl", "*.stream.jsonl", "heartbeat.json"):
        for f in glob.glob(os.path.join(rundir, pat)):
            best = max(best, os.path.getmtime(f))
    return best


def _rows(rundir):
    """Read either loop shape: tick mode (ticks.jsonl) or stream mode (*.stream.jsonl).

    Both normalise to the same row keys so the view and the metrics do not care which
    runtime produced them.
    """
    rows = []
    tick = os.path.join(rundir, "ticks.jsonl")
    if os.path.exists(tick):
        for line in open(tick, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if "sleep" in d or "thought" not in d:
                continue
            rows.append(d)
        return rows
    # stream mode
    for path in sorted(glob.glob(os.path.join(rundir, "*.stream.jsonl"))):
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            # a pulled run may carry only a thought, with no text field
            if "text" not in d and "thought" not in d:
                continue
            d = dict(d)
            d["tick"] = d.get("breath")
            d["thought"] = d.get("text") or d.get("thought") or ""
            d["rep_overlap"] = d.get("rep", 0.0)
            d["n_invented_refs"] = d.get("invented", 0)
            rows.append(d)
    rows.sort(key=lambda r: (r.get("creature") or "", r.get("tick") or 0))
    return rows


def _pct(rows, pred):
    return round(100 * sum(1 for r in rows if pred(r)) / len(rows), 1) if rows else None


def bucket(rows, width=10):
    """Compress the series so the page stays cheap no matter how long the run is."""
    out = []
    by = {}
    for r in rows:
        by.setdefault((r["tick"] - 1) // width, []).append(r)
    for k in sorted(by):
        g = by[k]
        out.append({
            "t": (k + 1) * width,
            "rep": round(sum(x.get("rep_overlap") or 0 for x in g) / len(g), 3),
            "inv": _pct(g, lambda x: x.get("n_invented_refs")),
            "inhabit": _pct(g, lambda x: x.get("stance") == "inhabit"),
            "comment": _pct(g, lambda x: x.get("stance") == "comment"),
        })
    return out


def build(rundir, stream_n=30):
    rows = _rows(rundir)
    latest = rows[-1] if rows else {}
    creatures = sorted({r.get("creature") for r in rows if r.get("creature")})
    stamp = os.path.basename(rundir.rstrip("/"))
    mtime = mtime_of(rundir, rows)
    # the continuous stream, for the terminal view: total length plus a tail, so the
    # page can type out only what is new since it last looked
    # the terminal shows ONE mind, not an interleaving of several
    first = creatures[0] if creatures else None
    full = ""
    for r in rows:
        if first and r.get("creature") != first:
            continue
        t = (r.get("thought") or "").strip()
        if t:
            full += (" " if full else "") + t
    live = {"chars": len(full), "text": full[-6000:],
            "breaths": max((r.get("tick") or 0 for r in rows), default=0)}
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run": {
            "tag": stamp,
            "model": latest.get("model"),
            "creatures": creatures,
            "ticks": max((r["tick"] for r in rows), default=0),
            "ticks_total": len(rows),
            "started": (rows[0].get("ts") if rows else None),
            "last_ts": latest.get("ts"),
        },
        "headline": {
            "target_pct": TARGET,
            "human_pct": HUMAN,
            "repetition": round(sum((r.get("rep_overlap") or 0) for r in rows[1:]) / max(1, len(rows) - 1), 3),
            "invention_pct": _pct(rows, lambda r: r.get("n_invented_refs")),
            "inhabit_pct": _pct(rows, lambda r: r.get("stance") == "inhabit"),
            "comment_pct": _pct(rows, lambda r: r.get("stance") == "comment"),
            "empty_pct": _pct(rows, lambda r: not (r.get("thought") or "").strip()),
            "drift_pct": None,
            "drift_note": "no external actions wired yet: every tick is internal by construction",
        },
        "stats": (json.load(open(os.path.join(rundir, "stats.json")))
                  if os.path.exists(os.path.join(rundir, "stats.json")) else None),
        "drives": {k: latest.get(k) for k in ("energy", "comfort", "stimulation")},
        "live": live,
        "series": bucket(rows),
        "stream": [{k: r.get(k) for k in
                    ("tick", "creature", "ts", "stimulation", "stance", "rep_overlap",
                     "n_invented_refs", "thought")}
                   for r in rows[-stream_n:]][::-1],
        "health": {
            "last_tick_age_s": round(time.time() - mtime, 1) if mtime else None,
            "records": len(rows),
        },
    }


def newest_run(root=None):
    root = root or os.path.expanduser("~/creature/runs")
    dirs = [d for d in glob.glob(os.path.join(root, "*")) if os.path.isdir(d)]
    dirs = [d for d in dirs
            if os.path.exists(os.path.join(d, "ticks.jsonl"))
            or glob.glob(os.path.join(d, "*.stream.jsonl"))]
    return max(dirs, key=os.path.getmtime) if dirs else None


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else newest_run()
    if not d:
        raise SystemExit("no runs found")
    print(json.dumps(build(d), indent=1)[:2000])
