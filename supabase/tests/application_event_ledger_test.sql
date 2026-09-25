\set ON_ERROR_STOP on
SET client_min_messages = warning;
INSERT INTO auth.users(id) SELECT ('32000000-0000-4000-8000-'||lpad(n::text,12,'0'))::uuid FROM generate_series(1,8) n;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.interactions TO authenticated;
GRANT SELECT ON public.interaction_status_changes TO authenticated;
SET ROLE authenticated;
SELECT set_config('test.uid','32000000-0000-4000-8000-000000000001',false);
DO $$
DECLARE u text:='32000000-0000-4000-8000-000000000001'; id uuid:='32000000-0000-4000-8000-000000000001';
 first jsonb; replay jsonb; before_summary jsonb; n int;
BEGIN
 first:=public.confirm_application_event(u,id,'opp','web_form','https://lab.example/apply',
   '2026-01-01T12:00:00Z','Saved application note','Portal reported submitted','Wait for a reply');
 IF first->>'replayed'<>'false' OR first#>>'{event,confirmation_source}'<>'user_reported'
   OR first#>>'{interaction,interaction_type}'<>'applied' OR first#>'{interaction,last_contacted_at}'<>'null'::jsonb
   OR first#>'{interaction,notes}'<>'null'::jsonb OR first#>'{interaction,remind_at}'<>'null'::jsonb
   OR (first#>>'{event,actual_submitted_at}')::timestamptz<>'2026-01-01T12:00:00Z'::timestamptz
   OR (first#>>'{event,confirmed_at}')::timestamptz<='2026-01-01T12:00:00Z'::timestamptz THEN RAISE EXCEPTION 'application create contract %',first; END IF;
 UPDATE public.interactions SET interaction_type='replied',notes='Current notes',remind_at='2026-12-20',last_contacted_at='2026-02-01'
   WHERE device_id=u AND opportunity_id='opp';
 SELECT to_jsonb(i) INTO before_summary FROM public.interactions i WHERE device_id=u AND opportunity_id='opp';
 replay:=public.confirm_application_event(u,id,'opp','web_form','https://lab.example/apply',
   '2026-01-01T12:00:00Z','Saved application note','Portal reported submitted','Wait for a reply');
 IF replay->>'replayed'<>'true' OR replay->'event'<>first->'event' OR replay->'interaction'<>before_summary THEN RAISE EXCEPTION 'exact replay mutated application/summary'; END IF;
 FOR n IN 1..7 LOOP
  BEGIN
   PERFORM public.confirm_application_event(u,id,CASE WHEN n=1 THEN 'other' ELSE 'opp' END,
    CASE WHEN n=2 THEN 'other' ELSE 'web_form' END,CASE WHEN n=3 THEN 'https://other.example/apply' ELSE 'https://lab.example/apply' END,
    CASE WHEN n=4 THEN '2026-02-01'::timestamptz ELSE '2026-01-01T12:00:00Z'::timestamptz END,
    CASE WHEN n=5 THEN 'Different note' ELSE 'Saved application note' END,
    CASE WHEN n=6 THEN 'Different result' ELSE 'Portal reported submitted' END,
    CASE WHEN n=7 THEN 'Different next step' ELSE 'Wait for a reply' END);
   RAISE EXCEPTION 'different payload % accepted',n;
  EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'application_event_conflict' THEN RAISE; END IF; END;
 END LOOP;
 -- Two explicit attempts with identical content are distinct submissions.
 replay:=public.confirm_application_event(u,'32000000-0000-4000-8000-000000000002','opp','web_form','https://lab.example/apply',
   '2026-01-01T12:00:00Z','Saved application note','Portal reported submitted','Wait for a reply');
 IF replay->>'replayed'<>'false' OR (SELECT count(*) FROM public.application_events WHERE device_id=u)<>2
   OR replay#>>'{interaction,interaction_type}'<>'replied' OR replay#>>'{interaction,notes}'<>'Current notes'
   OR replay#>>'{interaction,remind_at}'<>'2026-12-20' OR (replay#>>'{interaction,last_contacted_at}')::timestamptz<>'2026-02-01' THEN RAISE EXCEPTION 'distinct attempt lost or damaged summary'; END IF;
 DELETE FROM public.interactions WHERE device_id=u AND opportunity_id='opp';
 replay:=public.confirm_application_event(u,id,'opp','web_form','https://lab.example/apply',
   '2026-01-01T12:00:00Z','Saved application note','Portal reported submitted','Wait for a reply');
 IF replay->'interaction'<>'null'::jsonb OR replay->'event'<>first->'event'
   OR EXISTS(SELECT 1 FROM public.interactions WHERE device_id=u AND opportunity_id='opp') THEN RAISE EXCEPTION 'replay resurrected removed summary'; END IF;
 RAISE WARNING 'PASS application create, exact replay, seven payload conflicts, separate identical attempts, independent times and no summary resurrection';
END $$;
DO $$
DECLARE u text:='32000000-0000-4000-8000-000000000001'; state text; r jsonb; count_before int;
BEGIN
 FOREACH state IN ARRAY ARRAY['contacted','applied','replied','interviewing','rejected','dismissed'] LOOP
  INSERT INTO public.interactions(device_id,opportunity_id,interaction_type,notes,remind_at,last_contacted_at,updated_at)
    VALUES(u,'state-'||state,state,'Keep notes','2026-12-21','2026-01-03','2027-01-01');
  SELECT count(*) INTO count_before FROM public.interaction_status_changes WHERE device_id=u AND opportunity_id='state-'||state;
  r:=public.confirm_application_event(u,gen_random_uuid(),'state-'||state,'other','Paper submission');
  IF r#>>'{interaction,interaction_type}'<>(CASE WHEN state='contacted' THEN 'applied' ELSE state END)
    OR r#>>'{interaction,notes}'<>'Keep notes' OR r#>>'{interaction,remind_at}'<>'2026-12-21'
    OR (r#>>'{interaction,last_contacted_at}')::timestamptz<>'2026-01-03'
    OR (r#>>'{interaction,updated_at}')::timestamptz<>'2027-01-01'
    OR r#>'{event,actual_submitted_at}'<>'null'::jsonb THEN RAISE EXCEPTION 'state preservation failed %',state; END IF;
  IF (SELECT count(*) FROM public.interaction_status_changes WHERE device_id=u AND opportunity_id='state-'||state)
    <>count_before+(CASE WHEN state='contacted' THEN 1 ELSE 0 END) THEN RAISE EXCEPTION 'fabricated status history %',state; END IF;
 END LOOP;
 SELECT count(*) INTO count_before FROM public.application_events WHERE device_id=u;
 INSERT INTO public.interactions(device_id,opportunity_id,interaction_type) VALUES(u,'manual-status','applied');
 PERFORM public.confirm_interaction_contact(u,'legacy-contact',NULL);
 PERFORM public.confirm_contact_event(u,gen_random_uuid(),'email-contact','a@b.c','Subject','Email body');
 IF (SELECT count(*) FROM public.application_events WHERE device_id=u)<>count_before THEN RAISE EXCEPTION 'status/contact backfilled formal applications'; END IF;
 RAISE WARNING 'PASS application status matrix, contact date and metadata preserved, monotone update time, no status/contact backfill';
END $$;
DO $$
DECLARE u text:='32000000-0000-4000-8000-000000000001'; bad text;
BEGIN
 FOREACH bad IN ARRAY ARRAY['ftp://lab.example/apply','javascript:alert(1)','https:///apply','https://user:password@lab.example','https://@lab.example',E'https://lab.example\\wrong','https://lab.example:70000','https://lab.example/a b','https://a..b','https://-a.b','https://a-.b',
   'https://'||repeat('a',64)||'.example','https://'||repeat('a.',126)||'ab',
   'https://256.1.1.1','https://123','https://127.1','https://01.2.3.4','https://[not-ipv6]',
   'https://[1:2:3]','https://[::1]:65536','https://[::1]:000000'] LOOP
  BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','web_form',bad); RAISE EXCEPTION 'bad web address accepted %',bad; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 END LOOP;
 FOREACH bad IN ARRAY ARRAY['a@b','a@b.c;second@b.c','<a@b.c>',E'a\001@b.c',E'a@b.c\n'] LOOP
  BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','email',bad); RAISE EXCEPTION 'bad email accepted %',bad; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 END LOOP;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','unknown','address'); RAISE EXCEPTION 'bad channel'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','other',NULL); RAISE EXCEPTION 'null address'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','other',repeat('d',2001)); RAISE EXCEPTION 'overlong address'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','email',repeat('a',315)||'@b.com'); RAISE EXCEPTION 'overlong email'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','other','Office','infinity'); RAISE EXCEPTION 'infinite time'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','other','Office',clock_timestamp()+interval '1 day'); RAISE EXCEPTION 'future time'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','other','Office',NULL,'  '); RAISE EXCEPTION 'blank note'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','other','Office',NULL,repeat('n',4001)); RAISE EXCEPTION 'long note'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','other','Office',NULL,NULL,repeat('n',4001)); RAISE EXCEPTION 'long result'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'x','other','Office',NULL,NULL,NULL,repeat('n',4001)); RAISE EXCEPTION 'long next step'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.confirm_application_event('32000000-0000-4000-8000-000000000002',gen_random_uuid(),'x','other','Office'); RAISE EXCEPTION 'wrong owner'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid','',false);
 BEGIN PERFORM public.confirm_application_event(NULL,gen_random_uuid(),'x','other','Office'); RAISE EXCEPTION 'null owner'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid','32000000-0000-4000-8000-000000000099',false);
 BEGIN PERFORM public.confirm_application_event('32000000-0000-4000-8000-000000000099',gen_random_uuid(),'x','other','Office'); RAISE EXCEPTION 'unknown auth owner'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS application invalid channel/address/time/text and stale identity guards';
END $$;
SELECT set_config('test.uid','32000000-0000-4000-8000-000000000002',false);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.application_events) THEN RAISE EXCEPTION 'cross-owner read leak'; END IF;
 BEGIN INSERT INTO public.application_events(device_id,event_id,opportunity_id,channel,destination,confirmed_at) VALUES('32000000-0000-4000-8000-000000000002',gen_random_uuid(),'x','other','Office','2020-01-01'); RAISE EXCEPTION 'direct insert/time spoof'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.application_events SET notes='changed'; RAISE EXCEPTION 'direct update'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN DELETE FROM public.application_events; RAISE EXCEPTION 'direct delete'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN TRUNCATE public.application_events; RAISE EXCEPTION 'direct truncate'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
SELECT set_config('test.uid','32000000-0000-4000-8000-000000000001',false);
DO $$ BEGIN IF (SELECT count(*) FROM public.application_events)<>8 THEN RAISE EXCEPTION 'owner cannot read applications'; END IF; END $$;
RESET ROLE;
DO $$
DECLARE role_name text; ns text; sig text;
BEGIN
 FOREACH role_name IN ARRAY ARRAY['public','anon','authenticated','service_role'] LOOP
  IF has_table_privilege(role_name,'public.application_events','INSERT,UPDATE,DELETE,TRUNCATE') THEN RAISE EXCEPTION 'DML privilege leak %',role_name; END IF;
 END LOOP;
 FOREACH ns IN ARRAY ARRAY['public','private'] LOOP
  sig:=ns||'.confirm_application_event(text,uuid,text,text,text,timestamptz,text,text,text)';
  IF has_function_privilege('public',sig,'EXECUTE') OR has_function_privilege('anon',sig,'EXECUTE')
    OR NOT has_function_privilege('authenticated',sig,'EXECUTE') THEN RAISE EXCEPTION 'RPC ACL mismatch'; END IF;
  IF (SELECT prosecdef FROM pg_proc WHERE oid=sig::regprocedure) IS DISTINCT FROM (ns='private')
    OR NOT (SELECT 'search_path=""'=ANY(proconfig) FROM pg_proc WHERE oid=sig::regprocedure) THEN RAISE EXCEPTION 'definer/search_path mismatch'; END IF;
 END LOOP;
 BEGIN UPDATE public.application_events SET notes='privileged mutation'; RAISE EXCEPTION 'snapshot mutable'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS application real owner RLS, direct DML denial, immutable rows and RPC privileges';
END $$;
DO $$
DECLARE good text;
BEGIN
 FOREACH good IN ARRAY ARRAY['https://lab.example/apply','HTTPS://LOCALHOST:0/path?x=1#anchor',
   'http://127.0.0.1:65535','https://[::1]:443/apply','https://[2001:db8::1]/apply',
   'https://[::ffff:192.0.2.1]/apply','https://'||repeat('a',63)||'.example',
   'https://'||repeat('a.',126)||'a'] LOOP
   IF NOT private.application_web_destination_valid(good) THEN RAISE EXCEPTION 'valid web address rejected %',good; END IF;
 END LOOP;
 RAISE WARNING 'PASS application URL hostname, IPv4, IPv6, port and exact grammar boundaries';
END $$;
SET ROLE anon;
DO $$ BEGIN
 BEGIN PERFORM public.confirm_application_event(NULL,gen_random_uuid(),'x','other','Office'); RAISE EXCEPTION 'anon RPC'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM 1 FROM public.application_events; RAISE EXCEPTION 'anon read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
CREATE FUNCTION pg_temp.fail_application_summary() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.opportunity_id='atomic-fail-app' THEN RAISE EXCEPTION 'synthetic_summary_failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER application_test_summary_fail BEFORE INSERT ON public.interactions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_application_summary();
DO $$
DECLARE u text:='32000000-0000-4000-8000-000000000002';
BEGIN
 PERFORM set_config('test.uid',u,false);
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'atomic-fail-app','other','Office'); RAISE EXCEPTION 'failure absent'; EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'synthetic_summary_failure' THEN RAISE; END IF; END;
 IF EXISTS(SELECT 1 FROM public.application_events WHERE device_id=u) OR EXISTS(SELECT 1 FROM public.interactions WHERE device_id=u) THEN RAISE EXCEPTION 'torn event/summary transaction'; END IF;
 RAISE WARNING 'PASS application event and summary roll back together';
END $$;
DROP TRIGGER application_test_summary_fail ON public.interactions;
DO $$
DECLARE src text:='32000000-0000-4000-8000-000000000003'; dst text:='32000000-0000-4000-8000-000000000004'; tok uuid; original jsonb; r jsonb;
BEGIN
 PERFORM set_config('test.uid',src,false);
 r:=public.confirm_application_event(src,'32000000-0000-4000-8000-000000000003','merge-app','other','Office'); original:=r->'event';
 PERFORM public.confirm_contact_event(src,'32000000-0000-4000-8000-000000000033','merge-app','a@b.c','s','b');
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('application-merge@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"application-merge@example.invalid"}',false);
 r:=public.redeem_merge_grant(tok);
 IF r->>'merged'<>'true' OR EXISTS(SELECT 1 FROM public.application_events WHERE device_id=src)
   OR (SELECT to_jsonb(e)-'device_id' FROM public.application_events e WHERE device_id=dst)<>original-'device_id'
   OR NOT EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=dst) THEN RAISE EXCEPTION 'mixed ledger merge lost data'; END IF;
 r:=public.confirm_application_event(dst,'32000000-0000-4000-8000-000000000003','merge-app','other','Office');
 IF r->>'replayed'<>'true' OR (r->'event')-'device_id'<>original-'device_id' THEN RAISE EXCEPTION 'transferred attempt not replayable'; END IF;
 PERFORM set_config('test.uid',src,false);
 BEGIN PERFORM public.confirm_application_event(src,gen_random_uuid(),'after','other','Office'); RAISE EXCEPTION 'merged source wrote'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 SET LOCAL ROLE authenticated;
 IF EXISTS(SELECT 1 FROM public.application_events) THEN RAISE EXCEPTION 'retired source read'; END IF;
 PERFORM set_config('test.uid',dst,false);
 IF (SELECT count(*) FROM public.application_events)<>1 THEN RAISE EXCEPTION 'target owner cannot read'; END IF;
 RESET ROLE;
 RAISE WARNING 'PASS application real Flow B transfer preserves mixed ledger payload/times, stable retry, stale source denial';
END $$;
DO $$
DECLARE src text:='32000000-0000-4000-8000-000000000005'; dst text:='32000000-0000-4000-8000-000000000006'; id uuid:='32000000-0000-4000-8000-000000000005'; tok uuid;
BEGIN
 PERFORM set_config('test.uid',src,false); PERFORM public.confirm_application_event(src,id,'collision','other','Office one');
 PERFORM public.confirm_contact_event(src,gen_random_uuid(),'collision','a@b.c','s','source mail');
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('application-collision@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM public.confirm_application_event(dst,id,'collision','other','Office two');
 PERFORM set_config('test.jwt','{"email":"application-collision@example.invalid"}',false);
 BEGIN PERFORM public.redeem_merge_grant(tok); RAISE EXCEPTION 'collision accepted'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'application_event_merge_conflict' THEN RAISE; END IF; END;
 IF EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src) OR (SELECT consumed_at FROM public.merge_grants WHERE token=tok) IS NOT NULL
   OR (SELECT count(*) FROM public.application_events WHERE device_id IN(src,dst))<>2
   OR NOT EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=src)
   OR (SELECT count(*) FROM public.interactions WHERE device_id IN(src,dst))<>2 THEN RAISE EXCEPTION 'application collision partially committed mixed merge'; END IF;
 RAISE WARNING 'PASS application collision rolls back all summaries, both ledgers and merge grant';
END $$;
DO $$
DECLARE u text:='32000000-0000-4000-8000-000000000008'; other_count bigint;
BEGIN
 PERFORM set_config('test.uid',u,false);
 PERFORM public.confirm_application_event(u,gen_random_uuid(),'delete-app','other','Office',NULL,'Private application details');
 PERFORM public.confirm_contact_event(u,gen_random_uuid(),'delete-app','a@b.c','s','Private contact');
 SELECT count(*) INTO other_count FROM public.application_events WHERE device_id<>u;
 DELETE FROM auth.users WHERE id=u::uuid;
 IF EXISTS(SELECT 1 FROM public.application_events WHERE device_id=u) OR EXISTS(SELECT 1 FROM public.contact_events WHERE device_id=u)
   OR (SELECT count(*) FROM public.application_events)<>other_count THEN RAISE EXCEPTION 'auth deletion retained data or deleted another owner'; END IF;
 BEGIN PERFORM public.confirm_application_event(u,gen_random_uuid(),'after-delete','other','Office'); RAISE EXCEPTION 'deleted auth token wrote'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 DELETE FROM auth.users WHERE id='32000000-0000-4000-8000-000000000003';
 IF NOT EXISTS(SELECT 1 FROM public.application_events WHERE device_id='32000000-0000-4000-8000-000000000004') THEN RAISE EXCEPTION 'deleting source removed target records'; END IF;
 RAISE WARNING 'PASS auth deletion cleans both ledgers, preserves other/merged owners, rejects stale token';
END $$;
DO $$
DECLARE src text:='32000000-0000-4000-8000-000000000002'; dst text:='32000000-0000-4000-8000-000000000099'; tok uuid;
BEGIN
 PERFORM set_config('test.uid',src,false); PERFORM public.confirm_application_event(src,gen_random_uuid(),'dead-target','other','Office');
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('application-dead-target@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"application-dead-target@example.invalid"}',false);
 BEGIN PERFORM public.redeem_merge_grant(tok); RAISE EXCEPTION 'dead target transfer accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src) OR (SELECT consumed_at FROM public.merge_grants WHERE token=tok) IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM public.application_events WHERE device_id=src) THEN RAISE EXCEPTION 'dead target transfer lost source'; END IF;
 RAISE WARNING 'PASS application merge into deleted/unknown auth owner is rejected atomically';
END $$;
