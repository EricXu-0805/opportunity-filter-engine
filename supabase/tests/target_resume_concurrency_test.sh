#!/usr/bin/env bash
# Sourced only by run_flow_b_test.sh: uses its throwaway local socket/PSQL.
set -euo pipefail
TARGET_UID='77000000-0000-4000-8000-000000000007'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$TARGET_UID')"
TARGET_DOC='{"kind":"full_resume","version":1,"id":"writer-a","opportunity_id":"race","base":{},"base_snapshot":{},"target_snapshot":{},"document":{"sections":[]}}'
PGAPPNAME=ofe_target_resume_writer_a psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 BEGIN; SET LOCAL test.uid = '$TARGET_UID';
 SELECT public.commit_target_resume_cas('$TARGET_UID','race',0,'$TARGET_DOC'::jsonb);
 SELECT pg_sleep(5); COMMIT;" >"$WORK/target-writer-a.log" 2>&1 &
TARGET_A=$!
# Observe the server inside its post-write sleep; redirected psql output is
# buffered and cannot be used as a transaction-ready handshake.
TARGET_A_READY=false
for _attempt in {1..100}; do
  if psql -h "$SOCK" -U postgres -d postgres -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='ofe_target_resume_writer_a' AND wait_event='PgSleep'" | grep -q 1; then TARGET_A_READY=true; break; fi
  sleep 0.02
done
if [[ "$TARGET_A_READY" != true ]]; then wait "$TARGET_A" || true; cat "$WORK/target-writer-a.log"; exit 1; fi
TARGET_OTHER_DOC="${TARGET_DOC/writer-a/writer-b}"
PGAPPNAME=ofe_target_resume_writer_b psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 SET test.uid = '$TARGET_UID';
 SELECT public.commit_target_resume_cas('$TARGET_UID','race',0,'$TARGET_OTHER_DOC'::jsonb);" >"$WORK/target-writer-b.log" 2>&1 &
TARGET_B=$!
TARGET_WAIT_SEEN=false
for _attempt in {1..50}; do
  if psql -h "$SOCK" -U postgres -d postgres -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='ofe_target_resume_writer_b' AND wait_event='advisory'" | grep -q 1; then TARGET_WAIT_SEEN=true; break; fi
  sleep 0.02
done
wait "$TARGET_A"
wait "$TARGET_B"
if [[ "$TARGET_WAIT_SEEN" != true ]]; then echo 'target writer B never waited on A advisory lock'; exit 1; fi
if ! grep -q '"status": "conflict"' "$WORK/target-writer-b.log"; then cat "$WORK/target-writer-b.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN
 IF (SELECT count(*) FROM public.target_resume_versions WHERE owner_id='$TARGET_UID') <> 1
   OR (SELECT doc->>'id' FROM public.target_resumes WHERE owner_id='$TARGET_UID' AND opportunity_id='race') <> 'writer-a'
 THEN RAISE EXCEPTION 'target concurrent CAS lost update'; END IF; END \$\$;"
echo '    PASS target real concurrent CAS: one saved, one conflict, one history row'

# Account deletion locks its auth.users row, then its AFTER DELETE triggers take
# the owner advisory lock. A save that queued on that advisory lock (held here by
# a third session, as any other owner RPC would) must already hold the auth row,
# or it takes the advisory lock and then its foreign-key check waits on the
# deleter: a deadlock.
target_wait() {
  for _attempt in {1..200}; do
    if psql -h "$SOCK" -U postgres -d postgres -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='$1' AND $2" | grep -q 1; then return 0; fi
    sleep 0.02
  done
  return 1
}
TARGET_UID='77000000-0000-4000-8000-000000000017'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$TARGET_UID')"
TARGET_ORDER_DOC="${TARGET_DOC/race/lock-order}"
PGAPPNAME=ofe_target_order_holder psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 BEGIN; SELECT pg_advisory_xact_lock(hashtext('ofe-profile:$TARGET_UID')); SELECT pg_sleep(3); COMMIT;" >"$WORK/target-order-holder.log" 2>&1 &
TARGET_H=$!
if ! target_wait ofe_target_order_holder "wait_event='PgSleep'"; then wait "$TARGET_H" || true; cat "$WORK/target-order-holder.log"; exit 1; fi
PGAPPNAME=ofe_target_order_save psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 SET test.uid = '$TARGET_UID';
 SELECT public.commit_target_resume_cas('$TARGET_UID','lock-order',0,'$TARGET_ORDER_DOC'::jsonb);" >"$WORK/target-order-save.log" 2>&1 &
TARGET_A=$!
if ! target_wait ofe_target_order_save "wait_event='advisory'"; then wait "$TARGET_A" || true; cat "$WORK/target-order-save.log"; exit 1; fi
PGAPPNAME=ofe_target_order_delete psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "DELETE FROM auth.users WHERE id='$TARGET_UID'" >"$WORK/target-order-delete.log" 2>&1 &
TARGET_B=$!
if ! target_wait ofe_target_order_delete "wait_event_type='Lock'"; then wait "$TARGET_B" || true; cat "$WORK/target-order-delete.log"; exit 1; fi
wait "$TARGET_H"
if ! wait "$TARGET_A"; then wait "$TARGET_B" || true; cat "$WORK/target-order-save.log"; exit 1; fi
if ! wait "$TARGET_B"; then cat "$WORK/target-order-delete.log"; exit 1; fi
if ! grep -q '"status": "saved"' "$WORK/target-order-save.log"; then cat "$WORK/target-order-save.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN
 IF EXISTS(SELECT 1 FROM auth.users WHERE id='$TARGET_UID') OR EXISTS(SELECT 1 FROM public.target_resumes WHERE owner_id='$TARGET_UID')
   OR EXISTS(SELECT 1 FROM public.target_resume_versions WHERE owner_id='$TARGET_UID') THEN RAISE EXCEPTION 'deletion after target save did not complete'; END IF; END \$\$;"
echo '    PASS target save takes the auth row before the owner advisory lock, so account deletion cannot deadlock it'
