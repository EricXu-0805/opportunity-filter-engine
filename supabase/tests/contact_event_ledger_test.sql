\set ON_ERROR_STOP on
SET client_min_messages = warning;
INSERT INTO auth.users(id) SELECT ('31000000-0000-4000-8000-' || lpad(n::text,12,'0'))::uuid FROM generate_series(1,8) n;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.interactions TO authenticated;
GRANT SELECT ON public.interaction_status_changes TO authenticated;

-- Run the actual browser-role endpoint, not a postgres-only imitation of RLS.
SET ROLE authenticated;
SELECT set_config('test.uid','31000000-0000-4000-8000-000000000001',false);
DO $$
DECLARE u text := '31000000-0000-4000-8000-000000000001'; id uuid := '31000000-0000-8000-8000-000000000001';
 first jsonb; replay jsonb; before_summary jsonb; n int;
BEGIN
 first := public.confirm_contact_event(u,id,'opp','faculty@example.invalid','Subject','Original body',
   '[{"kind":"profile","version":"1"},{"kind":"contact_context","version":"sha256:abc"}]', '2026-01-01T12:00:00Z');
 IF first->>'replayed' <> 'false' OR first#>>'{event,confirmation_source}' <> 'user_reported'
   OR first#>>'{interaction,interaction_type}' <> 'contacted'
   OR (first#>>'{event,confirmed_at}')::timestamptz <= '2026-01-01T12:00:00Z'
   OR (first#>>'{event,actual_sent_at}')::timestamptz <> '2026-01-01T12:00:00Z'::timestamptz
   OR first#>>'{event,confirmed_at}' <> first#>>'{interaction,last_contacted_at}' THEN
   RAISE EXCEPTION 'new receipt failed %',first;
 END IF;
 UPDATE public.interactions SET interaction_type='replied',notes='keep my notes',remind_at='2026-12-20'
   WHERE device_id=u AND opportunity_id='opp';
 SELECT to_jsonb(i) INTO before_summary FROM public.interactions i WHERE device_id=u AND opportunity_id='opp';
 replay := public.confirm_contact_event(u,id,'opp','faculty@example.invalid','Subject','Original body',
   '[{"kind":"profile","version":"1"},{"kind":"contact_context","version":"sha256:abc"}]', '2026-01-01T12:00:00Z');
 IF replay->>'replayed' <> 'true' OR replay->'event' <> first->'event' OR replay->'interaction' <> before_summary
   OR (SELECT count(*) FROM public.contact_events WHERE device_id=u) <> 1 THEN
   RAISE EXCEPTION 'exact retry changed historical event or live summary';
 END IF;
 -- Every independently editable payload part is part of idempotency equality.
 FOR n IN 1..6 LOOP
   BEGIN
     PERFORM public.confirm_contact_event(u,id,CASE WHEN n=1 THEN 'other' ELSE 'opp' END,
       CASE WHEN n=2 THEN 'other@example.invalid' ELSE 'faculty@example.invalid' END,
       CASE WHEN n=3 THEN 'Changed' ELSE 'Subject' END,CASE WHEN n=4 THEN 'Changed' ELSE 'Original body' END,
       CASE WHEN n=5 THEN '[]'::jsonb ELSE '[{"kind":"profile","version":"1"},{"kind":"contact_context","version":"sha256:abc"}]'::jsonb END,
       CASE WHEN n=6 THEN '2026-02-01'::timestamptz ELSE '2026-01-01T12:00:00Z'::timestamptz END);
     RAISE EXCEPTION 'changed payload % accepted',n;
   EXCEPTION WHEN unique_violation THEN IF SQLERRM <> 'contact_event_conflict' THEN RAISE; END IF; END;
 END LOOP;
 -- Distinct event is saved; advanced status and user metadata stay unchanged.
 replay := public.confirm_contact_event(u,'31000000-0000-8000-8000-000000000002','opp','faculty@example.invalid','Follow-up','New body');
 IF replay#>>'{interaction,interaction_type}' <> 'replied' OR replay#>>'{interaction,notes}' <> 'keep my notes'
   OR replay#>>'{interaction,remind_at}' <> '2026-12-20' OR replay#>'{event,actual_sent_at}' <> 'null'::jsonb
   OR (SELECT count(*) FROM public.interaction_status_changes WHERE device_id=u AND opportunity_id='opp') <> 2 THEN
   RAISE EXCEPTION 'new event damaged summary or invented status change';
 END IF;
 -- Legacy summary confirmation and ordinary changes never invent event rows.
 PERFORM public.confirm_interaction_contact(u,'legacy',NULL);
 IF (SELECT count(*) FROM public.contact_events WHERE device_id=u) <> 2 THEN RAISE EXCEPTION 'legacy backfilled event'; END IF;
 DELETE FROM public.interactions WHERE device_id=u AND opportunity_id='opp';
 replay := public.confirm_contact_event(u,id,'opp','faculty@example.invalid','Subject','Original body',
   '[{"kind":"profile","version":"1"},{"kind":"contact_context","version":"sha256:abc"}]', '2026-01-01T12:00:00Z');
 IF replay->'interaction' <> 'null'::jsonb OR replay->'event' <> first->'event'
   OR EXISTS (SELECT 1 FROM public.interactions WHERE device_id=u AND opportunity_id='opp') THEN
   RAISE EXCEPTION 'retry recreated deleted summary';
 END IF;
 RAISE WARNING 'PASS contact create, exact retry, six payload conflicts, preserved status/notes/reminder, independent timestamps, legacy no-backfill, deleted-summary replay';
END $$;

DO $$
DECLARE u text := '31000000-0000-4000-8000-000000000001'; bad jsonb; email text;
BEGIN
 FOREACH email IN ARRAY ARRAY['a@b','a b@c.d','a@b.c,other@b.c','a@b.c;other@b.c','<a@b.c>','a"@b.c',E'a\\@b.c',E'a@b.c\n',E'a\001@b.c'] LOOP
   BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x',email,'s','b'); RAISE EXCEPTION 'bad address accepted %',email;
   EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 END LOOP;
 FOR bad IN SELECT value FROM jsonb_array_elements('[null,{},[{}],[{"kind":"attachment","version":"1"}],[{"kind":"profile","version":null}],[{"kind":"profile","version":""}],[{"kind":"profile","version":"1","delivered":true}],[{"kind":"profile","version":"1"},{"kind":"profile","version":"1"}]]') LOOP
   BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c','s','b',bad); RAISE EXCEPTION 'bad materials accepted %',bad;
   EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 END LOOP;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c','s','b','[]',clock_timestamp()+interval '1 day'); RAISE EXCEPTION 'future send accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c','s','b','[]','infinity'); RAISE EXCEPTION 'infinite send accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c',E'line\nsubject','b'); RAISE EXCEPTION 'newline subject'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c',E'control\001subject','b'); RAISE EXCEPTION 'control subject'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c','s',NULL); RAISE EXCEPTION 'null body'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c',repeat('s',1001),'b'); RAISE EXCEPTION 'subject over limit'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c','s',repeat('b',100001)); RAISE EXCEPTION 'body over limit'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c','s','b',jsonb_build_array(jsonb_build_object('kind','profile','version',repeat('v',201)))); RAISE EXCEPTION 'version over limit'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'x','a@b.c','s','b',(SELECT jsonb_agg(jsonb_build_object('kind','profile','version',n)) FROM generate_series(1,33) n)); RAISE EXCEPTION 'too many materials'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_contact_event('31000000-0000-4000-8000-000000000002',gen_random_uuid(),'x','a@b.c','s','b'); RAISE EXCEPTION 'wrong owner accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid','',false);
 BEGIN PERFORM public.confirm_contact_event(NULL,gen_random_uuid(),'x','a@b.c','s','b'); RAISE EXCEPTION 'missing owner accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid','31000000-0000-4000-8000-000000000099',false);
 BEGIN PERFORM public.confirm_contact_event('31000000-0000-4000-8000-000000000099',gen_random_uuid(),'x','a@b.c','s','b'); RAISE EXCEPTION 'unknown auth user accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS contact invalid payload, timestamp and identity rejection';
END $$;
SELECT set_config('test.uid','31000000-0000-4000-8000-000000000002',false);
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM public.contact_events) THEN RAISE EXCEPTION 'other owner read leaked'; END IF;
 BEGIN INSERT INTO public.contact_events(device_id,event_id,opportunity_id,recipient,subject,body,confirmed_at) VALUES ('31000000-0000-4000-8000-000000000002',gen_random_uuid(),'x','x@y.z','x','y','2020-01-01'); RAISE EXCEPTION 'direct insert stamped time'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.contact_events SET body='tampered'; RAISE EXCEPTION 'direct update accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN DELETE FROM public.contact_events; RAISE EXCEPTION 'direct delete accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN TRUNCATE public.contact_events; RAISE EXCEPTION 'direct truncate accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
SELECT set_config('test.uid','31000000-0000-4000-8000-000000000001',false);
DO $$ BEGIN IF (SELECT count(*) FROM public.contact_events) <> 2 THEN RAISE EXCEPTION 'owner cannot read'; END IF; END $$;
RESET ROLE;
DO $$
DECLARE role_name text; ns text; sig text;
BEGIN
 FOREACH role_name IN ARRAY ARRAY['public','anon','authenticated','service_role'] LOOP
   IF has_table_privilege(role_name,'public.contact_events','INSERT,UPDATE,DELETE,TRUNCATE') THEN RAISE EXCEPTION 'event DML privilege leaks to %',role_name; END IF;
 END LOOP;
 FOREACH ns IN ARRAY ARRAY['public','private'] LOOP
   sig := ns||'.confirm_contact_event(text,uuid,text,text,text,text,jsonb,timestamptz)';
   IF has_function_privilege('public',sig,'EXECUTE') OR has_function_privilege('anon',sig,'EXECUTE') THEN RAISE EXCEPTION 'unauthed RPC leak'; END IF;
   IF NOT has_function_privilege('authenticated',sig,'EXECUTE') THEN RAISE EXCEPTION 'missing authed EXECUTE'; END IF;
   IF (SELECT prosecdef FROM pg_proc WHERE oid=sig::regprocedure) IS DISTINCT FROM (ns='private')
     OR NOT (SELECT 'search_path=""'=ANY(proconfig) FROM pg_proc WHERE oid=sig::regprocedure) THEN RAISE EXCEPTION 'privilege/search_path contract wrong %',ns; END IF;
 END LOOP;
 BEGIN UPDATE public.contact_events SET confirmed_at='2020-01-01'; RAISE EXCEPTION 'snapshot update allowed even to owner'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS contact real RLS, DML denial, private definer/public invoker and immutable snapshot';
END $$;
SET ROLE anon;
DO $$ BEGIN
 BEGIN PERFORM public.confirm_contact_event(NULL,gen_random_uuid(),'x','a@b.c','s','b'); RAISE EXCEPTION 'anon called RPC'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM 1 FROM public.contact_events; RAISE EXCEPTION 'anon read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;

-- Force a summary write failure after event insertion: both must roll back.
CREATE FUNCTION pg_temp.fail_contact_summary() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.opportunity_id='atomic-fail' THEN RAISE EXCEPTION 'synthetic_summary_failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER contact_test_summary_fail BEFORE INSERT ON public.interactions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_contact_summary();
DO $$
DECLARE u text := '31000000-0000-4000-8000-000000000002';
BEGIN
 PERFORM set_config('test.uid',u,false);
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'atomic-fail','a@b.c','s','b'); RAISE EXCEPTION 'test trigger did not fail'; EXCEPTION WHEN raise_exception THEN IF SQLERRM <> 'synthetic_summary_failure' THEN RAISE; END IF; END;
 IF EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=u) OR EXISTS(SELECT 1 FROM public.interactions WHERE device_id=u) THEN RAISE EXCEPTION 'torn event-summary transaction'; END IF;
 RAISE WARNING 'PASS contact event + summary atomic rollback';
END $$;
DROP TRIGGER contact_test_summary_fail ON public.interactions;

-- Exercise real proof-bound Flow B, not a hand-written ownership UPDATE.
DO $$
DECLARE src text := '31000000-0000-4000-8000-000000000003'; dst text := '31000000-0000-4000-8000-000000000004'; tok uuid; old_event jsonb; r jsonb;
BEGIN
 PERFORM set_config('test.uid',src,false);
 r:=public.confirm_contact_event(src,'31000000-0000-8000-8000-000000000003','merge','a@b.c','s','b'); old_event:=r->'event';
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('contact-merge@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"contact-merge@example.invalid"}',false);
 r:=public.redeem_merge_grant(tok);
 IF r->>'merged' <> 'true' OR EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=src)
   OR (SELECT to_jsonb(e)-'device_id' FROM public.contact_events e WHERE device_id=dst) <> old_event-'device_id' THEN RAISE EXCEPTION 'merge lost snapshot'; END IF;
 r:=public.confirm_contact_event(dst,'31000000-0000-8000-8000-000000000003','merge','a@b.c','s','b');
 IF r->>'replayed' <> 'true' OR r#>>'{event,device_id}' <> dst OR (r->'event')-'device_id' <> old_event-'device_id' THEN RAISE EXCEPTION 'post-merge exact retry not stable'; END IF;
 PERFORM set_config('test.uid',src,false);
 BEGIN PERFORM public.confirm_contact_event(src,gen_random_uuid(),'after','a@b.c','s','b'); RAISE EXCEPTION 'merged source wrote'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 SET LOCAL ROLE authenticated;
 IF EXISTS(SELECT 1 FROM public.contact_events) THEN RAISE EXCEPTION 'retired source reads'; END IF;
 PERFORM set_config('test.uid',dst,false);
 IF (SELECT count(*) FROM public.contact_events) <> 1 THEN RAISE EXCEPTION 'merge target unable to read'; END IF;
 RESET ROLE;
 RAISE WARNING 'PASS contact real Flow B ownership transfer preserves payload/time; stale source denied';
END $$;
-- Event IDs omit the owner so a transferred event stays retryable, so two
-- accounts can hold the same ID. The same snapshot is one contact: keep the
-- earlier confirmation. A different snapshot keeps both under a new source ID.
-- Neither may make the merge fail forever.
DO $$
DECLARE id uuid := '31000000-0000-8000-8000-000000000021'; other_id uuid := '31000000-0000-8000-8000-000000000031';
 mats jsonb := '[{"kind":"profile","version":"same"}]'; pair text[]; src text; dst text; tok uuid; earlier jsonb; later jsonb; moved jsonb; r jsonb;
BEGIN
 INSERT INTO auth.users(id) SELECT ('31000000-0000-4000-8000-' || lpad(n::text,12,'0'))::uuid FROM generate_series(21,25) n;
 FOREACH pair SLICE 1 IN ARRAY ARRAY[['source-first','31000000-0000-4000-8000-000000000021','31000000-0000-4000-8000-000000000022'],
                                     ['target-first','31000000-0000-4000-8000-000000000023','31000000-0000-4000-8000-000000000024']] LOOP
   src := pair[2]; dst := pair[3];
   PERFORM set_config('test.uid',CASE WHEN pair[1]='source-first' THEN src ELSE dst END,false);
   earlier := public.confirm_contact_event(current_setting('test.uid'),id,'dup','a@b.c','Same subject','Same body',mats)->'event';
   PERFORM set_config('test.uid',CASE WHEN pair[1]='source-first' THEN dst ELSE src END,false);
   later := public.confirm_contact_event(current_setting('test.uid'),id,'dup','a@b.c','Same subject','Same body',mats)->'event';
   IF (later->>'confirmed_at')::timestamptz <= (earlier->>'confirmed_at')::timestamptz THEN RAISE EXCEPTION 'fixture timestamps not ordered'; END IF;
   PERFORM set_config('test.uid',src,false);
   moved := public.confirm_contact_event(src,other_id,'dup-other','a@b.c','s','unrelated')->'event';
   PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok := public.mint_merge_grant('contact-dup-' || pair[1] || '@example.invalid');
   PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt',jsonb_build_object('email','contact-dup-' || pair[1] || '@example.invalid')::text,false);
   r := public.redeem_merge_grant(tok);
   IF r->>'merged' <> 'true' OR (SELECT consumed_at FROM public.merge_grants WHERE token=tok) IS NULL
     OR EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=src)
     OR (SELECT count(*) FROM public.contact_events WHERE device_id=dst) <> 2
     OR (SELECT to_jsonb(e)-'device_id' FROM public.contact_events e WHERE device_id=dst AND event_id=id) <> earlier-'device_id'
     OR (SELECT to_jsonb(e)-'device_id' FROM public.contact_events e WHERE device_id=dst AND event_id=other_id) <> moved-'device_id' THEN
     RAISE EXCEPTION 'identical % snapshot did not merge into one earliest confirmation',pair[1];
   END IF;
   r := public.confirm_contact_event(dst,id,'dup','a@b.c','Same subject','Same body',mats);
   IF r->>'replayed' <> 'true' OR (r->'event')-'device_id' <> earlier-'device_id' THEN RAISE EXCEPTION 'merged duplicate not replayable %',pair[1]; END IF;
 END LOOP;
 RAISE WARNING 'PASS identical contact snapshot on both accounts merges into the earlier confirmation; rest of merge commits';
END $$;
DO $$
DECLARE src text := '31000000-0000-4000-8000-000000000005'; dst text := '31000000-0000-4000-8000-000000000006'; id uuid := '31000000-0000-8000-8000-000000000005';
 tok uuid; source_event jsonb; target_event jsonb; rekeyed jsonb;
BEGIN
 PERFORM set_config('test.uid',src,false); source_event := public.confirm_contact_event(src,id,'merge-conflict','a@b.c','s','source')->'event';
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('contact-collision@example.invalid');
 PERFORM set_config('test.uid',dst,false); target_event := public.confirm_contact_event(dst,id,'merge-conflict','a@b.c','s','target')->'event';
 PERFORM set_config('test.jwt','{"email":"contact-collision@example.invalid"}',false);
 PERFORM public.redeem_merge_grant(tok);
 SELECT to_jsonb(e) INTO rekeyed FROM public.contact_events e WHERE device_id=dst AND event_id<>id;
 IF NOT EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src) OR (SELECT consumed_at FROM public.merge_grants WHERE token=tok) IS NULL
   OR EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=src)
   OR (SELECT count(*) FROM public.contact_events WHERE device_id=dst) <> 2
   OR (SELECT to_jsonb(e) FROM public.contact_events e WHERE device_id=dst AND event_id=id) <> target_event
   OR rekeyed-'device_id'-'event_id' <> source_event-'device_id'-'event_id' THEN
   RAISE EXCEPTION 'different same-ID snapshot was not kept under a new ID %',rekeyed;
 END IF;
 RAISE WARNING 'PASS different same-ID contact snapshot is kept under a new ID and the merge commits';
END $$;
-- Only a merge's own duplicate/collision may be removed or re-keyed: identical
-- rows in unrelated accounts, or a merge target whose source is already empty,
-- stay immutable even to the table owner.
DO $$
DECLARE loner text := '31000000-0000-4000-8000-000000000025'; merged_target text := '31000000-0000-4000-8000-000000000022';
BEGIN
 PERFORM set_config('test.uid',loner,false);
 PERFORM public.confirm_contact_event(loner,'31000000-0000-8000-8000-000000000021','dup','a@b.c','Same subject','Same body','[{"kind":"profile","version":"same"}]');
 BEGIN DELETE FROM public.contact_events WHERE device_id=loner; RAISE EXCEPTION 'unrelated duplicate deleted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN DELETE FROM public.contact_events WHERE device_id=merged_target; RAISE EXCEPTION 'merge target history deleted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.contact_events SET event_id=gen_random_uuid() WHERE device_id=loner; RAISE EXCEPTION 'unrelated event re-keyed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.contact_events SET event_id=gen_random_uuid() WHERE device_id=merged_target; RAISE EXCEPTION 'merged event re-keyed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS merge dedupe/re-key exceptions do not open deletion or re-keying outside a merge';
END $$;

-- Account deletion cleans new email PII; a source already merged into another
-- owner no longer owns those snapshots and cannot delete the target's history.
DO $$
DECLARE u text := '31000000-0000-4000-8000-000000000008'; other_count bigint;
BEGIN
 PERFORM set_config('test.uid',u,false);
 PERFORM public.confirm_contact_event(u,gen_random_uuid(),'cleanup-1','a@b.c','s','private body');
 PERFORM public.confirm_contact_event(u,gen_random_uuid(),'cleanup-2','a@b.c','s','other private body');
 SELECT count(*) INTO other_count FROM public.contact_events WHERE device_id<>u;
 DELETE FROM auth.users WHERE id=u::uuid;
 IF EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=u) OR (SELECT count(*) FROM public.contact_events) <> other_count THEN RAISE EXCEPTION 'account deletion did not remove only its event PII'; END IF;
 BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),'after-delete','a@b.c','s','b'); RAISE EXCEPTION 'deleted auth token wrote'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 DELETE FROM auth.users WHERE id='31000000-0000-4000-8000-000000000003';
 IF NOT EXISTS(SELECT 1 FROM public.contact_events WHERE device_id='31000000-0000-4000-8000-000000000004') THEN RAISE EXCEPTION 'deleting merged source removed target history'; END IF;
 RAISE WARNING 'PASS auth deletion removes event PII, preserves other/merged owners, rejects deleted-token writes';
END $$;

-- A deleted target's still-unexpired token must not pull another user's PII
-- into an owner that the auth deletion cleanup has already retired.
DO $$
DECLARE src text := '31000000-0000-4000-8000-000000000002'; dst text := '31000000-0000-4000-8000-000000000098'; tok uuid;
BEGIN
 PERFORM set_config('test.uid',src,false); PERFORM public.confirm_contact_event(src,gen_random_uuid(),'dead-target','a@b.c','s','retained');
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('deleted-target@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"deleted-target@example.invalid"}',false);
 BEGIN PERFORM public.redeem_merge_grant(tok); RAISE EXCEPTION 'unknown/deleted target accepted email transfer'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src)
   OR (SELECT consumed_at FROM public.merge_grants WHERE token=tok) IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=src AND opportunity_id='dead-target')
   OR EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=dst) THEN RAISE EXCEPTION 'missing target transfer partially committed'; END IF;
 RAISE WARNING 'PASS real Flow B rejects missing/deleted target auth owner without moving events or consuming grant';
END $$;

-- A private import target must still be the caller's live import. An exact
-- retry of an already recorded event replays even after the import is deleted.
DO $$
DECLARE u text := '31000000-0000-4000-8000-000000000026'; other text := '31000000-0000-4000-8000-000000000027';
 live text := 'private-import:a2000000-0000-4000-8000-00000000c001'; gone text := 'private-import:a2000000-0000-4000-8000-00000000c002';
 foreign_target text := 'private-import:a2000000-0000-4000-8000-00000000c003'; missing text := 'private-import:a2000000-0000-4000-8000-00000000c004';
 recorded uuid := '31000000-0000-8000-8000-000000000026'; first jsonb; r jsonb; t text;
BEGIN
 INSERT INTO auth.users(id) VALUES (u::uuid),(other::uuid);
 INSERT INTO public.private_import_targets(id,owner_id,revision,opportunity) VALUES
   (live,u::uuid,1,'{"source":"text_parser","title":"Live","description_raw":"d"}'),
   (gone,u::uuid,1,'{"source":"text_parser","title":"Gone","description_raw":"d"}'),
   (foreign_target,other::uuid,1,'{"source":"text_parser","title":"Other","description_raw":"d"}');
 PERFORM set_config('test.uid',u,false);
 PERFORM public.confirm_contact_event(u,gen_random_uuid(),live,'a@b.c','s','live body');
 first := public.confirm_contact_event(u,recorded,gone,'a@b.c','s','recorded body');
 UPDATE public.private_import_targets SET opportunity=NULL,revision=2,deleted_at=clock_timestamp() WHERE id=gone;
 r := public.confirm_contact_event(u,recorded,gone,'a@b.c','s','recorded body');
 IF r->>'replayed' <> 'true' OR r->'event' <> first->'event' THEN RAISE EXCEPTION 'recorded event on deleted import did not replay'; END IF;
 FOREACH t IN ARRAY ARRAY[gone,foreign_target,missing] LOOP
   BEGIN PERFORM public.confirm_contact_event(u,gen_random_uuid(),t,'a@b.c','s','new body'); RAISE EXCEPTION 'unavailable private target accepted %',t;
   EXCEPTION WHEN no_data_found THEN IF SQLERRM <> 'private_target_unavailable' THEN RAISE; END IF; END;
 END LOOP;
 IF (SELECT count(*) FROM public.contact_events WHERE device_id=u) <> 2
   OR EXISTS(SELECT 1 FROM public.interactions WHERE device_id=u AND opportunity_id IN (foreign_target,missing)) THEN
   RAISE EXCEPTION 'refused private target still wrote';
 END IF;
 RAISE WARNING 'PASS contact refuses deleted/other-owner/unknown private import targets after exact replay';
END $$;
