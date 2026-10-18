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


def _rows(rundir):
    rows = []
    for line in open(os.path.join(rundir, "ticks.jsonl"), encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if "sleep" in d or "thought" not in d:
            continue
        rows.append(d)
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
    mtime = os.path.getmtime(os.path.join(rundir, "ticks.jsonl")) if rows else 0
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run": {
            "tag": stamp,
            "model": latest.get("model"),
            "creatures": creatures,
            "ticks": max((r["tick"] for r in rows), default=0),
            "ticks_total": len(rows),
            "started": rows[0]["ts"] if rows else None,
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
        "drives": {k: latest.get(k) for k in ("energy", "comfort", "stimulation")},
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
    dirs = [d for d in dirs if os.path.exists(os.path.join(d, "ticks.jsonl"))]
    return max(dirs, key=os.path.getmtime) if dirs else None


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else newest_run()
    if not d:
        raise SystemExit("no runs found")
    print(json.dumps(build(d), indent=1)[:2000])
