#!/usr/bin/env bash
# Verify migrations 017/018 (Flow B cross-device merge), 019 (orders RLS),
# 022/023 (professor tracking + its merge), 024 (pre-LLC order hard-close),
# 025 (atomic confirm_interaction_contact RPC), and 026 (idempotent
# merge-grant replay) against a real, throwaway Postgres cluster. Spins
# an ephemeral cluster in a temp dir, loads test stubs -> the effective prod
# schema (migrations, 004 is excluded because 006 supersedes it), runs
# flow_b_merge_test.sql + orders_rls_test.sql + professor_tracking_merge_
# test.sql + confirm_interaction_contact_test.sql, and tears everything down.
#
# Usage:  supabase/tests/run_flow_b_test.sh
# Requires: postgresql@16 (initdb/pg_ctl/psql on PATH).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS="$HERE/../migrations"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/flowb.XXXXXX")"
DATA="$WORK/data"
SOCK="$WORK/sock"
mkdir -p "$SOCK"

cleanup() {
  pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "==> initdb ($WORK)"
initdb -D "$DATA" -U postgres --auth=trust >/dev/null

echo "==> start postgres (socket-only)"
pg_ctl -D "$DATA" -o "-k $SOCK -c listen_addresses=''" -w start >/dev/null

PSQL=(psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -q)

echo "==> load test stubs"
"${PSQL[@]}" -f "$HERE/_stubs.sql"

echo "==> load migrations (effective prod schema; 004 superseded by 006)"
for f in "$MIGRATIONS"/*.sql; do
  base="$(basename "$f")"
  case "$base" in
    004_*) echo "    skip $base (superseded by 006)"; continue ;;
  esac
  if [[ "$base" == "026_disable_pre_llc_orders.sql" ]]; then
    # Supabase grants browser roles access to public tables through its
    # managed default privileges. Mirror that state immediately before the
    # hard-close migration so this test proves 024 actively revokes it.
    "${PSQL[@]}" -c \
      "GRANT SELECT, INSERT, UPDATE, DELETE ON public.orders TO anon, authenticated"
  fi
  if [[ "$base" == "029_profile_save_cas.sql" ]]; then
    # Same reasoning as 024: without this, "authenticated cannot INSERT into
    # profiles" would be true on a vanilla cluster that never granted it, and
    # the ACL assertions in profile_save_cas_test.sql would pass whether or
    # not 027's REVOKE existed at all.
    "${PSQL[@]}" -c \
      "GRANT SELECT, INSERT, UPDATE, DELETE ON public.profiles, public.profile_versions TO PUBLIC, anon, authenticated"
    "${PSQL[@]}" -c \
      "GRANT SELECT, INSERT, UPDATE, DELETE ON public.profiles, public.profile_versions TO service_role"
  fi
  if [[ "$base" == "20260819164641_disable_unaccepted_mtp_data_api.sql" ]]; then
    # Mirror Supabase's managed browser grants before the capability-close
    # migration.  Seed one row per table first so the post-migration contract
    # also proves that closing access preserves existing data.
    "${PSQL[@]}" -c \
      "GRANT SELECT, INSERT, UPDATE, DELETE ON public.resume_renovations, public.resume_renovation_versions, public.professor_follows, public.professor_update_reads TO PUBLIC, anon, authenticated, service_role"
    "${PSQL[@]}" -c "
      INSERT INTO public.resume_renovations
        (device_id, opportunity_id, doc, base_snapshot)
      VALUES ('acl-preserve-device', 'acl-preserve-opportunity', '{}'::jsonb, '{}'::jsonb);
      INSERT INTO public.resume_renovation_versions
        (device_id, opportunity_id, doc)
      VALUES ('acl-preserve-device', 'acl-preserve-opportunity', '{}'::jsonb);
      INSERT INTO public.professor_follows
        (device_id, professor_id, professor_name, school)
      VALUES ('acl-preserve-device', 'prof:v1:uiuc:eeeeeeeeeeeeeeeeeeee', 'Preserved Faculty', 'uiuc');
      INSERT INTO public.professor_update_reads
        (device_id, professor_id, last_read_event_id)
      VALUES ('acl-preserve-device', 'prof:v1:uiuc:eeeeeeeeeeeeeeeeeeee', 'prof-event:v1:eeeeeeeeeeeeeeeeeeeeeeee');"
  fi
  if [[ "$base" == "20260925052636_legacy_renovation_cas_rpc.sql" ]]; then
    "${PSQL[@]}" -f "$HERE/legacy_renovation_seed.sql"
  fi
  echo "    apply $base"
  "${PSQL[@]}" -f "$f"
done

echo "==> run flow_b_merge_test.sql"
"${PSQL[@]}" -f "$HERE/flow_b_merge_test.sql"

echo "==> run merge_preserves_tracker_test.sql"
"${PSQL[@]}" -f "$HERE/merge_preserves_tracker_test.sql"

echo "==> run orders_rls_test.sql"
"${PSQL[@]}" -f "$HERE/orders_rls_test.sql"

echo "==> run professor_tracking_merge_test.sql"
"${PSQL[@]}" -f "$HERE/professor_tracking_merge_test.sql"

echo "==> run confirm_interaction_contact_test.sql"
"${PSQL[@]}" -f "$HERE/confirm_interaction_contact_test.sql"

echo "==> run merge_grant_replay_test.sql"
"${PSQL[@]}" -f "$HERE/merge_grant_replay_test.sql"

echo "==> run profile_save_cas_test.sql"
"${PSQL[@]}" -f "$HERE/profile_save_cas_test.sql"

echo "==> run target_resume_cas_test.sql"
"${PSQL[@]}" -f "$HERE/target_resume_cas_test.sql"

echo "==> run target_resume_concurrency_test.sh"
source "$HERE/target_resume_concurrency_test.sh"

echo "==> run legacy_renovation_cas_test.sql"
"${PSQL[@]}" -f "$HERE/legacy_renovation_cas_test.sql"

echo "==> run legacy_renovation_concurrency_test.sh"
source "$HERE/legacy_renovation_concurrency_test.sh"

echo "==> run hidden_capabilities_acl_test.sql"
"${PSQL[@]}" -f "$HERE/hidden_capabilities_acl_test.sql"

# 027's advisory lock only matters under real concurrency, which a single
# psql session cannot demonstrate: advisory locks are re-entrant per session,
# so the same connection re-taking its own key always succeeds. Hold the key
# from a SECOND connection and confirm commit_profile_patch_cas actually
# BLOCKS on it (surfacing as lock_timeout) rather than proceeding.
echo "==> run CAS advisory-lock contention check (2 connections)"
LOCK_UID='9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9aff'
psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -q -c "
  BEGIN;
  SELECT pg_advisory_xact_lock(hashtext('ofe-profile:${LOCK_UID}'));
  SELECT pg_sleep(6);
  COMMIT;" >/dev/null 2>&1 &
HOLDER_PID=$!
sleep 1
set +e
CONTENTION_OUT="$(psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -q -c "
  SET lock_timeout = '1500ms';
  SELECT set_config('test.uid', '${LOCK_UID}', false);
  SELECT commit_profile_patch_cas('${LOCK_UID}', 0,
    '{\"home_school\":\"uiuc\",\"search_weight\":50,\"college\":\"C\",\"major\":\"M\",\"grade\":\"G\"}'::jsonb);" 2>&1)"
CONTENTION_RC=$?
set -e
wait "$HOLDER_PID" 2>/dev/null || true
if [[ $CONTENTION_RC -eq 0 ]]; then
  echo "TEST FAIL cas-lock-contention: CAS did not block on a held ofe-profile key"
  exit 1
fi
if ! grep -qi "lock_timeout\|canceling statement" <<<"$CONTENTION_OUT"; then
  echo "TEST FAIL cas-lock-contention: expected a lock timeout, got: $CONTENTION_OUT"
  exit 1
fi
echo "    PASS cas advisory-lock contention"

echo "==> run ops_and_tickets_test.sql"
"${PSQL[@]}" -f "$HERE/ops_and_tickets_test.sql"

echo "==> run contact_event_ledger_test.sql"
"${PSQL[@]}" -f "$HERE/contact_event_ledger_test.sql"

echo "==> run contact_event_concurrency_test.sh"
source "$HERE/contact_event_concurrency_test.sh"

echo "==> run application_event_ledger_test.sql"
"${PSQL[@]}" -f "$HERE/application_event_ledger_test.sql"

echo "==> run application_event_concurrency_test.sh"
source "$HERE/application_event_concurrency_test.sh"

echo "==> run application_material_archive_test.sql"
"${PSQL[@]}" -f "$HERE/application_material_archive_test.sql"

echo "==> run application_material_concurrency_test.sh"
source "$HERE/application_material_concurrency_test.sh"

# The contact suite is written against Supabase's real claim GUC names;
# _stubs.sql reads test.uid/test.jwt, so translate only those two names.
echo "==> run contact_material_archive_test.sql"
sed -e 's/request.jwt.claim.sub/test.uid/g' -e 's/request.jwt.claims/test.jwt/g' \
  "$HERE/contact_material_archive_test.sql" > "$WORK/contact_material_archive_test.sql"
"${PSQL[@]}" -f "$WORK/contact_material_archive_test.sql"

echo "==> run contact_material_concurrency_test.sh"
source "$HERE/contact_material_concurrency_test.sh"

for suite in target_resume_provenance_test.sql target_resume_research_provenance_test.sql \
             target_resume_lab_provenance_test.sql; do
  echo "==> run $suite"
  { printf 'BEGIN;\n'; cat "$HERE/$suite"; printf '\nROLLBACK;\n'; } \
    | "${PSQL[@]}" -v fixture_path="$HERE/target_resume_provenance_fixtures.sql"
done

echo "==> run target_resume_provenance_security_test.sql"
"${PSQL[@]}" -f "$HERE/target_resume_provenance_security_test.sql"

echo "==> run private_import_targets_test.sql"
"${PSQL[@]}" -f "$HERE/private_import_targets_test.sql"

# The upgrade suite needs the schema as it stood right before the contact
# archive migration (it applies that migration itself, then rolls back), so
# it gets its own database migrated only up to that point.
CONTACT_MIGRATION="20260925151438_contact_material_archive.sql"
echo "==> run contact_material_migration_upgrade_test.sql (pre-$CONTACT_MIGRATION database)"
"${PSQL[@]}" -c "CREATE DATABASE contact_material_upgrade"
UPGRADE_PSQL=(psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d contact_material_upgrade -q)
"${UPGRADE_PSQL[@]}" -f "$HERE/_stubs.sql"
for f in "$MIGRATIONS"/*.sql; do
  base="$(basename "$f")"
  [[ "$base" == 004_* ]] && continue
  [[ "$base" < "$CONTACT_MIGRATION" ]] || continue
  "${UPGRADE_PSQL[@]}" -f "$f"
done
"${UPGRADE_PSQL[@]}" -v contact_migration="$MIGRATIONS/$CONTACT_MIGRATION" \
  -f "$HERE/contact_material_migration_upgrade_test.sql"

echo "==> OK"
