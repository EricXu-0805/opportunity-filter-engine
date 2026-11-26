"""The Wisconsin source pairing preserves the independently retired SRO alias."""

import copy
import json

from backend.lib.target_actionability import actionable_opportunities
from backend.routes import matches
from src import reviewed_program_pairs as pairs
from src.collectors.base import RawOpportunity
from src.collectors.uiuc_sro import merge_into_processed, raw_to_normalized
from src.matcher import ranker
from src.saved_searches.filter import matching_ids
from tests.test_fodommat_identity import programs as ncsa_programs  # noqa: F401
from tests.test_match_consistency import _opp, _profile, client, snapshot_env  # noqa: F401
from tests.test_program_windows import _row
from tests.test_saved_search_digest import AUTH, _digest_row, _install_stubs, _set_digest_env


def _wisconsin():
    pair = pairs.WISCONSIN
    directory = raw_to_normalized(
        RawOpportunity(
            "uiuc_sro",
            "https://researchops.web.illinois.edu/?page=9",
            "Cellular and Molecular Biology of Stress",
            "",
            pair.directory_url,
            organization="University of Wisconsin-Madison",
            extra_fields={"deadline_raw": "Anticipated 2/15/27", "program_url": pair.window.url},
        )
    )
    return [_row("wisc", "ibs_srp_cmbs_reu"), directory]


def test_the_collector_still_selects_the_preferred_sro_id_and_preserves_its_alias(tmp_path, monkeypatch):
    pair = pairs.WISCONSIN
    host, directory = _wisconsin()
    alias = raw_to_normalized(
        RawOpportunity(
            "uiuc_sro",
            "https://researchops.web.illinois.edu/?page=9",
            "Cellular and Molecular Biology of Stress",
            "",
            pair.directory_url.removesuffix("-0"),
            organization="University of Wisconsin-Madison",
            extra_fields={
                "deadline_raw": "Anticipated 2/15/27",
                "program_url": "https://wiscience.wisc.edu/research/srp/",
            },
        )
    )
    target = tmp_path / "national.json"
    target.write_text(json.dumps([host, directory, alias]))
    merge_into_processed([directory, alias], str(target))
    refreshed = {r["id"]: r for r in json.loads(target.read_text())}
    assert refreshed[alias["id"]]["metadata"]["duplicate_of"] == pair.directory_id
    assert not refreshed[alias["id"]]["metadata"]["is_active"]
    active = actionable_opportunities(list(refreshed.values()))
    assert matching_ids(active, {}) == [pair.host_id]
    assert matching_ids(active, {"source": "uiuc_sro"}) == [pair.directory_id]
    assert matching_ids(active, {"source": pair.host_source}) == [pair.host_id]
    assert matching_ids(active, {}, preferred_ids=[pair.directory_id]) == [pair.directory_id]
    assert matching_ids([host, {**directory, "deadline": "2028-02-10"}], {}) == list(pair.ids)

    # If the preferred SRO page goes away, its independently verified alias
    # can again be the SRO result. The old reminder already knew this cohort.
    refreshed[pair.directory_id]["metadata"].update(is_active=False, deactivation_reason="source_removed")
    target.write_text(json.dumps(list(refreshed.values())))
    merge_into_processed([alias], str(target))
    recovered = json.loads(target.read_text())
    active = actionable_opportunities(recovered)
    assert matching_ids(active, {}) == [pair.host_id]
    assert matching_ids(active, {"source": "uiuc_sro"}) == [alias["id"]]
    _set_digest_env(monkeypatch)
    row = _digest_row(
        last_run_at="2026-11-25T00:00:00Z",
        last_result_ids=[pair.directory_id],
        new_match_ids=[],
        filters_json={"source": "uiuc_sro"},
    )
    patches = []
    _install_stubs(monkeypatch, rows=[row], opportunities=recovered, patches=patches)
    result = client.get("/api/cron/saved-searches/refresh", headers=AUTH)
    assert result.status_code == 200 and result.json()["new_matches"] == 0
    assert patches[0]["json"]["last_result_ids"] == [alias["id"]] and patches[0]["json"]["new_match_ids"] == []


def test_a_saved_wisconsin_source_keeps_its_original_notification_link(monkeypatch):
    host, directory = _wisconsin()
    pairs_found = pairs.pairs_in_records([host, directory])
    assert pairs_found == (pairs.WISCONSIN,)
    _set_digest_env(monkeypatch)
    for source, expected in [("uiuc_sro", directory["id"]), (host["source"], host["id"]), ("", host["id"])]:
        sends = []
        row = _digest_row(new_match_ids=[directory["id"], host["id"]], filters_json={"source": source})
        _install_stubs(monkeypatch, opportunities=[host, directory], rows=[row], sends=sends)
        response = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert response.status_code == 200 and response.json()["sent"] == 1
        urls = [oid for oid in pairs.WISCONSIN.ids if "/opportunities/" + oid in sends[0]["text"]]
        assert urls == [expected]


def test_one_page_cursor_can_cross_both_proven_pairs(snapshot_env, monkeypatch, ncsa_programs):  # noqa: F811
    host, directory = _wisconsin()
    corpus = []
    for row in (directory, *ncsa_programs, host):
        # Shared ranking fields ensure all four source pages reach the viewport.
        entry = {
            **_opp(row["id"]),
            **{
                k: copy.deepcopy(row[k])
                for k in (
                    "url",
                    "source_url",
                    "source",
                    "metadata",
                    "application",
                    "deadline",
                    "is_rolling",
                )
            },
        }
        entry.update(title="Campus program", opportunity_type="summer_program", source_type="summer_program")
        corpus.append(entry)
    corpus.append(_opp("different-program", title="Campus program", opportunity_type="summer_program"))
    ranker.register_corpus(corpus)
    monkeypatch.setattr(matches, "load_opportunities_generation", lambda: (corpus, "two-reviewed-cycles"))
    profile = _profile(seeking_type=["summer_program"])
    expected = {pairs.NCSA.host_id, pairs.WISCONSIN.host_id, "different-program"}
    for size in (1, 2, 3, 8):
        params = {"limit": size}
        ids = []
        while True:
            response = client.post("/api/matches", params=params, json=profile)
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == len(expected) == sum(data[k] for k in ("high_priority", "good_match", "reach"))
            ids.extend(r["opportunity_id"] for r in data["results"])
            if not data["has_more"]:
                break
            assert len(ids) < len(expected)
            params["cursor"] = data["next_cursor"]
        assert len(ids) == len(expected) and set(ids) == expected
