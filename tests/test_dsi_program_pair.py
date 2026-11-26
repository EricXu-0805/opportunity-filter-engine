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
    assert len(verified_pairs(cards, projected=True)) == 1
    changed = deepcopy(directory)
    changed["application"]["application_url"] = "https://example.edu/another-project"
    changed["application_deadline_source_url"] = DSI_WINDOW.page
    cards[changed["id"]] = _match_card(changed)
    assert "application_deadline_source_url" not in cards[changed["id"]]
    assert not verified_pairs(cards, projected=True)
    assert set(matching_ids([host, changed], {})) == {r["id"] for r in rows}
