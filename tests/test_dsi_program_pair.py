from copy import deepcopy

from backend.routes.matches import _match_card
from src.collectors.base import RawOpportunity
from src.collectors.uiuc_sro import raw_to_normalized
from src.program_windows import DSI_DIRECTORY, DSI_WINDOW
from src.reviewed_program_pairs import verified_pairs
from src.saved_searches.filter import matching_ids
from tests.test_program_windows import _row


def test_dsi_results_preserve_saved_sources_and_independent_cohorts():
    host = _row("uchicago", "dsi_summer_lab")
    directory = raw_to_normalized(RawOpportunity(
        "uiuc_sro", "https://researchops.web.illinois.edu/?page=0", "Data Science Institute Summer Lab",
        "", DSI_DIRECTORY, organization="University of Chicago",
        extra_fields={"deadline_raw": "Anticipated 1/12/27", "program_url": DSI_WINDOW.url + "#program-overview"},
    ))
    rows = [directory, host]
    assert matching_ids(rows, {}) == [host["id"]]
    assert matching_ids(rows, {"source": "uiuc_sro"}) == [directory["id"]]
    assert matching_ids(rows, {}, preferred_ids=[directory["id"]]) == [directory["id"]]
    cards = {r["id"]: _match_card(r) for r in rows}
    assert all(card["application_closes_at"] == "2027-01-11T23:59:00-06:00" for card in cards.values())
    assert len(verified_pairs(cards, projected=True)) == 1
    changed = deepcopy(directory)
    changed["application"]["application_url"] = "https://example.edu/another-project"
    changed["application_deadline_source_url"] = DSI_WINDOW.page
    changed["application_closes_at"] = "2027-01-11T23:59:00-06:00"
    cards[changed["id"]] = _match_card(changed)
    assert "application_deadline_source_url" not in cards[changed["id"]]
    assert "application_closes_at" not in cards[changed["id"]]
    assert not verified_pairs(cards, projected=True)
    assert set(matching_ids([host, changed], {})) == {r["id"] for r in rows}


def test_published_central_cutoff_expires_both_source_ids_and_warm_match_cache(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from backend.routes import matches
    from src import evidence
    from src.program_windows import reviewed_program_cutoff

    host = _row("uchicago", "dsi_summer_lab")
    directory = raw_to_normalized(RawOpportunity(
        "uiuc_sro", "https://researchops.web.illinois.edu/?page=0", "Data Science Institute Summer Lab",
        "", DSI_DIRECTORY, organization="University of Chicago",
        extra_fields={"deadline_raw": "Anticipated 1/12/27", "program_url": DSI_WINDOW.url + "#program-overview"},
    ))
    other = deepcopy(directory)
    other["application"]["application_url"] = "https://example.edu/another-program"
    cutoff = datetime(2027, 1, 12, 5, 59, tzinfo=UTC)
    moment = cutoff - timedelta(seconds=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    monkeypatch.setattr(evidence, "datetime", Clock)
    monkeypatch.setattr(matches.time, "time", lambda: moment.timestamp())
    monkeypatch.setattr(matches, "_active_corpus_identity", None)
    monkeypatch.setattr(matches, "_project_cutoffs", ())
    monkeypatch.setattr(matches, "_match_universe", None)
    monkeypatch.setattr(matches, "_match_snapshots", {})
    monkeypatch.setattr(matches, "_match_view_rows", {})
    corpus = [host, directory]
    matches._activate_corpus_generation(corpus)
    assert matches.release_actionable_corpus(corpus) == corpus
    stamp = matches._ranked_with(None)
    assert all(reviewed_program_cutoff(row) == cutoff for row in corpus)
    moment = cutoff
    assert matches.release_actionable_corpus(corpus) == []
    assert matches._ranked_with(None) != stamp
    for row in corpus:
        truth = evidence.target_truth(row)
        assert (truth.actionable, truth.reason_code) == (False, "listing_closed")
        assert datetime.fromisoformat(truth.expires_at) == cutoff
    assert reviewed_program_cutoff(other) is None
    assert evidence.target_truth(other).actionable
