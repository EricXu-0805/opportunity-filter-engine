"""Replay the normal UF refresh and persistent merge under both entry URLs and an outage."""
import copy
import json
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.collectors import refresh_all, ucb_common
from src.collectors.schools import uf_faculty
from tests.test_refresh_all import _stub_with_processed_file

CURRENT = "https://phys.ufl.edu/people/faculty/"
OLD = "https://www.phys.ufl.edu/wp/index.php/people/faculty/"


def index(rows):
    return {r["id"]: r for r in rows}


def public_fields(r):
    return {k: r[k] for k in ("id","pi_name","title","url","source_url","description_clean")} | {
        "eligibility_text": r["eligibility"]["eligibility_text_raw"],
        "rank":r["metadata"]["faculty_title"],"rank_source":r["metadata"]["faculty_title_observation"]}


def main():
    seed=json.loads(Path("data/processed/shards/uf.json").read_bytes())
    initial=index(seed); original={i:r for i,r in initial.items() if i.startswith("faculty-uf-phy-")}
    current=ucb_common.fetch_soup(CURRENT);old=ucb_common.fetch_soup(OLD)
    assert old and current and current.select("article.ufclas-team-grid__item")
    assert len(current.select("article.ufclas-team-grid__item"))==len(old.select("article.ufclas-team-grid__item"))==92
    # Preserve the document's actual landing address in the real parser. Returning None
    # is the normal result when the campus page is unavailable.
    rounds=[]; before=seed
    physics=next(d for d in uf_faculty.SCHOOL["departments"] if d["short"]=="PHY")
    baseline_ledger={}; baseline=copy.deepcopy(physics)
    for label, page in (("canonical",current),("unavailable",None),("legacy_redirect",old),("repeat",current)):
        previous=index(before)
        with tempfile.TemporaryDirectory() as temp, pytest.MonkeyPatch.context() as mp:
            processed=_stub_with_processed_file(mp,Path(temp),before)
            mp.setattr(uf_faculty,"SCHOOL",{**uf_faculty.SCHOOL,"departments":[physics]})
            mp.setattr(refresh_all,"fetch_uf_faculty",uf_faculty.fetch_and_normalize)
            mp.setattr(refresh_all,"merge_uf_faculty",uf_faculty.merge_into_processed)
            mp.setattr(ucb_common,"PROCESSED_FILE",processed)
            mp.setattr(ucb_common,"fetch_soup",lambda request,**kw: page if request==CURRENT else None)
            summary=refresh_all.refresh_all(deep=True,schools={"uf"})
            source=summary["sources"]["uf_faculty"]
            unit=source["stale_unit_ledger"]["phy"]
            before=json.loads(processed.read_text())
        rows=index(before)
        assert len(before)==len(rows)==len(initial) and set(rows)==set(initial)
        assert all(r["metadata"].get("first_seen_at")==rows[i]["metadata"].get("first_seen_at") for i,r in initial.items())
        assert all(rows[i]["metadata"].get("is_active") is not False for i in original)
        observed=unit["observed_count"]
        assert observed==(0 if page is None else len(original))
        seen_moved=[i for i in sorted(original) if rows[i]["metadata"]["last_seen_at"]!=previous[i]["metadata"]["last_seen_at"]]
        assert len(seen_moved)==(0 if page is None else len(original))
        rounds.append({"case":label,"fetch":unit["fetch_status"],"parse":unit["parse_status"],
                      "completeness":unit["completeness_status"],"observed":observed,
                      "coverage":{k:v for k,v in unit.get("coverage",{}).items() if isinstance(v,int)},
                      "originals_seen_at_changed":len(seen_moved),"retained_uf_ids":len(rows),
                      "active_originals":sum(rows[i]["metadata"].get("is_active") is not False for i in original)})
    output=[public_fields(rows[i]) for i in sorted(original)]
    assert all(r["rank_source"]["source"]==CURRENT and r["rank_source"]["profile"]==r["url"] for r in output)
    result={"observed_utc":datetime.now(UTC).isoformat(timespec="seconds"),"actual_pages":[CURRENT,OLD],
            "original_uf_ids":len(initial),"physics_count":len(original),"rounds":rounds,
            "previous_index_fallback_person_contact_confirmation":{
                i:bool(r.get("contact_email") and r["contact_email"].casefold()==(rows[i].get("contact_email") or "").casefold())
                for i,r in original.items() if r["url"].strip()==OLD},
            "reviewed_fields":output}
    Path("../uf-physics-normal-replay.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print([(r["case"],r["observed"],r["originals_seen_at_changed"]) for r in rounds],len(rows))
if __name__=="__main__":main()
