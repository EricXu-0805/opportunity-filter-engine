"""Target truth contract: may a student act on this record today?

The defect this pins: 861 UCB URAP records carry
``metadata.urap_status='closed'`` together with ``metadata.is_active=True``
(top-level ``is_active`` is absent entirely). Their own description says the
listing is closed and shown only as a reference, yet ``hard_exclusion`` looked
solely at ``metadata.is_active is False`` — so they ranked into High Priority
and exposed Apply / Tailor / Cold Email / Renovate.

Closed and reference-only are kept as two dimensions, not one flag: a source
may publish a closed listing that is still worth reading, and may publish a
reference record that was never a listing.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from backend.data_loader import load_opportunities_by_id
from backend.lib.public_projection import (
    neutralize_lifecycle_title,
    project_public_opportunity_payload,
    public_target_truth,
)
from backend.main import app
from backend.routes import opportunities as opportunities_module

# Frozen here rather than imported — see the drift-detection test in
# tests/test_public_contact_projection.py, which pins production against it.
_EXPECTED_EVIDENCE_KEYS = frozenset({
    "is_active",
    "listing_status",
    "urap_status",
    "reference_only",
    "last_verified",
    "expires_at",
    "faculty_availability_status",
    "faculty_availability_scan_version",
    "faculty_not_accepting_undergraduates_stated",
    "faculty_research_inactive_stated",
})
from src.evidence import record_kind, target_truth

SHARDS_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "shards"


@pytest.fixture(scope="module")
def committed_shard_corpus() -> dict[str, dict]:
    """The corpus as it is COMMITTED, read straight from the shards.

    The loader fixture below prefers `data/processed/opportunities.json` when
    it exists — and it does exist in a working tree, while being gitignored.
    So a loader-only receipt still proves nothing about what deploys. This
    reads the committed shards directly, first-id-wins on the (currently
    empty) intersection, and the test below asserts the two agree.
    """
    corpus: dict[str, dict] = {}
    for shard in sorted(SHARDS_DIR.glob("*.json")):
        with shard.open() as handle:
            for record in json.load(handle):
                corpus.setdefault(record["id"], record)
    return corpus


@pytest.fixture(scope="module")
def served_corpus() -> dict[str, dict]:
    """The corpus keyed by id, through the loader production actually uses.

    Previously this read ``data/processed/opportunities.json`` directly and
    skipped when it was absent. That file is GITIGNORED — it is the assembled
    work file, not the committed form — so on a clean checkout every receipt
    below silently skipped, and CI reported green while proving nothing about
    the shards that actually deploy.

    ``load_opportunities_by_id`` is the same entry point the routes call, and
    it falls back to ``data/processed/shards/*.json`` when the work file is
    missing. Both paths are verified to yield the identical 26 unreviewed
    rows, so the receipt now holds in a clean checkout instead of vanishing.
    """
    return load_opportunities_by_id()


def _record(**overrides) -> dict:
    record = {
        "id": "ucb-urap-proj-test",
        "source": "ucb_urap_projects",
        "source_type": "ucb_program",
        "title": "Machine learning approaches to image processing",
        "metadata": {
            "urap_status": "closed",
            "is_active": True,
            "last_verified": "2026-07-21T08:18:35.780761",
        },
    }
    record.update(overrides)
    return record


class TestClosedListing:
    def test_closed_plus_active_poison_is_not_actionable(self):
        """The exact live shape: status closed, is_active True."""
        truth = target_truth(_record())
        assert truth.listing_state == "closed"
        assert truth.reference_only is True
        assert truth.actionable is False
        assert truth.accepting_state == "not_accepting"
        assert truth.reason_code == "listing_closed"

    def test_evidence_names_the_field_that_decided_it(self):
        truth = target_truth(_record())
        assert truth.evidence_source == "metadata"
        assert truth.evidence_key == "urap_status"
        assert truth.evidence_value == "closed"

    def test_verified_at_is_read_never_invented(self):
        assert target_truth(_record()).verified_at == "2026-07-21T08:18:35.780761"
        bare = _record(metadata={"urap_status": "closed", "is_active": True})
        assert target_truth(bare).verified_at is None
        assert target_truth(bare).expires_at is None

    @pytest.mark.parametrize("raw", ["closed", "CLOSED", "  Closed  ", "\tclosed\n"])
    def test_status_match_ignores_case_and_whitespace(self, raw):
        truth = target_truth(_record(metadata={"urap_status": raw, "is_active": True}))
        assert truth.actionable is False
        assert truth.reason_code == "listing_closed"


class TestOpenListing:
    def test_open_status_stays_actionable(self):
        truth = target_truth(_record(metadata={"urap_status": "open", "is_active": True}))
        assert truth.listing_state == "open"
        assert truth.reference_only is False
        assert truth.actionable is True
        assert truth.accepting_state == "accepting"
        assert truth.reason_code is None


class TestInactiveIsItsOwnReason:
    def test_generic_inactive_keeps_the_existing_reason_code(self):
        """`inactive` predates this contract and must not be renamed."""
        truth = target_truth({"id": "x", "metadata": {"is_active": False}})
        assert truth.actionable is False
        assert truth.reason_code == "inactive"

    def test_closed_outranks_inactive_so_a_refresh_cannot_blur_the_reason(self):
        """The fixed collector writes BOTH markers on a past project.

        If `inactive` won, every closed URAP record would silently change its
        reason from `listing_closed` to `inactive` the first time the source is
        re-collected — the same record, the same closure, a vaguer answer.
        """
        truth = target_truth(
            _record(metadata={"urap_status": "closed", "is_active": False}),
        )
        assert truth.reason_code == "listing_closed"
        assert truth.actionable is False
        assert truth.listing_state == "closed"

    def test_inactive_never_reports_an_open_listing_as_accepting(self):
        """A deactivated record cannot be accepting, whatever its stale status."""
        truth = target_truth(
            _record(metadata={"urap_status": "open", "is_active": False}),
        )
        assert truth.actionable is False
        assert truth.accepting_state != "accepting"


class TestReferenceOnlyIsASeparateDimension:
    def test_explicit_reference_marker_without_a_closed_status(self):
        truth = target_truth(
            _record(metadata={"reference_only": True, "is_active": True}),
        )
        assert truth.reference_only is True
        assert truth.actionable is False
        assert truth.reason_code == "reference_only"
        assert truth.listing_state == "unknown"

    @pytest.mark.parametrize("status", ["closed", "past", "archived", "expired"])
    def test_a_closed_listing_is_not_reference_material_by_default(self, status):
        """Closed means "you cannot apply", not "we publish this as a reference".

        URAP earns `reference_only` because its collector states that contract
        in prose. A generic expired posting from any other source states no
        such thing, and claiming it does would invent an editorial promise the
        source never made.
        """
        truth = target_truth({
            "id": "x",
            "source": "some_other_board",
            "metadata": {"urap_status": status, "is_active": True},
        })
        assert truth.listing_state == "closed"
        assert truth.actionable is False
        assert truth.reason_code == "listing_closed"
        assert truth.reference_only is False

    def test_ucb_urap_closed_records_do_carry_the_reference_contract(self):
        truth = target_truth(_record())
        assert truth.reference_only is True
        assert truth.reason_code == "listing_closed"


class TestConflictingStatusKeysFailClosed:
    """A vaguer key must never mask an explicit closure.

    ``_listing_status`` consulted the authoritative keys in order and stopped at
    the first non-empty one, so a record carrying both ``listing_status`` and
    ``urap_status`` was decided by whichever key came first — including when
    that key said nothing useful and the other said "closed".
    """

    def test_unknown_in_the_first_key_does_not_mask_a_closed_second_key(self):
        truth = target_truth(_record(metadata={
            "listing_status": "unknown",
            "urap_status": "closed",
            "is_active": True,
        }))
        assert truth.listing_state == "closed"
        assert truth.actionable is False
        assert truth.reason_code == "listing_closed"
        assert truth.evidence_key == "urap_status"
        assert truth.evidence_value == "closed"

    def test_open_in_the_first_key_does_not_beat_a_closed_second_key(self):
        truth = target_truth(_record(metadata={
            "listing_status": "open",
            "urap_status": "closed",
            "is_active": True,
        }))
        assert truth.listing_state == "closed"
        assert truth.actionable is False
        assert truth.evidence_key == "urap_status"

    def test_closed_first_key_beats_a_recognized_open_second_key(self):
        """The reverse conflict: closure wins from either side, not by position."""
        truth = target_truth(_record(metadata={
            "listing_status": "closed",
            "urap_status": "open",
            "is_active": True,
        }))
        assert truth.listing_state == "closed"
        assert truth.actionable is False
        assert truth.reason_code == "listing_closed"
        assert truth.evidence_key == "listing_status"
        assert truth.evidence_value == "closed"

    def test_garbage_in_the_second_key_does_not_mask_a_closed_first_key(self):
        truth = target_truth(_record(metadata={
            "listing_status": "closed",
            "urap_status": "whatever",
            "is_active": True,
        }))
        assert truth.listing_state == "closed"
        assert truth.evidence_key == "listing_status"

    def test_a_recognized_open_still_wins_when_no_key_says_closed(self):
        truth = target_truth(_record(metadata={
            "listing_status": "unknown",
            "urap_status": "open",
            "is_active": True,
        }))
        assert truth.listing_state == "open"
        assert truth.actionable is True
        assert truth.accepting_state == "accepting"


class TestLegacyAndMalformed:
    def test_legacy_record_without_status_keeps_todays_behaviour(self):
        """This PR must not turn the rest of the corpus non-actionable.

        `source_type` is part of "the rest of the corpus": 135,287 of the
        135,877 rows carry one. A record without it is a different case,
        pinned below.
        """
        truth = target_truth({
            "id": "x", "source_type": "faculty_research",
            "metadata": {"is_active": True},
        })
        assert truth.listing_state == "unknown"
        assert truth.reference_only is False
        assert truth.actionable is True
        assert truth.accepting_state == "unknown"
        assert truth.reason_code is None

    def test_an_unreviewed_source_type_is_not_actionable(self):
        """The 26 rows nobody has classified.

        Being unable to say what a record IS is not a reason to treat it as a
        listing. Decided here rather than at each surface: otherwise every
        card, digest, export and facet maintains its own third state, and one
        of them eventually defaults it to "listing".
        """
        truth = target_truth({"id": "x", "metadata": {"is_active": True}})
        assert truth.actionable is False
        assert truth.reason_code == "record_kind_unverified"
        assert truth.listing_state == "unknown"
        # Not reference material: nobody published it as such, and saying so
        # would invent an editorial claim the source never made.
        assert truth.reference_only is False
        assert truth.accepting_state == "unknown"

    @pytest.mark.parametrize("source_type", ["campus_program", "faculty_research"])
    def test_a_reviewed_source_type_stays_actionable(self, source_type):
        truth = target_truth({"id": "x", "source_type": source_type, "metadata": {}})
        assert truth.actionable is True
        assert truth.reason_code is None

    def test_a_more_specific_reason_still_wins_over_the_unreviewed_kind(self):
        """Copy accuracy: an unreviewed row that ALSO states it closed.

        The closure is the more specific fact and gets the reason, so the
        student is told what the source said rather than a vaguer truth about
        our own review queue.
        """
        truth = target_truth({
            "id": "x", "metadata": {"urap_status": "closed", "is_active": True},
        })
        assert truth.reason_code == "listing_closed"

    def test_record_with_no_metadata_at_all(self):
        # No metadata AND no source_type: the truth still resolves without
        # raising, and reports the one thing it can say — nobody has confirmed
        # what this is.
        truth = target_truth({"id": "x"})
        assert truth.actionable is False
        assert truth.reason_code == "record_kind_unverified"
        assert truth.listing_state == "unknown"

    def test_record_with_no_metadata_but_a_reviewed_kind(self):
        truth = target_truth({"id": "x", "source_type": "campus_program"})
        assert truth.actionable is True
        assert truth.listing_state == "unknown"

    @pytest.mark.parametrize(
        "metadata",
        [
            "not-a-dict",
            ["also", "not", "a", "dict"],
            42,
            None,
            {"urap_status": 42, "is_active": True},
            {"urap_status": ["closed"], "is_active": True},
            {"urap_status": None, "is_active": True},
            {"reference_only": "yes-ish", "is_active": True},
            {"is_active": "true"},
        ],
    )
    def test_malformed_metadata_never_raises(self, metadata):
        truth = target_truth({"id": "x", "metadata": metadata})
        assert truth.actionable in (True, False)
        assert truth.listing_state in ("open", "closed", "unknown")


class TestServedCorpusRegression:
    """The shield over the 861 rows already committed to the shard.

    Counts are deliberately not asserted: the shard is data and a refresh may
    legitimately change how many closed projects exist. What must hold is the
    semantic exclusion — no record that states it is closed or reference-only
    is ever actionable, whatever the count.
    """

    SAMPLE_ID = "ucb-urap-proj-40703a6958e1"

    def test_the_real_closed_sample_is_non_actionable(self, served_corpus):
        record = served_corpus.get(self.SAMPLE_ID)
        assert record is not None, "sample must stay in the corpus as reference"
        truth = target_truth(record)
        assert truth.actionable is False
        assert truth.reason_code == "listing_closed"
        assert truth.reference_only is True
        assert truth.accepting_state == "not_accepting"
        assert truth.evidence_key == "urap_status"
        assert truth.evidence_value == "closed"

    def test_no_explicitly_closed_record_anywhere_is_actionable(self, served_corpus):
        leaked = [
            record["id"]
            for record in served_corpus.values()
            if target_truth(record).listing_state == "closed"
            and target_truth(record).actionable
        ]
        assert not leaked, f"{len(leaked)} closed records still actionable, e.g. {leaked[:5]}"

    def test_no_reference_only_record_anywhere_is_actionable(self, served_corpus):
        leaked = [
            record["id"]
            for record in served_corpus.values()
            if target_truth(record).reference_only and target_truth(record).actionable
        ]
        assert not leaked, f"{len(leaked)} reference records still actionable, e.g. {leaked[:5]}"

    def test_the_shield_does_not_retire_the_rest_of_the_corpus(self, served_corpus):
        """Guard against over-reach: the unstamped majority stays actionable."""
        actionable = sum(1 for r in served_corpus.values() if target_truth(r).actionable)
        assert actionable > len(served_corpus) * 0.9


class TestTheUnreviewedRowsAreNamed:
    """An exact receipt for the 26 rows this contract removed from action.

    A percentage guard ("<1% affected") cannot show that the RIGHT rows were
    affected, and a >90% actionable check passes just as happily if a
    different 26 disappeared. So: the count, and the id set, pinned.

    Sorted before hashing — the corpus is a JSON array whose order is a
    refresh artefact, and a test that depended on it would fail for reasons
    that have nothing to do with truth.
    """

    def _unreviewed(self, served_corpus) -> list[dict]:
        return sorted(
            (r for r in served_corpus.values() if record_kind(r) == "unknown"),
            key=lambda r: r["id"],
        )

    def test_exactly_twenty_six_rows_have_an_unreviewed_kind(self, served_corpus):
        rows = self._unreviewed(served_corpus)
        assert len(rows) == 26
        digest = hashlib.sha256(
            ",".join(r["id"] for r in rows).encode(),
        ).hexdigest()
        assert digest == (
            "5a53b51e43355e535bfcbc2e542d9c1933d20bf2b9bacf41f1f865dc403c2cc9"
        )
        # Endpoints of the sorted set, so a failure names something a human can
        # look up rather than only reporting that a hash moved.
        assert rows[0]["id"] == "0088a9eb2812c2f4"
        assert rows[-1]["id"] == "f77770a1733a0600"

    def test_the_id_and_reason_pairing_is_frozen(self, served_corpus):
        """Which rows, AND what each one is refused for.

        The id-only digest above cannot see a reason changing underneath a
        stable id — a row silently moving from "we never confirmed what this
        is" to "this closed" is a different sentence shown to a student, from
        the same 26 ids. Pairing them is what makes that visible.

        Deliberately NOT a digest over the whole projected payload: that
        would include `verified_at`, and a legitimate verification refresh
        would then fail a build for a reason unrelated to truth.
        """
        rows = self._unreviewed(served_corpus)
        digest = hashlib.sha256(
            ",".join(f"{r['id']}:{target_truth(r).reason_code}" for r in rows).encode(),
        ).hexdigest()
        assert digest == (
            "d67c30f6b15b8c366e9c795589dcf29e22d38943e83b202ddb314cf1d6036fa1"
        )

    def test_the_committed_shards_carry_the_same_twenty_six(
        self, committed_shard_corpus, served_corpus,
    ):
        """The receipt above, re-derived from what is actually in git.

        A working tree has the assembled work file, so the loader reads that
        and never touches a shard. Deployment has only the shards. Asserting
        the same digest from both is what makes the receipt meaningful on a
        clean checkout rather than an artefact of one developer's machine.
        """
        rows = self._unreviewed(committed_shard_corpus)
        assert len(rows) == 26
        digest = hashlib.sha256(
            ",".join(f"{r['id']}:{target_truth(r).reason_code}" for r in rows).encode(),
        ).hexdigest()
        assert digest == (
            "d67c30f6b15b8c366e9c795589dcf29e22d38943e83b202ddb314cf1d6036fa1"
        )
        assert [r["id"] for r in rows] == [
            r["id"] for r in self._unreviewed(served_corpus)
        ]

    @pytest.mark.parametrize("corpus_name", ["served_corpus", "committed_shard_corpus"])
    def test_each_row_carries_the_exact_public_envelope(self, corpus_name, request):
        # Field by field, not just "non-actionable". The seven-key shape is
        # what a client branches on, and an eighth key would be an internal
        # evidence path reaching a browser.
        #
        # Run against BOTH sources. The assembled work file is gitignored, so
        # a claim proven only against it is a claim about one machine.
        corpus = request.getfixturevalue(corpus_name)
        for record in self._unreviewed(corpus):
            truth = public_target_truth(record)
            assert set(truth) == {
                "listing_state", "reference_only", "actionable",
                "accepting_state", "reason_code", "verified_at", "expires_at",
            }, record["id"]
            assert record_kind(record) == "unknown", record["id"]
            assert truth["reason_code"] == "record_kind_unverified", record["id"]
            assert truth["actionable"] is False, record["id"]
            assert truth["listing_state"] == "unknown", record["id"]
            assert truth["reference_only"] is False, record["id"]
            assert truth["accepting_state"] == "unknown", record["id"]
            assert truth["expires_at"] is None, record["id"]
            # Read from the record, never synthesized — so it is asserted as
            # present-and-a-string rather than pinned to a value that a
            # re-verification pass is supposed to move.
            assert isinstance(truth["verified_at"], str), record["id"]

    @pytest.mark.parametrize("corpus_name", ["served_corpus", "committed_shard_corpus"])
    def test_the_two_misleading_titles_no_longer_claim_an_open_round(
        self, corpus_name, request,
    ):
        """The runtime defect, named by id.

        Both rows shipped a payload that said "record type unverified" and,
        in the title directly above it, "(applications open)". The expected
        strings below are written out rather than computed, so a neutralizer
        that stopped working could not quietly redefine what passing means.

        Run against both corpora: the assembled file could agree with the
        shards on ids and reasons while carrying different TITLES, and this
        is the only assertion about the actual defect.
        """
        corpus = request.getfixturevalue(corpus_name)
        expected = {
            "b27723bb1ca91202":
                "URSA — Undergraduate Research in Scientific Advancement",
            # The second parenthetical is NOT a lifecycle claim and survives.
            "a22e863a3bd7ce87":
                "CS DRP — Directed Reading Program (Computer Science, Winter Break)",
        }
        for opportunity_id, base_title in expected.items():
            record = corpus[opportunity_id]
            assert record_kind(record) == "unknown"
            # The raw record really does make the claim — otherwise this test
            # would pass on a corpus where there was nothing to fix.
            assert record["title"].casefold().endswith("(applications open)")
            assert neutralize_lifecycle_title(record.get("title"), record) == base_title

    @pytest.mark.parametrize("corpus_name", ["served_corpus", "committed_shard_corpus"])
    def test_the_batch_projection_of_all_twenty_six_is_exact(self, corpus_name, request):
        """One receipt over the whole set, through the real projector.

        Asserted as properties rather than as a digest of the output: the
        payload carries `verified_at`, so a frozen hash would turn a routine
        re-verification into an unrelated red build.

        Both corpora, for the same reason as the envelope test above.
        """
        rows = self._unreviewed(request.getfixturevalue(corpus_name))
        before = deepcopy(rows)
        projected = [
            project_public_opportunity_payload(deepcopy(r), r) for r in rows
        ]
        assert len(projected) == 26
        assert [p["id"] for p in projected] == [r["id"] for r in rows]
        for payload in projected:
            assert payload["record_kind"] == "unknown", payload["id"]
            assert payload["target_truth"]["actionable"] is False, payload["id"]
            for field in (
                "deadline", "deadline_is_estimate", "is_rolling", "posted_date",
                "start_date", "paid", "compensation_details", "duration",
                "opportunity_type", "on_campus", "remote_option", "location",
                "audience", "description_clean", "description_raw", "description",
                "status", "semester",
            ):
                assert field not in payload, (payload["id"], field)
            if "eligibility" in payload:
                assert payload["eligibility"] == {}, payload["id"]
            if "application" in payload:
                assert payload["application"] == {}, payload["id"]
            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                # Written out, not imported: deriving the absence check from
                # the production set would let deleting a key there shrink
                # this loop and still pass.
                for evidence_key in _EXPECTED_EVIDENCE_KEYS | {"deadline_note"}:
                    assert evidence_key not in metadata, (payload["id"], evidence_key)
        # Title-by-title, against the shared helper rather than against a
        # substring ban. "applications open" is legitimate inside prose — a
        # description reading "Learn when applications open" says something
        # true — and only a TERMINAL parenthetical is a false opening claim.
        for payload, record in zip(projected, rows, strict=True):
            assert payload["title"] == neutralize_lifecycle_title(
                record.get("title"), record,
            ), payload["id"]
        # The loader hands out the process-wide corpus. A projection that
        # wrote through to it would corrupt every later request in the worker.
        assert rows == before

    def test_every_one_of_them_is_non_actionable_for_a_stated_reason(
        self, served_corpus,
    ):
        for record in self._unreviewed(served_corpus):
            truth = target_truth(record)
            assert truth.actionable is False, record["id"]
            # Exact, not a set of four. The reason ladder still allows a more
            # specific fact to win — a closure, reference material, a
            # deactivation — and the contract test for that lives in
            # TestTheRecordKindLadder. What is asserted HERE is the state of
            # these 26 rows today: none of them states anything more
            # specific, so all 26 say `record_kind_unverified`. A four-way
            # allowance would let a row change its sentence to a student
            # without any test noticing.
            assert truth.reason_code == "record_kind_unverified", (
                record["id"], truth.reason_code,
            )

    def test_none_of_them_has_a_source_type_we_recognise(self, served_corpus):
        for record in self._unreviewed(served_corpus):
            source_type = record.get("source_type")
            assert source_type in (None, ""), (record["id"], source_type)

    def test_they_stay_readable_even_though_they_are_not_actionable(
        self, served_corpus,
    ):
        # Removing them from action is not removing them from the product: the
        # record still resolves, and the source link is still the way a
        # student finds out what it actually is.
        for record in self._unreviewed(served_corpus):
            assert record.get("title"), record["id"]
            assert record.get("source_url") or record.get("url"), record["id"]


class TestStagedRolloutWireContract:
    """The truth ships without moving the version string — permanently.

    Vercel and Render deploy independently, and a stale bundle or a long-open
    tab can speak the old wire long after both services are current. There is
    no safe moment for a global rename, so the promise travels as its own
    marker and the version stays put. A future v4 would need explicit client
    capability negotiation, not a flip.
    """

    def test_the_public_wire_version_is_frozen_at_v3(self):
        from backend.routes.matches import (
            MATCH_CONTRACT_VERSION,
            MATCH_VIEW_CONTRACT_VERSION,
        )

        assert MATCH_CONTRACT_VERSION == "match-page-v3-faculty-trust"
        assert MATCH_VIEW_CONTRACT_VERSION == "match-view-v3-faculty-trust"

    def test_the_internal_snapshot_version_did_move(self):
        """A pre-filter snapshot still holds the closed rows and the bucket
        thresholds derived from them, so it must not be reused."""
        from backend.routes.matches import (
            MATCH_SNAPSHOT_VERSION,
            MATCH_VIEW_CONTRACT_VERSION,
        )

        assert MATCH_SNAPSHOT_VERSION == "match-snapshot-v5-record-kind"
        assert MATCH_SNAPSHOT_VERSION != MATCH_VIEW_CONTRACT_VERSION

    def test_the_snapshot_key_keys_off_the_snapshot_version(self, monkeypatch):
        from backend.routes import matches as matches_module

        before = matches_module._snapshot_key({"school": "uiuc"}, False, "corpus-1")
        monkeypatch.setattr(matches_module, "MATCH_SNAPSHOT_VERSION", "match-snapshot-v5")
        after = matches_module._snapshot_key({"school": "uiuc"}, False, "corpus-1")
        assert before != after

    def test_the_marker_is_its_own_constant(self):
        from backend.routes.matches import TARGET_TRUTH_CONTRACT

        # v2 since `record_kind_unverified` joined the reason set: a v1 client
        # cannot parse it, so the marker has to move even though the wire
        # version deliberately does not.
        assert TARGET_TRUTH_CONTRACT == "target-truth-v2"

    def test_a_cursor_round_trips_under_the_v3_wire_version(self):
        """The cursor stays readable across this release.

        Invalidating it would break pagination mid-session for a client that
        is otherwise working fine — the opposite of what a compatible release
        does.
        """
        import base64
        import json

        from backend.routes import matches as matches_module

        def stamped_version(cursor: str) -> str:
            padded = cursor + "=" * (-len(cursor) % 4)
            return json.loads(base64.b64decode(padded, altchars=b"-_"))["v"]

        # Real-shaped ids: the decoder requires the 64-char hashes production
        # mints, so a short fixture would fail for its own reasons and prove
        # nothing about the contract.
        result_set_id = "a" * 64
        view_id = "b" * 64

        # Round-trip through the real signature check, so this covers the
        # signature and the version together — and the version matters because
        # it travels INSIDE the cursor: bumping the wire version would
        # invalidate every cursor a client is already holding, breaking
        # pagination mid-session for a client that is otherwise fine.
        page_cursor = matches_module._encode_match_cursor(result_set_id, 50)
        assert matches_module._decode_match_cursor(page_cursor) == (result_set_id, 50)
        assert stamped_version(page_cursor) == "match-page-v3-faculty-trust"

        view_cursor = matches_module._encode_match_view_cursor(result_set_id, view_id, 50)
        assert matches_module._decode_match_view_cursor(view_cursor) == (
            result_set_id, view_id, 50,
        )
        assert stamped_version(view_cursor) == "match-view-v3-faculty-trust"

    def test_neither_dead_cursor_code_asks_the_client_to_retry(self):
        """Replaying a dead cursor cannot succeed.

        Marked retryable, the client's generic retry layer sent the same dead
        cursor twice more — three rate-limited requests to reach the answer the
        first response already gave. Recovery is a fresh page-1 request.
        """
        source = (
            Path(__file__).parents[1] / "backend" / "routes" / "matches.py"
        ).read_text()
        for block in source.split('"code": "MATCH_CURSOR_EXPIRED"')[1:]:
            head = block[: block.index("}")]
            assert '"retryable": False' in head, head


# ---------------------------------------------------------------------------
# The historical-detail capability bridge
# ---------------------------------------------------------------------------
# Vercel and Render deploy independently. During the rollout window a HEAD
# bundle asks for detail with the OLD release scope, and that bundle cannot
# read a target truth: it renders a surviving source URL as "Apply" on a record
# this contract has already retired. There is nowhere to put the truth such an
# old client would honour, so the backend fails closed instead — historical
# detail is served only to a caller that proves, by sending the exact current
# full scope, that it is the truth-aware build.
#
# What this cannot do is revoke a link an old tab has ALREADY painted. That is
# a release-governance stop, not something to fix by weakening the gate.

_BRIDGE_CLIENT = TestClient(app)

CURRENT_TRUTH_AWARE_SCOPE = (
    "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
)
_OLD_SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1"
_FUTURE_SCOPE = (
    "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v3"
)

# Every shape the query can arrive in. `duplicate` and `mixed` are the reason
# the check reads the whole list rather than a first value: a proxy, a retry
# layer or a hand-edited URL can repeat the parameter, and "the first one said
# the right thing" is not the same claim as "this client is the current build".
_SCOPE_FORMS: dict[str, list[str] | None] = {
    "absent": None,
    "old": [_OLD_SCOPE],
    "current": [CURRENT_TRUTH_AWARE_SCOPE],
    "empty": [""],
    "future": [_FUTURE_SCOPE],
    "duplicate": [CURRENT_TRUTH_AWARE_SCOPE, CURRENT_TRUTH_AWARE_SCOPE],
    "mixed": [CURRENT_TRUTH_AWARE_SCOPE, _FUTURE_SCOPE],
    # Strings that CONTAIN the current scope without being it. The `future`
    # form above cannot catch a partial match: v3 does not end with
    # "-target-truth-v2", so `endswith` refuses it and the whole matrix passes
    # while the gate is a substring test. These two do catch it — a client can
    # put anything in a query parameter, and "ends with something we recognise"
    # is not the same claim as "is the build we shipped".
    "forged-suffix": ["unknown-prefix-" + CURRENT_TRUTH_AWARE_SCOPE],
    "forged-prefix": [CURRENT_TRUTH_AWARE_SCOPE + "-next-capability-v1"],
}
_BLOCKED_FORMS = [
    "absent", "old", "empty", "future", "duplicate", "mixed",
    "forged-suffix", "forged-prefix",
]

_ACTIONABLE_RECORD = {
    "id": "bridge-open-1",
    "source_type": "campus_program",
    "title": "Open summer program",
    "url": "https://example.edu/open",
    "source_url": "https://example.edu/open-source",
    "application": {"application_url": "https://example.edu/apply"},
    "metadata": {"is_active": True},
}
_NON_ACTIONABLE_RECORDS = {
    "closed": {
        "id": "bridge-closed-1",
        "source_type": "campus_program",
        "title": "Closed summer program",
        "url": "https://example.edu/closed",
        "source_url": "https://example.edu/closed-source",
        "application": {"application_url": "https://example.edu/closed-apply"},
        "metadata": {"is_active": True, "urap_status": "closed"},
    },
    # No `source_type` at all — one of the 26 shapes named above.
    "unknown_kind": {
        "id": "bridge-unknown-1",
        "title": "Unreviewed row",
        "url": "https://example.edu/unreviewed",
        "source_url": "https://example.edu/unreviewed-source",
        "application": {"application_url": "https://example.edu/unreviewed-apply"},
        "metadata": {"is_active": True},
    },
    # The remaining three reasons in the ladder. A gate written against
    # "closed or unreviewed" passes the two shapes above and serves these to
    # an old client anyway, so each one has to travel the whole matrix.
    "inactive": {
        "id": "bridge-inactive-1",
        "source_type": "campus_program",
        "title": "Retired summer program",
        "url": "https://example.edu/inactive",
        "source_url": "https://example.edu/inactive-source",
        "application": {"application_url": "https://example.edu/inactive-apply"},
        "metadata": {"is_active": False},
    },
    "reference_only": {
        "id": "bridge-reference-1",
        "source_type": "campus_program",
        "title": "Reference programme record",
        "url": "https://example.edu/reference",
        "source_url": "https://example.edu/reference-source",
        "application": {"application_url": "https://example.edu/reference-apply"},
        "metadata": {"is_active": True, "reference_only": True},
    },
    "faculty_not_accepting": {
        "id": "bridge-faculty-1",
        "source_type": "faculty_research",
        "title": "Prof. Alex Rivera",
        "url": "https://example.edu/people/rivera",
        "source_url": "https://example.edu/people/rivera-source",
        "application": {"application_url": "https://example.edu/faculty-apply"},
        "metadata": {
            "is_active": True,
            "faculty_availability_status": "not_accepting_undergraduates",
            "faculty_not_accepting_undergraduates_stated": True,
        },
    },
}

# Read off the canonical fixtures rather than restated, so a fixture that
# stopped being non-actionable for the reason it is named after fails here
# instead of quietly turning its whole row of the matrix into a control.
_EXPECTED_REFUSAL_REASONS = {
    "closed": "listing_closed",
    "unknown_kind": "record_kind_unverified",
    "inactive": "inactive",
    "reference_only": "reference_only",
    "faculty_not_accepting": "faculty_not_accepting",
}

_CAPABILITY_REFUSAL = {
    "code": "TARGET_TRUTH_CAPABILITY_REQUIRED",
    "reason": "target_truth_v2_required",
    "message": "Refresh JoinALab to view this historical record safely.",
    "retryable": False,
}


def _detail(opportunity_id: str, form: str, **kwargs):
    """GET one detail with the query built by hand, so repeats survive."""
    scopes = _SCOPE_FORMS[form]
    url = f"/api/opportunities/{quote(opportunity_id, safe='')}"
    if scopes is not None:
        url += "?" + "&".join(
            f"_release_scope={quote(scope, safe='')}" for scope in scopes
        )
    return _BRIDGE_CLIENT.get(url, **kwargs)


class TestHistoricalDetailCapabilityBridge:
    @pytest.fixture
    def serve(self, monkeypatch):
        def _install(record: dict) -> dict:
            monkeypatch.setattr(
                opportunities_module,
                "load_opportunities_by_id",
                lambda: {record["id"]: record},
            )
            return record
        return _install

    @pytest.mark.parametrize("form", list(_SCOPE_FORMS))
    def test_an_actionable_record_is_still_served_to_every_client(self, form, serve):
        """The compatibility half. Nothing about a live record changed."""
        record = serve(deepcopy(_ACTIONABLE_RECORD))
        response = _detail(record["id"], form)

        assert response.status_code == 200, form
        body = response.json()
        assert body["id"] == record["id"]
        assert body["target_truth"]["actionable"] is True

    @pytest.mark.parametrize("shape", sorted(_NON_ACTIONABLE_RECORDS))
    def test_each_fixture_really_is_non_actionable_for_its_own_reason(self, shape):
        """Read from the canonical record, never from a wire field.

        A top-level `target_truth` key on a fixture proves nothing: the truth
        contract does not read one, so a record carrying it would sail through
        every assertion below while the gate under test never fired.
        """
        truth = target_truth(_NON_ACTIONABLE_RECORDS[shape])
        assert truth.actionable is False, shape
        assert truth.reason_code == _EXPECTED_REFUSAL_REASONS[shape], shape
        assert "target_truth" not in _NON_ACTIONABLE_RECORDS[shape], shape

    @pytest.mark.parametrize("shape", sorted(_NON_ACTIONABLE_RECORDS))
    def test_the_current_build_still_reads_a_historical_record(self, shape, serve):
        record = serve(deepcopy(_NON_ACTIONABLE_RECORDS[shape]))
        response = _detail(record["id"], "current")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == record["id"]
        assert body["target_truth"]["actionable"] is False
        assert body["target_truth"]["reason_code"] == _EXPECTED_REFUSAL_REASONS[shape]

    @pytest.mark.parametrize("form", _BLOCKED_FORMS)
    @pytest.mark.parametrize("shape", sorted(_NON_ACTIONABLE_RECORDS))
    def test_every_other_declared_capability_is_refused(self, shape, form, serve):
        record = serve(deepcopy(_NON_ACTIONABLE_RECORDS[shape]))
        response = _detail(record["id"], form)

        assert response.status_code == 409, (shape, form)
        assert response.json() == {"detail": _CAPABILITY_REFUSAL}, (shape, form)

    @pytest.mark.parametrize("form", _BLOCKED_FORMS)
    def test_the_refusal_is_never_stored_and_varies_on_authorization(
        self, form, serve,
    ):
        """The headers must ride on the EXCEPTION, not on the injected
        Response: FastAPI builds a fresh response for a raised HTTPException,
        so anything written to the handler's `response` before raising is
        discarded and a shared cache would be free to keep the refusal."""
        record = serve(deepcopy(_NON_ACTIONABLE_RECORDS["closed"]))
        response = _detail(record["id"], form)

        assert response.status_code == 409
        assert response.headers["Cache-Control"] == "private, no-store, max-age=0"
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Vary"] == "Authorization"

    def test_the_refusal_describes_no_record_at_all(self, serve):
        record = serve(deepcopy(_NON_ACTIONABLE_RECORDS["closed"]))
        response = _detail(record["id"], "old")

        assert set(response.json()) == {"detail"}
        for leaked in (
            record["id"], record["title"], record["url"], record["source_url"],
            record["application"]["application_url"],
        ):
            assert leaked not in response.text, leaked

    def test_authorization_cannot_buy_the_capability(self, serve, monkeypatch):
        """A credential says who is asking, never what their build can parse."""
        auth_calls: list[str] = []

        async def tripwire(*_args, **_kwargs):
            auth_calls.append("auth")
            raise AssertionError("the auth lookup ran for a refused historical detail")

        monkeypatch.setattr(opportunities_module, "authenticated_uid", tripwire)
        record = serve(deepcopy(_NON_ACTIONABLE_RECORDS["closed"]))

        anonymous = _detail(record["id"], "old")
        authorized = _detail(
            record["id"], "old",
            headers={"Authorization": "Bearer not-a-real-token"},
        )

        assert anonymous.status_code == authorized.status_code == 409
        assert anonymous.json() == authorized.json()
        assert auth_calls == []

    @pytest.mark.parametrize("shape", sorted(_NON_ACTIONABLE_RECORDS))
    def test_a_refused_detail_is_never_projected(self, shape, serve, monkeypatch):
        """The gate comes before `_redact`, so a refused record is never even
        assembled — the alternative reads the whole payload into a local and
        leaves serving it one edit away."""
        def tripwire(_opportunity):
            raise AssertionError("the record was projected for a refused detail")

        monkeypatch.setattr(opportunities_module, "_redact", tripwire)
        record = serve(deepcopy(_NON_ACTIONABLE_RECORDS[shape]))

        assert _detail(record["id"], "absent").status_code == 409

    @pytest.mark.parametrize("form", ["absent", "current"])
    def test_id_validation_and_resolution_still_come_first(self, form):
        """A malformed or missing id is not a capability problem.

        Bodies asserted, not only statuses: a gate placed too early answers
        "refresh JoinALab" to a typo, and a status-only check cannot tell the
        two refusals apart.
        """
        too_long = _detail("a" * 150, form)
        assert too_long.status_code == 400, form
        assert too_long.json() == {"detail": "Invalid opportunity ID"}, form

        missing = _detail("this-id-does-not-exist-xyz", form)
        assert missing.status_code == 404, form
        assert missing.json() == {"detail": "Opportunity not found"}, form

    @pytest.mark.parametrize("shape", sorted(_NON_ACTIONABLE_RECORDS))
    def test_the_served_historical_detail_still_offers_no_action(self, shape, serve):
        """The positive path keeps every existing historical guarantee."""
        record = serve(deepcopy(_NON_ACTIONABLE_RECORDS[shape]))
        body = _detail(record["id"], "current").json()

        assert body["contact_email_status"] == "unavailable"
        assert "contact_email" not in body
        assert body["target_truth"]["reason_code"] == _EXPECTED_REFUSAL_REASONS[shape]
        assert body.get("application", {}).get("application_url") is None

    def test_the_capability_string_is_the_frozen_current_release_scope(self):
        """Written out, not imported into the assertion.

        The gate is an exact string match against what the frontend sends. If
        the constant were only compared to itself, renaming it on one side
        would keep this green while every current client started being told to
        refresh.
        """
        assert opportunities_module.CURRENT_TRUTH_AWARE_SCOPE == (
            "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
        )


class TestPurity:
    def test_the_record_is_never_mutated(self):
        record = _record()
        before = deepcopy(record)
        target_truth(record)
        target_truth(record)
        assert record == before

    def test_repeated_calls_agree(self):
        record = _record()
        assert target_truth(record) == target_truth(record)
