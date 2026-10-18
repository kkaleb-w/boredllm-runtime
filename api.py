"""DeepInfra client. The model identifier is pinned and logged on every tick.

Version drift is the biggest operational threat to a long run (doc 19, section 6):
providers silently update and retire models, so the exact ID goes in every record.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://api.deepinfra.com/v1/openai"
DEFAULT_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"

# prices in $ per million tokens, for the cost report only
PRICES = {
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": (0.02, 0.04),
    "Qwen/Qwen3.5-9B": (0.10, 0.15),
    "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": (0.40, 0.40),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.10, 0.32),
}

STOP = ["\n[", "[[", " [", "###"]


class Client:
    def __init__(self, model=None, key=None, timeout=120):
        self.model = model or os.environ.get("MODEL", DEFAULT_MODEL)
        self.key = key or self._load_key()
        self.timeout = timeout
        if not self.key:
            raise SystemExit("no DEEPINFRA_API_KEY")
        self.tok_in = 0
        self.tok_out = 0
        self.calls = 0
        self.errors = 0
        self.latency = 0.0

    @staticmethod
    def _load_key():
        k = os.environ.get("DEEPINFRA_API_KEY")
        if k:
            return k
        for p in (os.path.expanduser("~/.hermes/.env"), os.path.expanduser("~/.env")):
            if os.path.exists(p):
                for line in open(p):
                    if line.strip().startswith("DEEPINFRA_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        return None

    def _post(self, path, body):
        req = urllib.request.Request(
            BASE + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def generate(self, prompt, max_tokens=90, temperature=0.95, top_p=0.95, retries=3):
        """Raw completion. No chat template, no system prompt: nothing imperative."""
        body = {"model": self.model, "prompt": prompt, "max_tokens": max_tokens,
                "temperature": temperature, "top_p": top_p, "stop": STOP, "stream": False}
        last = None
        for attempt in range(retries):
            t0 = time.time()
            try:
                d = self._post("/completions", body)
                u = d.get("usage") or {}
                self.tok_in += u.get("prompt_tokens") or 0
                self.tok_out += u.get("completion_tokens") or 0
                self.calls += 1
                self.latency += time.time() - t0
                return (d["choices"][0].get("text") or "").strip(), u
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code in (400, 404, 422):      # completions not supported: fall back
                    try:
                        body2 = {"model": self.model,
                                 "messages": [{"role": "user", "content": prompt}],
                                 "max_tokens": max_tokens, "temperature": temperature,
                                 "stop": STOP, "stream": False}
                        d = self._post("/chat/completions", body2)
                        u = d.get("usage") or {}
                        self.tok_in += u.get("prompt_tokens") or 0
                        self.tok_out += u.get("completion_tokens") or 0
                        self.calls += 1
                        self.latency += time.time() - t0
                        return (d["choices"][0]["message"].get("content") or "").strip(), u
                    except Exception as e2:
                        last = f"{last} / {e2}"
            except Exception as e:
                last = str(e)
            time.sleep(1.5 * (attempt + 1))
        self.errors += 1
        return "", {"error": last}

    def cost(self):
        pin, pout = PRICES.get(self.model, (0.0, 0.0))
        return self.tok_in / 1e6 * pin + self.tok_out / 1e6 * pout
