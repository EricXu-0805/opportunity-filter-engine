#!/usr/bin/env bash
# Real disposable PostgreSQL; no hosted database or email/model calls.
# Supabase platform functions are stubbed; application schema is real migrations.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ofe-contact-ledger.XXXXXX")"
DATA="$WORK/data"; SOCK="$WORK/sock"; PORT="${OFE_CONTACT_TEST_PORT:-55437}"
mkdir -p "$SOCK"
cleanup() { pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
initdb -D "$DATA" -U postgres --auth=trust >/dev/null
openssl req -new -x509 -days 1 -nodes -subj '/CN=localhost' -out "$DATA/server.crt" -keyout "$DATA/server.key" >/dev/null 2>&1
chmod 600 "$DATA/server.key"
pg_ctl -D "$DATA" -o "-k $SOCK -p $PORT -c listen_addresses=127.0.0.1 -c ssl=on" -w start >/dev/null
PSQL=(psql -v ON_ERROR_STOP=1 -h "$SOCK" -p "$PORT" -U postgres -d postgres -q)
"${PSQL[@]}" -f "$HERE/_stubs.sql"
# Mirror managed default table grants so our explicit revokes are exercised.
"${PSQL[@]}" -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role'
for migration in "$ROOT/supabase/migrations/"*.sql; do "${PSQL[@]}" -f "$migration"; done
"${PSQL[@]}" -f "$HERE/contact_event_ledger_test.sql"
source "$HERE/contact_event_concurrency_test.sh"
# Runs against this loopback-only disposable cluster. Existing unrelated schema
# findings are reported without claiming this is a clean hosted advisor audit.
supabase db advisors --db-url "postgresql://postgres@127.0.0.1:$PORT/postgres?sslmode=require" --type security --level warn --fail-on none
printf '%s\n' 'PASS real PostgreSQL contact event ledger suite'
