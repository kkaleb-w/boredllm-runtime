#!/usr/bin/env python3
"""Pull the creature's output from the isolated machine. Outbound only, by construction.

That box is firewalled FROM this one, verified: it cannot open a connection here on any port.
The Hermes box reaches out over ssh and reads, so the link is one-directional as an enforced
property rather than a convention.

Reads the structured log, not the human transcript. The transcript version broke twice: the
file outgrew the tail window I was reading, and the section separator changed. The jsonl has
fixed fields and cannot drift.
"""
import json, os, subprocess, time

KEY = os.path.expanduser("~/.ssh/boredllm_ec2.pem")
HOST = "ubuntu@13.58.240.27"
OUT = os.path.expanduser("~/creature/runs/ultron-live")
os.makedirs(OUT, exist_ok=True)


def ssh(cmd, timeout=40):
    try:
        p = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                            "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", HOST, cmd],
                           capture_output=True, text=True, timeout=timeout)
        return p.stdout or ""
    except Exception:
        return ""


def build(turns=40):
    raw = ssh("tail -n %d /opt/creature/ultron.jsonl 2>/dev/null" % turns)
    skills = [s for s in ssh("ls /opt/creature/bin 2>/dev/null").split()]
    model = ssh("systemctl show ultron -p Environment --value 2>/dev/null | tr ' ' '\\n' | grep ULTRON_MODEL").strip()
    spend = ssh("sudo -n cat /var/lib/ultron/proxy_state.json 2>/dev/null").strip()
    rows = [{"breath": 0, "thought":
             f"brain: {model.split('=')[-1] or '?'}    tools: {len(skills)}    {spend}"}]
    n = 1
    for line in raw.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = " ".join(str(d.get("thought") or "").split())
        if t:
            rows.append({"breath": n, "thought": t[:900]}); n += 1
        cmd = " ".join(str(d.get("cmd") or "").split())
        if cmd:
            rows.append({"breath": n, "thought": "  running  " + cmd[:300]}); n += 1
        res = " ".join(str(d.get("result") or "").split())
        if res:
            rows.append({"breath": n, "thought": "  got  " + res[:300]}); n += 1
        if d.get("skills"):
            rows.append({"breath": n, "thought": f"  tools now: {len(d['skills'])}"}); n += 1
    with open(os.path.join(OUT, "s0.stream.jsonl"), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    # what the little button on the page reads from
    stats = {"model": (model.split("=")[-1] or "?"), "tools": skills,
             "turns": None, "tokens": None, "calls": None}
    try:
        stats["turns"] = int(ssh("grep -c . /opt/creature/ultron.jsonl 2>/dev/null").strip() or 0)
    except Exception:
        pass
    try:
        sp = json.loads(spend) if spend.strip().startswith("{") else {}
        stats["tokens"] = sp.get("tokens")
        stats["calls"] = sp.get("calls")
    except Exception:
        pass
    open(os.path.join(OUT, "stats.json"), "w").write(json.dumps(stats))
    open(os.path.join(OUT, "heartbeat.json"), "w").write(
        json.dumps({"rows": len(rows), "tools": len(skills), "ts": time.time()}))


if __name__ == "__main__":
    while True:
        build()
        time.sleep(5)
