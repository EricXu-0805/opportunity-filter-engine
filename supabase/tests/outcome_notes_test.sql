-- Append-only outcome notes (20261018052512_outcome_notes.sql), on a real
-- migration replay with the platform stubs. No hosted database.
\set ON_ERROR_STOP on
SET client_min_messages = warning;
INSERT INTO auth.users(id) SELECT ('49000000-0000-4000-8000-'||lpad(n::text,12,'0'))::uuid FROM generate_series(1,8) n;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.interactions TO authenticated;
GRANT SELECT ON public.interaction_status_changes TO authenticated;
SET ROLE authenticated;
SELECT set_config('test.uid','49000000-0000-4000-8000-000000000001',false);
DO $$
DECLARE u text:='49000000-0000-4000-8000-000000000001'; id uuid:='49000000-0000-4000-8000-0000000000a1';
 first jsonb; replay jsonb; r jsonb; before_summary jsonb; n int;
BEGIN
 INSERT INTO public.interactions(device_id,opportunity_id,interaction_type,notes,remind_at,last_contacted_at,updated_at)
   VALUES(u,'opp','contacted','Working notes','2026-12-20','2026-01-03','2026-01-04');
 -- A note without an outcome leaves the summary exactly as it was.
 SELECT to_jsonb(i) INTO before_summary FROM public.interactions i WHERE device_id=u AND opportunity_id='opp';
 r:=public.append_outcome_note(u,'49000000-0000-4000-8000-0000000000a0','opp','Waiting to hear back after my email.');
 IF r->>'replayed'<>'false' OR r#>>'{note,body}'<>'Waiting to hear back after my email.' OR r#>'{note,outcome}'<>'null'::jsonb
   OR r->'interaction'<>before_summary
   OR (SELECT to_jsonb(i) FROM public.interactions i WHERE device_id=u AND opportunity_id='opp')<>before_summary THEN
   RAISE EXCEPTION 'plain note changed the summary %',r; END IF;
 -- An outcome sets the status; notes, reminder date and contact date stay.
 first:=public.append_outcome_note(u,id,'opp','Professor Lee replied and wants to meet next week.','replied');
 IF first->>'replayed'<>'false' OR first#>>'{note,outcome}'<>'replied'
   OR first#>>'{interaction,interaction_type}'<>'replied' OR first#>>'{interaction,notes}'<>'Working notes'
   OR first#>>'{interaction,remind_at}'<>'2026-12-20' OR (first#>>'{interaction,last_contacted_at}')::timestamptz<>'2026-01-03'
   OR (first#>>'{note,recorded_at}')::timestamptz<>(first#>>'{interaction,updated_at}')::timestamptz THEN
   RAISE EXCEPTION 'outcome note contract %',first; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.interaction_status_changes WHERE device_id=u AND opportunity_id='opp'
   AND from_status='contacted' AND to_status='replied') THEN RAISE EXCEPTION 'outcome missing from status history'; END IF;
 -- An exact retry returns the saved note and does not re-apply its outcome.
 UPDATE public.interactions SET interaction_type='interviewing' WHERE device_id=u AND opportunity_id='opp';
 SELECT to_jsonb(i) INTO before_summary FROM public.interactions i WHERE device_id=u AND opportunity_id='opp';
 replay:=public.append_outcome_note(u,id,'opp','Professor Lee replied and wants to meet next week.','replied');
 IF replay->>'replayed'<>'true' OR replay->'note'<>first->'note' OR replay->'interaction'<>before_summary THEN
   RAISE EXCEPTION 'exact replay mutated note or summary'; END IF;
 FOR n IN 1..3 LOOP
  BEGIN
   PERFORM public.append_outcome_note(u,id,CASE WHEN n=1 THEN 'other' ELSE 'opp' END,
     CASE WHEN n=2 THEN 'Professor Lee did not reply.' ELSE 'Professor Lee replied and wants to meet next week.' END,
     CASE WHEN n=3 THEN 'rejected' ELSE 'replied' END);
   RAISE EXCEPTION 'different payload % accepted under one note id',n;
  EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'outcome_note_conflict' THEN RAISE; END IF; END;
 END LOOP;
 -- A correction is a new note; the original wording stays.
 r:=public.append_outcome_note(u,gen_random_uuid(),'opp','Correction: it was his lab manager who replied, not him.');
 IF (SELECT count(*) FROM public.outcome_notes WHERE device_id=u AND opportunity_id='opp')<>3
   OR (SELECT body FROM public.outcome_notes WHERE device_id=u AND note_id=id)<>'Professor Lee replied and wants to meet next week.' THEN
   RAISE EXCEPTION 'correction replaced the original note'; END IF;
 -- No summary yet: an outcome creates one, a plain note does not.
 r:=public.append_outcome_note(u,gen_random_uuid(),'untracked','Met her at the poster session.');
 IF r->'interaction'<>'null'::jsonb OR EXISTS(SELECT 1 FROM public.interactions WHERE device_id=u AND opportunity_id='untracked') THEN
   RAISE EXCEPTION 'plain note created a summary'; END IF;
 r:=public.append_outcome_note(u,gen_random_uuid(),'untracked','She said the lab is full this year.','rejected');
 IF r#>>'{interaction,interaction_type}'<>'rejected' THEN RAISE EXCEPTION 'outcome did not create summary'; END IF;
 RAISE WARNING 'PASS outcome note append, status from outcome, preserved summary fields, exact replay, payload conflicts, correction as new note';
END $$;
-- The reminder cron reads interaction_type=in.(contacted,applied) and
-- remind_at<=today (backend/routes/push.py); the same predicate here.
DO $$
DECLARE u text:='49000000-0000-4000-8000-000000000001'; outcome text;
BEGIN
 FOREACH outcome IN ARRAY ARRAY['replied','interviewing','rejected','dismissed'] LOOP
  INSERT INTO public.interactions(device_id,opportunity_id,interaction_type,remind_at)
    VALUES(u,'remind-'||outcome,CASE WHEN outcome='rejected' THEN 'applied' ELSE 'contacted' END,current_date-1);
  IF NOT EXISTS(SELECT 1 FROM public.interactions WHERE device_id=u AND opportunity_id='remind-'||outcome
    AND interaction_type IN ('contacted','applied') AND remind_at<=current_date) THEN RAISE EXCEPTION 'reminder not due before note'; END IF;
  PERFORM public.append_outcome_note(u,gen_random_uuid(),'remind-'||outcome,'Recording the outcome: '||outcome||'.',outcome);
  IF EXISTS(SELECT 1 FROM public.interactions WHERE device_id=u AND opportunity_id='remind-'||outcome
    AND interaction_type IN ('contacted','applied') AND remind_at<=current_date) THEN RAISE EXCEPTION 'reminder still due after %',outcome; END IF;
  IF (SELECT remind_at FROM public.interactions WHERE device_id=u AND opportunity_id='remind-'||outcome)<>current_date-1 THEN
    RAISE EXCEPTION 'reminder date erased by %',outcome; END IF;
 END LOOP;
 RAISE WARNING 'PASS reminders stop on replied, interviewing, rejected and dismissed (no longer contacting); date kept';
END $$;
DO $$
DECLARE u text:='49000000-0000-4000-8000-000000000001'; bad text;
BEGIN
 FOREACH bad IN ARRAY ARRAY['','   ',repeat('a',301),E'Two lines\nof text',E'Tab\there'] LOOP
  BEGIN PERFORM public.append_outcome_note(u,gen_random_uuid(),'opp',bad); RAISE EXCEPTION 'bad body accepted %',bad; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 END LOOP;
 PERFORM public.append_outcome_note(u,gen_random_uuid(),'opp',repeat('a',300));
 BEGIN PERFORM public.append_outcome_note(u,gen_random_uuid(),'opp',NULL); RAISE EXCEPTION 'null body'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.append_outcome_note(u,gen_random_uuid(),'opp','Fine.','applied'); RAISE EXCEPTION 'applied outcome'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.append_outcome_note(u,NULL,'opp','Fine.'); RAISE EXCEPTION 'null id'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.append_outcome_note(u,gen_random_uuid(),'  ','Fine.'); RAISE EXCEPTION 'blank target'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.append_outcome_note('49000000-0000-4000-8000-000000000002',gen_random_uuid(),'opp','Fine.'); RAISE EXCEPTION 'wrong owner'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid','',false);
 BEGIN PERFORM public.append_outcome_note(NULL,gen_random_uuid(),'opp','Fine.'); RAISE EXCEPTION 'null owner'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid','49000000-0000-4000-8000-000000000099',false);
 BEGIN PERFORM public.append_outcome_note('49000000-0000-4000-8000-000000000099',gen_random_uuid(),'opp','Fine.'); RAISE EXCEPTION 'unknown auth owner'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS outcome note empty, blank, overlong, multi-line, outcome and identity guards';
END $$;
SELECT set_config('test.uid','49000000-0000-4000-8000-000000000002',false);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.outcome_notes) THEN RAISE EXCEPTION 'cross-owner read leak'; END IF;
END $$;
SELECT set_config('test.uid','49000000-0000-4000-8000-000000000001',false);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.outcome_notes) THEN RAISE EXCEPTION 'owner cannot read notes'; END IF;
 BEGIN INSERT INTO public.outcome_notes(device_id,note_id,opportunity_id,body,recorded_at) VALUES('49000000-0000-4000-8000-000000000001',gen_random_uuid(),'opp','Spoofed date.','2020-01-01'); RAISE EXCEPTION 'direct insert/time spoof'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.outcome_notes SET body='Rewritten.'; RAISE EXCEPTION 'owner edited a note'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN DELETE FROM public.outcome_notes; RAISE EXCEPTION 'owner deleted a note'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN TRUNCATE public.outcome_notes; RAISE EXCEPTION 'owner truncated notes'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS owner reads own notes; direct insert, edit, delete and truncate denied';
END $$;
RESET ROLE;
DO $$
DECLARE role_name text; ns text; sig text;
BEGIN
 FOREACH role_name IN ARRAY ARRAY['public','anon','authenticated','service_role'] LOOP
  IF has_table_privilege(role_name,'public.outcome_notes','INSERT,UPDATE,DELETE,TRUNCATE') THEN RAISE EXCEPTION 'DML privilege leak %',role_name; END IF;
 END LOOP;
 FOREACH ns IN ARRAY ARRAY['public','private'] LOOP
  sig:=ns||'.append_outcome_note(text,uuid,text,text,text)';
  IF has_function_privilege('public',sig,'EXECUTE') OR has_function_privilege('anon',sig,'EXECUTE')
    OR NOT has_function_privilege('authenticated',sig,'EXECUTE') THEN RAISE EXCEPTION 'RPC ACL mismatch'; END IF;
  IF (SELECT prosecdef FROM pg_proc WHERE oid=sig::regprocedure) IS DISTINCT FROM (ns='private')
    OR NOT (SELECT 'search_path=""'=ANY(proconfig) FROM pg_proc WHERE oid=sig::regprocedure) THEN RAISE EXCEPTION 'definer/search_path mismatch'; END IF;
 END LOOP;
 -- The table owner (what a definer function or the SQL editor runs as) still
 -- cannot rewrite or remove a note while its account exists.
 BEGIN UPDATE public.outcome_notes SET body='Privileged rewrite.'; RAISE EXCEPTION 'privileged edit'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.outcome_notes SET outcome=NULL; RAISE EXCEPTION 'privileged outcome edit'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.outcome_notes SET recorded_at=recorded_at-interval '1 day'; RAISE EXCEPTION 'privileged date edit'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN DELETE FROM public.outcome_notes; RAISE EXCEPTION 'privileged delete'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS outcome note privileges; privileged edit and delete refused';
END $$;
SET ROLE anon;
DO $$ BEGIN
 BEGIN PERFORM public.append_outcome_note(NULL,gen_random_uuid(),'x','Fine.'); RAISE EXCEPTION 'anon RPC'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM 1 FROM public.outcome_notes; RAISE EXCEPTION 'anon read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
CREATE FUNCTION pg_temp.fail_outcome_summary() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.opportunity_id='atomic-fail-note' THEN RAISE EXCEPTION 'synthetic_summary_failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER outcome_test_summary_fail BEFORE INSERT ON public.interactions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_outcome_summary();
DO $$
DECLARE u text:='49000000-0000-4000-8000-000000000002';
BEGIN
 PERFORM set_config('test.uid',u,false);
 BEGIN PERFORM public.append_outcome_note(u,gen_random_uuid(),'atomic-fail-note','They said no.','rejected'); RAISE EXCEPTION 'failure absent'; EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'synthetic_summary_failure' THEN RAISE; END IF; END;
 IF EXISTS(SELECT 1 FROM public.outcome_notes WHERE device_id=u) THEN RAISE EXCEPTION 'torn note/summary transaction'; END IF;
 RAISE WARNING 'PASS outcome note and status roll back together';
END $$;
DROP TRIGGER outcome_test_summary_fail ON public.interactions;
DO $$
DECLARE src text:='49000000-0000-4000-8000-000000000003'; dst text:='49000000-0000-4000-8000-000000000004'; tok uuid; original jsonb; r jsonb;
BEGIN
 PERFORM set_config('test.uid',src,false);
 r:=public.append_outcome_note(src,'49000000-0000-4000-8000-0000000000b3','merge-note','Guest note before signing in.'); original:=r->'note';
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('outcome-merge@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"outcome-merge@example.invalid"}',false);
 r:=public.redeem_merge_grant(tok);
 IF r->>'merged'<>'true' OR EXISTS(SELECT 1 FROM public.outcome_notes WHERE device_id=src)
   OR (SELECT to_jsonb(n)-'device_id' FROM public.outcome_notes n WHERE device_id=dst)<>original-'device_id' THEN RAISE EXCEPTION 'merge lost or changed a note'; END IF;
 r:=public.append_outcome_note(dst,'49000000-0000-4000-8000-0000000000b3','merge-note','Guest note before signing in.');
 IF r->>'replayed'<>'true' THEN RAISE EXCEPTION 'transferred note not replayable'; END IF;
 PERFORM set_config('test.uid',src,false);
 BEGIN PERFORM public.append_outcome_note(src,gen_random_uuid(),'after','Late write.'); RAISE EXCEPTION 'merged source wrote'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS Flow B moves notes unchanged, keeps retry, refuses retired source';
END $$;
DO $$
DECLARE src text:='49000000-0000-4000-8000-000000000005'; dst text:='49000000-0000-4000-8000-000000000006'; id uuid:='49000000-0000-4000-8000-0000000000b5'; tok uuid;
BEGIN
 PERFORM set_config('test.uid',src,false); PERFORM public.append_outcome_note(src,id,'collision','Source wording.');
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('outcome-collision@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM public.append_outcome_note(dst,id,'collision','Target wording.');
 PERFORM set_config('test.jwt','{"email":"outcome-collision@example.invalid"}',false);
 BEGIN PERFORM public.redeem_merge_grant(tok); RAISE EXCEPTION 'collision accepted'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'outcome_note_merge_conflict' THEN RAISE; END IF; END;
 IF EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src)
   OR (SELECT body FROM public.outcome_notes WHERE device_id=src AND note_id=id)<>'Source wording.'
   OR (SELECT body FROM public.outcome_notes WHERE device_id=dst AND note_id=id)<>'Target wording.' THEN RAISE EXCEPTION 'collision partially merged'; END IF;
 RAISE WARNING 'PASS note id collision rolls the merge back with both wordings kept';
END $$;
DO $$
DECLARE u text:='49000000-0000-4000-8000-000000000008'; other_count bigint;
BEGIN
 PERFORM set_config('test.uid',u,false);
 PERFORM public.append_outcome_note(u,gen_random_uuid(),'delete-note','Private outcome wording.','rejected');
 SELECT count(*) INTO other_count FROM public.outcome_notes WHERE device_id<>u;
 DELETE FROM auth.users WHERE id=u::uuid;
 IF EXISTS(SELECT 1 FROM public.outcome_notes WHERE device_id=u) OR (SELECT count(*) FROM public.outcome_notes)<>other_count THEN
   RAISE EXCEPTION 'auth deletion kept notes or deleted another owner''s'; END IF;
 BEGIN PERFORM public.append_outcome_note(u,gen_random_uuid(),'after-delete','Late write.'); RAISE EXCEPTION 'deleted auth token wrote'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS auth deletion removes the account''s notes only and refuses its stale token';
END $$;
DO $$
DECLARE u text:='49000000-0000-4000-8000-000000000007'; live text:='private-import:a4900000-0000-4000-8000-00000000d001';
 gone text:='private-import:a4900000-0000-4000-8000-00000000d002'; recorded uuid:='49000000-0000-4000-8000-0000000000c7'; first jsonb; r jsonb;
BEGIN
 INSERT INTO public.private_import_targets(id,owner_id,revision,opportunity) VALUES
   (live,u::uuid,1,'{"source":"text_parser","title":"Live","description_raw":"d"}'),
   (gone,u::uuid,1,'{"source":"text_parser","title":"Gone","description_raw":"d"}');
 PERFORM set_config('test.uid',u,false);
 PERFORM public.append_outcome_note(u,gen_random_uuid(),live,'Imported lab replied.','replied');
 first:=public.append_outcome_note(u,recorded,gone,'Noted before deleting the import.');
 UPDATE public.private_import_targets SET opportunity=NULL,revision=2,deleted_at=clock_timestamp() WHERE id=gone;
 r:=public.append_outcome_note(u,recorded,gone,'Noted before deleting the import.');
 IF r->>'replayed'<>'true' OR r->'note'<>first->'note' THEN RAISE EXCEPTION 'recorded note on deleted import did not replay'; END IF;
 BEGIN PERFORM public.append_outcome_note(u,gen_random_uuid(),gone,'New note after delete.'); RAISE EXCEPTION 'note on deleted import'; EXCEPTION WHEN no_data_found THEN IF SQLERRM<>'private_target_unavailable' THEN RAISE; END IF; END;
 RAISE WARNING 'PASS private import notes need the live import; exact retry replays';
END $$;
SELECT set_config('test.uid','',false);
SELECT set_config('test.jwt','',false);
