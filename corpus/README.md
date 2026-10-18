# BoredLLM frozen corpus

Real, human-authored text for the runtime to browse. Every byte here was written
by a person before any language model existed. **No part of this corpus is
AI-generated, AI-paraphrased, or AI-summarised** — the harvester only downloads,
unwraps licensing furniture, and normalises whitespace.

- **1364 documents · 15,764,028 words · 89,590,545 bytes (~85 MiB)**
- Built by [`harvest_corpus.py`](harvest_corpus.py); frozen on 2026-10-18 (UTC).
- Manifest: [`manifest.json`](manifest.json) · Checksums: [`SHA256SUMS`](SHA256SUMS)

## Layout

```
corpus/
├── harvest_corpus.py     the harvester (stdlib only; the ONLY code here)
├── manifest.json         per-file provenance + totals (the record of what this is)
├── SHA256SUMS            sha256 of every text file, relative paths
├── README.md             this file
└── text/
    ├── gutenberg/        119 full books            (public domain, US)
    ├── wikipedia/        1147 lead-section extracts (CC BY-SA 4.0)
    └── wikisource/       98 primary texts           (CC BY-SA 4.0 / PD)
```

## Sources and licensing

| Source | Docs | Licence | Access |
|---|---|---|---|
| Project Gutenberg | 119 | Public domain in the US (PG License) | `gutenberg.org/cache/epub`, `/files` |
| Wikipedia (en) | 1147 | CC BY-SA 4.0 | MediaWiki action API (`prop=extracts`) |
| Wikisource (en) | 98 | CC BY-SA 4.0 / public domain | MediaWiki action API (`prop=extracts`) |

Every file's `manifest.json` entry records its `source`, `source_id`, `title`,
`author` (where available), exact `url`, `license`, `bytes`, `words`, and
`sha256`. **Attribution travels with the file** — the CC BY-SA (Wikipedia and
Wikisource) material must be re-attributed if redistributed.

### What we deliberately did not use

- **Standard Ebooks** — its `robots.txt` disallows `/ebooks/*/downloads/*` for all
  user agents (and names AI crawlers specifically). Not used.
- Any login, API key, or account. Every source above is keyless.
- Wikipedia's `/ebooks/search`-style endpoints on Gutenberg — disallowed by
  robots; we use only the permitted text paths.

## How it was built

```bash
cd ~/boredllm-runtime/corpus
python3 harvest_corpus.py            # full rebuild (network; ~8 min)
python3 harvest_corpus.py --scale 0.1    # small smoke build
python3 harvest_corpus.py --source gutenberg
```

The build is deterministic given the same upstream pages: titles come from
`gutenberg.org/browse/scores/top` and from MediaWiki category walks; both are
recorded per file in the manifest, so any document can be located again.

### Politeness / rate limits

Wikimedia returns **HTTP 429** to aggressive requesters. The harvester paces wiki
API calls (~0.6 s apart), batches Wikipedia extraction **20 titles per request**
(`exintro=1`, the only form the TextExtracts extension honours in batches), and
cools off 25 s on any 429. Wikisource primary texts have no lead section, so they
are fetched one at a time (`exlimit=1`) at a serial pace.

## Content, cleaning and dedup

**Content.** Long-form English literature (novels, plays, poetry, essays) from
Gutenberg across many genres and three centuries; encyclopedic lead sections
spanning physics, biology, history, philosophy, law, music and more; and
Wikisource speeches, essays and short primary texts. Registers therefore range
from narrative fiction to expository reference prose.

**Boilerplate removed.**
- Project Gutenberg licence header/footer stripped from all 119 books: the
  `*** START/END OF … PROJECT GUTENBERG EBOOK ***` block, plus the older
  prose footers ("End of Project Gutenberg's …", "Updated editions will
  replace …", license sections) and leading promo/transcriber/URL blocks that
  illustrated editions place after the start marker. Files still naming Project
  Gutenberg (6 of 119) do so only inside the work itself.
- Whitespace normalised to NFC, `\r\n` → `\n`, runs of spaces collapsed, 3+ blank
  lines → 2, single trailing newline.

**Duplicates / low-value docs removed.**
- 2 documents dropped as byte-identical duplicates by content sha256.
- Non-article titles skipped: encyclopedic disambiguation pages, MediaWiki
  namespace pages (Portal:/Category:/Index:/Page:), stubs under the word floor,
  and Wikisource pages with unexpanded template markup.
- Word floors: Wikipedia ≥120 words; Wikisource 60–60,000 words (upper bound
  stops one multi-book Wikisource page dominating).

## Verify it

```bash
cd ~/boredllm-runtime/corpus
sha256sum -c SHA256SUMS | grep -c OK            # expect 1364
find text -type f | wc -l                        # expect 1364
python3 -c "import json;print(json.load(open('manifest.json'))['totals'])"
```

## Downstream use

The runtime does not yet consume a corpus (README: "the synthetic web, and the
corpus" is not built). When it does, treat `text/` as the reading surface and
`manifest.json` as the world's record of provenance — the world owns every fact,
so the licence and source of each document must stay attached to it.
