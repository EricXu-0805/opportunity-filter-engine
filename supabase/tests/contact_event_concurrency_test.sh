#!/usr/bin/env bash
# Sourced by run_contact_event_test.sh, which supplies the disposable cluster.
set -euo pipefail
CONTACT_UID='31000000-0000-4000-8000-000000000007'
CONTACT_ID='31000000-0000-8000-8000-000000000007'
CONTACT_CALL="SELECT public.confirm_contact_event('$CONTACT_UID','$CONTACT_ID','race','a@b.c','s','race body')"
contact_wait_event() {
  local app="$1" expected="$2"
  for _attempt in {1..150}; do
    if "${PSQL[@]}" -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='$app' AND wait_event='$expected'" | grep -q 1; then return 0; fi
    sleep 0.02
  done
  return 1
}
PGAPPNAME=ofe_contact_writer_a "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$CONTACT_UID'; $CONTACT_CALL; SELECT pg_sleep(3); COMMIT" >"$WORK/contact-a.log" 2>&1 &
CONTACT_A=$!
if ! contact_wait_event ofe_contact_writer_a PgSleep; then wait "$CONTACT_A" || true; cat "$WORK/contact-a.log"; exit 1; fi
PGAPPNAME=ofe_contact_writer_b "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$CONTACT_UID'; $CONTACT_CALL" >"$WORK/contact-b.log" 2>&1 &
CONTACT_B=$!
if ! contact_wait_event ofe_contact_writer_b advisory; then wait "$CONTACT_B" || true; cat "$WORK/contact-b.log"; exit 1; fi
wait "$CONTACT_A"; wait "$CONTACT_B"
if ! grep -q '"replayed": true' "$WORK/contact-b.log"; then cat "$WORK/contact-b.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN IF (SELECT count(*) FROM public.contact_events WHERE device_id='$CONTACT_UID') <> 1 OR (SELECT count(*) FROM public.interaction_status_changes WHERE device_id='$CONTACT_UID') <> 1 THEN RAISE EXCEPTION 'concurrent identical request duplicated event/status'; END IF; END \$\$"
printf '%s\n' 'PASS contact real concurrent identical requests: one event, one status change, second replayed'

# Concurrent different payload with same id must not overwrite the first writer.
CONTACT_ID='31000000-0000-8000-8000-000000000017'
CONTACT_CALL="SELECT public.confirm_contact_event('$CONTACT_UID','$CONTACT_ID','race','a@b.c','s','winner body')"
PGAPPNAME=ofe_contact_conflict_a "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$CONTACT_UID'; $CONTACT_CALL; SELECT pg_sleep(3); COMMIT" >"$WORK/contact-conflict-a.log" 2>&1 &
CONTACT_A=$!
if ! contact_wait_event ofe_contact_conflict_a PgSleep; then wait "$CONTACT_A" || true; cat "$WORK/contact-conflict-a.log"; exit 1; fi
PGAPPNAME=ofe_contact_conflict_b "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$CONTACT_UID'; SELECT public.confirm_contact_event('$CONTACT_UID','$CONTACT_ID','race','a@b.c','s','loser body')" >"$WORK/contact-conflict-b.log" 2>&1 &
CONTACT_B=$!
if ! contact_wait_event ofe_contact_conflict_b advisory; then wait "$CONTACT_B" || true; cat "$WORK/contact-conflict-b.log"; exit 1; fi
wait "$CONTACT_A"
if wait "$CONTACT_B"; then echo 'concurrent different payload unexpectedly accepted'; exit 1; fi
if ! grep -q 'contact_event_conflict' "$WORK/contact-conflict-b.log"; then cat "$WORK/contact-conflict-b.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN IF (SELECT body FROM public.contact_events WHERE device_id='$CONTACT_UID' AND event_id='$CONTACT_ID') <> 'winner body' THEN RAISE EXCEPTION 'conflicting writer overwrote snapshot'; END IF; END \$\$"
printf '%s\n' 'PASS contact real concurrent different payload: loser conflicts, winner unchanged'

# A manual advanced-status write holds the actual interaction row lock; ledger
# upsert must wait and preserve the newly committed status, notes and reminder.
PGAPPNAME=ofe_contact_status_a "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$CONTACT_UID'; UPDATE public.interactions SET interaction_type='interviewing', notes='concurrent note', remind_at='2027-01-01' WHERE device_id='$CONTACT_UID' AND opportunity_id='race'; SELECT pg_sleep(3); COMMIT" >"$WORK/contact-status-a.log" 2>&1 &
CONTACT_A=$!
if ! contact_wait_event ofe_contact_status_a PgSleep; then wait "$CONTACT_A" || true; cat "$WORK/contact-status-a.log"; exit 1; fi
PGAPPNAME=ofe_contact_status_b "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$CONTACT_UID'; SELECT public.confirm_contact_event('$CONTACT_UID','31000000-0000-8000-8000-000000000027','race','a@b.c','s','after status body')" >"$WORK/contact-status-b.log" 2>&1 &
CONTACT_B=$!
if ! contact_wait_event ofe_contact_status_b transactionid; then wait "$CONTACT_B" || true; cat "$WORK/contact-status-b.log"; exit 1; fi
wait "$CONTACT_A"; wait "$CONTACT_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM public.interactions WHERE device_id='$CONTACT_UID' AND opportunity_id='race' AND interaction_type='interviewing' AND notes='concurrent note' AND remind_at='2027-01-01') THEN RAISE EXCEPTION 'ledger downgraded concurrent status'; END IF; END \$\$"
printf '%s\n' 'PASS contact real race against manual status update: advanced status, notes and reminder preserved'

# Account deletion waits for a pre-existing writer and removes its committed
# snapshot in the same deletion transaction. A stale token cannot resurrect it.
CONTACT_UID='31000000-0000-4000-8000-000000000009'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$CONTACT_UID')"
PGAPPNAME=ofe_contact_delete_writer "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$CONTACT_UID'; SELECT public.confirm_contact_event('$CONTACT_UID','31000000-0000-8000-8000-000000000009','delete-race','a@b.c','s','private'); SELECT pg_sleep(3); COMMIT" >"$WORK/contact-delete-writer.log" 2>&1 &
CONTACT_A=$!
if ! contact_wait_event ofe_contact_delete_writer PgSleep; then wait "$CONTACT_A" || true; cat "$WORK/contact-delete-writer.log"; exit 1; fi
PGAPPNAME=ofe_contact_deleter "${PSQL[@]}" -At -c "DELETE FROM auth.users WHERE id='$CONTACT_UID'" >"$WORK/contact-deleter.log" 2>&1 &
CONTACT_B=$!
if ! contact_wait_event ofe_contact_deleter advisory; then wait "$CONTACT_B" || true; cat "$WORK/contact-deleter.log"; exit 1; fi
wait "$CONTACT_A"; wait "$CONTACT_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF EXISTS(SELECT 1 FROM public.contact_events WHERE device_id='$CONTACT_UID') THEN RAISE EXCEPTION 'delete race retained email PII'; END IF; END \$\$"
printf '%s\n' 'PASS contact real concurrent account deletion waits for writer and removes the snapshot'

# Flow B waits for an in-flight source writer and transfers that just-written
# event together with its summary. No row can remain under the retired owner.
CONTACT_UID='31000000-0000-4000-8000-000000000010'
CONTACT_DEST='31000000-0000-4000-8000-000000000011'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$CONTACT_UID'),('$CONTACT_DEST')"
CONTACT_TOKEN="$("${PSQL[@]}" -At -c "SET test.uid='$CONTACT_UID'; SET test.jwt='{\"is_anonymous\":true}'; SELECT public.mint_merge_grant('concurrent-contact-merge@example.invalid')")"
PGAPPNAME=ofe_contact_merge_writer "${PSQL[@]}" -At -c "BEGIN; SET LOCAL ROLE authenticated; SET LOCAL test.uid='$CONTACT_UID'; SELECT public.confirm_contact_event('$CONTACT_UID','31000000-0000-8000-8000-000000000010','merge-race','a@b.c','s','moved'); SELECT pg_sleep(3); COMMIT" >"$WORK/contact-merge-writer.log" 2>&1 &
CONTACT_A=$!
if ! contact_wait_event ofe_contact_merge_writer PgSleep; then wait "$CONTACT_A" || true; cat "$WORK/contact-merge-writer.log"; exit 1; fi
PGAPPNAME=ofe_contact_merger "${PSQL[@]}" -At -c "SET ROLE authenticated; SET test.uid='$CONTACT_DEST'; SET test.jwt='{\"email\":\"concurrent-contact-merge@example.invalid\"}'; SELECT public.redeem_merge_grant('$CONTACT_TOKEN')" >"$WORK/contact-merger.log" 2>&1 &
CONTACT_B=$!
if ! contact_wait_event ofe_contact_merger advisory; then wait "$CONTACT_B" || true; cat "$WORK/contact-merger.log"; exit 1; fi
wait "$CONTACT_A"; wait "$CONTACT_B"
"${PSQL[@]}" -c "DO \$\$ BEGIN IF EXISTS(SELECT 1 FROM public.contact_events WHERE device_id='$CONTACT_UID') OR NOT EXISTS(SELECT 1 FROM public.contact_events WHERE device_id='$CONTACT_DEST' AND opportunity_id='merge-race') OR NOT EXISTS(SELECT 1 FROM public.interactions WHERE device_id='$CONTACT_DEST' AND opportunity_id='merge-race') THEN RAISE EXCEPTION 'merge race stranded event or summary'; END IF; END \$\$"
printf '%s\n' 'PASS contact real concurrent Flow B waits for source writer and transfers its event and summary'
