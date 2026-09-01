"""Historical remediation of professor-paper attribution.

The product rule this file defends, in two halves:

    verified attribution              -> a trusted professor paper
    everything else                   -> not a trusted professor paper

    old-gate record -> re-harvest -> re-attribute -> exactly-once disposition

The second half is what makes the first half true of data that already exists.
6,255 professors carry papers a *superseded* gate approved — gate 1 judged a
paper by the nine-field family the professor's department could plausibly
touch, which handed a UIUC MRI professor a search-agent paper. Stamping future
harvests correctly does nothing for them, so these tests are about the
machinery that finds them, withdraws the trust, re-judges them, and proves each
was processed exactly once.

Where a case can be exercised through a real application path it is — the
backend match card, the professor detail projection, the cold-email builder —
rather than through the gate helper alone, because the helper being right has
never been the thing that broke.
"""
from __future__ import annotations

import json
import threading

import pytest

from src.publication_remediation import (
    DISPOSITION_AMBIGUOUS,
    DISPOSITION_NEEDS_REVIEW,
    DISPOSITION_REMOVED,
    DISPOSITION_UNKNOWN,
    DISPOSITION_VERIFIED,
    FAILED,
    HARVEST_SUCCEEDED,
    NEEDS_REVIEW,
    QUEUED,
    VERIFIED_COMPLETE,
    Ledger,
    apply_disposition,
    disposition_for,
    idempotency_key,
    invalidate_population,
    invalidate_record,
    pending_population,
    population_summary,
    remediation_population,
    unit_for,
)
from src.publication_trust import (
    CURRENT_WORKS_GATE,
    NAME_MATCH,
    PENDING_REMEDIATION,
    VERIFIED_AUTHOR_ID,
    attribution_status,
    is_pending_remediation,
    needs_publication_remediation,
    verified_recent_works,
    works_are_verified,
)

_OLD_GATE = CURRENT_WORKS_GATE - 1

_WORKS = [
    {"title": "SearchAuditor: Auditing Failures in Long-Horizon Search Agents", "year": 2026},
    {"title": "Spectral-Spatial Networks for Geochemical Anomalies", "year": 2026},
    {"title": "Crafter: Editable Scientific Figure Generation", "year": 2026},
]


def faculty(
    rid="fac-1",
    *,
    status=VERIFIED_AUTHOR_ID,
    gate=_OLD_GATE,
    works=_WORKS,
    school="uiuc",
    name="Zhi-Pei Liang",
    url="https://ece.illinois.edu/about/directory/faculty/zliang",
    keywords=("magnetic resonance imaging",),
    keyword_source="derived:openalex_topics",
    author_id=None,
):
    """A faculty record shaped exactly like the corpus, not like a fixture.

    Defaults describe the real record this whole effort started from: a UIUC
    MRI professor stamped verified at gate 1, holding three 2026 papers that
    are not his.
    """
    md: dict = {"is_active": True}
    if works is not None:
        md["recent_works"] = [dict(w) for w in works]
    if status is not None:
        md["publication_attribution_status"] = status
    if gate is not None:
        md["works_gate"] = gate
    if author_id:
        md["publication_author_id"] = author_id
    if keyword_source:
        md["inferred_fields"] = {"keywords": keyword_source}
    return {
        "id": rid,
        "source_type": "faculty_research",
        "title": f"Research with Prof. {name}",
        "opportunity_type": "research",
        "pi_name": name,
        "school": school,
        "department": "Electrical & Computer Engineering",
        "url": url,
        "source_url": url,
        "keywords": list(keywords),
        "eligibility": {},
        "application": {},
        "metadata": md,
    }


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.jsonl")


# ---------------------------------------------------------------------------
# 1-8  Historical remediation
# ---------------------------------------------------------------------------

class TestRemediationPopulation:
    def test_old_gate_relationship_enters_the_population(self):
        """1. A record an older gate stamped is selected for re-judgement."""
        record = faculty(gate=_OLD_GATE)
        assert needs_publication_remediation(record)
        population = remediation_population([record])
        assert [u["professor_id"] for u in population] == ["fac-1"]
        assert population[0]["relationship_count"] == 3
        assert population[0]["old_gate_version"] == _OLD_GATE
        assert population[0]["to_gate_version"] == CURRENT_WORKS_GATE

    def test_absent_gate_stamp_reads_as_the_oldest_gate(self):
        """The 6,255 real records carry no works_gate at all — the field is
        newer than they are. Reading its absence as "current" would exclude
        the entire population from its own remediation."""
        record = faculty(gate=None)
        assert "works_gate" not in record["metadata"]
        assert needs_publication_remediation(record)

    def test_current_gate_verified_relationship_is_not_re_run(self):
        """2. Already judged by the living rule: leave it alone."""
        record = faculty(gate=CURRENT_WORKS_GATE)
        assert not needs_publication_remediation(record)
        assert remediation_population([record]) == []
        # And it stays trusted — the remediation must not cost a good record.
        assert works_are_verified(record)
        assert verified_recent_works(record)

    def test_legacy_missing_verification_fails_closed_and_is_not_in_scope(self):
        """3. A record with works and no stamp is already untrusted.

        It must not be swept into the remediation population — that population
        is about withdrawing trust, and there is none here to withdraw. It must
        also stay untrusted, which is the part that matters."""
        record = faculty(status=None, gate=None)
        assert not works_are_verified(record)
        assert verified_recent_works(record) == []
        assert not needs_publication_remediation(record)
        assert remediation_population([record]) == []

    def test_name_match_is_untrusted_and_out_of_scope(self):
        record = faculty(status=NAME_MATCH, gate=None)
        assert not works_are_verified(record)
        assert not needs_publication_remediation(record)

    def test_population_is_deterministic_and_counts_both_dimensions(self):
        records = [faculty("b"), faculty("a"), faculty("c", works=_WORKS[:1])]
        first = remediation_population(records)
        second = remediation_population(records)
        assert [u["professor_id"] for u in first] == ["a", "b", "c"]
        assert first == second
        summary = population_summary(records)
        # Professors and relationships are different numbers, and the report
        # has to be able to say both. 3 professors, 3+3+1 relationships.
        assert summary["old_gate_professors"] == 3
        assert summary["old_gate_relationships"] == 7


class TestInvalidationWindow:
    def test_old_relationship_becomes_unavailable_while_pending(self):
        """4. Trust is withdrawn the moment the population is identified."""
        record = faculty()
        assert works_are_verified(record)

        assert invalidate_record(record) is True

        assert not works_are_verified(record)
        assert is_pending_remediation(record)
        assert verified_recent_works(record) == []
        # The papers stay as candidates for the re-harvest to be judged
        # against; only the trust is gone.
        assert len(record["metadata"]["recent_works"]) == 3
        # The resolved-author claim goes with the trust: that id asserts "this
        # OpenAlex person is this professor", which is the claim in doubt.
        assert "publication_author_id" not in record["metadata"]

    def test_the_withdrawn_status_is_the_shared_literal(self):
        """The invalidation must write the status the trust module knows, not a
        private string of its own. A drifted literal would be reported by
        `attribution_status` as None — indistinguishable from a legacy record —
        and the ledger, the operator queue and the re-harvest all key on the
        difference between "withdrawn on purpose" and "never stamped"."""
        record = faculty()
        invalidate_record(record)
        assert record["metadata"]["publication_attribution_status"] == PENDING_REMEDIATION
        assert attribution_status(record) == PENDING_REMEDIATION
        assert PENDING_REMEDIATION != VERIFIED_AUTHOR_ID

    def test_invalidation_is_idempotent(self):
        record = faculty()
        assert invalidate_record(record) is True
        snapshot = json.dumps(record, sort_keys=True)
        assert invalidate_record(record) is False
        assert json.dumps(record, sort_keys=True) == snapshot

    def test_invalidation_leaves_the_current_gate_alone(self):
        good = faculty("good", gate=CURRENT_WORKS_GATE)
        stale = faculty("stale", gate=_OLD_GATE)
        result = invalidate_population([good, stale])
        assert result == {"professors_withdrawn": 1, "relationships_withdrawn": 3}
        assert works_are_verified(good)
        assert is_pending_remediation(stale)

    def test_pending_records_are_tracked_separately_from_the_population(self):
        """The two questions — "what is still unsafe" and "what is safe but
        unresolved" — must not collapse into one, or the first hitting zero
        reads as done while thousands of professors are still withdrawn."""
        record = faculty()
        invalidate_record(record)
        assert remediation_population([record]) == []
        assert [u["professor_id"] for u in pending_population([record])] == ["fac-1"]
        assert population_summary([record])["pending_professors"] == 1


class TestDispositions:
    def test_verified_re_attribution_restores_the_relationship(self, ledger):
        """5. Only a fresh verified stamp brings a record back."""
        from src.collectors.openalex_enrich import apply_works

        record = faculty()
        invalidate_record(record)
        entry = {"author_id": "A5000", "works": [{"title": "Real MRI Paper", "year": 2026}]}
        apply_works([record], {unit_for(record)["person_key"]: entry})

        assert works_are_verified(record)
        assert record["metadata"]["works_gate"] == CURRENT_WORKS_GATE
        assert record["metadata"]["publication_author_id"] == "A5000"
        assert [w["title"] for w in verified_recent_works(record)] == ["Real MRI Paper"]
        assert disposition_for(record, entry, harvested=True) == DISPOSITION_VERIFIED

    def test_rediscovery_is_not_verification(self):
        """7 (contract §7). The same paper coming back does not re-trust it —
        the NEW stamp does. A harvest that resolves no author leaves the record
        exactly as untrusted as the withdrawal left it, even though the titles
        on the record are unchanged."""
        from src.collectors.openalex_enrich import apply_works

        record = faculty()
        invalidate_record(record)
        # The pre-provenance bare-list form: same titles, no author id.
        apply_works([record], {unit_for(record)["person_key"]: list(_WORKS)})
        assert not works_are_verified(record)
        assert verified_recent_works(record) == []

    def test_failed_re_attribution_removes_the_trusted_relationship(self):
        """6. The gate rejected every paper: the citations are retracted."""
        from src.collectors.openalex_enrich import apply_works

        record = faculty()
        invalidate_record(record)
        entry = {"author_id": "A5000", "works": []}
        apply_works([record], {unit_for(record)["person_key"]: entry})

        assert "recent_works" not in record["metadata"]
        assert not works_are_verified(record)
        assert record["metadata"]["works_gate"] == CURRENT_WORKS_GATE
        assert disposition_for(record, entry, harvested=True) == DISPOSITION_REMOVED

    def test_retraction_reaches_records_the_withdrawal_already_touched(self):
        """The withdrawal is what makes the record un-verified, so a retraction
        rule keyed only on `works_are_verified` would refuse to clean up
        exactly the records the remediation created. Regression guard."""
        from src.collectors.openalex_enrich import _is_a_retraction

        withdrawn = faculty()
        invalidate_record(withdrawn)
        assert _is_a_retraction({"author_id": "A1", "works": []}, withdrawn)
        # A record already at the current gate is not retracted by a run that
        # merely happened to return nothing for it.
        current = faculty(gate=CURRENT_WORKS_GATE)
        assert not _is_a_retraction({"author_id": "A1", "works": []}, current)
        # And a person nobody asked about is never cleared.
        assert not _is_a_retraction(None, withdrawn)

    def test_ambiguous_attribution_stays_unavailable(self):
        """7. Two candidates the rule cannot separate: no restoration."""
        record = faculty()
        invalidate_record(record)
        assert disposition_for(record, None, harvested=True) == DISPOSITION_AMBIGUOUS
        apply_disposition(record, DISPOSITION_AMBIGUOUS)
        assert not works_are_verified(record)
        assert verified_recent_works(record) == []
        assert "recent_works" not in record["metadata"]

    def test_manual_review_stays_unavailable_until_verified(self):
        """8. Routed to a human; untrusted in the meantime."""
        record = faculty()
        invalidate_record(record)
        apply_disposition(record, DISPOSITION_NEEDS_REVIEW)
        assert not works_are_verified(record)
        assert record["metadata"]["publication_remediation"]["disposition"] == \
            DISPOSITION_NEEDS_REVIEW

    def test_unresolved_unit_loses_its_candidates_and_stops_being_re_bought(self):
        record = faculty()
        invalidate_record(record)
        outcome = apply_disposition(record, DISPOSITION_UNKNOWN)
        assert outcome["relationships_removed"] == 3
        assert "recent_works" not in record["metadata"]
        assert record["metadata"]["works_gate"] == CURRENT_WORKS_GATE


# ---------------------------------------------------------------------------
# 9-15  Ledger / idempotency
# ---------------------------------------------------------------------------

class TestLedger:
    def test_one_logical_ledger_record_per_unit(self, ledger):
        """9."""
        record = faculty()
        unit = unit_for(record)
        ledger.append(unit, QUEUED, relationships_before=3)
        assert ledger.claim(unit) is True
        ledger.append(unit, HARVEST_SUCCEEDED)
        ledger.settle(unit, record, DISPOSITION_VERIFIED)

        index = ledger.index()
        assert list(index) == [unit["idempotency_key"]]
        assert index[unit["idempotency_key"]]["status"] == VERIFIED_COMPLETE
        assert index[unit["idempotency_key"]]["result"] == DISPOSITION_VERIFIED
        assert ledger.duplicate_count() == 0

    def test_retry_after_failure_is_safe(self, ledger):
        """10. A failure leaves the unit claimable, and the second attempt is
        the one that counts."""
        record = faculty()
        unit = unit_for(record)
        assert ledger.claim(unit) is True
        ledger.fail(unit, "OpenAlex 429")
        assert ledger.index()[unit["idempotency_key"]]["status"] == FAILED
        assert ledger.is_complete(unit["idempotency_key"]) is False

        assert ledger.claim(unit) is True
        ledger.settle(unit, record, DISPOSITION_VERIFIED)
        entry = ledger.index()[unit["idempotency_key"]]
        assert entry["status"] == VERIFIED_COMPLETE
        assert entry["attempt_count"] == 2       # retries are allowed...
        assert ledger.duplicate_count() == 0     # ...duplicates are not

    def test_retry_after_committed_success_does_not_reapply(self, ledger):
        """11. The §9 scenario: attempt 1 times out AFTER the commit."""
        record = faculty()
        unit = unit_for(record)
        ledger.claim(unit)
        ledger.settle(unit, record, DISPOSITION_VERIFIED)

        # Attempt 2 arrives. It must decline before touching anything.
        assert ledger.claim(unit) is False
        assert ledger.is_complete(unit["idempotency_key"]) is True
        assert ledger.duplicate_count() == 0

    def test_crash_between_mutation_and_ledger_is_reconciled_not_reapplied(self, ledger):
        """The gap the two files cannot close by ordering: the corpus write
        landed, the ledger append did not. The mutated record is its own proof,
        so the replay records the completion instead of mutating again."""
        from src.collectors.openalex_enrich import apply_works

        record = faculty()
        invalidate_record(record)
        unit = unit_for(record)
        ledger.claim(unit)
        # ...mutation happens and is durable...
        apply_works([record], {unit["person_key"]:
                               {"author_id": "A1", "works": [{"title": "T", "year": 2026}]}})
        # ...and the process dies before settle().
        assert not ledger.is_complete(unit["idempotency_key"])

        before = json.dumps(record, sort_keys=True)
        assert ledger.reconcile(unit, record) is True
        assert json.dumps(record, sort_keys=True) == before   # nothing re-applied
        assert ledger.is_complete(unit["idempotency_key"])
        assert ledger.index()[unit["idempotency_key"]]["reconciled"] is True
        assert ledger.duplicate_count() == 0

    def test_reconcile_refuses_a_unit_whose_mutation_did_not_land(self, ledger):
        record = faculty()          # still at the old gate: no proof of anything
        unit = unit_for(record)
        assert ledger.reconcile(unit, record) is False
        assert not ledger.is_complete(unit["idempotency_key"])

    def test_scheduler_rerun_does_not_reprocess(self, ledger):
        """12."""
        record = faculty()
        unit = unit_for(record)
        ledger.claim(unit)
        ledger.settle(unit, record, DISPOSITION_REMOVED)

        for _ in range(5):          # five nightly reruns
            assert ledger.claim(unit) is False
        assert ledger.report()["completed"] == 1
        assert ledger.duplicate_count() == 0

    def test_concurrent_workers_cannot_both_claim_a_finished_unit(self, ledger):
        """13. Two workers race a unit that already has a result."""
        record = faculty()
        unit = unit_for(record)
        ledger.claim(unit)
        ledger.settle(unit, record, DISPOSITION_VERIFIED)

        results: list[bool] = []
        lock = threading.Lock()

        def worker():
            got = Ledger(ledger.path).claim(dict(unit))
            with lock:
                results.append(got)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results == [False] * 8
        assert ledger.duplicate_count() == 0

    def test_concurrent_appends_do_not_corrupt_the_log(self, ledger):
        """The lock's other job: eight writers, eight readable lines."""
        units = [unit_for(faculty(f"fac-{i}")) for i in range(8)]

        def worker(u):
            Ledger(ledger.path).append(u, QUEUED)

        threads = [threading.Thread(target=worker, args=(u,)) for u in units]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(list(ledger.events())) == 8
        assert len(ledger.index()) == 8

    def test_failed_remediation_is_not_marked_completed(self, ledger):
        """14. Starting, or harvesting nothing, is not completion."""
        record = faculty()
        unit = unit_for(record)
        ledger.append(unit, QUEUED)
        assert ledger.is_complete(unit["idempotency_key"]) is False
        ledger.claim(unit)
        assert ledger.is_complete(unit["idempotency_key"]) is False
        ledger.append(unit, HARVEST_SUCCEEDED)
        assert ledger.is_complete(unit["idempotency_key"]) is False
        ledger.fail(unit, "roster incomplete")
        assert ledger.is_complete(unit["idempotency_key"]) is False
        assert ledger.report()["completed"] == 0

    def test_ledger_preserves_the_final_disposition(self, ledger):
        """15."""
        for rid, disposition in (
            ("a", DISPOSITION_VERIFIED),
            ("b", DISPOSITION_REMOVED),
            ("c", DISPOSITION_AMBIGUOUS),
            ("d", DISPOSITION_NEEDS_REVIEW),
        ):
            record = faculty(rid)
            unit = unit_for(record)
            ledger.claim(unit)
            ledger.settle(unit, record, disposition)

        report = ledger.report()
        assert report["by_result"] == {
            DISPOSITION_VERIFIED: 1,
            DISPOSITION_REMOVED: 1,
            DISPOSITION_AMBIGUOUS: 1,
            DISPOSITION_NEEDS_REVIEW: 1,
        }
        assert report["by_status"] == {VERIFIED_COMPLETE: 3, NEEDS_REVIEW: 1}
        assert report["duplicate_logical_remediations"] == 0

    def test_a_torn_final_line_does_not_destroy_the_audit_trail(self, ledger):
        record = faculty()
        unit = unit_for(record)
        ledger.claim(unit)
        ledger.settle(unit, record, DISPOSITION_VERIFIED)
        with ledger.path.open("a", encoding="utf-8") as fh:
            fh.write('{"idempotency_key": "half-writ')   # crashed mid-append

        assert ledger.is_complete(unit["idempotency_key"])
        assert ledger.duplicate_count() == 0

    def test_a_bumped_gate_is_a_different_logical_unit(self, ledger):
        """The invariant is unit + TARGET GATE. A future gate 3 must be able to
        re-remediate a record gate 2 already settled, without that reading as a
        duplicate."""
        record = faculty()
        unit2 = unit_for(record, to_gate=2)
        unit3 = unit_for(record, to_gate=3)
        assert unit2["idempotency_key"] != unit3["idempotency_key"]
        ledger.claim(unit2)
        ledger.settle(unit2, record, DISPOSITION_VERIFIED)
        assert ledger.claim(unit3) is True
        assert ledger.duplicate_count() == 0

    def test_survives_a_new_process(self, ledger):
        """10 (durability). Proof is on disk, not in memory."""
        record = faculty()
        unit = unit_for(record)
        ledger.claim(unit)
        ledger.settle(unit, record, DISPOSITION_VERIFIED)

        fresh = Ledger(ledger.path)          # a restarted worker
        assert fresh.is_complete(unit["idempotency_key"])
        assert fresh.report()["completed"] == 1

    def test_idempotency_key_is_stable_and_self_describing(self):
        assert idempotency_key("fac-1", 2) == "fac-1@gate2"
        assert unit_for(faculty())["idempotency_key"] == f"fac-1@gate{CURRENT_WORKS_GATE}"


# ---------------------------------------------------------------------------
# 16-18  Re-harvest
# ---------------------------------------------------------------------------

class TestReHarvest:
    def test_withdrawn_records_are_selected_by_the_current_harvest_path(self):
        """16. The remediation reuses `_works_targets`, the supported
        selector, rather than a private list — so a record the withdrawal
        touched is picked up by the same pass a normal harvest uses."""
        from src.collectors.openalex_enrich import _works_targets

        withdrawn = faculty("withdrawn")
        invalidate_record(withdrawn)
        done = faculty("done", gate=CURRENT_WORKS_GATE)
        legacy = faculty("legacy", status=None, gate=None)

        targets = _works_targets([withdrawn, done, legacy], ["uiuc"])
        ids = {t["id"] for t in targets}
        assert "withdrawn" in ids       # withdrawn -> re-harvest
        assert "legacy" in ids          # never stamped -> still a target
        assert "done" not in ids        # judged by the living rule -> skip

    def test_harvest_failure_is_not_verified_completion(self, ledger):
        """17."""
        record = faculty()
        invalidate_record(record)
        unit = unit_for(record)
        ledger.claim(unit)
        ledger.fail(unit, "budget exhausted (confirmed 429)")

        assert ledger.report()["completed"] == 0
        assert not works_are_verified(record)
        # And the record is still in the pending population, so the next run
        # picks it up rather than leaving it stranded.
        assert [u["professor_id"] for u in pending_population([record])] == ["fac-1"]

    def test_a_never_asked_unit_is_not_a_disposition(self):
        """A harvest that did not run must not produce a verdict. `harvested`
        false is `unknown`, never `removed` — the difference between "we asked
        and there is nothing" and "we never asked" is the difference between a
        correction and a fabrication."""
        record = faculty()
        invalidate_record(record)
        assert disposition_for(record, None, harvested=False) == DISPOSITION_UNKNOWN

    def test_rediscovered_paper_without_verified_attribution_stays_blocked(self):
        """18."""
        from src.collectors.openalex_enrich import apply_works

        record = faculty()
        invalidate_record(record)
        # A bare-list answer rediscovers all three titles; none becomes citable.
        apply_works([record], {unit_for(record)["person_key"]: list(_WORKS)})
        assert verified_recent_works(record) == []
        assert not works_are_verified(record)


# ---------------------------------------------------------------------------
# 19-21  The trusted professor record
# ---------------------------------------------------------------------------

class TestTrustedProfessorRecord:
    def test_removed_paper_no_longer_appears_in_the_professor_api(self):
        """19. Through the real projection, not the helper."""
        from backend.routes.opportunities import _redact

        record = faculty(author_id="A-WRONG")
        invalidate_record(record)
        payload = _redact(record)
        md = payload.get("metadata") or {}
        assert "recent_works" not in md
        assert "publication_attribution_status" not in md
        assert "publication_author_id" not in md
        # And the audit trail the withdrawal leaves behind must not become the
        # back door that re-publishes what the strip above removed: it names
        # the gate, the withdrawal time, and the author id we have explicitly
        # stopped standing behind.
        assert "publication_remediation" not in md
        assert "works_gate" not in md
        assert "A-WRONG" not in json.dumps(payload)

    def test_removed_paper_no_longer_appears_on_the_match_card(self):
        """20. The detail/profile surface reads the card projection."""
        from backend.routes.matches import _match_card

        record = faculty()
        invalidate_record(record)
        card = _match_card(record)
        assert "recent_works" not in card
        assert "publication_attribution_status" not in card

    def test_a_verified_paper_still_appears_correctly(self):
        """21. The remediation must not cost a record that is actually fine."""
        from backend.routes.matches import _match_card
        from backend.routes.opportunities import _redact

        record = faculty(gate=CURRENT_WORKS_GATE, author_id="A5000")
        invalidate_population([record])          # a full remediation sweep

        card = _match_card(record)
        assert card["publication_attribution_status"] == VERIFIED_AUTHOR_ID
        assert len(card["recent_works"]) == 2    # card cap, not a removal
        assert (_redact(record)["metadata"]["recent_works"])


# ---------------------------------------------------------------------------
# 22-27  Downstream
# ---------------------------------------------------------------------------
# The exhaustive per-surface sweep lives in tests/test_publication_trust.py,
# whose UNVERIFIED_STATUSES tuple now includes PENDING_REMEDIATION — so every
# surface there is asserted against this status by construction. What follows
# pins the four the contract names explicitly, against a record put into the
# withdrawn state by the REAL invalidation rather than by a hand-set literal.

class TestDownstreamFailsClosed:
    def test_cannot_affect_the_match_score(self):
        """23. Through the real ranker.

        The rule-based ranker reads no publication data at all, which is a
        property worth pinning rather than assuming: a future scorer that
        reached for `recent_works` would silently let a stranger's paper move a
        student's ranking. Scored against a profile whose stated interests are
        the *wrong* papers' topics, a withdrawn record must not out-score the
        same record with no papers at all.
        """
        from src.matcher.ranker import rank_opportunity

        profile = {
            "year": "sophomore", "major": "Electrical Engineering",
            "college": "Grainger College of Engineering",
            "research_interests_text": "long-horizon search agents, geochemical anomalies",
            "desired_fields": ["search agents", "geochemical anomalies"],
            "hard_skills": [], "coursework": [], "seeking_type": ["research"],
            "home_school": "uiuc", "can_cold_email": True, "international_student": False,
        }
        withdrawn = faculty("w")
        invalidate_record(withdrawn)
        paperless = faculty("p", works=None, status=None, gate=None)

        with_papers = rank_opportunity(profile, withdrawn)
        without = rank_opportunity(profile, paperless)
        assert with_papers.final_score == without.final_score
        assert "SearchAuditor" not in json.dumps(
            [with_papers.reasons_fit, with_papers.reasons_gap, with_papers.next_steps]
        )

    def test_cannot_enter_the_match_reason_the_model_sees(self, monkeypatch):
        """22. The rerank candidate text is where papers actually reach a
        model, so that is where the exclusion has to be observed."""
        from backend.routes import matches
        from src.matcher.ranker import MatchResult

        captured: dict = {}
        monkeypatch.setattr(matches, "_resolve", lambda *a, **k: object())

        def fake_score(query, cand):
            captured["cand"] = dict(cand)
            return {c[0]: {"s": 50.0, "r": ""} for c in cand}

        monkeypatch.setattr(matches, "_llm_score_candidates", fake_score)

        withdrawn = faculty("wd")
        invalidate_record(withdrawn)
        results = [
            MatchResult(opportunity_id="wd", eligibility_score=50, readiness_score=50,
                        upside_score=50, final_score=50.0, bucket="good_match",
                        reasons_fit=[], reasons_gap=[], next_steps=[])
        ]
        matches.llm_rerank({"research_interests_text": "q"}, results, {"wd": withdrawn})
        assert "SearchAuditor" not in json.dumps(captured.get("cand"))

    def test_cannot_enter_ask_ai_prompt_context(self):
        """24 + 25. Filtered before the context is built, not after."""
        from backend.routes.cold_email import _format_recent_works

        record = faculty()
        invalidate_record(record)
        assert _format_recent_works(record) == ""

    def test_cannot_influence_resume_tailoring(self):
        """26. The tailor prompt is built from profile + target text and never
        reads publications at all; assert the absence rather than assume it."""
        import inspect

        from backend.routes import tailor

        source = inspect.getsource(tailor)
        assert "recent_works" not in source
        assert "publication_attribution_status" not in source

    def test_cannot_enter_a_cold_email(self):
        """27. The claim this whole effort exists to stop.

        "Your recent paper on SearchAuditor…" in an email a student sends under
        their own name, to a professor who did not write it.
        """
        from src.recommender.cold_email import _common_parts

        record = faculty(keywords=(), keyword_source=None)
        invalidate_record(record)
        profile = {"name": "A Student", "year": "sophomore", "major": "ECE",
                   "school": "UIUC", "hard_skills": []}
        parts = _common_parts(profile, record)
        assert not parts.get("recent_works")
        assert "SearchAuditor" not in json.dumps(parts)

    def test_a_withdrawn_paper_cannot_be_the_evidence_that_unlocks_a_draft(self):
        """The gate one level up: a verified paper is one of the things that
        lets the provider personalize at all. A record whose ONLY specific
        signal was its papers must stop qualifying when they are withdrawn,
        or the draft runs and has to invent its specificity."""
        from src.recommender.cold_email import has_source_backed_target_evidence

        record = faculty(keywords=(), keyword_source=None)
        record["description_clean"] = ""
        assert has_source_backed_target_evidence(record) is True
        invalidate_record(record)
        assert has_source_backed_target_evidence(record) is False


# ---------------------------------------------------------------------------
# 28-31  Derived artifacts
# ---------------------------------------------------------------------------

class TestDerivedArtifacts:
    def test_keywords_from_the_discredited_resolution_are_invalidated(self):
        """28 + 30. The sibling derivation.

        `metadata.keywords` stamped derived:openalex_topics came from the SAME
        author resolution that chose the papers. When the re-judgement destroys
        the relationship, the description that rests on the same evidence goes
        with it — otherwise the professor keeps being described by a stranger's
        research areas after the stranger's papers have been taken away.
        """
        record = faculty()
        invalidate_record(record)
        outcome = apply_disposition(record, DISPOSITION_AMBIGUOUS)

        assert outcome["keywords_invalidated"] is True
        # Emptied, not deleted: the field's shape is part of the record
        # contract, and an empty list is what makes the record a target for the
        # next keyword harvest.
        assert record["keywords"] == []
        assert "keywords" not in (record["metadata"].get("inferred_fields") or {})

    def test_scraped_keywords_survive_because_they_share_no_provenance(self):
        """The other half, and the reason this is not a blanket delete: a
        keyword the professor's own page stated is not evidence from OpenAlex
        and is not impeached by anything the re-harvest found."""
        record = faculty(keyword_source=None)
        invalidate_record(record)
        outcome = apply_disposition(record, DISPOSITION_AMBIGUOUS)

        assert outcome["keywords_invalidated"] is False
        assert record["keywords"] == ["magnetic resonance imaging"]

    def test_a_re_verified_record_keeps_its_derived_keywords(self):
        """Destroying the derivation is the cost of destroying the
        relationship. A record the current gate re-verifies has had its
        resolution confirmed, so there is nothing to invalidate."""
        record = faculty()
        invalidate_record(record)
        outcome = apply_disposition(record, DISPOSITION_VERIFIED)
        assert outcome["keywords_invalidated"] is False
        assert record["keywords"] == ["magnetic resonance imaging"]
        assert "publication_remediation" not in record["metadata"]

    def test_the_client_match_cache_is_invalidated_by_version(self):
        """29 + 31. A cached match page carries `recent_works` copied off the
        card, so a seven-day local payload would keep rendering revoked
        citations — and keep feeding them to a cold-email draft — after the
        server stopped serving them. The cache version is the invalidation."""
        from pathlib import Path

        source = Path("frontend/src/lib/match-cache.ts").read_text(encoding="utf-8")
        assert "pubtrust-v3" in source, (
            "the historical remediation changes what a cached match page may "
            "contain; CACHE_VERSION must move with it"
        )

    def test_the_withdrawal_is_recorded_on_the_record_for_audit(self):
        record = faculty(author_id="A-WRONG")
        invalidate_record(record)
        block = record["metadata"]["publication_remediation"]
        assert block["from_gate"] == _OLD_GATE
        assert block["to_gate"] == CURRENT_WORKS_GATE
        assert block["prior_status"] == VERIFIED_AUTHOR_ID
        assert block["prior_author_id"] == "A-WRONG"
        assert block["withdrawn_at"]


# ---------------------------------------------------------------------------
# Manual review routing
# ---------------------------------------------------------------------------

class TestManualReview:
    def test_unsettled_units_reach_the_review_queue_with_evidence(self, ledger):
        settled = faculty("settled")
        unclear = faculty("unclear")
        for record, disposition in ((settled, DISPOSITION_VERIFIED),
                                    (unclear, DISPOSITION_AMBIGUOUS)):
            unit = unit_for(record)
            ledger.claim(unit)
            ledger.settle(unit, record, disposition)

        queue = ledger.manual_review_queue()
        assert [row["professor_id"] for row in queue] == ["unclear"]
        row = queue[0]
        assert row["reason"] == DISPOSITION_AMBIGUOUS
        assert row["review_status"] == "open"
        assert row["school"] == "uiuc"
        assert row["dedup_key"].startswith("manual_review:publication_attribution:")
        assert row["from_gate_version"] == _OLD_GATE

    def test_a_queued_review_does_not_restore_trust(self):
        record = faculty()
        invalidate_record(record)
        apply_disposition(record, DISPOSITION_NEEDS_REVIEW)
        assert verified_recent_works(record) == []


# ---------------------------------------------------------------------------
# The pipeline enforces the invariant without anyone running a script
# ---------------------------------------------------------------------------

class TestPipelineEnforcement:
    def test_refresh_all_withdraws_superseded_trust_every_run(self):
        """§2 of the contract: production must not depend on a human
        remembering to run a CLI. The refresh pass is the enforcement."""
        import inspect

        from src.collectors import refresh_all

        source = inspect.getsource(refresh_all)
        assert "invalidate_population(all_opps)" in source
        assert 'summary["sources"]["publication_remediation"]' in source

    def test_the_pass_is_idempotent_over_a_clean_corpus(self):
        clean = [faculty("a", gate=CURRENT_WORKS_GATE), faculty("b", status=None, gate=None)]
        assert invalidate_population(clean) == {
            "professors_withdrawn": 0, "relationships_withdrawn": 0
        }
