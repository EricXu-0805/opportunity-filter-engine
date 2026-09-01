"""Historical remediation of professor-paper attribution, and its ledger.

WHAT THIS EXISTS FOR

``src/publication_trust`` answers "may this record's papers be cited today".
It cannot answer "were the papers this record holds ever judged by a rule we
still believe in", and that is a different question with a different answer for
6,255 professors. Gate 1 decided whether a paper could be a professor's by
asking whether its OpenAlex field sat anywhere in the nine-field family their
*department* could plausibly touch. For a UIUC MRI professor that family
admitted a search-agent paper and a geochemistry paper and excluded his own
imaging work. #846 replaced the rule; it could only ever apply to future
harvests, because a record already stamped verified was skipped by the pass
that would have re-judged it.

So the corpus carries a population of relationships that are *trusted* and have
*never been judged by a living rule*. This module is the machinery that finds
them, withdraws the trust, drives the re-judgement, and proves each unit was
processed exactly once.

THE THREE THINGS THAT MAKE THIS HARD, AND WHERE EACH IS ANSWERED

1. **Fail closed during the window.** Remediation is not instantaneous — it
   needs a metered third-party API and runs over days. A design that leaves
   records trusted "until their turn comes" serves known-suspect citations for
   the whole window. ``invalidate_population`` withdraws trust for the entire
   population up front, in one cheap local pass, before any harvesting.
   ``pending_remediation`` is not verified, so every downstream consumer
   (match reasons, Ask AI, resume, cold email, the public API projection)
   stops reading those papers the moment the write lands.

2. **Exactly-once, across crashes.** The mutation and the ledger append cannot
   be one atomic act — they are different files, and a worker can die between
   them. Rather than pretend otherwise, the ledger *reconciles*: the mutated
   record carries ``works_gate`` as self-describing proof the mutation landed,
   so a replay that finds the proof without a terminal ledger entry writes the
   entry instead of re-applying the mutation. That is what makes "attempt 1
   timed out after the commit, attempt 2 must not re-apply" work.

3. **Derived signals outliving their source.** A record's OpenAlex *keywords*
   are not derived from its papers, but they are derived from the same author
   resolution, so when the re-judgement says "that was a different person" the
   keywords inherit the verdict. See ``apply_disposition``.

WHAT IS DELIBERATELY NOT HERE

Any network call. This module decides and records; ``openalex_enrich`` fetches.
Keeping them apart is what lets the whole invalidation half — the half that
makes the system safe — run with no API key, no budget and no third party.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evidence import INFERRED_FIELDS_KEY
from .publication_trust import (
    CURRENT_WORKS_GATE,
    PENDING_REMEDIATION,
    VERIFIED_AUTHOR_ID,
    is_pending_remediation,
    needs_publication_remediation,
    record_works_gate,
    works_are_verified,
)

_PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"
LEDGER_PATH = _PROCESSED / "publication_remediation_ledger.jsonl"

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

# A unit moves through these in order. The split between the last two is the
# whole point of having them: a job that started, or harvested, or even decided
# an attribution, has changed nothing a reader can see. Only after the
# authoritative professor record has been written may the unit be called done —
# so a crash anywhere before MUTATION_COMMITTED leaves a unit that the next run
# picks up again, and no run can report success for work it did not land.
QUEUED = "queued"
STARTED = "started"
HARVEST_SUCCEEDED = "harvest_succeeded"
ATTRIBUTION_COMPLETED = "attribution_completed"
MUTATION_COMMITTED = "mutation_committed"
VERIFIED_COMPLETE = "verified_complete"
FAILED = "failed"
NEEDS_REVIEW = "needs_review"

# Terminal states: a unit in one of these is never re-processed for the same
# target gate. NEEDS_REVIEW is terminal for the *automated* pipeline and open
# for a human — the relationship stays untrusted either way, which is why it is
# safe to stop asking about it.
_TERMINAL = frozenset({VERIFIED_COMPLETE, NEEDS_REVIEW})

# Dispositions — what the current gate decided about the relationship.
DISPOSITION_VERIFIED = "verified"      # re-attributed; trust restored
DISPOSITION_REMOVED = "removed"        # gate rejected every paper; citations retracted
DISPOSITION_UNKNOWN = "unknown"        # never resolved to an author at all
DISPOSITION_AMBIGUOUS = "ambiguous"    # two candidates the rule cannot separate
DISPOSITION_NEEDS_REVIEW = "needs_review"  # routed to a human

# Only this one restores a trusted professor-paper relationship. Rediscovery is
# not verification: a paper the old gate chose and the new harvest happens to
# return again is verified by the *new* stamp it earns, never by having been
# there before.
_RESTORING = frozenset({DISPOSITION_VERIFIED})


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# The population
# ---------------------------------------------------------------------------

class RemediationUnit(dict):
    """One professor record awaiting (or having completed) re-judgement.

    A plain dict so it serialises straight into the ledger. Field names are the
    audit contract: ``professor_id`` identifies the corpus record,
    ``person_key`` is the key the harvest mapping is keyed by, and the two are
    not interchangeable — a harvest answers about a person, a mutation lands on
    a record, and a person can own more than one record.
    """


def person_key(record: dict) -> str:
    """The harvest join key for a record: ``url#name``.

    Imported lazily from the collector so this module stays importable without
    ``requests`` — the serving side reads the ledger and must not need the
    scraping stack to do it.
    """
    from .collectors.openalex_enrich import _person_key

    return _person_key(record)


def _record_url(record: dict) -> str:
    return (record.get("url") or record.get("source_url") or "").strip()


def unit_for(record: dict, *, to_gate: int = CURRENT_WORKS_GATE) -> RemediationUnit:
    """Describe one record as a remediation unit, with enough to audit it."""
    md = record.get("metadata") or {}
    works = md.get("recent_works") or []
    professor_id = str(record.get("id") or "")
    return RemediationUnit(
        professor_id=professor_id,
        person_key=person_key(record),
        school=record.get("school"),
        professor_name=record.get("pi_name"),
        department=record.get("department"),
        source_url=_record_url(record),
        old_attribution_status=md.get("publication_attribution_status"),
        old_gate_version=record_works_gate(record),
        old_author_id=md.get("publication_author_id"),
        relationship_count=len(works),
        paper_ids=[_paper_id(w) for w in works],
        current_verification_status=md.get("publication_attribution_status"),
        remediation_required=True,
        to_gate_version=to_gate,
        idempotency_key=idempotency_key(professor_id, to_gate),
    )


def _paper_id(work: dict) -> str:
    """A stable identifier for one professor-paper relationship.

    The corpus stores title+year only — no DOI, no OpenAlex work id — because
    the works library was built to a 2 GB memory budget. Title+year IS the
    identity we hold, so it is the identity the ledger records; inventing a
    surrogate would make the ledger unauditable against the data.
    """
    return f"{str(work.get('title', ''))[:200]}|{work.get('year')}"


def idempotency_key(professor_id: str, to_gate: int) -> str:
    """The exactly-once identity of one logical remediation.

    Deliberately readable rather than a hash: the invariant this enforces —
    *same unit + same target gate = one result* — should be legible in the
    ledger without a decoder, and a human diagnosing a duplicate needs to see
    which two things collided.
    """
    return f"{professor_id}@gate{to_gate}"


def remediation_population(
    records: Iterable[dict], *, to_gate: int = CURRENT_WORKS_GATE
) -> list[RemediationUnit]:
    """Every record whose papers a superseded gate approved. Deterministic.

    This is *the* authoritative query — the driver, the reports and the tests
    all call it rather than re-deriving the membership rule, because a second
    copy of "which records are affected" is how a remediation misses some.

    Sorted by professor_id so two runs enumerate in the same order and a
    partially-processed population resumes predictably.
    """
    out = [
        unit_for(r, to_gate=to_gate)
        for r in records
        if needs_publication_remediation(r)
    ]
    out.sort(key=lambda u: u["professor_id"])
    return out


def pending_population(
    records: Iterable[dict], *, to_gate: int = CURRENT_WORKS_GATE
) -> list[RemediationUnit]:
    """Records already withdrawn and awaiting re-judgement.

    Separate from ``remediation_population`` because the two answer different
    questions: that one is "what still has to be made safe", this one is "what
    is safe but unresolved". Both must reach zero before the remediation is
    over, and conflating them would let the first hit zero and read as done.
    """
    out = []
    for r in records:
        if not is_pending_remediation(r):
            continue
        u = unit_for(r, to_gate=to_gate)
        u["remediation_required"] = True
        out.append(u)
    out.sort(key=lambda u: u["professor_id"])
    return out


def population_summary(records: Iterable[dict]) -> dict:
    """Counts a report can quote, computed in ONE pass over the corpus.

    Professors and relationships are counted separately and deliberately: they
    are not the same number (18,621 relationships across 6,255 professors at
    the time this was written), and a remediation that reports only the first
    cannot say how many citations it actually withdrew.
    """
    s = {
        "faculty_records": 0,
        "verified_professors": 0,
        "verified_relationships": 0,
        "old_gate_professors": 0,
        "old_gate_relationships": 0,
        "pending_professors": 0,
        "pending_relationships": 0,
        "current_gate_professors": 0,
        "current_gate_relationships": 0,
        "unstamped_with_works_professors": 0,
        "unstamped_with_works_relationships": 0,
    }
    for r in records:
        if r.get("source_type") != "faculty_research":
            continue
        s["faculty_records"] += 1
        md = r.get("metadata") or {}
        n = len(md.get("recent_works") or [])
        if works_are_verified(r):
            s["verified_professors"] += 1
            s["verified_relationships"] += n
            if needs_publication_remediation(r):
                s["old_gate_professors"] += 1
                s["old_gate_relationships"] += n
            else:
                s["current_gate_professors"] += 1
                s["current_gate_relationships"] += n
        elif is_pending_remediation(r):
            s["pending_professors"] += 1
            s["pending_relationships"] += n
        elif n:
            s["unstamped_with_works_professors"] += 1
            s["unstamped_with_works_relationships"] += n
    return s


# ---------------------------------------------------------------------------
# Invalidation — the step that makes the window safe
# ---------------------------------------------------------------------------

def invalidate_record(record: dict, *, to_gate: int = CURRENT_WORKS_GATE) -> bool:
    """Withdraw trust in one record's papers. Returns whether anything changed.

    The papers themselves STAY. They are the candidate list the re-harvest is
    judged against, and a record that has forgotten what it used to claim
    cannot be audited afterwards — "we removed three citations from this
    professor" is a sentence the ledger can only write if the three were still
    there to count. What leaves is the trust: the status becomes
    ``pending_remediation`` and the resolved-author claim is dropped, because
    that id is the assertion "this OpenAlex person is this professor" and it
    was made by the same superseded rule.

    Idempotent. Re-running over an already-withdrawn record changes nothing and
    returns False, which is what lets the pipeline pass (below) run every
    refresh without churning the corpus.
    """
    if not needs_publication_remediation(record):
        return False
    md = record.setdefault("metadata", {})
    md["publication_attribution_status"] = PENDING_REMEDIATION
    # The id asserted an identity the retired gate resolved. Keep it where the
    # audit can see it, out of the field every consumer reads.
    prior_author = md.pop("publication_author_id", None)
    md["publication_remediation"] = {
        "from_gate": record_works_gate(record),
        "to_gate": to_gate,
        "withdrawn_at": _now(),
        "prior_status": VERIFIED_AUTHOR_ID,
        "prior_author_id": prior_author,
    }
    return True


def invalidate_population(
    records: Iterable[dict], *, to_gate: int = CURRENT_WORKS_GATE
) -> dict:
    """Withdraw trust across a whole corpus. Returns what it did."""
    professors = relationships = 0
    for r in records:
        n = len((r.get("metadata") or {}).get("recent_works") or [])
        if invalidate_record(r, to_gate=to_gate):
            professors += 1
            relationships += n
    return {"professors_withdrawn": professors, "relationships_withdrawn": relationships}


# ---------------------------------------------------------------------------
# Dispositions — what the current gate decided
# ---------------------------------------------------------------------------

def disposition_for(record: dict, entry: Any, *, harvested: bool) -> str:
    """Classify one re-judged unit from the harvest answer and the record.

    ``entry`` is what ``harvest_works_by_roster`` produced for this person:
    a dict with ``author_id`` and ``works`` when the roster resolved them,
    absent when it did not.

    The outcome is read off the record AFTER ``apply_works`` has run, not
    predicted from the entry, because ``apply_works`` owns the upgrade rule and
    a prediction that disagrees with it is a lie in the ledger.
    """
    if not harvested:
        return DISPOSITION_UNKNOWN
    if works_are_verified(record) and record_works_gate(record) >= CURRENT_WORKS_GATE:
        return DISPOSITION_VERIFIED
    if isinstance(entry, dict) and entry.get("author_id") and not entry.get("works"):
        # Asked, answered, and the gate kept none of it.
        return DISPOSITION_REMOVED
    if entry is None:
        # The roster could not settle who this is. ``_match_in_roster`` folds
        # "two candidates" and "no candidate" into the same absent answer here,
        # so this is reported as ambiguous rather than claiming to know which.
        return DISPOSITION_AMBIGUOUS
    return DISPOSITION_NEEDS_REVIEW


def apply_disposition(record: dict, disposition: str, *, to_gate: int = CURRENT_WORKS_GATE) -> dict:
    """Bring the authoritative record into line with the verdict.

    ``apply_works`` has already done the part it owns — writing verified papers
    and retracting explicitly-rejected ones. This closes the two gaps it cannot:

    * A unit the harvest never resolved keeps ``pending_remediation`` forever
      unless something removes the stale candidates. They are not this
      professor's publications by any rule we still hold, so they go, and the
      record is marked at the current gate so the next run does not re-buy an
      answer nobody can act on.

    * **Sibling derivations.** ``metadata.keywords`` stamped
      ``derived:openalex_topics`` came from the *same* author resolution that
      chose the papers. They are not derived from the papers — so a verdict of
      "these papers are not his" does not automatically condemn them — but a
      verdict of "we cannot tell who this is" or "the gate rejected all of
      their recent output" undermines the resolution both rest on. Where the
      relationship is destroyed, the derivation that shares its provenance is
      destroyed with it; where the relationship is re-verified, it stands.
      Anything less leaves a professor described by a stranger's research areas
      after the stranger's papers have been taken away.
    """
    md = record.setdefault("metadata", {})
    removed_relationships = 0
    keywords_invalidated = False

    if disposition in _RESTORING:
        md.pop("publication_remediation", None)
        return {"relationships_removed": 0, "keywords_invalidated": False}

    works = md.get("recent_works") or []
    if works:
        removed_relationships = len(works)
        md.pop("recent_works", None)
    md.pop("publication_attribution_status", None)
    md.pop("publication_author_id", None)
    md["works_gate"] = to_gate

    stamps = md.get(INFERRED_FIELDS_KEY) or {}
    if stamps.get("keywords") == "derived:openalex_topics":
        # Emptied rather than deleted. Every faculty record in the corpus
        # carries the field, the data-quality gate type-checks it where it is
        # present, and `[]` and absent are identical to every reader — so the
        # one that keeps the record's shape intact is the one to write. An
        # empty list also makes the record a target for the next keyword
        # harvest, which is where a replacement should come from.
        record["keywords"] = []
        stamps.pop("keywords", None)
        if stamps:
            md[INFERRED_FIELDS_KEY] = stamps
        else:
            md.pop(INFERRED_FIELDS_KEY, None)
        keywords_invalidated = True

    md["publication_remediation"] = {
        **(md.get("publication_remediation") or {}),
        "to_gate": to_gate,
        "disposition": disposition,
        "resolved_at": _now(),
        "relationships_removed": removed_relationships,
        "keywords_invalidated": keywords_invalidated,
    }
    return {
        "relationships_removed": removed_relationships,
        "keywords_invalidated": keywords_invalidated,
    }


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

class Ledger:
    """Append-only, crash-safe, exactly-once-by-reconciliation.

    Append-only JSONL rather than a rewritten document, for the reason the
    repo already keeps ``collector_status_history.jsonl`` that way: a partial
    final line after a crash is detectable and skippable, whereas a truncated
    rewrite of a whole-file JSON loses everything that came before. Each append
    is one ``write`` of one line under an exclusive lock, then fsync, so a
    concurrent worker never interleaves inside a record.

    The index is derived by replaying the log. That is O(events) per run and
    the log is one line per unit per stage — a few hundred thousand lines at
    full scale, which reads in well under a second — and it means the file on
    disk is the only state there is. An in-memory "already processed" set would
    prove nothing across the restart it exists to survive.
    """

    def __init__(self, path: Path | str = LEDGER_PATH):
        self.path = Path(path)
        self._worker = f"{socket.gethostname()}:{os.getpid()}"

    # -- reading -----------------------------------------------------------

    def events(self) -> Iterator[dict]:
        """Every well-formed event, oldest first. A torn final line is skipped.

        Skipping rather than raising is the crash-safe behaviour: the writer
        that died mid-line did not commit whatever it was describing, so the
        line has no meaning, and refusing to read the whole ledger because of
        it would turn one lost event into a total outage of the audit trail.
        """
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("idempotency_key"):
                    yield event

    def index(self) -> dict[str, dict]:
        """Latest state per idempotency key, plus the attempt count.

        ``attempt_count`` counts STARTED events, so a unit retried three times
        and finished once reads as three attempts and one result — which is the
        distinction §9 turns on: retries are allowed, duplicate logical
        remediation is not.
        """
        state: dict[str, dict] = {}
        for e in self.events():
            key = e["idempotency_key"]
            cur = state.setdefault(
                key,
                {
                    "idempotency_key": key,
                    "attempt_count": 0,
                    "status": None,
                    "result": None,
                    "error": None,
                    "history": [],
                },
            )
            if e.get("status") == STARTED:
                cur["attempt_count"] += 1
            # A terminal state is sticky: once a unit is complete, a later
            # stray event (a slow duplicate worker, a replayed job) must not
            # reopen it — that would be exactly the duplicate this ledger
            # exists to make impossible.
            if cur["status"] in _TERMINAL:
                cur["history"].append(e.get("status"))
                continue
            cur["status"] = e.get("status")
            cur["history"].append(e.get("status"))
            for field in ("professor_id", "person_key", "school",
                          "from_gate_version", "to_gate_version", "result",
                          "error", "started_at", "completed_at",
                          "relationships_before", "relationships_after",
                          "relationships_removed", "keywords_invalidated",
                          "reconciled"):
                if e.get(field) is not None:
                    cur[field] = e[field]
        return state

    def is_complete(self, key: str, index: dict[str, dict] | None = None) -> bool:
        """Whether this exact unit+gate already has a logical result."""
        idx = index if index is not None else self.index()
        return (idx.get(key) or {}).get("status") in _TERMINAL

    # -- writing -----------------------------------------------------------

    def append(self, unit: dict, status: str, **fields: Any) -> dict:
        """Record one lifecycle event. Returns the event as written.

        ``paper_ids`` and ``person_key`` are written ONCE — on the QUEUED and
        STARTED events respectively — and not repeated. The corpus holds no DOI
        or work id, so title+year is the only identity these relationships
        have, and a unit emits five events: three copies of the same three
        titles and five copies of a directory URL put the ledger at 12 MB for
        6,255 units before this was noticed. ``index()`` carries both forward
        from the event that has them, so nothing downstream loses anything, and
        the queued event remains the only place the identity of a retracted
        citation survives once the record no longer holds it.
        """
        event = {
            "remediation_id": unit.get("professor_id"),
            "professor_id": unit.get("professor_id"),
            "school": unit.get("school"),
            "from_gate_version": unit.get("old_gate_version"),
            "to_gate_version": unit.get("to_gate_version", CURRENT_WORKS_GATE),
            "idempotency_key": unit.get("idempotency_key"),
            "status": status,
            "worker": self._worker,
            "at": _now(),
        }
        event.update({k: v for k, v in fields.items() if v is not None})
        self._append_line(json.dumps(event, ensure_ascii=False, sort_keys=True))
        return event

    def _append_line(self, line: str) -> None:
        """One locked, fsynced append.

        ``flock`` is what stops two workers interleaving a line, and the fsync
        is what stops the OS holding the line in cache past a power loss. Both
        matter for the same reason: the ledger's whole value is that reading it
        back tells the truth about what happened.
        """
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    # -- exactly-once ------------------------------------------------------

    def claim(self, unit: dict, index: dict[str, dict] | None = None) -> bool:
        """Take this unit, or decline because someone already has a result.

        The check and the STARTED append happen under one lock so two workers
        cannot both see "not complete" and both proceed. A unit another worker
        merely *started* is still claimable — a started-and-abandoned unit must
        not be stranded forever by a crashed worker — which is safe precisely
        because the terminal check below, and the reconciliation in
        ``settle``, are what actually prevent a double mutation.
        """
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                if self.is_complete(unit["idempotency_key"]):
                    return False
                event = {
                    "remediation_id": unit.get("professor_id"),
                    "professor_id": unit.get("professor_id"),
                    "person_key": unit.get("person_key"),
                    "school": unit.get("school"),
                    "from_gate_version": unit.get("old_gate_version"),
                    "to_gate_version": unit.get("to_gate_version", CURRENT_WORKS_GATE),
                    "idempotency_key": unit["idempotency_key"],
                    "status": STARTED,
                    "worker": self._worker,
                    "at": _now(),
                    "started_at": _now(),
                }
                fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
                return True
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def reconcile(self, unit: dict, record: dict) -> bool:
        """Close a unit whose mutation landed but whose ledger entry did not.

        The gap between "the corpus was written" and "the ledger says so" is
        real and cannot be closed by ordering alone — they are two files. What
        closes it is that the mutation is *self-describing*: a record at the
        target gate is proof its remediation ran, whoever failed to write it
        down. Finding that proof, this records the completion rather than
        re-applying anything, which is the difference between a safe retry and
        a duplicate.
        """
        if self.is_complete(unit["idempotency_key"]):
            return False
        if record_works_gate(record) < unit.get("to_gate_version", CURRENT_WORKS_GATE):
            return False
        disposition = (
            DISPOSITION_VERIFIED if works_are_verified(record) else DISPOSITION_REMOVED
        )
        self.append(
            unit,
            VERIFIED_COMPLETE,
            result=disposition,
            completed_at=_now(),
            reconciled=True,
        )
        return True

    def settle(self, unit: dict, record: dict, disposition: str, **fields: Any) -> dict:
        """Write the two events that mean "this landed, and here is the result".

        Two events rather than one because they answer different questions and
        a reader needs both: MUTATION_COMMITTED says the professor record was
        written, VERIFIED_COMPLETE says the written state was checked against
        the verdict. A run that dies between them leaves a unit that
        ``reconcile`` closes on the next pass instead of re-mutating.
        """
        self.append(unit, MUTATION_COMMITTED, result=disposition, **fields)
        status = NEEDS_REVIEW if disposition == DISPOSITION_NEEDS_REVIEW else VERIFIED_COMPLETE
        return self.append(
            unit,
            status,
            result=disposition,
            completed_at=_now(),
            relationships_after=len((record.get("metadata") or {}).get("recent_works") or []),
            **fields,
        )

    def fail(self, unit: dict, error: str) -> dict:
        """Record a failure. Explicitly NOT terminal.

        A failed unit stays in the population and is picked up again. The one
        thing this must never do is look like completion — a job that harvested
        nothing, or crashed, or hit an exhausted budget has not remediated
        anything, and a ledger that says otherwise is worse than no ledger.
        """
        return self.append(unit, FAILED, error=str(error)[:500])

    # -- reporting ---------------------------------------------------------

    def report(self) -> dict:
        """The numbers the acceptance criteria ask for, straight from the log."""
        idx = self.index()
        by_status: dict[str, int] = {}
        by_result: dict[str, int] = {}
        retries = 0
        for entry in idx.values():
            by_status[entry.get("status") or "unknown"] = (
                by_status.get(entry.get("status") or "unknown", 0) + 1
            )
            if entry.get("result"):
                by_result[entry["result"]] = by_result.get(entry["result"], 0) + 1
            retries += max(0, entry.get("attempt_count", 0) - 1)
        # Relationships are counted before-minus-after rather than read from a
        # stored field, because two steps can retract (apply_works' explicit
        # rejection and the disposition's cleanup) and only the difference
        # describes what the professor actually lost. Derived here so the
        # headline is right for events written before that was understood —
        # the log is append-only and is not rewritten to make a number nicer.
        removed = 0
        for entry in idx.values():
            before = entry.get("relationships_before")
            after = entry.get("relationships_after")
            if isinstance(before, int) and isinstance(after, int):
                removed += max(0, before - after)
        return {
            "units": len(idx),
            "by_status": by_status,
            "by_result": by_result,
            "retry_count": retries,
            "relationships_removed": removed,
            "completed": sum(1 for e in idx.values() if e.get("status") in _TERMINAL),
            "duplicate_logical_remediations": self.duplicate_count(),
        }

    def duplicate_count(self) -> int:
        """How many units were logically remediated more than once.

        A duplicate is a SECOND terminal event for the same idempotency key —
        not a second attempt, not a second MUTATION_COMMITTED retry that never
        reached terminal. This is the number that has to be zero, and computing
        it from the raw event stream (rather than from the deduplicating index)
        is what makes it able to be non-zero at all.
        """
        seen: dict[str, int] = {}
        for e in self.events():
            if e.get("status") in _TERMINAL:
                seen[e["idempotency_key"]] = seen.get(e["idempotency_key"], 0) + 1
        return sum(n - 1 for n in seen.values() if n > 1)

    def manual_review_queue(self) -> list[dict]:
        """Units a human has to settle, with the evidence to settle them.

        Shaped for the ``manual_review`` kind the ops incident table already
        has (migration 031), so this feeds the operator queue that exists
        rather than inventing a second one.
        """
        out = []
        for entry in self.index().values():
            if entry.get("result") not in (DISPOSITION_AMBIGUOUS, DISPOSITION_NEEDS_REVIEW):
                continue
            out.append(
                {
                    "dedup_key": f"manual_review:publication_attribution:{entry['idempotency_key']}",
                    "professor_id": entry.get("professor_id"),
                    "person_key": entry.get("person_key"),
                    "school": entry.get("school"),
                    "reason": entry.get("result"),
                    "from_gate_version": entry.get("from_gate_version"),
                    "to_gate_version": entry.get("to_gate_version"),
                    "relationships_before": entry.get("relationships_before"),
                    "review_status": "open",
                }
            )
        out.sort(key=lambda r: r["dedup_key"])
        return out


def write_json_atomic(path: Path | str, payload: Any) -> None:
    """Small local atomic write for the report artifacts this module emits."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
