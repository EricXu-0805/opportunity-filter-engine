#!/usr/bin/env bash
# Sourced by the disposable cluster runner after application_material_archive_test.sql.
set -euo pipefail
material_wait_event() {
  local app="$1" expected="$2"
  for _attempt in {1..200}; do
    if "${PSQL[@]}" -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='$app' AND wait_event='$expected'" | grep -q 1; then return 0; fi
    sleep 0.02
  done
  return 1
}
material_wait_lock() {
  for _attempt in {1..200}; do
    if "${PSQL[@]}" -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='$1' AND wait_event_type='Lock'" | grep -q 1; then return 0; fi
    sleep 0.02
  done
  return 1
}
material_fixture() {
  printf -v MATERIAL_OWNER '33000000-0000-4000-8000-%012d' "$1"
  printf -v MATERIAL_ID '34000000-0000-4000-9000-%012d' "$1"
  printf -v MATERIAL_RECORD '34000000-0000-4000-a000-%012d' "$1"
  MATERIAL_AUTH="SET ROLE authenticated; SET test.uid='$MATERIAL_OWNER'; SET test.jwt='{\"session_id\":\"$MATERIAL_OWNER\",\"exp\":4102444800}'"
  MATERIAL_STAGE="public.stage_application_material('$MATERIAL_OWNER','$MATERIAL_ID','$MATERIAL_RECORD','$MATERIAL_OWNER','opp','race.pdf',123,repeat('a',64))"
  MATERIAL_FINAL="public.finalize_application_material('$MATERIAL_OWNER','$MATERIAL_OWNER','$MATERIAL_ID',(SELECT (v#>>'{upload,stage_token}')::uuid FROM public.material_test_receipts WHERE k='race-$1'),123,repeat('a',64))"
}
material_fixture 13
PGAPPNAME=ofe_material_stage_a "${PSQL[@]}" -At -c "BEGIN; $MATERIAL_AUTH; INSERT INTO public.material_test_receipts VALUES('race-old-13',$MATERIAL_STAGE); SELECT pg_sleep(3); COMMIT" >"$WORK/material-stage-a.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_stage_a PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-stage-a.log"; exit 1; fi
PGAPPNAME=ofe_material_stage_b "${PSQL[@]}" -At -c "$MATERIAL_AUTH; INSERT INTO public.material_test_receipts VALUES('race-13',$MATERIAL_STAGE)" >"$WORK/material-stage-b.log" 2>&1 &
MATERIAL_B=$!
if ! material_wait_event ofe_material_stage_b advisory; then wait "$MATERIAL_B" || true; cat "$WORK/material-stage-b.log"; exit 1; fi
wait "$MATERIAL_A"; wait "$MATERIAL_B"
"${PSQL[@]}" -c "SET ROLE service_role; DO \$\$ BEGIN BEGIN PERFORM public.finalize_application_material('$MATERIAL_OWNER','$MATERIAL_OWNER','$MATERIAL_ID',(SELECT (v#>>'{upload,stage_token}')::uuid FROM public.material_test_receipts WHERE k='race-old-13'),123,repeat('a',64)); RAISE EXCEPTION 'old parallel upload finalized'; EXCEPTION WHEN object_in_use THEN NULL; END; END \$\$; SELECT $MATERIAL_FINAL" >"$WORK/material-stage-verify.log" 2>&1
"${PSQL[@]}" -c "DO \$\$ BEGIN IF (SELECT count(*) FROM public.application_material_records WHERE material_id='$MATERIAL_ID')<>1 THEN RAISE EXCEPTION 'parallel stage duplicated association'; END IF; END \$\$"
printf '%s\n' 'PASS material concurrent stage retry waits, rotates capability and fences old finalize'

material_fixture 14
"${PSQL[@]}" -c "$MATERIAL_AUTH; INSERT INTO public.material_test_receipts VALUES('race-14',$MATERIAL_STAGE)"
PGAPPNAME=ofe_material_finalize_a "${PSQL[@]}" -At -c "BEGIN; SET ROLE service_role; SELECT $MATERIAL_FINAL; SELECT pg_sleep(3); COMMIT" >"$WORK/material-finalize-a.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_finalize_a PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-finalize-a.log"; exit 1; fi
PGAPPNAME=ofe_material_delete_b "${PSQL[@]}" -At -c "$MATERIAL_AUTH; SELECT public.delete_application_material('$MATERIAL_OWNER','$MATERIAL_RECORD','$MATERIAL_ID','$MATERIAL_OWNER','opp')" >"$WORK/material-delete-b.log" 2>&1 &
MATERIAL_B=$!
if ! material_wait_event ofe_material_delete_b advisory; then wait "$MATERIAL_B" || true; cat "$WORK/material-delete-b.log"; exit 1; fi
wait "$MATERIAL_A"; wait "$MATERIAL_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM public.material_artifacts WHERE material_id='$MATERIAL_ID' AND status='deleted' AND sha256 IS NULL) OR NOT EXISTS(SELECT 1 FROM public.application_material_records WHERE material_id='$MATERIAL_ID') OR NOT EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='$MATERIAL_ID') THEN RAISE EXCEPTION 'concurrent delete failed atomic revoke/redaction'; END IF; END \$\$"
printf '%s\n' 'PASS material concurrent delete waits for finalize then revokes download and queues bytes removal'

material_fixture 15
"${PSQL[@]}" -c "$MATERIAL_AUTH; INSERT INTO public.material_test_receipts VALUES('race-15',$MATERIAL_STAGE)"
PGAPPNAME=ofe_material_logout_writer "${PSQL[@]}" -At -c "BEGIN; SET ROLE service_role; SELECT $MATERIAL_FINAL; SELECT pg_sleep(3); COMMIT" >"$WORK/material-logout-writer.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_logout_writer PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-logout-writer.log"; exit 1; fi
PGAPPNAME=ofe_material_logout "${PSQL[@]}" -At -c "DELETE FROM auth.sessions WHERE id='$MATERIAL_OWNER'" >"$WORK/material-logout.log" 2>&1 &
MATERIAL_B=$!
if ! material_wait_event ofe_material_logout transactionid; then wait "$MATERIAL_B" || true; cat "$WORK/material-logout.log"; exit 1; fi
wait "$MATERIAL_A"; wait "$MATERIAL_B"
"${PSQL[@]}" -c "$MATERIAL_AUTH; DO \$\$ BEGIN BEGIN PERFORM public.authorize_application_material_download('$MATERIAL_OWNER','$MATERIAL_RECORD','$MATERIAL_OWNER','opp'); RAISE EXCEPTION 'logged out session read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END; END \$\$"
printf '%s\n' 'PASS material real session logout fences transaction and old JWT can no longer authorize download'

material_fixture 16
"${PSQL[@]}" -c "$MATERIAL_AUTH; INSERT INTO public.material_test_receipts VALUES('race-16',$MATERIAL_STAGE)"
PGAPPNAME=ofe_material_auth_writer "${PSQL[@]}" -At -c "BEGIN; SET ROLE service_role; SELECT $MATERIAL_FINAL; SELECT pg_sleep(3); COMMIT" >"$WORK/material-auth-writer.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_auth_writer PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-auth-writer.log"; exit 1; fi
PGAPPNAME=ofe_material_auth_delete "${PSQL[@]}" -At -c "DELETE FROM auth.users WHERE id='$MATERIAL_OWNER'" >"$WORK/material-auth-delete.log" 2>&1 &
MATERIAL_B=$!
if ! material_wait_lock ofe_material_auth_delete; then wait "$MATERIAL_B" || true; cat "$WORK/material-auth-delete.log"; exit 1; fi
wait "$MATERIAL_A"; wait "$MATERIAL_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF EXISTS(SELECT 1 FROM public.material_artifacts WHERE owner_id='$MATERIAL_OWNER') OR EXISTS(SELECT 1 FROM public.application_material_records WHERE owner_id='$MATERIAL_OWNER') OR NOT EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='$MATERIAL_ID') THEN RAISE EXCEPTION 'auth deletion orphaned private material'; END IF; END \$\$"
printf '%s\n' 'PASS material account deletion waits before session cascade and preserves only opaque cleanup intent'

material_fixture 17
MATERIAL_DEST='33000000-0000-4000-8000-000000000018'
MATERIAL_GRANT="$("${PSQL[@]}" -At -c "SET test.uid='$MATERIAL_OWNER'; SET test.jwt='{\"is_anonymous\":true}'; SELECT public.mint_merge_grant('material-race@example.invalid')")"
PGAPPNAME=ofe_material_merge_writer "${PSQL[@]}" -At -c "BEGIN; $MATERIAL_AUTH; INSERT INTO public.material_test_receipts VALUES('race-17',$MATERIAL_STAGE); SELECT pg_sleep(3); COMMIT" >"$WORK/material-merge-writer.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_merge_writer PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-merge-writer.log"; exit 1; fi
PGAPPNAME=ofe_material_merger "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$MATERIAL_DEST'; SET test.jwt='{\"email\":\"material-race@example.invalid\"}'; SELECT public.redeem_merge_grant('$MATERIAL_GRANT')" >"$WORK/material-merger.log" 2>&1 &
MATERIAL_B=$!
if ! material_wait_event ofe_material_merger advisory; then wait "$MATERIAL_B" || true; cat "$WORK/material-merger.log"; exit 1; fi
wait "$MATERIAL_A"; wait "$MATERIAL_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM public.material_artifacts WHERE material_id='$MATERIAL_ID' AND owner_id='$MATERIAL_DEST' AND status='deleted' AND filename IS NULL) OR NOT EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='$MATERIAL_ID') THEN RAISE EXCEPTION 'merge left resumable old upload'; END IF; END \$\$"
printf '%s\n' 'PASS material concurrent Flow B waits for stage then revokes the old upload without moving its object key'

"${PSQL[@]}" -c "UPDATE private.material_cleanup_outbox SET next_attempt_at=now()-interval '1 day',claim_token=NULL,claimed_until=NULL"
PGAPPNAME=ofe_material_cleanup_a "${PSQL[@]}" -At -c "BEGIN; SET ROLE service_role; INSERT INTO public.material_test_receipts VALUES('cleanup-a',public.claim_material_cleanup(1)); SELECT pg_sleep(3); COMMIT" >"$WORK/material-cleanup-a.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_cleanup_a PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-cleanup-a.log"; exit 1; fi
"${PSQL[@]}" -c "SET ROLE service_role; INSERT INTO public.material_test_receipts VALUES('cleanup-b',public.claim_material_cleanup(1))"
wait "$MATERIAL_A"
"${PSQL[@]}" -c "DO \$\$ DECLARE a jsonb;b jsonb; BEGIN SELECT v INTO a FROM public.material_test_receipts WHERE k='cleanup-a'; SELECT v INTO b FROM public.material_test_receipts WHERE k='cleanup-b'; IF jsonb_array_length(a->'jobs')<>1 OR jsonb_array_length(b->'jobs')<>1 OR a#>>'{jobs,0,material_id}'=b#>>'{jobs,0,material_id}' THEN RAISE EXCEPTION 'parallel cleanup claim duplicated job'; END IF; END \$\$"
printf '%s\n' 'PASS material concurrent cleanup workers skip locked keys and claim distinct revoked objects'

# An explicit cancel which commits first wins even when the original HTTP stage
# arrives on another connection while cancellation still holds its owner lock.
material_fixture 19
PGAPPNAME=ofe_material_cancel_first "${PSQL[@]}" -At -c "BEGIN; $MATERIAL_AUTH; SELECT public.delete_application_material('$MATERIAL_OWNER','$MATERIAL_RECORD','$MATERIAL_ID','$MATERIAL_OWNER','opp'); SELECT pg_sleep(3); COMMIT" >"$WORK/material-cancel-first.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_cancel_first PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-cancel-first.log"; exit 1; fi
PGAPPNAME=ofe_material_late_stage "${PSQL[@]}" -At -c "$MATERIAL_AUTH; INSERT INTO public.material_test_receipts VALUES('race-cancel-first',$MATERIAL_STAGE)" >"$WORK/material-late-stage.log" 2>&1 &
MATERIAL_B=$!
if ! material_wait_event ofe_material_late_stage advisory; then wait "$MATERIAL_B" || true; cat "$WORK/material-late-stage.log"; exit 1; fi
wait "$MATERIAL_A"; wait "$MATERIAL_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF (SELECT v#>>'{artifact,status}' FROM public.material_test_receipts WHERE k='race-cancel-first')<>'deleted' OR EXISTS(SELECT 1 FROM public.application_material_records WHERE material_id='$MATERIAL_ID') OR NOT EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='$MATERIAL_ID') THEN RAISE EXCEPTION 'late stage revived cancelled attempt'; END IF; END \$\$"
printf '%s\n' 'PASS material concurrent pre-stage cancel wins, late stage receives deleted and no association is created'

material_fixture 20
PGAPPNAME=ofe_material_stage_first "${PSQL[@]}" -At -c "BEGIN; $MATERIAL_AUTH; INSERT INTO public.material_test_receipts VALUES('race-20',$MATERIAL_STAGE); SELECT pg_sleep(3); COMMIT" >"$WORK/material-stage-first.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_stage_first PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-stage-first.log"; exit 1; fi
PGAPPNAME=ofe_material_cancel_after_stage "${PSQL[@]}" -At -c "$MATERIAL_AUTH; SELECT public.delete_application_material('$MATERIAL_OWNER','$MATERIAL_RECORD','$MATERIAL_ID','$MATERIAL_OWNER','opp')" >"$WORK/material-cancel-after-stage.log" 2>&1 &
MATERIAL_B=$!
if ! material_wait_event ofe_material_cancel_after_stage advisory; then wait "$MATERIAL_B" || true; cat "$WORK/material-cancel-after-stage.log"; exit 1; fi
wait "$MATERIAL_A"; wait "$MATERIAL_B"
"${PSQL[@]}" -c "SET ROLE service_role; DO \$\$ BEGIN IF ($MATERIAL_FINAL)#>>'{artifact,status}'<>'deleted' THEN RAISE EXCEPTION 'late finalize revived cancelled stage'; END IF; END \$\$"
printf '%s\n' 'PASS material concurrent stage then cancel revokes original capability before delayed finalize'

# Account deletion locks the auth.users row before its triggers take the owner
# advisory lock. An owner-locked transaction that later touches that row, as a
# foreign-key check does, must not wait on the deleter while it waits back.
printf -v MATERIAL_OWNER '33000000-0000-4000-8000-%012d' 21
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES('$MATERIAL_OWNER'); INSERT INTO auth.sessions(id,user_id) VALUES('$MATERIAL_OWNER','$MATERIAL_OWNER')"
PGAPPNAME=ofe_material_owner_lock "${PSQL[@]}" -At -c "BEGIN; SET test.uid='$MATERIAL_OWNER'; SET test.jwt='{\"session_id\":\"$MATERIAL_OWNER\",\"exp\":4102444800}'; SELECT private.material_user('$MATERIAL_OWNER'); SELECT pg_sleep(3); SELECT 1 FROM auth.users WHERE id='$MATERIAL_OWNER' FOR KEY SHARE; COMMIT" >"$WORK/material-owner-lock.log" 2>&1 &
MATERIAL_A=$!
if ! material_wait_event ofe_material_owner_lock PgSleep; then wait "$MATERIAL_A" || true; cat "$WORK/material-owner-lock.log"; exit 1; fi
PGAPPNAME=ofe_material_owner_delete "${PSQL[@]}" -At -c "DELETE FROM auth.users WHERE id='$MATERIAL_OWNER'" >"$WORK/material-owner-delete.log" 2>&1 &
MATERIAL_B=$!
if ! material_wait_lock ofe_material_owner_delete; then wait "$MATERIAL_B" || true; cat "$WORK/material-owner-delete.log"; exit 1; fi
if ! wait "$MATERIAL_A"; then wait "$MATERIAL_B" || true; cat "$WORK/material-owner-lock.log"; exit 1; fi
if ! wait "$MATERIAL_B"; then cat "$WORK/material-owner-delete.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN IF EXISTS(SELECT 1 FROM auth.users WHERE id='$MATERIAL_OWNER') THEN RAISE EXCEPTION 'account deletion did not complete'; END IF; END \$\$"
printf '%s\n' 'PASS material owner lock takes the auth row before the owner advisory lock, so account deletion cannot deadlock it'
