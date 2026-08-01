#!/usr/bin/env python3
"""Read-only audit of identity-bound faculty contact evidence.

This canary never fetches, refreshes, or writes the corpus. It answers a much
narrower release question: how many records carry a complete, fresh six-field
contact claim (``contact_email`` plus the five metadata proof fields), and are
any attempted claims partial, invalid, stale, mismatched, or duplicated across
different people?

Usage:
    python -m scripts.contact_evidence_canary
    python -m scripts.contact_evidence_canary --json
    python -m scripts.contact_evidence_canary --fail-on-invalid --min-fresh 1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # Keep the shebang honest when invoked as ``python scripts/...py``.
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.lib.contact_visibility import (
    CONTACT_EVIDENCE_FIELDS,
    CONTACT_VERIFICATION_TTL_DAYS,
    IDENTITY_BOUND_EMAIL_SOURCES,
    _has_identity_bound_contact_evidence,
    _valid_email_target,
    canonical_profile_evidence_url,
    safe_contact_source_url,
)

DEFAULT_ASSEMBLED_CORPUS = (
    PROJECT_ROOT / "data" / "processed" / "opportunities.json"
)
DEFAULT_SHARD_CORPUS = PROJECT_ROOT / "data" / "processed" / "shards"
_EVIDENCE_SIGNAL_FIELDS = CONTACT_EVIDENCE_FIELDS - {"email_source"}
_CLOCK_SKEW_GRACE = timedelta(minutes=5)


def _load_json_records(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or any(
        not isinstance(record, dict) for record in payload
    ):
        raise ValueError(f"{path}: expected a JSON array of objects")
    return payload


def load_records(paths: list[Path]) -> list[dict]:
    """Load explicit JSON files or every ``*.json`` file in a directory."""

    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        elif path.is_file():
            files.append(path)
        else:
            raise ValueError(f"corpus path does not exist: {path}")
    if not files:
        raise ValueError("no JSON corpus files found")
    records: list[dict] = []
    for path in files:
        records.extend(_load_json_records(path))
    return records


def default_runtime_corpus_path() -> Path:
    """Mirror backend.data_loader's assembled-file-before-shards precedence."""

    return (
        DEFAULT_ASSEMBLED_CORPUS
        if DEFAULT_ASSEMBLED_CORPUS.exists()
        else DEFAULT_SHARD_CORPUS
    )


def _parse_aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.astimezone(UTC)


def _canonical_person_identity(
    record: dict,
    *,
    ordinal: int,
) -> tuple[str, dict[str, object] | None]:
    """Best available person key, independent of a possibly duplicated row id."""

    organization = " ".join(
        str(record.get("organization") or "").split()
    ).casefold()
    name = " ".join(str(record.get("pi_name") or "").split()).casefold()
    application = record.get("application")
    profile_candidates = [
        record.get("url"),
        record.get("source_url"),
        application.get("application_url")
        if isinstance(application, dict)
        else None,
    ]
    profile_identities: set[str] = set()
    invalid_profile_urls: set[str] = set()
    for candidate in profile_candidates:
        if candidate is None or (
            isinstance(candidate, str) and not candidate.strip()
        ):
            continue
        if not isinstance(candidate, str):
            invalid_profile_urls.add(
                f"<non-string:{type(candidate).__name__}>"
            )
            continue
        canonical = canonical_profile_evidence_url(candidate)
        if canonical is None:
            invalid_profile_urls.add(
                " ".join(candidate.split())
            )
            continue
        hostname, port, path, query = canonical
        authority = hostname if port == 443 else f"{hostname}:{port}"
        suffix = f"?{query}" if query else ""
        profile_identities.add(f"https://{authority}{path}{suffix}")
    stable_id = str(record.get("id") or "").strip()
    person = f"{organization}|{name}" if organization and name else name
    if invalid_profile_urls or len(profile_identities) > 1:
        record_ref = f"id:{stable_id}" if stable_id else f"row:{ordinal}"
        issue = {
            "record_id": stable_id or None,
            "organization": organization or None,
            "pi_name": name or None,
            "reason": (
                "invalid_profile_url"
                if invalid_profile_urls
                else "conflicting_profile_urls"
            ),
            "profile_urls": sorted(
                [*profile_identities, *invalid_profile_urls]
            ),
        }
        identity_prefix = person or "unknown"
        return f"{identity_prefix}|ambiguous-profile:{record_ref}", issue
    profile_identity = "&".join(sorted(profile_identities))
    if name:
        return (
            (
                f"{person}|profile:{profile_identity}"
                if profile_identity
                else person
            ),
            None,
        )
    if profile_identity:
        return f"profile:{profile_identity}", None
    return (f"id:{stable_id}" if stable_id else "unknown"), None


def _classify_claim(record: dict, *, now: datetime) -> tuple[str, str | None]:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return "none", None

    # A legacy ``email_source=profile_page`` is provenance, not an attempted
    # identity-bound tuple. Only one of the four stronger proof fields starts
    # an atomic-claim audit.
    source = metadata.get("email_source")
    bound_source_signal = (
        isinstance(source, str)
        and source.strip().casefold().startswith("bound_")
    )
    if (
        not bound_source_signal
        and not any(field in metadata for field in _EVIDENCE_SIGNAL_FIELDS)
    ):
        return "none", None
    if not all(field in metadata for field in CONTACT_EVIDENCE_FIELDS):
        return "partial", None

    email = record.get("contact_email")
    verified_email = metadata.get("contact_verified_email")
    if (
        not isinstance(email, str)
        or not _valid_email_target(email.strip())
        or not isinstance(verified_email, str)
        or verified_email.strip().casefold() != email.strip().casefold()
    ):
        return "mismatch", None

    source = metadata.get("email_source")
    if (
        not isinstance(source, str)
        or source != source.strip().casefold()
        or source not in IDENTITY_BOUND_EMAIL_SOURCES
        or metadata.get("identity_bound") is not True
        or safe_contact_source_url(metadata.get("contact_source_url")) is None
    ):
        return "invalid", None

    timestamp = _parse_aware_timestamp(metadata.get("contact_verified_at"))
    if timestamp is None or timestamp > now + _CLOCK_SKEW_GRACE:
        return "invalid", None
    if now - timestamp > timedelta(days=CONTACT_VERIFICATION_TTL_DAYS):
        return "stale", None
    if not _has_identity_bound_contact_evidence(record, email.strip(), now=now):
        return "invalid", None
    return "fresh", email.strip().casefold()


def audit_records(
    records: list[dict],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return bounded aggregate evidence counts without mutating ``records``."""

    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    checked_at = checked_at.astimezone(UTC)

    statuses: Counter[str] = Counter()
    fresh_by_source: Counter[str] = Counter()
    identities_by_email: dict[str, set[str]] = defaultdict(set)
    person_identity_issues: list[dict[str, object]] = []
    record_id_counts: Counter[str] = Counter()
    records_with_email = 0
    legacy_email_source = 0

    for ordinal, record in enumerate(records):
        record_id = record.get("id")
        if isinstance(record_id, str) and record_id.strip():
            record_id_counts[record_id.strip()] += 1
        if isinstance(record.get("contact_email"), str) and record[
            "contact_email"
        ].strip():
            records_with_email += 1
        metadata = record.get("metadata")
        if (
            isinstance(metadata, dict)
            and isinstance(metadata.get("email_source"), str)
            and not metadata["email_source"].strip().casefold().startswith("bound_")
            and not any(field in metadata for field in _EVIDENCE_SIGNAL_FIELDS)
        ):
            legacy_email_source += 1

        status, canonical_email = _classify_claim(record, now=checked_at)
        statuses[status] += 1
        if status == "fresh" and canonical_email is not None:
            source = str(metadata["email_source"])
            fresh_by_source[source] += 1
            identity, identity_issue = _canonical_person_identity(
                record,
                ordinal=ordinal,
            )
            identities_by_email[canonical_email].add(identity)
            if identity_issue is not None:
                person_identity_issues.append(identity_issue)

    duplicates = sorted(
        {
            email: sorted(identities)
            for email, identities in identities_by_email.items()
            if len(identities) > 1
        }.items()
    )
    return {
        "checked_at": checked_at.isoformat(),
        "records": len(records),
        "records_with_email": records_with_email,
        "legacy_email_source": legacy_email_source,
        "evidence_status": {
            status: statuses[status]
            for status in ("fresh", "stale", "partial", "mismatch", "invalid", "none")
        },
        "fresh_by_source": dict(sorted(fresh_by_source.items())),
        "duplicate_fresh_emails": [
            {"email": email, "identities": identities}
            for email, identities in duplicates
        ],
        "duplicate_record_ids": sorted(
            record_id
            for record_id, count in record_id_counts.items()
            if count > 1
        ),
        "person_identity_issues": person_identity_issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=None,
        help=(
            "JSON corpus file(s) or shard directories "
            "(default: runtime assembled-file/shard precedence)"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help=(
            "Fail on stale, partial, mismatched, invalid, or "
            "cross-identity duplicate claims"
        ),
    )
    parser.add_argument(
        "--min-fresh",
        type=int,
        default=0,
        help="Require at least this many fresh verified claims",
    )
    args = parser.parse_args(argv)
    if args.min_fresh < 0:
        parser.error("--min-fresh must be non-negative")

    try:
        paths = args.paths or [default_runtime_corpus_path()]
        report = audit_records(load_records(paths))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        statuses = report["evidence_status"]
        print(
            f"records={report['records']} email={report['records_with_email']} "
            f"fresh={statuses['fresh']} stale={statuses['stale']} "
            f"partial={statuses['partial']} mismatch={statuses['mismatch']} "
            f"invalid={statuses['invalid']} "
            f"duplicates={len(report['duplicate_fresh_emails'])} "
            f"duplicate_ids={len(report['duplicate_record_ids'])} "
            f"identity_issues={len(report['person_identity_issues'])}"
        )

    statuses = report["evidence_status"]
    invalid_count = sum(
        statuses[key] for key in ("stale", "partial", "mismatch", "invalid")
    ) + (
        len(report["duplicate_fresh_emails"])
        + len(report["duplicate_record_ids"])
        + len(report["person_identity_issues"])
    )
    if args.fail_on_invalid and invalid_count:
        return 1
    return 0 if statuses["fresh"] >= args.min_fresh else 1


if __name__ == "__main__":
    sys.exit(main())
