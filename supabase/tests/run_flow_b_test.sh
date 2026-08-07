#!/usr/bin/env bash
# Verify migrations 017/018 (Flow B cross-device merge) + 019 (orders RLS)
# against a real, throwaway Postgres cluster — no docker, no Supabase. Spins
# an ephemeral cluster in a temp dir, loads test stubs -> the effective prod
# schema (migrations, 004 is excluded because 006 supersedes it), runs
# flow_b_merge_test.sql + orders_rls_test.sql, and tears everything down.
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
  echo "    apply $base"
  "${PSQL[@]}" -f "$f"
done

echo "==> run flow_b_merge_test.sql"
"${PSQL[@]}" -f "$HERE/flow_b_merge_test.sql"

echo "==> run orders_rls_test.sql"
"${PSQL[@]}" -f "$HERE/orders_rls_test.sql"

echo "==> run professor_tracking_merge_test.sql"
"${PSQL[@]}" -f "$HERE/professor_tracking_merge_test.sql"

echo "==> run ops_and_tickets_test.sql"
"${PSQL[@]}" -f "$HERE/ops_and_tickets_test.sql"

echo "==> OK"
