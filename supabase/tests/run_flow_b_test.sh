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
for f in "$MIGRATIONS"/0*.sql; do
  base="$(basename "$f")"
  case "$base" in
    004_*) echo "    skip $base (superseded by 006)"; continue ;;
  esac
  if [[ "$base" == "024_disable_pre_llc_orders.sql" ]]; then
    # Supabase grants browser roles access to public tables through its
    # managed default privileges. Mirror that state immediately before the
    # hard-close migration so this test proves 024 actively revokes it.
    "${PSQL[@]}" -c \
      "GRANT SELECT, INSERT, UPDATE, DELETE ON public.orders TO anon, authenticated"
  fi
  if [[ "$base" == "027_profile_save_cas.sql" ]]; then
    # Same reasoning as 024: without this, "authenticated cannot INSERT into
    # profiles" would be true on a vanilla cluster that never granted it, and
    # the ACL assertions in profile_save_cas_test.sql would pass whether or
    # not 027's REVOKE existed at all.
    "${PSQL[@]}" -c \
      "GRANT SELECT, INSERT, UPDATE, DELETE ON public.profiles, public.profile_versions TO PUBLIC, anon, authenticated"
    "${PSQL[@]}" -c \
      "GRANT SELECT, INSERT, UPDATE, DELETE ON public.profiles, public.profile_versions TO service_role"
  fi
  echo "    apply $base"
  "${PSQL[@]}" -f "$f"
done

echo "==> run flow_b_merge_test.sql"
"${PSQL[@]}" -f "$HERE/flow_b_merge_test.sql"

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

echo "==> OK"
