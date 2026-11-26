"""Point-in-time row totals for the application tables checked by a restore drill."""
from __future__ import annotations

TABLES = (
    "profiles", "favorites", "interactions", "profile_versions",
    "interaction_status_changes", "saved_searches", "match_feedback",
    "push_subscriptions", "analytics_events", "waitlist", "feedback",
    "feedback_events", "merged_devices", "merge_grants", "orders",
    "usage_events", "resume_renovations", "resume_renovation_versions",
    "professor_follows", "professor_update_reads", "ops_incidents",
    "ops_incident_events", "ops_heartbeats",
)


def capture_query(catalogue_query: str) -> str:
    # A single PostgreSQL statement observes table totals and schema at the same snapshot.
    pairs = ",\n".join(
        f"'{table}', CASE WHEN pg_catalog.row_security_active('public.{table}'::regclass) THEN NULL "
        f"ELSE (SELECT count(*) FROM public.{table}) END" for table in TABLES
    )
    return (f"SELECT snapshot::jsonb || jsonb_build_object('row_counts', jsonb_build_object({pairs})) "
            f"FROM ({catalogue_query}) AS catalogue(snapshot)")


def complete(counts: object) -> bool:
    return (isinstance(counts, dict) and set(counts) == set(TABLES)
            and all(type(value) is int and value >= 0 for value in counts.values()))


def compare(source: object, restored: object) -> tuple[str, list[str]]:
    """Compare all tables, including expected empty ones; no evidence means no PASS."""
    if not complete(source) or not complete(restored):
        return "UNVERIFIED", []
    different = [name for name in TABLES if source[name] != restored[name]]
    return ("FAIL" if different else "PASS"), different
