"""Point-in-time row totals for the application tables checked by a restore drill."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

TABLES = (
    "profiles", "favorites", "interactions", "profile_versions",
    "interaction_status_changes", "saved_searches", "match_feedback",
    "push_subscriptions", "analytics_events", "waitlist", "feedback",
    "feedback_events", "merged_devices", "merge_grants", "orders",
    "usage_events", "resume_renovations", "resume_renovation_versions",
    "professor_follows", "professor_update_reads", "ops_incidents",
    "ops_incident_events", "ops_heartbeats",
)

# The source is captured from the live project hours after the nightly backup, so its totals
# include rows the backup cannot hold. This column says when a row was written; rows stamped
# after the recovery point are subtracted from what the restore must contain. It is the creation
# stamp where the table has one. interactions and professor_update_reads carry only a last-write
# stamp, which subtracts rows edited since as well: a lower requirement, never a false failure.
STAMPS = {
    "profiles": "created_at", "favorites": "created_at", "interactions": "updated_at",
    "profile_versions": "created_at", "interaction_status_changes": "changed_at",
    "saved_searches": "created_at", "match_feedback": "created_at", "push_subscriptions": "created_at",
    "analytics_events": "created_at", "waitlist": "created_at", "feedback": "created_at",
    "feedback_events": "created_at", "merged_devices": "merged_at", "merge_grants": "created_at",
    "orders": "created_at", "usage_events": "created_at", "resume_renovations": "created_at",
    "resume_renovation_versions": "created_at", "professor_follows": "created_at",
    "professor_update_reads": "updated_at", "ops_incidents": "created_at",
    "ops_incident_events": "created_at", "ops_heartbeats": "registered_at",
}

# Tables that only grow: the application inserts into them and has no delete path (no DELETE
# policy, no delete call in backend or frontend, no DELETE in any migration's functions; an
# account merge re-keys their rows). A correct restore can therefore never hold more of their
# rows than the later capture counted. Every other table also loses rows in normal use (a
# favourite removed, two devices merged), so a restore may hold rows the live table no longer has.
# ops_incident_events is append-only too (031) and is left out on purpose: a restore is a binary
# copy that brings the ops-dead-man-sweep pg_cron job (032) with it, and that job files incidents
# on the scratch project within ten minutes of the restore.
GROWING = frozenset({
    "analytics_events",     # browser INSERT policy only (migration 015)
    "usage_events",         # service-role insert from backend/lib/metering.py (0201)
    "feedback_events",      # append-only admin audit trail (030)
    "profile_versions",     # INSERT and SELECT policies only (014); written by the profile save RPC
})

# The dashboard shows one time for a backup that takes minutes to complete. Rows stamped up to
# this long before that time are treated as possibly later than the backup.
STAMP_MARGIN = timedelta(minutes=15)

# Seven daily backups are retained (docs/DISASTER_RECOVERY.md §1), so no backup that can be restored
# is older than this. A time before any of them would subtract rows the restored backup does hold.
OLDEST_RECOVERY_POINT = timedelta(days=8)

# The drill restores the newest daily backup (§3 step 1). Backups are a day apart, so when the capture
# runs that backup is at most 24 hours old; two more hours allow for one that starts or completes late.
# An earlier time is accepted only when the operator says the backup is an older one.
NEWEST_BACKUP_AGE = timedelta(hours=26)


def capture_query(catalogue_query: str, recovery_point: datetime) -> str:
    # A single PostgreSQL statement observes table totals and schema at the same snapshot.
    cutoff = (recovery_point - STAMP_MARGIN).astimezone(UTC).isoformat()
    pairs = ",\n".join(
        f"'{table}', CASE WHEN pg_catalog.row_security_active('public.{table}'::regclass) THEN NULL "
        f"ELSE (SELECT jsonb_build_array(count(*), "
        f"count(*) FILTER (WHERE {column} IS NULL OR {column} > '{cutoff}'::timestamptz)) "
        f"FROM public.{table}) END" for table, column in STAMPS.items()
    )
    return (f"SELECT snapshot::jsonb || jsonb_build_object('row_counts', jsonb_build_object({pairs})) "
            f"FROM ({catalogue_query}) AS catalogue(snapshot)")


def complete(counts: object) -> bool:
    return (isinstance(counts, dict) and set(counts) == set(TABLES)
            and all(type(value) is int and value >= 0 for value in counts.values()))


def compare(source: object, restored: object, stamped_after: object) -> tuple[str, list[dict]]:
    """Check every restored table against what the source says existed at the recovery point.

    No evidence means no PASS. A table fails when the restore lacks rows the source stamps at or
    before the recovery point, or when a table that only grows holds more than the source did.
    """
    if (not complete(source) or not complete(restored) or not complete(stamped_after)
            or any(stamped_after[name] > source[name] for name in TABLES)):
        return "UNVERIFIED", []
    findings = []
    for name in TABLES:
        observed = {"table": name, "restored": restored[name], "source": source[name],
                    "stamped_after": stamped_after[name]}
        if restored[name] < source[name] - stamped_after[name]:
            findings.append(observed | {"observed": "rows_missing"})
        elif name in GROWING and restored[name] > source[name]:
            findings.append(observed | {"observed": "more_rows_than_source"})
    return ("FAIL" if findings else "PASS"), findings


# Row counts say how many users, orders and waitlist entries exist, and the drill record is
# committed to a public repository. The record therefore names tables and outcomes only; the
# numbers stay in the private files, which the record binds by SHA-256.
OBSERVED = {
    "rows_missing": "holds fewer rows than existed at the recovery point",
    "more_rows_than_source": "holds more rows than the later source capture counted, in a table the "
                             "application never deletes from",
}


def evidence_bytes(source: str, backup: str, recovery_point_time: str, row_counts: dict, rows_stamped_after: dict) -> bytes:
    """The private row evidence file; the source receipt carries only its SHA-256."""
    doc = {"source_environment": source, "source_backup_id": backup, "recovery_point_time": recovery_point_time,
           "row_counts": row_counts, "rows_stamped_after": rows_stamped_after}
    return (json.dumps(doc, sort_keys=True, indent=2) + "\n").encode()


def counts_digest(counts: dict) -> str:
    return hashlib.sha256(json.dumps(counts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recorded_verdict(data: object, pin: object) -> str:
    """What a committed, count-free record establishes about the data step."""
    if not isinstance(data, dict):
        return "UNVERIFIED"
    different, unreadable = data.get("different_tables"), data.get("unreadable_tables")
    if not isinstance(different, list) or not isinstance(unreadable, list):
        return "UNVERIFIED"
    if different or unreadable or data.get("result") == "FAIL":
        return "FAIL"
    digests = (pin, data.get("source_rows_sha256"), data.get("restored_rows_sha256"))
    if (data.get("result") != "PASS" or data.get("tables_compared") != len(TABLES)
            or not all(isinstance(d, str) and re.fullmatch(r"[a-f0-9]{64}", d) for d in digests)
            or data["source_rows_sha256"] != pin):
        return "UNVERIFIED"
    return "PASS"


def describe(finding: dict) -> str:
    """The observed numbers, for the operator's terminal and the private record."""
    table, restored, source = finding["table"], finding["restored"], finding["source"]
    if finding["observed"] == "more_rows_than_source":
        return (f"{table}: restored {restored} rows, but the later source capture counted {source} "
                "and the application never deletes from this table")
    existed = source - finding["stamped_after"]
    return (f"{table}: restored {restored} rows; the source capture counted {source}, of which "
            f"{finding['stamped_after']} may be later than the backup, so at least {existed} existed "
            f"at the recovery point and at least {existed - restored} are missing")
