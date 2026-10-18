#!/usr/bin/env python3
"""Pull the creature's output from the isolated machine. Outbound only, by construction.

That box is firewalled FROM this one, verified: it cannot open a connection here on any port.
So the flow is one-directional as an enforced property rather than a convention. The Hermes
box reaches out over ssh and reads. The creature never pushes and never dials in.

The output is converted into the same shape the terminal already reads, one thought per turn,
so bored.kkaleb.com types it out without knowing where it came from.
"""
import json, os, subprocess, time

KEY = os.path.expanduser("~/.ssh/boredllm_ec2.pem")
HOST = "ubuntu@13.58.240.27"
OUT = os.path.expanduser("~/creature/runs/ultron-live")
os.makedirs(OUT, exist_ok=True)


def ssh(cmd, timeout=30):
    try:
        p = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                            "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", HOST, cmd],
                           capture_output=True, text=True, timeout=timeout)
        return p.stdout or ""
    except Exception:
        return ""


def build():
    md = ssh("tail -c 60000 /opt/creature/ultron.md 2>/dev/null")
    skills = [s for s in ssh("ls /opt/creature/skills 2>/dev/null").split() if s.endswith(".py")]
    outbound = ssh("tail -n 3 /opt/creature/outbound.log 2>/dev/null")
    rows = []
    rows.append({"breath": 0, "thought":
                 f"ultron, running on its own machine. root, no credentials, no route back here. "
                 f"tools it has written for itself: {len(skills)}"
                 + (f" ({', '.join(s[:-3] for s in skills)})" if skills else " (none yet)")})
    chunks = [c.strip() for c in md.split("### ") if c.strip()]
    for i, c in enumerate(chunks, 1):
        txt = " ".join(c.split())
        if txt:
            rows.append({"breath": i, "thought": txt[:1200]})
    if outbound.strip():
        rows.append({"breath": len(rows), "thought": "outbound: " + " ".join(outbound.split())[:400]})
    with open(os.path.join(OUT, "s0.stream.jsonl"), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    open(os.path.join(OUT, "heartbeat.json"), "w").write(
        json.dumps({"rows": len(rows), "skills": len(skills), "ts": time.time()}))


if __name__ == "__main__":
    while True:
        build()
        time.sleep(20)
