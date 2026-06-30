"""Run-once LLM enrichment of fieldless faculty research areas.

Some faculty reach the corpus with no research keywords because their directory
or profile exposes no parseable research field — only a prose biography. This
pass mines that prose with the configured LLM (Gemini) through the
anti-fabrication + generic-noise-gated extractor
(:func:`uiuc_faculty._llm_research_keywords`), which the model is told to ABSTAIN
on (return nothing) when the text has no genuine personal research.

Run ONCE per school, like the Illinois-Experts pass: keywords are written into
the corpus and the richer-keyword dedup in the collectors protects them on later
refreshes, so this never runs on the weekly schedule (zero refresh cost).

Accuracy guards — every one favours "better broad than fragments":
  * **listing-URL skip** — faculty whose URL is shared by >=2 records sit on a
    department *listing* page, not an individual profile; extraction would leak
    other people's areas, so skip (they stay broad).
  * **thin-page skip** — pages with < ``min_bio_chars`` of real text are
    name/title/contact/nav only; nothing to mine, so skip.
  * **extractor abstention** — course lists, advisee theses, administrative
    bios, and dictionary-of-"research" boilerplate yield [] from the extractor.
  * **junk gate** — surviving keywords pass ``_is_junk_keyword``.

Two-phase CLI keeps parallel per-school runs race-free and reviewable:

    python -m src.collectors.llm_enrich harvest uw --out enrich_uw.json
    python -m src.collectors.llm_enrich apply enrich_uw.json enrich_ucla.json ...

``harvest`` is pure (writes a {url: keywords} map); ``apply`` mutates the corpus
updates-only (only fieldless records whose URL is in a map).
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict

from .ucb_common import PROCESSED_FILE, fetch_soup
from .uiuc_faculty import _is_junk_keyword, _llm_research_keywords

MIN_BIO_CHARS = 180
# washington.edu / uw.edu share ONE per-IP edge rate limit (~1 req/1.5s); a
# faster cadence 429-storms. Everything else has diverse hosts.
_SLOW_HOSTS = ("washington.edu", "uw.edu")
_SLOW_THROTTLE = 2.5

_MAIN_SELECTORS = ("main", "article", ".entry-content", ".faculty-member-content",
                   "#content", ".content")


def _record_url(o: dict) -> str | None:
    return o.get("url") or o.get("source_url")


def _is_faculty(o: dict) -> bool:
    return bool(o.get("source_type") == "faculty_research" or o.get("pi_name"))


def _main_text(soup) -> str:
    for sel in _MAIN_SELECTORS:
        el = soup.select_one(sel)
        if el and len(el.get_text(" ", strip=True)) > 120:
            return el.get_text(" ", strip=True)
    return soup.get_text(" ", strip=True)


def _broad_targets(opps: list[dict], schools: list[str] | None) -> list[dict]:
    """Fieldless faculty with a per-person URL (URL not shared by >=2 records)."""
    url_counts = Counter(
        _record_url(o) for o in opps if _is_faculty(o) and _record_url(o)
    )
    out = []
    for o in opps:
        if not _is_faculty(o) or o.get("keywords"):
            continue
        if schools and o.get("school") not in schools:
            continue
        url = _record_url(o)
        if not url or url_counts[url] >= 2:   # listing-URL skip
            continue
        out.append(o)
    return out


def _stratified(targets: list[dict], n: int) -> list[dict]:
    buckets: dict[tuple, list] = defaultdict(list)
    for o in targets:
        buckets[(o.get("school"), o.get("department", "?"))].append(o)
    pools = [iter(v) for v in buckets.values()]
    out: list[dict] = []
    progressed = True
    while len(out) < n and progressed:
        progressed = False
        for it in pools:
            nxt = next(it, None)
            if nxt is not None:
                out.append(nxt)
                progressed = True
                if len(out) >= n:
                    break
    return out


def harvest_llm_keywords(
    opps: list[dict],
    *,
    schools: list[str] | None = None,
    sample: int | None = None,
    throttle: float = 0.4,
    min_bio_chars: int = MIN_BIO_CHARS,
    progress: bool = False,
) -> dict[str, list[str]]:
    """Fetch each fieldless faculty profile and extract grounded research
    keywords. Pure — no mutation. Returns ``{url: keywords}`` only for records
    that yielded keywords (abstentions and skips are simply absent)."""
    targets = _broad_targets(opps, schools)
    if sample is not None:
        targets = _stratified(targets, sample)
    mapping: dict[str, list[str]] = {}
    for i, o in enumerate(targets):
        url = _record_url(o)
        delay = _SLOW_THROTTLE if any(h in url for h in _SLOW_HOSTS) else throttle
        soup = fetch_soup(url)
        time.sleep(delay)
        if not soup:
            continue
        body = _main_text(soup)
        if len(body.strip()) < min_bio_chars:   # thin-page skip
            continue
        page = soup.get_text(" ")
        kws = [k for k in _llm_research_keywords(body[:1500], page) if not _is_junk_keyword(k)]
        if kws:
            mapping[url] = kws
        if progress and (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(targets)} processed, {len(mapping)} enriched", flush=True)
    return mapping


def apply_llm_keywords(opps: list[dict], mapping: dict[str, list[str]]) -> int:
    """Updates-only: set keywords on fieldless faculty records whose URL is in
    ``mapping``. Never overwrites an existing keyword set. Returns count set."""
    n = 0
    for o in opps:
        if not _is_faculty(o) or o.get("keywords"):
            continue
        kws = mapping.get(_record_url(o))
        if kws:
            o["keywords"] = kws
            n += 1
    return n


def _load_dotenv() -> None:
    """Load backend/.env into os.environ for the standalone CLI run (the app
    process gets these the same way; importable functions never touch env)."""
    import os
    from pathlib import Path

    for envf in ("backend/.env", ".env"):
        p = Path(envf)
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _cli(argv: list[str]) -> int:
    if not argv or argv[0] not in ("harvest", "apply"):
        print(__doc__)
        return 2
    _load_dotenv()
    mode, rest = argv[0], argv[1:]
    if mode == "harvest":
        schools = [s for s in rest[0].split(",")] if rest and not rest[0].startswith("-") else None
        out = "enrich.json"
        throttle, sample = 0.4, None
        for i, a in enumerate(rest):
            if a == "--out":
                out = rest[i + 1]
            elif a == "--throttle":
                throttle = float(rest[i + 1])
            elif a == "--sample":
                sample = int(rest[i + 1])
        opps = json.load(open(PROCESSED_FILE))
        mapping = harvest_llm_keywords(
            opps, schools=schools, sample=sample, throttle=throttle, progress=True
        )
        json.dump(mapping, open(out, "w"), indent=2)
        print(f"harvested {len(mapping)} enriched profiles -> {out}")
        return 0
    # apply
    opps = json.load(open(PROCESSED_FILE))
    merged: dict[str, list[str]] = {}
    for f in rest:
        merged.update(json.load(open(f)))
    n = apply_llm_keywords(opps, merged)
    json.dump(opps, open(PROCESSED_FILE, "w"), ensure_ascii=False, indent=2)
    print(f"applied {n} enrichments from {len(rest)} map(s) -> {PROCESSED_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
