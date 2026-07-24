#!/usr/bin/env bash
# Prove the migration directory with the real Supabase CLI, including its
# supabase_migrations history table. This catches dependency ordering and
# duplicate-version failures that a plain `psql -f` loop cannot detect
# (the Flow B runner skips 004 and never writes migration history).
#
# Requires: supabase CLI (pinned version), PostgreSQL client/server tools,
# and openssl. No Docker: runs against a throwaway local cluster with the
# Supabase platform stubs from _stubs.sql.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ofe-supabase-cli.XXXXXX")"
DATA="$WORK/data"
SOCK="$WORK/sock"
PORT="${OFE_SUPABASE_CLI_TEST_PORT:-55436}"
mkdir -p "$SOCK"

cleanup() {
  pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

for required in supabase initdb pg_ctl psql openssl; do
  if ! command -v "$required" >/dev/null 2>&1; then
    echo "missing required command: $required" >&2
    exit 2
  fi
done

EXPECTED_SUPABASE_CLI_VERSION="${OFE_SUPABASE_CLI_VERSION:-2.95.4}"
ACTUAL_SUPABASE_CLI_VERSION="$(supabase --version)"
if [[ "$ACTUAL_SUPABASE_CLI_VERSION" != "$EXPECTED_SUPABASE_CLI_VERSION" ]]; then
  echo "Supabase CLI version mismatch: expected $EXPECTED_SUPABASE_CLI_VERSION, got $ACTUAL_SUPABASE_CLI_VERSION" >&2
  exit 2
fi

echo "==> init stock PostgreSQL with Supabase platform-only stubs"
initdb -D "$DATA" -U postgres --auth=trust >/dev/null
openssl req -new -x509 -days 1 -nodes -subj '/CN=localhost' \
  -out "$DATA/server.crt" -keyout "$DATA/server.key" >/dev/null 2>&1
chmod 600 "$DATA/server.key"
pg_ctl -D "$DATA" \
  -o "-k $SOCK -p $PORT -c listen_addresses=127.0.0.1 -c ssl=on" \
  -w start >/dev/null

PSQL=(psql -v ON_ERROR_STOP=1 -h "$SOCK" -p "$PORT" -U postgres -d postgres -q)
"${PSQL[@]}" -f "$HERE/_stubs.sql"

DB_URL="postgresql://postgres@127.0.0.1:${PORT}/postgres?sslmode=require"

echo "==> real Supabase CLI push (includes migration history)"
(
  cd "$ROOT"
  supabase db push --include-all --yes --db-url "$DB_URL"
)

echo "==> verify migration history"
"${PSQL[@]}" -f "$HERE/migration_history_contract_test.sql"

echo "==> REAL SUPABASE CLI MIGRATION CONTRACT OK"
