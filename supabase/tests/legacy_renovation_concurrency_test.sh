#!/usr/bin/env bash
# Sourced only by run_flow_b_test.sh: uses its throwaway local socket/PSQL.
set -euo pipefail
LEGACY_UID='88000000-0000-4000-8000-000000000013'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$LEGACY_UID')"
LEGACY_DOC='{"doc":{"sections":[],"id":"writer-a"},"base_snapshot":{},"method":null,"warnings":[]}'
PGAPPNAME=ofe_legacy_resume_writer_a psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 BEGIN; SET LOCAL test.uid = '$LEGACY_UID';
 SELECT public.save_renovation_cas('$LEGACY_UID','race',0,'$LEGACY_DOC'::jsonb);
 SELECT pg_sleep(5); COMMIT;" >"$WORK/legacy-writer-a.log" 2>&1 &
LEGACY_A=$!
# Observe the server inside its post-write sleep; redirected psql output is
# buffered and cannot be used as a transaction-ready handshake.
LEGACY_A_READY=false
for _attempt in {1..100}; do
  if psql -h "$SOCK" -U postgres -d postgres -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='ofe_legacy_resume_writer_a' AND wait_event='PgSleep'" | grep -q 1; then LEGACY_A_READY=true; break; fi
  sleep 0.02
done
if [[ "$LEGACY_A_READY" != true ]]; then wait "$LEGACY_A" || true; cat "$WORK/legacy-writer-a.log"; exit 1; fi
LEGACY_OTHER_DOC="${LEGACY_DOC/writer-a/writer-b}"
PGAPPNAME=ofe_legacy_resume_writer_b psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 SET test.uid = '$LEGACY_UID';
 SELECT public.save_renovation_cas('$LEGACY_UID','race',0,'$LEGACY_OTHER_DOC'::jsonb);" >"$WORK/legacy-writer-b.log" 2>&1 &
LEGACY_B=$!
LEGACY_WAIT_SEEN=false
for _attempt in {1..50}; do
  if psql -h "$SOCK" -U postgres -d postgres -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='ofe_legacy_resume_writer_b' AND wait_event='advisory'" | grep -q 1; then LEGACY_WAIT_SEEN=true; break; fi
  sleep 0.02
done
wait "$LEGACY_A"
wait "$LEGACY_B"
if [[ "$LEGACY_WAIT_SEEN" != true ]]; then echo 'legacy writer B never waited on A advisory lock'; exit 1; fi
if ! grep -q '"status": "conflict"' "$WORK/legacy-writer-b.log"; then cat "$WORK/legacy-writer-b.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN
 IF (SELECT count(*) FROM public.resume_renovation_versions WHERE owner_id='$LEGACY_UID') <> 1
   OR (SELECT doc->>'id' FROM public.resume_renovations WHERE owner_id='$LEGACY_UID' AND opportunity_id='race') <> 'writer-a'
 THEN RAISE EXCEPTION 'legacy concurrent CAS lost update'; END IF; END \$\$;"
echo '    PASS legacy real concurrent CAS: one saved, one conflict, one history row'

# Actual auth deletion waits for an already-authorized save; after commit it
# cascades both current/history and the old JWT is no longer a read capability.
PGAPPNAME=ofe_legacy_account_writer psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 BEGIN; SET LOCAL test.uid = '$LEGACY_UID';
 SELECT public.save_renovation_cas('$LEGACY_UID','race',1,'$LEGACY_OTHER_DOC'::jsonb);
 SELECT pg_sleep(3); COMMIT;" >"$WORK/legacy-account-writer.log" 2>&1 &
LEGACY_ACCOUNT_A=$!
LEGACY_ACCOUNT_READY=false
for _attempt in {1..100}; do
 if psql -h "$SOCK" -U postgres -d postgres -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='ofe_legacy_account_writer' AND wait_event='PgSleep'" | grep -q 1; then LEGACY_ACCOUNT_READY=true; break; fi
 sleep 0.02
done
if [[ "$LEGACY_ACCOUNT_READY" != true ]]; then wait "$LEGACY_ACCOUNT_A" || true; cat "$WORK/legacy-account-writer.log"; exit 1; fi
PGAPPNAME=ofe_legacy_account_delete psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "DELETE FROM auth.users WHERE id='$LEGACY_UID';" >"$WORK/legacy-account-delete.log" 2>&1 &
LEGACY_ACCOUNT_B=$!
LEGACY_DELETE_WAIT=false
for _attempt in {1..50}; do
 if psql -h "$SOCK" -U postgres -d postgres -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='ofe_legacy_account_delete' AND wait_event_type='Lock'" | grep -q 1; then LEGACY_DELETE_WAIT=true; break; fi
 sleep 0.02
done
wait "$LEGACY_ACCOUNT_A"
wait "$LEGACY_ACCOUNT_B"
if [[ "$LEGACY_DELETE_WAIT" != true ]]; then echo 'auth deletion did not wait for accepted save'; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN
 IF EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id='$LEGACY_UID') OR EXISTS(SELECT 1 FROM public.resume_renovation_versions WHERE device_id='$LEGACY_UID') THEN RAISE EXCEPTION 'concurrent account delete left material'; END IF;
 PERFORM set_config('test.uid','$LEGACY_UID',false);
 BEGIN PERFORM public.read_renovation('$LEGACY_UID','race'); RAISE EXCEPTION 'deleted account token read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 END \$\$;"
echo '    PASS legacy real auth deletion contention: wait, cascade, stale token rejected'

# Account deletion locks its auth.users row, then its AFTER DELETE triggers take
# the owner advisory lock. A save that queued on that advisory lock (held here by
# a third session, as any other owner RPC would) must already hold the auth row,
# or it takes the advisory lock and then waits on the deleter: a deadlock.
legacy_wait() {
  for _attempt in {1..200}; do
    if psql -h "$SOCK" -U postgres -d postgres -At -c "SELECT 1 FROM pg_stat_activity WHERE application_name='$1' AND $2" | grep -q 1; then return 0; fi
    sleep 0.02
  done
  return 1
}
LEGACY_UID='88000000-0000-4000-8000-000000000014'
"${PSQL[@]}" -c "INSERT INTO auth.users(id) VALUES ('$LEGACY_UID')"
PGAPPNAME=ofe_legacy_order_holder psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 BEGIN; SELECT pg_advisory_xact_lock(hashtext('ofe-profile:$LEGACY_UID')); SELECT pg_sleep(3); COMMIT;" >"$WORK/legacy-order-holder.log" 2>&1 &
LEGACY_H=$!
if ! legacy_wait ofe_legacy_order_holder "wait_event='PgSleep'"; then wait "$LEGACY_H" || true; cat "$WORK/legacy-order-holder.log"; exit 1; fi
PGAPPNAME=ofe_legacy_order_save psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 SET test.uid = '$LEGACY_UID';
 SELECT public.save_renovation_cas('$LEGACY_UID','lock-order',0,'$LEGACY_DOC'::jsonb);" >"$WORK/legacy-order-save.log" 2>&1 &
LEGACY_A=$!
if ! legacy_wait ofe_legacy_order_save "wait_event='advisory'"; then wait "$LEGACY_A" || true; cat "$WORK/legacy-order-save.log"; exit 1; fi
PGAPPNAME=ofe_legacy_order_delete psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "DELETE FROM auth.users WHERE id='$LEGACY_UID'" >"$WORK/legacy-order-delete.log" 2>&1 &
LEGACY_B=$!
if ! legacy_wait ofe_legacy_order_delete "wait_event_type='Lock'"; then wait "$LEGACY_B" || true; cat "$WORK/legacy-order-delete.log"; exit 1; fi
wait "$LEGACY_H"
if ! wait "$LEGACY_A"; then wait "$LEGACY_B" || true; cat "$WORK/legacy-order-save.log"; exit 1; fi
if ! wait "$LEGACY_B"; then cat "$WORK/legacy-order-delete.log"; exit 1; fi
if ! grep -q '"status": "saved"' "$WORK/legacy-order-save.log"; then cat "$WORK/legacy-order-save.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN
 IF EXISTS(SELECT 1 FROM auth.users WHERE id='$LEGACY_UID') OR EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id='$LEGACY_UID')
   OR EXISTS(SELECT 1 FROM public.resume_renovation_versions WHERE device_id='$LEGACY_UID') THEN RAISE EXCEPTION 'deletion after save did not complete'; END IF; END \$\$;"
echo '    PASS legacy save takes the auth row before the owner advisory lock, so account deletion cannot deadlock it'

# The same race through a merge: the merge queues on the source's advisory lock
# while the anonymous source account is being deleted. It must hold both auth
# rows before either advisory lock, so the deletion waits for the merge instead.
LEGACY_SRC='88000000-0000-4000-8000-000000000015'
LEGACY_DST='88000000-0000-4000-8000-000000000016'
LEGACY_TOKEN="$(psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -qAt -c "
 INSERT INTO auth.users(id,is_anonymous) VALUES ('$LEGACY_SRC',true),('$LEGACY_DST',false);
 SELECT set_config('test.uid','$LEGACY_SRC',false) IS NULL;
 SELECT public.save_renovation_cas('$LEGACY_SRC','merge-order',0,'$LEGACY_DOC'::jsonb) IS NULL;
 SELECT set_config('test.jwt','{\"is_anonymous\":true}',false) IS NULL;
 SELECT public.mint_merge_grant('legacy-merge-order@example.invalid');" | tail -n 1)"
PGAPPNAME=ofe_legacy_merge_holder psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 BEGIN; SELECT pg_advisory_xact_lock(hashtext('ofe-profile:$LEGACY_SRC')); SELECT pg_sleep(3); COMMIT;" >"$WORK/legacy-merge-holder.log" 2>&1 &
LEGACY_H=$!
if ! legacy_wait ofe_legacy_merge_holder "wait_event='PgSleep'"; then wait "$LEGACY_H" || true; cat "$WORK/legacy-merge-holder.log"; exit 1; fi
PGAPPNAME=ofe_legacy_merge_redeem psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "
 SET test.uid = '$LEGACY_DST'; SET test.jwt = '{\"email\":\"legacy-merge-order@example.invalid\"}';
 SELECT public.redeem_merge_grant('$LEGACY_TOKEN'::uuid);" >"$WORK/legacy-merge-redeem.log" 2>&1 &
LEGACY_A=$!
if ! legacy_wait ofe_legacy_merge_redeem "wait_event='advisory'"; then wait "$LEGACY_A" || true; cat "$WORK/legacy-merge-redeem.log"; exit 1; fi
PGAPPNAME=ofe_legacy_merge_delete psql -v ON_ERROR_STOP=1 -h "$SOCK" -U postgres -d postgres -At -c "DELETE FROM auth.users WHERE id='$LEGACY_SRC'" >"$WORK/legacy-merge-delete.log" 2>&1 &
LEGACY_B=$!
if ! legacy_wait ofe_legacy_merge_delete "wait_event_type='Lock'"; then wait "$LEGACY_B" || true; cat "$WORK/legacy-merge-delete.log"; exit 1; fi
wait "$LEGACY_H"
if ! wait "$LEGACY_A"; then wait "$LEGACY_B" || true; cat "$WORK/legacy-merge-redeem.log"; exit 1; fi
if ! wait "$LEGACY_B"; then cat "$WORK/legacy-merge-delete.log"; exit 1; fi
if ! grep -q '"merged": true' "$WORK/legacy-merge-redeem.log"; then cat "$WORK/legacy-merge-redeem.log"; exit 1; fi
"${PSQL[@]}" -c "DO \$\$ BEGIN
 IF EXISTS(SELECT 1 FROM auth.users WHERE id='$LEGACY_SRC')
   OR NOT EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id='$LEGACY_SRC' AND target_device_id='$LEGACY_DST')
   OR (SELECT doc->>'id' FROM public.resume_renovations WHERE owner_id='$LEGACY_DST' AND opportunity_id='merge-order') IS DISTINCT FROM 'writer-a'
 THEN RAISE EXCEPTION 'merge then source deletion lost or kept data'; END IF; END \$\$;"
echo '    PASS legacy merge takes both auth rows before the profile advisory locks, so source deletion cannot deadlock it'
