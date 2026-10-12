"""The first refresh after UF PHHP moved to the UF Health Directory, replayed.

PHHP's Apollo feed went silent on 2026-10-09, and the college is now read from
directory.ufhealth.org: the college tree split by first name into PHHP, PHHP2
and PHHP3 (the old page boundaries, so a person listed under the same name
keeps their id), plus Biostatistics (PHHP4) and Epidemiology (PHHP5). Of the
132 stored rows, 81 keep their id. The other 51 are people the new roster does
not produce under the same id: 24 listed again with the same address under a
new id (one renamed), Marie N Séraphin listed again under a new address, Thomas
A Pearson listed under Epidemiology with no title, and 25 people the college no
longer lists.

Every json_dir unit used to report an all-zero roster coverage, which the
retirement pass reads as an empty roster, so it retired nobody: the 25 stayed
active, and so did Séraphin's old row beside her new one. The feed states its
size on every page and every row has its own slug, so the walk can now prove it
read every row. Pearson is still listed, so he stays as stored (owner decision,
2026-10-11) although the title gate does not publish a row with no title.

The fixture holds the pages as the directory served them on 2026-10-11, cut to
what the replay reads: rows of the people stored in the shard carry their slug,
name, title, address and profile link; rows the faculty gate publishes for
people not yet stored keep their title under an opaque stand-in slug, name and
address; every other row keeps only a stand-in slug. It also holds the
identity, contact and activity fields of the 132 PHHP rows of
data/processed/shards/uf.json at that date. The replay is refresh_all for the
uf shard with only the network replaced; every other UF department fails to
load.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import requests

import src.collectors.refresh_all as refresh_all
from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import uf_faculty
from src.normalizers.deactivate_stale_faculty import unit_retirement_authority
from tests.test_refresh_all import _stub_with_processed_file

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "uf_phhp_refresh.json").read_text())
SHORTS = ("phhp", "phhp2", "phhp3", "phhp4", "phhp5")
COLLEGE_PAGE_2 = next(u for u in FIXTURE["pages"]
                      if "/33000000/" in u and u.endswith("page=2"))
COLLEGE_PAGE_1 = COLLEGE_PAGE_2[:-1] + "1"


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return copy.deepcopy(self.payload)


def _replay(monkeypatch, tmp_path, pages):
    processed = _stub_with_processed_file(
        monkeypatch, tmp_path, copy.deepcopy(FIXTURE["stored"]))
    monkeypatch.setattr(refresh_all, "fetch_uf_faculty", uf_faculty.fetch_and_normalize)
    monkeypatch.setattr(refresh_all, "merge_uf_faculty", uf_faculty.merge_into_processed)
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", processed)
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *a, **k: None)
    monkeypatch.setattr(faculty_graph, "_render_soup", lambda *a, **k: None)

    def get(url, **_kw):
        if url not in pages:
            raise requests.ConnectionError(url)
        return _Resp(pages[url])

    def post(url, **_kw):
        raise requests.ConnectionError(url)

    monkeypatch.setattr("requests.get", get)
    monkeypatch.setattr("requests.post", post)
    summary = refresh_all.refresh_all(deep=True, schools={"uf"})
    return summary, json.loads(processed.read_text(encoding="utf-8"))


def _short(record):
    return record["id"].split("-")[2]


def _active(record):
    return record["metadata"].get("is_active") is not False


def test_the_next_refresh_lists_every_phhp_person_once(monkeypatch, tmp_path):
    summary, corpus = _replay(monkeypatch, tmp_path, FIXTURE["pages"])

    ledger = summary["sources"]["uf_faculty"]["stale_unit_ledger"]
    assert {u: ledger[u]["completeness_status"] for u in SHORTS} == dict.fromkeys(
        SHORTS, "complete")
    phhp = [r for r in corpus if _short(r) in SHORTS]
    counts = {s: (sum(1 for r in phhp if _short(r) == s and _active(r)),
                  sum(1 for r in phhp if _short(r) == s and not _active(r)))
              for s in SHORTS}
    # (active, retired) per short.
    assert counts == {"phhp": (79, 12), "phhp2": (72, 9), "phhp3": (11, 5),
                      "phhp4": (31, 0), "phhp5": (26, 0)}

    active = [r for r in phhp if _active(r)]
    emails = Counter(r["contact_email"] for r in active)
    assert [e for e, n in emails.items() if n > 1] == []
    stored = {r["id"]: r for r in FIXTURE["stored"]}
    by_id = {r["id"]: r for r in corpus}
    # Pearson is kept as stored: his link is still the college listing page,
    # and nothing this run observed refreshed him.
    pearson = next(r for r in active if r["pi_name"] == "Thomas A Pearson")
    was = stored[pearson["id"]]
    assert {k: pearson[k] for k in was if k != "metadata"} == {
        k: v for k, v in was.items() if k != "metadata"}
    assert pearson["metadata"]["last_seen_at"] == was["metadata"]["last_seen_at"]
    assert all(r["url"].startswith("https://directory.ufhealth.org/") for r in active
               if r is not pearson)

    kept = [i for i in stored if i in by_id and _active(by_id[i])]
    assert len(kept) == 82
    # The 24 listed again under a new id with the same address: retired, then
    # dropped as a tombstone of the live row that carries the address now.
    gone = [r for i, r in stored.items() if i not in by_id]
    assert len(gone) == 24
    assert all(emails[r["contact_email"]] == 1 for r in gone)
    retired = sorted(r["pi_name"] for r in phhp if not _active(r))
    assert len(retired) == 26
    assert len(kept) + len(gone) + len(retired) == len(stored) == 132
    assert {"Marie N Séraphin", "J. Glenn Morris"} <= set(retired)
    assert all(r["metadata"]["deactivation_reason"] == "absent_from_directory_rescrape"
               for r in phhp if not _active(r))
    seraphin = [r for r in active if r["pi_name"] == "Marie N Séraphin"]
    assert [_short(r) for r in seraphin] == ["phhp5"]
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 50


def test_a_college_page_that_does_not_load_retires_nobody(monkeypatch, tmp_path):
    pages = {u: p for u, p in FIXTURE["pages"].items() if u != COLLEGE_PAGE_2}
    summary, corpus = _replay(monkeypatch, tmp_path, pages)

    ledger = summary["sources"]["uf_faculty"]["stale_unit_ledger"]
    for unit in ("phhp", "phhp2", "phhp3"):
        # 980 stated, 500 read: the 480 on page 2 were never seen.
        assert ledger[unit]["coverage"]["partial_render_rows"] == 480
        assert unit_retirement_authority(ledger[unit], 0) == (
            False, "blocked_partial_render_rows")
    assert all(_active(r) for r in corpus if _short(r) in SHORTS)
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0



def test_a_feed_that_reorders_between_page_requests_retires_nobody(monkeypatch, tmp_path):
    # The feed's order moved between two captures 30 minutes apart. If it moves
    # after page 1 is served, page 2 can repeat page 1's last row and lose one
    # of its own, and the walk still reads 980 rows: Gaia L Zori, a stored
    # professor on page 2, would be retired while listed.
    pages = copy.deepcopy(FIXTURE["pages"])
    page_1 = pages[COLLEGE_PAGE_1]["data"]["results"]["profiles"]
    page_2 = pages[COLLEGE_PAGE_2]["data"]["results"]["profiles"]
    zori = next(r for r in page_2 if r.get("full_name") == "Gaia L Zori")
    page_2[:] = [page_1[-1], *(r for r in page_2 if r is not zori)]
    summary, corpus = _replay(monkeypatch, tmp_path, pages)

    ledger = summary["sources"]["uf_faculty"]["stale_unit_ledger"]
    for unit in ("phhp", "phhp2", "phhp3"):
        # 980 rows read, 979 different slugs among them.
        assert ledger[unit]["coverage"]["partial_render_rows"] == 1
        assert unit_retirement_authority(ledger[unit], 0) == (
            False, "blocked_partial_render_rows")
    stored = next(r for r in FIXTURE["stored"] if r["pi_name"] == "Gaia L Zori")
    assert _active(next(r for r in corpus if r["id"] == stored["id"]))
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
