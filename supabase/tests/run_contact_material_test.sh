#!/usr/bin/env bash
# Isolated PostgreSQL contract comparison. Platform auth/Storage are stubs,
# not proof that a hosted or local Supabase image is free of runtime defects.
set -euo pipefail
MODE="${1:-full}"
if [[ "$MODE" != full && "$MODE" != --upgrade-only ]]; then printf '%s\n' 'Usage: run_contact_material_test.sh [--upgrade-only]' >&2; exit 2; fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ofe-contact-material.XXXXXX")"
DATA="$WORK/data"; SOCK="$WORK/sock"; PORT="${OFE_CONTACT_MATERIAL_TEST_PORT:-55439}"
mkdir -p "$SOCK"
cleanup() { pg_ctl -D "$DATA" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
initdb -D "$DATA" -U postgres --auth=trust >/dev/null
openssl req -new -x509 -days 1 -nodes -subj '/CN=localhost' -out "$DATA/server.crt" -keyout "$DATA/server.key" >/dev/null 2>&1
chmod 600 "$DATA/server.key"
pg_ctl -D "$DATA" -o "-k $SOCK -p $PORT -c listen_addresses=127.0.0.1 -c ssl=on" -w start >/dev/null
PSQL=(psql -v ON_ERROR_STOP=1 -h "$SOCK" -p "$PORT" -U postgres -d postgres -q)
"${PSQL[@]}" -At -c "SELECT version()"
for phase in before after; do
  "${PSQL[@]}" -c "CREATE DATABASE material_$phase"
  PSQL=(psql -v ON_ERROR_STOP=1 -h "$SOCK" -p "$PORT" -U postgres -d "material_$phase" -q)
  "${PSQL[@]}" -f "$HERE/_stubs.sql" >/dev/null
  "${PSQL[@]}" -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role'
  for migration in "$ROOT/supabase/migrations/"*.sql; do
    # The quota migration replaces a function the contact migration creates.
    if [[ "$phase" == before && ( "$migration" == */20260925151438_contact_material_archive.sql
          || "$migration" == */20260930090000_owner_storage_quotas.sql ) ]]; then continue; fi
    "${PSQL[@]}" -f "$migration" >/dev/null
  done
  if [[ "$phase" == before && "$MODE" == --upgrade-only ]]; then
    "${PSQL[@]}" -v contact_migration="$ROOT/supabase/migrations/20260925151438_contact_material_archive.sql" -f "$HERE/contact_material_migration_upgrade_test.sql" >/dev/null
    printf '%s\n' 'PASS isolated same-database material migration upgrade'
    exit 0
  fi
  "${PSQL[@]}" -f "$HERE/application_material_archive_test.sql" >/dev/null
  source "$HERE/application_material_concurrency_test.sh"
  if [[ "$phase" == before ]]; then
    "${PSQL[@]}" -v contact_migration="$ROOT/supabase/migrations/20260925151438_contact_material_archive.sql" -f "$HERE/contact_material_migration_upgrade_test.sql" >/dev/null
  fi
  printf '%s\n' "PASS $phase application SQL and concurrency regression"
done
# New contact tests intentionally use real Supabase claim GUC names. Translate
# only those names for this platform-stub comparison, without editing the tests.
sed -e 's/request.jwt.claim.sub/test.uid/g' -e 's/request.jwt.claims/test.jwt/g' "$HERE/contact_material_archive_test.sql" > "$WORK/contact.sql"
"${PSQL[@]}" -f "$WORK/contact.sql" >/dev/null
source "$HERE/contact_material_concurrency_test.sh"
{ printf 'BEGIN;\n'; cat "$HERE/contact_event_ledger_test.sql"; printf '\nROLLBACK;\n'; } | "${PSQL[@]}" >/dev/null
printf '%s\n' 'PASS unchanged contact-event ledger regression'
"${PSQL[@]}" -f "$HERE/owner_storage_quota_test.sql" >/dev/null
printf '%s\n' 'PASS per-account material and private-import quotas'
"${PSQL[@]}" -c 'DROP TABLE public.material_test_receipts,public.contact_material_test_receipts'
supabase db advisors --db-url "postgresql://postgres@127.0.0.1:$PORT/material_after?sslmode=require" --type security --level warn --fail-on none
printf '%s\n' 'PASS isolated pre/post-migration application and contact material suites'
