#!/usr/bin/env bash
# Sourced by run_application_event_test.sh, which supplies the disposable cluster.
set -euo pipefail
APPLICATION_UID='32000000-0000-4000-8000-000000000007'
APPLICATION_ID='32000000-0000-8000-8000-000000000007'
APPLICATION_CALL="SELECT public.confirm_application_event('$APPLICATION_UID','$APPLICATION_ID','race','other','Office')"
application_wait_event() {
  local app="$1" expected="$2"
  for _attempt in {1..150}; do
    if "${PSQL[@]}" -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='$app' AND wait_event='$expected'" | grep -q 1; then return 0; fi
    sleep 0.02
  done
  return 1
}
application_wait_lock() {
  for _attempt in {1..200}; do
    if "${PSQL[@]}" -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='$1' AND wait_event_type='Lock'" | grep -q 1; then return 0; fi
    sleep 0.02
  done
  return 1
}
PGAPPNAME=ofe_application_writer_a "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$APPLICATION_UID'; $APPLICATION_CALL; SELECT pg_sleep(3); COMMIT" >"$WORK/application-a.log" 2>&1 &
APPLICATION_A=$!
if ! application_wait_event ofe_application_writer_a PgSleep; then wait "$APPLICATION_A" || true; cat "$WORK/application-a.log"; exit 1; fi
PGAPPNAME=ofe_application_writer_b "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$APPLICATION_UID'; $APPLICATION_CALL" >"$WORK/application-b.log" 2>&1 &
APPLICATION_B=$!
if ! application_wait_event ofe_application_writer_b advisory; then wait "$APPLICATION_B" || true; cat "$WORK/application-b.log"; exit 1; fi
wait "$APPLICATION_A"; wait "$APPLICATION_B"
if ! grep -q '"replayed": true' "$WORK/application-b.log"; then cat "$WORK/application-b.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN IF (SELECT count(*) FROM public.application_events WHERE device_id='$APPLICATION_UID') <> 1 OR (SELECT count(*) FROM public.interaction_status_changes WHERE device_id='$APPLICATION_UID') <> 1 THEN RAISE EXCEPTION 'concurrent identical request duplicated event/status'; END IF; END \$\$"
printf '%s\n' 'PASS application real concurrent identical requests: one event, one status change, second replayed'

# Concurrent different payload with same id must not overwrite the first writer.
APPLICATION_ID='32000000-0000-8000-8000-000000000017'
APPLICATION_CALL="SELECT public.confirm_application_event('$APPLICATION_UID','$APPLICATION_ID','race','other','Winner office')"
PGAPPNAME=ofe_application_conflict_a "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$APPLICATION_UID'; $APPLICATION_CALL; SELECT pg_sleep(3); COMMIT" >"$WORK/application-conflict-a.log" 2>&1 &
APPLICATION_A=$!
if ! application_wait_event ofe_application_conflict_a PgSleep; then wait "$APPLICATION_A" || true; cat "$WORK/application-conflict-a.log"; exit 1; fi
PGAPPNAME=ofe_application_conflict_b "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$APPLICATION_UID'; SELECT public.confirm_application_event('$APPLICATION_UID','$APPLICATION_ID','race','other','Loser office')" >"$WORK/application-conflict-b.log" 2>&1 &
APPLICATION_B=$!
if ! application_wait_event ofe_application_conflict_b advisory; then wait "$APPLICATION_B" || true; cat "$WORK/application-conflict-b.log"; exit 1; fi
wait "$APPLICATION_A"
if wait "$APPLICATION_B"; then echo 'concurrent different payload unexpectedly accepted'; exit 1; fi
if ! grep -q 'application_event_conflict' "$WORK/application-conflict-b.log"; then cat "$WORK/application-conflict-b.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN IF (SELECT destination FROM public.application_events WHERE device_id='$APPLICATION_UID' AND event_id='$APPLICATION_ID') <> 'Winner office' THEN RAISE EXCEPTION 'conflicting writer overwrote snapshot'; END IF; END \$\$"
printf '%s\n' 'PASS application real concurrent different payload: loser conflicts, winner unchanged'

# A manual advanced-status write holds the actual interaction row lock; ledger
# upsert must wait and preserve the newly committed status, notes and reminder.
PGAPPNAME=ofe_application_status_a "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$APPLICATION_UID'; UPDATE public.interactions SET interaction_type='interviewing', notes='concurrent note', remind_at='2027-01-01' WHERE device_id='$APPLICATION_UID' AND opportunity_id='race'; SELECT pg_sleep(3); COMMIT" >"$WORK/application-status-a.log" 2>&1 &
APPLICATION_A=$!
if ! application_wait_event ofe_application_status_a PgSleep; then wait "$APPLICATION_A" || true; cat "$WORK/application-status-a.log"; exit 1; fi
PGAPPNAME=ofe_application_status_b "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$APPLICATION_UID'; SELECT public.confirm_application_event('$APPLICATION_UID','32000000-0000-8000-8000-000000000027','race','other','After status office')" >"$WORK/application-status-b.log" 2>&1 &
APPLICATION_B=$!
if ! application_wait_event ofe_application_status_b transactionid; then wait "$APPLICATION_B" || true; cat "$WORK/application-status-b.log"; exit 1; fi
wait "$APPLICATION_A"; wait "$APPLICATION_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM public.interactions WHERE device_id='$APPLICATION_UID' AND opportunity_id='race' AND interaction_type='interviewing' AND notes='concurrent note' AND remind_at='2027-01-01') THEN RAISE EXCEPTION 'ledger downgraded concurrent status'; END IF; END \$\$"
printf '%s\n' 'PASS application real race against manual status update: advanced status, notes and reminder preserved'

# Account deletion waits for a pre-existing writer and removes its committed
# snapshot in the same deletion transaction. A stale token cannot resurrect it.
APPLICATION_UID='32000000-0000-4000-8000-000000000009'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$APPLICATION_UID')"
PGAPPNAME=ofe_application_delete_writer "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$APPLICATION_UID'; SELECT public.confirm_application_event('$APPLICATION_UID','32000000-0000-8000-8000-000000000009','delete-race','other','Private office'); SELECT pg_sleep(3); COMMIT" >"$WORK/application-delete-writer.log" 2>&1 &
APPLICATION_A=$!
if ! application_wait_event ofe_application_delete_writer PgSleep; then wait "$APPLICATION_A" || true; cat "$WORK/application-delete-writer.log"; exit 1; fi
PGAPPNAME=ofe_application_deleter "${PSQL[@]}" -At -c "DELETE FROM auth.users WHERE id='$APPLICATION_UID'" >"$WORK/application-deleter.log" 2>&1 &
APPLICATION_B=$!
if ! application_wait_lock ofe_application_deleter; then wait "$APPLICATION_B" || true; cat "$WORK/application-deleter.log"; exit 1; fi
wait "$APPLICATION_A"; wait "$APPLICATION_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF EXISTS(SELECT 1 FROM public.application_events WHERE device_id='$APPLICATION_UID') THEN RAISE EXCEPTION 'delete race retained application PII'; END IF; END \$\$"
printf '%s\n' 'PASS application real concurrent account deletion waits for writer and removes the snapshot'

# Flow B waits for an in-flight source writer and transfers that just-written
# event together with its summary. No row can remain under the retired owner.
APPLICATION_UID='32000000-0000-4000-8000-000000000010'
APPLICATION_DEST='32000000-0000-4000-8000-000000000011'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$APPLICATION_UID'),('$APPLICATION_DEST')"
APPLICATION_TOKEN="$("${PSQL[@]}" -At -c "SET test.uid='$APPLICATION_UID'; SET test.jwt='{\"is_anonymous\":true}'; SELECT public.mint_merge_grant('concurrent-application-merge@example.invalid')")"
PGAPPNAME=ofe_application_merge_writer "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$APPLICATION_UID'; SELECT public.confirm_application_event('$APPLICATION_UID','32000000-0000-8000-8000-000000000010','merge-race','other','Moved office'); SELECT pg_sleep(3); COMMIT" >"$WORK/application-merge-writer.log" 2>&1 &
APPLICATION_A=$!
if ! application_wait_event ofe_application_merge_writer PgSleep; then wait "$APPLICATION_A" || true; cat "$WORK/application-merge-writer.log"; exit 1; fi
PGAPPNAME=ofe_application_merger "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$APPLICATION_DEST'; SET test.jwt='{\"email\":\"concurrent-application-merge@example.invalid\"}'; SELECT public.redeem_merge_grant('$APPLICATION_TOKEN')" >"$WORK/application-merger.log" 2>&1 &
APPLICATION_B=$!
if ! application_wait_event ofe_application_merger advisory; then wait "$APPLICATION_B" || true; cat "$WORK/application-merger.log"; exit 1; fi
wait "$APPLICATION_A"; wait "$APPLICATION_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF EXISTS(SELECT 1 FROM public.application_events WHERE device_id='$APPLICATION_UID') OR NOT EXISTS(SELECT 1 FROM public.application_events WHERE device_id='$APPLICATION_DEST' AND opportunity_id='merge-race') OR NOT EXISTS(SELECT 1 FROM public.interactions WHERE device_id='$APPLICATION_DEST' AND opportunity_id='merge-race') THEN RAISE EXCEPTION 'merge race stranded event or summary'; END IF; END \$\$"
printf '%s\n' 'PASS application real concurrent Flow B waits for source writer and transfers its event and summary'

# Account deletion locks its auth.users row (and, by cascade, the owner's
# private import rows) before its triggers take the owner advisory lock. A
# confirmation queued on that advisory lock (held here by a third session) must
# already hold the auth row, or it takes the advisory lock and then waits on the
# deleter's cascaded private import row while the deleter waits back.
APPLICATION_UID='32000000-0000-4000-8000-000000000012'
APPLICATION_TARGET='private-import:32000000-0000-4000-8000-000000000012'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$APPLICATION_UID');
 INSERT INTO public.private_import_targets(id,owner_id,revision,opportunity) VALUES ('$APPLICATION_TARGET','$APPLICATION_UID',1,'{}'::jsonb)"
PGAPPNAME=ofe_application_order_holder "${PSQL[@]}" -At -c "BEGIN; SELECT pg_advisory_xact_lock(hashtext('ofe-profile:$APPLICATION_UID')); SELECT pg_sleep(3); COMMIT" >"$WORK/application-order-holder.log" 2>&1 &
APPLICATION_H=$!
if ! application_wait_event ofe_application_order_holder PgSleep; then wait "$APPLICATION_H" || true; cat "$WORK/application-order-holder.log"; exit 1; fi
PGAPPNAME=ofe_application_order_writer "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$APPLICATION_UID'; SELECT public.confirm_application_event('$APPLICATION_UID','32000000-0000-8000-8000-000000000012','$APPLICATION_TARGET','other','Lock order office')" >"$WORK/application-order-writer.log" 2>&1 &
APPLICATION_A=$!
if ! application_wait_event ofe_application_order_writer advisory; then wait "$APPLICATION_A" || true; cat "$WORK/application-order-writer.log"; exit 1; fi
PGAPPNAME=ofe_application_order_delete "${PSQL[@]}" -At -c "DELETE FROM auth.users WHERE id='$APPLICATION_UID'" >"$WORK/application-order-delete.log" 2>&1 &
APPLICATION_B=$!
if ! application_wait_lock ofe_application_order_delete; then wait "$APPLICATION_B" || true; cat "$WORK/application-order-delete.log"; exit 1; fi
wait "$APPLICATION_H"
if ! wait "$APPLICATION_A"; then wait "$APPLICATION_B" || true; cat "$WORK/application-order-writer.log"; exit 1; fi
if ! wait "$APPLICATION_B"; then cat "$WORK/application-order-delete.log"; exit 1; fi
if ! grep -q '"replayed": false' "$WORK/application-order-writer.log"; then cat "$WORK/application-order-writer.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN IF EXISTS(SELECT 1 FROM auth.users WHERE id='$APPLICATION_UID') OR EXISTS(SELECT 1 FROM public.application_events WHERE device_id='$APPLICATION_UID') OR EXISTS(SELECT 1 FROM public.private_import_targets WHERE owner_id='$APPLICATION_UID') THEN RAISE EXCEPTION 'deletion after application confirmation did not complete'; END IF; END \$\$"
printf '%s\n' 'PASS application confirmation takes the auth row before the owner advisory lock, so account deletion cannot deadlock it'
