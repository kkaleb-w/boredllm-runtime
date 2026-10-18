"""A window onto the real web. Read-only, capped, and safe by construction.

Why the real web is legitimate here
------------------------------------
The dossier's objection to the web was about it being the creature's *permanent* world:
unbounded, clockless, consequenceless, and made of the model's own training distribution.
As a condition for one day it is the opposite of a compromise: it is text that nobody in
this system wrote, which is exactly the exogeneity requirement, and it is the contrast arm
the switching-versus-drift hypothesis needs (BoredLLM doc 14).

What it can and cannot do
-------------------------
The creature can LOOK. It cannot write, post, click, authenticate, or change anything. There
is no write path anywhere in this module. A page it reads can therefore influence its stream
and its token spend, and nothing else. That is a real injection surface and it is bounded on
purpose.

What it must not do
-------------------
Return a wall of prose. Web text is still prose, and prose is what the model analyses. Items
are compressed hard and rendered flat and short, in the creature's own register.
"""
from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import time
import urllib.parse
import urllib.request

UA = "BoredLLM/0.1 (read-only research harness; contact: kkaleb-w)"
MAX_BYTES = 300_000
CACHE = {}


def _safe(url):
    """Only http(s), only public hosts. No file:, no loopback, no link-local."""
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = p.hostname
    if not host or "." not in host:
        return False
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except Exception:
        return False
    return True


def _plain(raw, limit):
    raw = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    txt = html.unescape(raw)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:limit]


def fetch(url, limit=400, ttl=1800):
    """Return (title, text) for a URL, or (None, None). Cached, capped, public hosts only."""
    key = (url, limit)
    if key in CACHE and time.time() - CACHE[key][0] < ttl:
        return CACHE[key][1], CACHE[key][2]
    if not _safe(url):
        return None, None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5"})
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read(MAX_BYTES).decode("utf-8", "replace")
    except Exception:
        return None, None
    title = None
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if m:
        title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()[:120]
    body = _plain(raw, limit)
    CACHE[key] = (time.time(), title, body)
    return title, body


# ---------------------------------------------------------------- keyless sources

def random_page(limit=320):
    """A real encyclopaedia article, picked at random. Nobody here wrote it."""
    try:
        req = urllib.request.Request(
            "https://en.wikipedia.org/api/rest_v1/page/random/summary",
            headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.load(r)
        t = (d.get("title") or "").strip()
        e = re.sub(r"\s+", " ", (d.get("extract") or "")).strip()
        if t and e:
            return t, e[:limit]
    except Exception:
        pass
    return None, None


def headline(limit=110):
    """A real headline from a real front page. Short on purpose: less to analyse."""
    try:
        req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            ids = json.load(r)[:12]
        for i in ids:
            try:
                req2 = urllib.request.Request(
                    f"https://hacker-news.firebaseio.com/v0/item/{i}.json",
                    headers={"User-Agent": UA})
                with urllib.request.urlopen(req2, timeout=8) as r2:
                    it = json.load(r2)
                t = (it.get("title") or "").strip()
                if t:
                    return t[:limit], it.get("url") or f"https://news.ycombinator.com/item?id={i}"
            except Exception:
                continue
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------- rendering
#
# Flat, first person, short, and framed as something *noticed*, not as a text to read.

def as_noticed():
    """One real thing from outside, in the creature's own register."""
    if time.time() % 2 < 1:
        t, e = random_page()
        if t and e:
            return f"[{time.strftime('%H:%M')}] through the window I get a piece of somewhere else: {t}. {e}"
    t, u = headline()
    if t:
        return (f"[{time.strftime('%H:%M')}] through the window, something happening somewhere else: {t}")
    t, e = random_page()
    if t and e:
        return f"[{time.strftime('%H:%M')}] through the window I get a piece of somewhere else: {t}. {e}"
    return None


def as_looked(url):
    """The creature produced a URL. The world honours it."""
    t, body = fetch(url, limit=360)
    if not body:
        return None
    lead = f"I looked at it: {t}. " if t else "I looked at it: "
    return f"[{time.strftime('%H:%M')}] {lead}{body}"


URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.I)


def url_in(text):
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(".,;:") if m else None
