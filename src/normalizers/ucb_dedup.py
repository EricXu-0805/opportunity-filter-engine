"""Cross-source deduplication for the campus opportunity graph.

The campus crawler surfaces the same opportunity from several angles — a lab
listed on its department's research page AND on its own "join our lab" page; a
program named in an OURS announcement AND on its dedicated page; a posting
reposted in a newsletter. Left unchecked this floods results with near-identical
rows. This module collapses them.

Two deterministic signals (stdlib only, no network/ML deps):

  * **URL canonicalization** — strip scheme, leading ``www.``, default ports,
    tracking query params (``utm_*``, ``fbclid``, ...), trailing slashes, and
    fragments, then lowercase the host. Two URLs that canonicalize equal point
    at the same posting.

  * **Normalized-title key** — lowercase, drop a parenthetical/dash "(UC
    Berkeley)" style suffix, collapse punctuation/whitespace, and drop a small
    set of filler words. Two postings with the same normalized title under the
    same emit bucket are treated as the same opportunity.

An optional embedding-similarity pass (``embedding_duplicate_pairs``) is wired
behind a guarded import so it is a no-op when no provider/deps are present — the
deterministic signals are always sufficient on their own.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_TRACKING_PARAM_RE = re.compile(r"^(utm_|fbclid$|gclid$|mc_eid$|ref$|ref_src$)", re.IGNORECASE)
_TITLE_SUFFIX_RE = re.compile(r"\s*[\(—\-]\s*(uc\s+berkeley|berkeley|ucb)\s*\)?\s*$", re.IGNORECASE)
_STATUS_SUFFIX_RE = re.compile(r"\s*\((applications?\s+(open|closed)|now\s+\w+)\)\s*$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")

_TITLE_FILLER = frozenset({
    "the", "a", "an", "and", "for", "of", "to", "at", "in", "on", "with",
    "program", "opportunity", "opportunities", "research", "undergraduate",
    "students", "student",
})


def canonicalize_url(url: str | None) -> str:
    """Return a canonical form of ``url`` for equality comparison.

    Robust to None/garbage (returns "" so callers can skip URL-keying a record
    with no usable link rather than crash)."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    if not url:
        return ""
    if "//" not in url and not url.startswith("http"):
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.lower().rstrip("/")

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    # Drop default ports.
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"

    # Filter tracking query params; keep meaningful ones (sorted for stability).
    kept = []
    for pair in parts.query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0]
        if _TRACKING_PARAM_RE.match(key):
            continue
        kept.append(pair)
    query = "&".join(sorted(kept))

    path = parts.path.rstrip("/")
    # Scheme normalized to https and fragment dropped — they never distinguish
    # two postings of the same opportunity.
    return urlunsplit(("https", netloc, path, query, "")).lower()


def normalize_title(title: str | None) -> str:
    """Collapse a title to a comparison key. Drops a Berkeley locator suffix,
    an open/closed status suffix, punctuation, and filler words."""
    if not title or not isinstance(title, str):
        return ""
    t = title.strip()
    t = _STATUS_SUFFIX_RE.sub("", t)
    t = _TITLE_SUFFIX_RE.sub("", t)
    t = t.lower()
    t = _PUNCT_RE.sub(" ", t)
    tokens = [w for w in _WS_RE.sub(" ", t).strip().split(" ") if w and w not in _TITLE_FILLER]
    return " ".join(tokens)


def _bucket(opp: dict) -> str:
    """Scope titles to their emit bucket so two genuinely different programs
    that normalize to the same short title across buckets aren't merged."""
    return opp.get("source") or opp.get("emit") or ""


def find_duplicate_groups(opportunities: list[dict]) -> list[list[int]]:
    """Group indices of records that are duplicates of one another.

    Union by (a) identical canonical URL or (b) identical (bucket, normalized
    title). Returns only the groups with >1 member. The lowest index in each
    group is the natural "keep" candidate (callers decide policy)."""
    parent: dict[int, int] = {i: i for i in range(len(opportunities))}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_url: dict[str, int] = {}
    by_title: dict[tuple[str, str], int] = {}
    for i, opp in enumerate(opportunities):
        cu = canonicalize_url(opp.get("url") or opp.get("source_url"))
        if cu:
            if cu in by_url:
                union(by_url[cu], i)
            else:
                by_url[cu] = i
        nt = normalize_title(opp.get("title"))
        if nt:
            key = (_bucket(opp), nt)
            if key in by_title:
                union(by_title[key], i)
            else:
                by_title[key] = i

    groups: dict[int, list[int]] = {}
    for i in range(len(opportunities)):
        groups.setdefault(find(i), []).append(i)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def dedupe_against_existing(
    new_opps: list[dict], existing: list[dict]
) -> tuple[list[dict], int]:
    """Drop incoming records whose canonical URL or (bucket, normalized title)
    already exists in the corpus. Existing-corpus-wins (same policy as the
    faculty joint-appointment dedup). Returns (kept, dropped_count).

    Records keyed by id are NOT handled here (that is the merge's upsert job);
    this only suppresses *different-id* near-duplicates that would otherwise
    flood the feed."""
    existing_urls: set[str] = set()
    existing_titles: set[tuple[str, str]] = set()
    new_ids = {o.get("id") for o in new_opps if o.get("id")}
    for o in existing:
        # A record with the same id is an upsert target, not a duplicate — skip.
        if o.get("id") in new_ids:
            continue
        cu = canonicalize_url(o.get("url") or o.get("source_url"))
        if cu:
            existing_urls.add(cu)
        nt = normalize_title(o.get("title"))
        if nt:
            existing_titles.add((_bucket(o), nt))

    kept: list[dict] = []
    dropped = 0
    # De-dup within the incoming batch first (first occurrence wins).
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    for o in new_opps:
        cu = canonicalize_url(o.get("url") or o.get("source_url"))
        nt = normalize_title(o.get("title"))
        tkey = (_bucket(o), nt)
        is_dup = (
            (cu and (cu in existing_urls or cu in seen_urls))
            or (nt and (tkey in existing_titles or tkey in seen_titles))
        )
        if is_dup and o.get("id") not in new_ids - {o.get("id")}:
            # Only drop when it is NOT a same-id upsert of an existing record.
            if o.get("id") not in {e.get("id") for e in existing}:
                dropped += 1
                continue
        if cu:
            seen_urls.add(cu)
        if nt:
            seen_titles.add(tkey)
        kept.append(o)
    return kept, dropped


def embedding_duplicate_pairs(
    opportunities: list[dict], threshold: float = 0.93
) -> list[tuple[int, int, float]]:
    """Optional semantic-dup detector. Returns (i, j, similarity) pairs whose
    title+description embeddings exceed ``threshold``.

    Guarded: if the embedding backend or its deps are unavailable this returns
    an empty list — the deterministic URL/title signals above are the always-on
    path; embeddings are a refinement only."""
    try:
        from src.matcher.embeddings import semantic_similarity_batch
    except Exception:
        return []

    texts = [
        " ".join(filter(None, [o.get("title", ""), (o.get("description_clean") or "")[:400]]))
        for o in opportunities
    ]
    pairs: list[tuple[int, int, float]] = []
    for i in range(len(texts)):
        rest = texts[i + 1:]
        if not rest:
            break
        try:
            sims = semantic_similarity_batch(texts[i], rest)
        except Exception:
            return pairs
        for offset, s in enumerate(sims):
            if float(s) >= threshold:
                pairs.append((i, i + 1 + offset, float(s)))
    return pairs
