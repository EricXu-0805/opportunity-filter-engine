-- Runs on the existing local Supabase instance inside a caller-owned rollback.
-- Uses actual auth.uid/auth.jwt and auth.sessions; never loads platform stubs.
\set ON_ERROR_STOP on
SET client_min_messages=warning;
INSERT INTO auth.users(id) SELECT ('36000000-0000-4000-8000-'||lpad(n::text,12,'0'))::uuid FROM generate_series(1,20)n;
INSERT INTO auth.sessions(id,user_id) SELECT id,id FROM auth.users WHERE id::text LIKE '36000000-%';
-- Auth fixtures carry real session IDs/exp rather than treating a still-signed
-- access token as proof the session survived sign-out.
CREATE FUNCTION pg_temp.login(n int) RETURNS text LANGUAGE plpgsql AS $$
DECLARE u text:='36000000-0000-4000-8000-'||lpad(n::text,12,'0');
BEGIN PERFORM set_config('request.jwt.claim.sub',u,false); PERFORM set_config('request.jwt.claims',jsonb_build_object('session_id',u,'exp',floor(extract(epoch FROM clock_timestamp()+interval '1 hour')))::text,false); RETURN u; END $$;
CREATE FUNCTION pg_temp.event(n int) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE u text:=pg_temp.login(n);
BEGIN PERFORM public.confirm_contact_event(u,u::uuid,'opp','faculty@example.invalid','Original subject','Original body','[{"kind":"profile","version":"1"}]','2026-01-01'); RETURN u::uuid; END $$;
DO $$BEGIN FOR n IN 1..20 LOOP PERFORM pg_temp.event(n); END LOOP; END$$;
CREATE TEMP TABLE original_contact_snapshot AS SELECT to_jsonb(e) AS v FROM public.contact_events e WHERE device_id='36000000-0000-4000-8000-000000000001';
CREATE TABLE public.contact_material_test_receipts(k text PRIMARY KEY,v jsonb);
GRANT ALL ON public.contact_material_test_receipts TO authenticated,service_role;
SET ROLE authenticated;
SELECT pg_temp.login(1);
INSERT INTO public.contact_material_test_receipts VALUES('first',public.stage_contact_material(auth.uid()::text,'36000000-0000-4000-9000-000000000001','36000000-0000-4000-a000-000000000001',auth.uid(),'opp','Résumé.pdf',123,repeat('a',64)));
DO $$DECLARE r jsonb; BEGIN
 SELECT v INTO r FROM public.contact_material_test_receipts WHERE k='first';
 IF r#>>'{artifact,status}'<>'staged' OR r#>'{artifact,sha256}'<>'null'::jsonb OR r#>'{artifact,recorded_at}'<>'null'::jsonb OR r->>'replayed'<>'false' THEN RAISE EXCEPTION 'stage fabricated verified record'; END IF;
 IF public.list_contact_materials(auth.uid()::text,auth.uid(),'opp')->'items'<>'[]'::jsonb THEN RAISE EXCEPTION 'staged listed as recorded'; END IF;
 BEGIN PERFORM public.authorize_contact_material_download(auth.uid()::text,'36000000-0000-4000-a000-000000000001',auth.uid(),'opp'); RAISE EXCEPTION 'staged download'; EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 BEGIN PERFORM public.finalize_contact_material(auth.uid(),auth.uid(),'36000000-0000-4000-9000-000000000001',(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64)); RAISE EXCEPTION 'browser forged verified hash'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 INSERT INTO public.contact_material_test_receipts VALUES('rotated',public.stage_contact_material(auth.uid()::text,'36000000-0000-4000-9000-000000000001','36000000-0000-4000-a000-000000000001',auth.uid(),'opp','Résumé.pdf',123,repeat('a',64)));
 IF (SELECT v#>>'{upload,stage_token}' FROM public.contact_material_test_receipts WHERE k='rotated')=r#>>'{upload,stage_token}' THEN RAISE EXCEPTION 'stage retry did not fence old request'; END IF;
 FOR n IN 1..4 LOOP BEGIN
  PERFORM public.stage_contact_material(auth.uid()::text,'36000000-0000-4000-9000-000000000001',CASE WHEN n=1 THEN gen_random_uuid() ELSE '36000000-0000-4000-a000-000000000001'::uuid END,auth.uid(),'opp',CASE WHEN n=2 THEN 'other.pdf' ELSE 'Résumé.pdf' END,CASE WHEN n=3 THEN 456 ELSE 123 END,repeat(CASE WHEN n=4 THEN 'b' ELSE 'a' END,64));
  RAISE EXCEPTION 'changed stage accepted'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'contact_material_conflict' THEN RAISE; END IF; END; END LOOP;
 RAISE WARNING 'PASS stage is durable but unverified, old token fenced, exact request frozen, browser cannot finalize';
END$$;
RESET ROLE;
SET ROLE service_role;
DO $$DECLARE r jsonb; BEGIN
 SELECT v INTO r FROM public.contact_material_test_receipts WHERE k='first';
 BEGIN PERFORM public.finalize_contact_material('36000000-0000-4000-8000-000000000001','36000000-0000-4000-8000-000000000001','36000000-0000-4000-9000-000000000001',(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64)); RAISE EXCEPTION 'old token finalized'; EXCEPTION WHEN object_in_use THEN NULL; END;
 SELECT v INTO r FROM public.contact_material_test_receipts WHERE k='rotated';
 BEGIN PERFORM public.finalize_contact_material('36000000-0000-4000-8000-000000000001','36000000-0000-4000-8000-000000000001','36000000-0000-4000-9000-000000000001',(r#>>'{upload,stage_token}')::uuid,123,repeat('b',64)); RAISE EXCEPTION 'false hash finalized'; EXCEPTION WHEN unique_violation THEN NULL; END;
 INSERT INTO public.contact_material_test_receipts VALUES('final',public.finalize_contact_material('36000000-0000-4000-8000-000000000001','36000000-0000-4000-8000-000000000001','36000000-0000-4000-9000-000000000001',(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64)));
 r:=public.finalize_contact_material('36000000-0000-4000-8000-000000000001','36000000-0000-4000-8000-000000000001','36000000-0000-4000-9000-000000000001',(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64));
 IF r->>'replayed'<>'true' OR r->'artifact'<>(SELECT v->'artifact' FROM public.contact_material_test_receipts WHERE k='final') THEN RAISE EXCEPTION 'final replay changed receipt'; END IF;
 SELECT v INTO r FROM public.contact_material_test_receipts WHERE k='first';
 r:=public.finalize_contact_material('36000000-0000-4000-8000-000000000001','36000000-0000-4000-8000-000000000001','36000000-0000-4000-9000-000000000001',(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64));
 IF r->>'replayed'<>'true' OR r->'artifact'<>(SELECT v->'artifact' FROM public.contact_material_test_receipts WHERE k='final') THEN RAISE EXCEPTION 'superseded stage not replayed as ready'; END IF;
END$$;
RESET ROLE;
SET ROLE authenticated;
DO $$DECLARE r jsonb; BEGIN
 r:=public.stage_contact_material(auth.uid()::text,'36000000-0000-4000-9000-000000000001','36000000-0000-4000-a000-000000000001',auth.uid(),'opp','Résumé.pdf',123,repeat('a',64));
 IF r#>>'{artifact,status}'<>'ready' OR r->'upload'<>'null'::jsonb THEN RAISE EXCEPTION 'ready retry requires reupload'; END IF;
 IF public.list_contact_materials(auth.uid()::text,auth.uid(),'opp')#>>'{items,0,sha256}'<>repeat('a',64) THEN RAISE EXCEPTION 'ready not in list'; END IF;
 r:=public.authorize_contact_material_download(auth.uid()::text,'36000000-0000-4000-a000-000000000001',auth.uid(),'opp');
 IF r->>'object_key'<>'pdf/36000000-0000-4000-9000-000000000001.pdf' THEN RAISE EXCEPTION 'object key not stable owner-free'; END IF;
 r:=public.delete_contact_material(auth.uid()::text,'36000000-0000-4000-a000-000000000001','36000000-0000-4000-9000-000000000001',auth.uid(),'opp');
 IF r#>>'{artifact,status}'<>'deleted' OR r#>'{artifact,filename}'<>'null'::jsonb OR r#>'{artifact,sha256}'<>'null'::jsonb OR r#>'{artifact,byte_length}'<>'null'::jsonb THEN RAISE EXCEPTION 'delete did not redact'; END IF;
 IF public.delete_contact_material(auth.uid()::text,'36000000-0000-4000-a000-000000000001','36000000-0000-4000-9000-000000000001',auth.uid(),'opp')->>'replayed'<>'true' THEN RAISE EXCEPTION 'delete not idempotent'; END IF;
 IF public.list_contact_materials(auth.uid()::text,auth.uid(),'opp')#>>'{items,0,status}'<>'deleted' THEN RAISE EXCEPTION 'deleted historical declaration vanished'; END IF;
 IF public.stage_contact_material(auth.uid()::text,'36000000-0000-4000-9000-000000000001','36000000-0000-4000-a000-000000000001',auth.uid(),'opp','Résumé.pdf',123,repeat('a',64))#>>'{artifact,status}'<>'deleted' THEN RAISE EXCEPTION 'revoked key resurrected'; END IF;
 BEGIN PERFORM public.authorize_contact_material_download(auth.uid()::text,'36000000-0000-4000-a000-000000000001',auth.uid(),'opp'); RAISE EXCEPTION 'deleted download'; EXCEPTION WHEN object_not_in_prerequisite_state THEN NULL; END;
 RAISE WARNING 'PASS verified finalize/replay, immutable key, redaction, revoked download and retained minimal association';
END$$;
RESET ROLE;
DO $$BEGIN
 IF NOT EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='36000000-0000-4000-9000-000000000001') THEN RAISE EXCEPTION 'delete missing cleanup intent'; END IF;
 IF (SELECT count(*) FROM public.contact_events WHERE device_id='36000000-0000-4000-8000-000000000001')<>1 OR (SELECT count(*) FROM public.interaction_status_changes WHERE device_id='36000000-0000-4000-8000-000000000001')<>1 THEN RAISE EXCEPTION 'material changed original event/status'; END IF;
END$$;
CREATE FUNCTION pg_temp.stage(n int,m int) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE u text:=pg_temp.login(n);
BEGIN RETURN public.stage_contact_material(u,('36000000-0000-4000-9000-'||lpad(m::text,12,'0'))::uuid,('36000000-0000-4000-a000-'||lpad(m::text,12,'0'))::uuid,u::uuid,'opp','submitted.pdf',123,repeat('a',64)); END$$;
CREATE FUNCTION pg_temp.archive(n int,m int) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE r jsonb:=pg_temp.stage(n,m);u uuid:=auth.uid();
BEGIN RETURN public.finalize_contact_material(u,u,(r#>>'{artifact,material_id}')::uuid,(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64)); END$$;
DO $$DECLARE bad text;r jsonb;u text:=pg_temp.login(2);BEGIN
 FOREACH bad IN ARRAY ARRAY['notpdf','x.pdf/other.pdf',E'x\\evil.pdf',E'x\001.pdf','x'||chr(127)||'.pdf',repeat('a',197)||'.pdf'] LOOP
  BEGIN PERFORM public.stage_contact_material(u,gen_random_uuid(),gen_random_uuid(),u::uuid,'opp',bad,123,repeat('a',64)); RAISE EXCEPTION 'invalid filename accepted %',bad; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 END LOOP;
 FOREACH bad IN ARRAY ARRAY['A'||repeat('a',63),repeat('g',64),repeat('a',63)] LOOP
  BEGIN PERFORM public.stage_contact_material(u,gen_random_uuid(),gen_random_uuid(),u::uuid,'opp','x.pdf',123,bad); RAISE EXCEPTION 'invalid hash accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 END LOOP;
 BEGIN PERFORM public.stage_contact_material(u,gen_random_uuid(),gen_random_uuid(),u::uuid,'opp','x.pdf',0,repeat('a',64)); RAISE EXCEPTION 'zero bytes'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.stage_contact_material(u,gen_random_uuid(),gen_random_uuid(),u::uuid,'opp','x.pdf',67108865,repeat('a',64)); RAISE EXCEPTION 'over 64MiB'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 r:=public.stage_contact_material(u,gen_random_uuid(),gen_random_uuid(),u::uuid,'opp',repeat('研',195)||'😀.PDF',67108864,repeat('a',64));
 IF r#>>'{artifact,byte_length}'<>'67108864' THEN RAISE EXCEPTION 'exact limits rejected'; END IF;
 BEGIN PERFORM public.stage_contact_material(u,gen_random_uuid(),gen_random_uuid(),u::uuid,'other','x.pdf',123,repeat('a',64)); RAISE EXCEPTION 'target mismatch'; EXCEPTION WHEN no_data_found THEN NULL; END;
 BEGIN PERFORM public.stage_contact_material(u,gen_random_uuid(),gen_random_uuid(),'36000000-0000-4000-8000-000000000001','opp','x.pdf',123,repeat('a',64)); RAISE EXCEPTION 'foreign event'; EXCEPTION WHEN no_data_found THEN NULL; END;
 IF public.get_contact_material(u,'36000000-0000-4000-a000-000000000001',u::uuid,'opp')->'artifact'<>'null'::jsonb THEN RAISE EXCEPTION 'cross-owner metadata exposed'; END IF;
 r:=pg_temp.archive(2,2);
 BEGIN UPDATE public.material_artifacts SET filename='replacement.pdf' WHERE material_id='36000000-0000-4000-9000-000000000002'; RAISE EXCEPTION 'privileged content mutated'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.contact_material_records SET recorded_at=now() WHERE material_id='36000000-0000-4000-9000-000000000002'; RAISE EXCEPTION 'record timestamp mutable'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS input boundaries, 64MiB/200 codepoints, scoped event lookup, immutable content and declaration times';
END$$;
DO $$DECLARE u text:=pg_temp.login(3);claims text:=current_setting('request.jwt.claims');BEGIN
 PERFORM set_config('request.jwt.claims','{}',false);
 BEGIN PERFORM public.list_contact_materials(u,u::uuid,'opp'); RAISE EXCEPTION 'missing session read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('request.jwt.claims',jsonb_build_object('session_id',u,'exp',1)::text,false);
 BEGIN PERFORM public.list_contact_materials(u,u::uuid,'opp'); RAISE EXCEPTION 'expired JWT read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('request.jwt.claims',jsonb_build_object('session_id','36000000-0000-4000-8000-000000000004','exp',floor(extract(epoch FROM now()+interval '1 hour')))::text,false);
 BEGIN PERFORM public.list_contact_materials(u,u::uuid,'opp'); RAISE EXCEPTION 'foreign session read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('request.jwt.claims',claims,false); UPDATE auth.users SET is_anonymous=true WHERE id=u::uuid;
 BEGIN PERFORM public.list_contact_materials(u,u::uuid,'opp'); RAISE EXCEPTION 'anonymous read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 UPDATE auth.users SET is_anonymous=false WHERE id=u::uuid; UPDATE auth.sessions SET not_after=clock_timestamp()-interval '1 second' WHERE id=u::uuid;
 BEGIN PERFORM public.list_contact_materials(u,u::uuid,'opp'); RAISE EXCEPTION 'not_after expiry ignored'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 UPDATE auth.sessions SET not_after=NULL WHERE id=u::uuid; DELETE FROM auth.sessions WHERE id=u::uuid;
 BEGIN PERFORM public.list_contact_materials(u,u::uuid,'opp'); RAISE EXCEPTION 'signed-out JWT read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 INSERT INTO auth.sessions(id,user_id) VALUES(u::uuid,u::uuid);
 RAISE WARNING 'PASS formal owner, JWT expiry, session owner/existence/not_after and logout checks';
END$$;
-- Broad inherited Storage grants/policies must not expose the new bucket.
GRANT USAGE ON SCHEMA storage TO authenticated,anon;
GRANT SELECT,INSERT,UPDATE,DELETE ON storage.objects TO authenticated,anon;
CREATE POLICY material_test_broad_storage_policy ON storage.objects FOR ALL TO authenticated,anon USING(true) WITH CHECK(true);
INSERT INTO storage.objects(bucket_id,name) VALUES('application-materials','private.pdf');
SET ROLE authenticated;
DO $$BEGIN
 BEGIN PERFORM * FROM public.material_artifacts; RAISE EXCEPTION 'browser direct metadata SELECT'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.material_artifacts SET sha256=repeat('f',64); RAISE EXCEPTION 'browser metadata DML'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM * FROM private.material_cleanup_outbox; RAISE EXCEPTION 'browser cleanup metadata'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF EXISTS(SELECT 1 FROM storage.objects WHERE bucket_id='application-materials') THEN RAISE EXCEPTION 'browser bucket leaked'; END IF;
 BEGIN INSERT INTO storage.objects(bucket_id,name) VALUES('application-materials','injected.pdf'); RAISE EXCEPTION 'direct bucket upload'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname IN ('stage_contact_material','finalize_contact_material','claim_material_cleanup') AND p.prosecdef) THEN RAISE EXCEPTION 'public definer'; END IF;
END$$;
RESET ROLE;
DROP POLICY material_test_broad_storage_policy ON storage.objects;
DO $$DECLARE role_name text;f regprocedure;BEGIN
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  IF has_table_privilege(role_name,'public.material_artifacts','INSERT,UPDATE,DELETE,SELECT') OR has_table_privilege(role_name,'public.contact_material_records','INSERT,UPDATE,DELETE,SELECT') THEN RAISE EXCEPTION 'direct table grant %',role_name; END IF;
 END LOOP;
 FOREACH f IN ARRAY ARRAY['private.finalize_contact_material(uuid,uuid,uuid,uuid,bigint,text)'::regprocedure,'public.finalize_contact_material(uuid,uuid,uuid,uuid,bigint,text)'::regprocedure,'private.claim_material_cleanup(integer)'::regprocedure,'public.claim_material_cleanup(integer)'::regprocedure] LOOP
  IF has_function_privilege('authenticated',f,'EXECUTE') OR has_function_privilege('anon',f,'EXECUTE') OR NOT has_function_privilege('service_role',f,'EXECUTE') THEN RAISE EXCEPTION 'service function ACL'; END IF;
 END LOOP;
 RAISE WARNING 'PASS real browser/service ACL and restrictive private-bucket policy';
END$$;
CREATE FUNCTION pg_temp.fail_material_record() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.owner_id='36000000-0000-4000-8000-000000000004' THEN RAISE EXCEPTION 'synthetic_record_failure'; END IF; RETURN NEW; END$$;
CREATE TRIGGER material_test_record_fail BEFORE INSERT ON public.contact_material_records FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_material_record();
DO $$DECLARE r jsonb:=pg_temp.stage(4,4);BEGIN
 BEGIN PERFORM public.finalize_contact_material(auth.uid(),auth.uid(),(r#>>'{artifact,material_id}')::uuid,(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64)); RAISE EXCEPTION 'missing synthetic failure'; EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'synthetic_record_failure' THEN RAISE; END IF; END;
 IF (SELECT status FROM public.material_artifacts WHERE material_id='36000000-0000-4000-9000-000000000004')<>'staged' OR EXISTS(SELECT 1 FROM public.contact_material_records WHERE material_id='36000000-0000-4000-9000-000000000004') THEN RAISE EXCEPTION 'torn finalize/association'; END IF;
 RAISE WARNING 'PASS finalize and contact association roll back atomically';
END$$;
DROP TRIGGER material_test_record_fail ON public.contact_material_records;
-- Expired records represent stages left behind by a stopped backend.
INSERT INTO public.material_artifacts(material_id,record_id,owner_id,artifact_kind,contact_event_id,opportunity_id,status,filename,byte_length,declared_sha256,created_at,expires_at,stage_token,stage_session_id,authorized_until)
SELECT ('36000000-0000-4000-9000-'||lpad(n::text,12,'0'))::uuid,('36000000-0000-4000-a000-'||lpad(n::text,12,'0'))::uuid,'36000000-0000-4000-8000-000000000005','contact','36000000-0000-4000-8000-000000000005','opp','staged','expired.pdf',123,repeat('a',64),now()-interval '2 days',now()-interval '1 day',gen_random_uuid(),'36000000-0000-4000-8000-000000000005',now()+interval '1 hour' FROM generate_series(5,7)n;
DO $$DECLARE u text:=pg_temp.login(5);r jsonb;j jsonb;token uuid;BEGIN
 r:=public.stage_contact_material(u,'36000000-0000-4000-9000-000000000005','36000000-0000-4000-a000-000000000005',u::uuid,'opp','expired.pdf',123,repeat('a',64));
 IF r#>>'{artifact,status}'<>'deleted' THEN RAISE EXCEPTION 'expired stage renewed'; END IF;
 SELECT stage_token INTO token FROM public.material_artifacts WHERE material_id='36000000-0000-4000-9000-000000000006';
 r:=public.finalize_contact_material(u::uuid,u::uuid,'36000000-0000-4000-9000-000000000006',token,123,repeat('a',64));
 IF r#>>'{artifact,status}'<>'deleted' THEN RAISE EXCEPTION 'expired finalized'; END IF;
 r:=public.claim_material_cleanup(100);
 IF EXISTS(SELECT 1 FROM public.material_artifacts WHERE material_id='36000000-0000-4000-9000-000000000007' AND status<>'deleted') THEN RAISE EXCEPTION 'sweeper missed expired stage'; END IF;
 FOR j IN SELECT value FROM jsonb_array_elements(r->'jobs') LOOP
  IF public.ack_material_cleanup((j->>'material_id')::uuid,gen_random_uuid(),true)->>'accepted'<>'false' THEN RAISE EXCEPTION 'stale cleanup ack'; END IF;
  IF public.ack_material_cleanup((j->>'material_id')::uuid,(j->>'claim_token')::uuid,true)->>'accepted'<>'true' THEN RAISE EXCEPTION 'cleanup ack absent'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM private.material_cleanup_outbox)<4 OR EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='36000000-0000-4000-9000-000000000002') THEN RAISE EXCEPTION 'cleanup tombstones missing or ready object scheduled'; END IF;
 IF public.claim_material_cleanup(100)->'jobs'<>'[]'::jsonb THEN RAISE EXCEPTION 'successful cleanup hot-loop'; END IF;
 UPDATE private.material_cleanup_outbox SET next_attempt_at=clock_timestamp()-interval '1 second';
 r:=public.claim_material_cleanup(100);
 IF jsonb_array_length(r->'jobs')<4 THEN RAISE EXCEPTION 'successful removal lost late-upload recheck'; END IF;
 RAISE WARNING 'PASS expiry commit, deleted-stage no revival, cleanup lease fencing and a late-upload recheck';
END$$;
-- Complete Flow B: keep immutable ready content; revoke unfinished uploads.
DO $$DECLARE src text:=pg_temp.login(8);dst text:='36000000-0000-4000-8000-000000000009';tok uuid;before jsonb;r jsonb;BEGIN
 r:=pg_temp.archive(8,8);before:=r->'artifact';PERFORM pg_temp.stage(8,9);
 PERFORM set_config('request.jwt.claims','{"is_anonymous":true}',false);tok:=public.mint_merge_grant('materials-merge@example.invalid');
 PERFORM pg_temp.login(9);PERFORM set_config('request.jwt.claims',(auth.jwt()||'{"email":"materials-merge@example.invalid"}'::jsonb)::text,false);
 r:=public.redeem_merge_grant(tok);
 IF r->>'merged'<>'true' OR EXISTS(SELECT 1 FROM public.material_artifacts WHERE owner_id=src::uuid) THEN RAISE EXCEPTION 'material merge stranded owner'; END IF;
 r:=public.get_contact_material(dst,'36000000-0000-4000-a000-000000000008',src::uuid,'opp');
 IF (r->'artifact')-'owner_id'<>before-'owner_id' THEN RAISE EXCEPTION 'ready material payload/time changed during merge'; END IF;
 r:=public.get_contact_material(dst,'36000000-0000-4000-a000-000000000009',src::uuid,'opp');
 IF r#>>'{artifact,status}'<>'deleted' OR r#>'{artifact,recorded_at}'<>'null'::jsonb THEN RAISE EXCEPTION 'unfinished upload resumed after merge'; END IF;
 PERFORM public.authorize_contact_material_download(dst,'36000000-0000-4000-a000-000000000008',src::uuid,'opp');
 PERFORM pg_temp.login(8);
 BEGIN PERFORM public.list_contact_materials(src,src::uuid,'opp'); RAISE EXCEPTION 'merged source read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 DELETE FROM auth.users WHERE id=src::uuid;
 IF NOT EXISTS(SELECT 1 FROM public.material_artifacts WHERE material_id='36000000-0000-4000-9000-000000000008' AND status='ready') OR EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='36000000-0000-4000-9000-000000000008') THEN RAISE EXCEPTION 'source deletion erased transferred material'; END IF;
 DELETE FROM auth.users WHERE id=dst::uuid;
 IF EXISTS(SELECT 1 FROM public.material_artifacts WHERE owner_id=dst::uuid) OR EXISTS(SELECT 1 FROM public.contact_material_records WHERE owner_id=dst::uuid)
   OR NOT EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='36000000-0000-4000-9000-000000000008') THEN RAISE EXCEPTION 'target deletion failed metadata/bytes cleanup intent'; END IF;
 PERFORM pg_temp.login(2);
 BEGIN PERFORM public.stage_contact_material(auth.uid()::text,'36000000-0000-4000-9000-000000000008',gen_random_uuid(),auth.uid(),'opp','new.pdf',123,repeat('a',64)); RAISE EXCEPTION 'erased key reused'; EXCEPTION WHEN unique_violation THEN NULL; END;
 RAISE WARNING 'PASS Flow B preserves ready archive, revokes unfinished stage, account deletion cleans only current owner and never reuses revoked key';
END$$;
-- A same-ID contact collision no longer blocks the merge (the ledger re-keys
-- the source snapshot); the archived PDF moves intact and is never cleaned up.
DO $$DECLARE src text:=pg_temp.login(10);dst text:='36000000-0000-4000-8000-000000000011';tok uuid;before jsonb;source_event jsonb;target_event jsonb;r jsonb;BEGIN
 r:=pg_temp.archive(10,10);before:=r->'artifact';
 SELECT to_jsonb(e) INTO source_event FROM public.contact_events e WHERE device_id=src AND event_id=src::uuid;
 PERFORM set_config('request.jwt.claims','{"is_anonymous":true}',false);tok:=public.mint_merge_grant('materials-collision@example.invalid');
 PERFORM pg_temp.login(11);target_event:=public.confirm_contact_event(dst,src::uuid,'opp','faculty@example.invalid','Collision','Collision body')->'event';
 PERFORM set_config('request.jwt.claims',(auth.jwt()||'{"email":"materials-collision@example.invalid"}'::jsonb)::text,false);
 PERFORM public.redeem_merge_grant(tok);
 IF (SELECT private.material_json(a) FROM public.material_artifacts a WHERE material_id='36000000-0000-4000-9000-000000000010')-'owner_id'<>before-'owner_id'
   OR (SELECT owner_id::text FROM public.material_artifacts WHERE material_id='36000000-0000-4000-9000-000000000010')<>dst
   OR EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id='36000000-0000-4000-9000-000000000010')
   OR NOT EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src)
   OR (SELECT consumed_at FROM public.merge_grants WHERE token=tok) IS NULL
   OR (SELECT to_jsonb(e) FROM public.contact_events e WHERE device_id=dst AND event_id=src::uuid)<>target_event
   OR (SELECT to_jsonb(e)-'device_id'-'event_id' FROM public.contact_events e WHERE device_id=dst AND event_id=private.contact_event_merge_key(src,src::uuid))
      <>source_event-'device_id'-'event_id' THEN RAISE EXCEPTION 'collision merge lost material or snapshot'; END IF;
 RAISE WARNING 'PASS same-ID contact collision merges, keeping both snapshots and the archived material';
END$$;
-- Tie-safe keyset pagination uses the association timestamp, never the mutable
-- source resume revision, upload time, or filename.
DO $$DECLARE u text:=pg_temp.login(12);mid uuid;rid uuid;r jsonb;r2 jsonb;c jsonb;stamp timestamptz:='2026-01-01';BEGIN
 FOR n IN 1201..1221 LOOP
  mid:=('36000000-0000-4000-9000-'||lpad(n::text,12,'0'))::uuid;rid:=('36000000-0000-4000-a000-'||lpad(n::text,12,'0'))::uuid;
  INSERT INTO public.material_artifacts(material_id,record_id,owner_id,artifact_kind,contact_event_id,opportunity_id,status,filename,byte_length,declared_sha256,sha256,created_at,expires_at,archived_at,stage_token,stage_session_id,authorized_until)
   VALUES(mid,rid,u::uuid,'contact',u::uuid,'opp','ready','same-name.pdf',123,repeat('a',64),repeat('a',64),stamp,stamp+interval '1 day',stamp,gen_random_uuid(),u::uuid,stamp+interval '1 hour');
  INSERT INTO public.contact_material_records(record_id,material_id,owner_id,contact_event_id,opportunity_id,recorded_at) VALUES(rid,mid,u::uuid,u::uuid,'opp',stamp);
 END LOOP;
 r:=public.list_contact_materials(u,u::uuid,'opp');c:=r->'next_cursor';
 IF jsonb_array_length(r->'items')<>20 OR c='null'::jsonb THEN RAISE EXCEPTION 'default 20+1 missing'; END IF;
 r2:=public.list_contact_materials(u,u::uuid,'opp',(c->>'recorded_at')::timestamptz,(c->>'record_id')::uuid);
 IF jsonb_array_length(r2->'items')<>1 OR r2->'next_cursor'<>'null'::jsonb OR (r2#>>'{items,0,record_id}')>=(r#>>'{items,19,record_id}') THEN RAISE EXCEPTION 'tie cursor duplicate/loss'; END IF;
 BEGIN PERFORM public.list_contact_materials(u,u::uuid,'opp',stamp,NULL); RAISE EXCEPTION 'partial cursor'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.list_contact_materials(u,u::uuid,'opp',NULL,NULL,51); RAISE EXCEPTION 'unbounded list'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 RAISE WARNING 'PASS bounded 20+1 keyset pages with identical timestamps and filenames';
END$$;

-- Explicit cancellation is durable even before the first stage exists.
DO $$DECLARE u text:=pg_temp.login(6);mid uuid:=gen_random_uuid();rid uuid:=gen_random_uuid();other uuid:=gen_random_uuid();r jsonb;before jsonb;BEGIN
 r:=public.delete_contact_material(u,rid,mid,u::uuid,'opp');before:=r->'artifact';
 IF r->>'replayed'<>'false' OR r#>>'{artifact,status}'<>'deleted' OR r#>'{artifact,filename}'<>'null'::jsonb OR r#>'{artifact,recorded_at}'<>'null'::jsonb
  OR NOT EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id=mid) THEN RAISE EXCEPTION 'pre-stage cancel missing durable redacted tombstone'; END IF;
 IF public.delete_contact_material(u,rid,mid,u::uuid,'opp')->>'replayed'<>'true' THEN RAISE EXCEPTION 'pre-stage cancel retry not idempotent'; END IF;
 r:=public.stage_contact_material(u,mid,rid,u::uuid,'opp','late.pdf',123,repeat('a',64));
 IF r->'artifact'<>before OR r->'upload'<>'null'::jsonb THEN RAISE EXCEPTION 'late stage resurrected cancelled ID'; END IF;
 r:=public.finalize_contact_material(u::uuid,u::uuid,mid,gen_random_uuid(),123,repeat('a',64));
 IF r->'artifact'<>before OR public.list_contact_materials(u,u::uuid,'opp')->'items'<>'[]'::jsonb THEN RAISE EXCEPTION 'cancelled ID finalized or fabricated submission record'; END IF;
 BEGIN PERFORM public.delete_contact_material(u,gen_random_uuid(),mid,u::uuid,'opp'); RAISE EXCEPTION 'material mismatch cancellation'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'contact_material_conflict' THEN RAISE; END IF; END;
 BEGIN PERFORM public.delete_contact_material(u,rid,other,u::uuid,'opp'); RAISE EXCEPTION 'record collision cancellation'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'contact_material_conflict' THEN RAISE; END IF; END;
 IF EXISTS(SELECT 1 FROM public.material_artifacts WHERE material_id=other) OR EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id=other) THEN RAISE EXCEPTION 'cancel collision partially committed'; END IF;
 BEGIN PERFORM public.delete_contact_material(u,NULL,gen_random_uuid(),u::uuid,'opp'); RAISE EXCEPTION 'null record accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.delete_contact_material(u,gen_random_uuid(),NULL,u::uuid,'opp'); RAISE EXCEPTION 'null material accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 PERFORM pg_temp.login(7);
 BEGIN PERFORM public.delete_contact_material(auth.uid()::text,rid,mid,auth.uid(),'opp'); RAISE EXCEPTION 'cross-owner cancellation accepted'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'contact_material_conflict' THEN RAISE; END IF; END;
 IF (SELECT private.material_json(a) FROM public.material_artifacts a WHERE material_id=mid)<>before THEN RAISE EXCEPTION 'conflict changed cancelled tombstone'; END IF;
 r:=pg_temp.stage(6,600);PERFORM public.delete_contact_material(u,(r#>>'{artifact,record_id}')::uuid,(r#>>'{artifact,material_id}')::uuid,u::uuid,'opp');
 IF public.finalize_contact_material(u::uuid,u::uuid,(r#>>'{artifact,material_id}')::uuid,(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64))#>>'{artifact,status}'<>'deleted' THEN RAISE EXCEPTION 'in-flight finalize resurrected cancelled stage'; END IF;
 IF (SELECT count(*) FROM public.contact_events WHERE device_id=u)<>1 OR (SELECT count(*) FROM public.interaction_status_changes WHERE device_id=u)<>1 THEN RAISE EXCEPTION 'cancel fabricated contact/status'; END IF;
 RAISE WARNING 'PASS pre-stage cancellation, late stage/finalize fencing, exact IDs and cross-owner conflict rollback';
END$$;

-- Deliberately reuse the same event UUID and opportunity across both ledgers.
-- A kind check, not coincidental UUID inequality, must prevent crossover.
DO $$DECLARE u text:=pg_temp.login(13); a jsonb;c jsonb;c2 jsonb;app_before jsonb;second_before jsonb;event2 uuid:=gen_random_uuid();other uuid:=gen_random_uuid();
 keys text[]:=ARRAY['material_id','record_id','contact_event_id','opportunity_id','owner_id','status','filename','mime_type','byte_length','sha256','created_at','expires_at','archived_at','recorded_at','deleted_at','confirmation_source'];
BEGIN
 PERFORM public.confirm_application_event(u,u::uuid,'opp','web_form','https://example.invalid/apply');
 a:=public.stage_application_material(u,'36000000-0000-4000-9000-000000013002','36000000-0000-4000-a000-000000013002',u::uuid,'opp','same.pdf',123,repeat('a',64));
 a:=public.finalize_application_material(u::uuid,u::uuid,(a#>>'{artifact,material_id}')::uuid,(a#>>'{upload,stage_token}')::uuid,123,repeat('a',64));app_before:=a->'artifact';
 c:=pg_temp.archive(13,13001);
 PERFORM public.confirm_contact_event(u,event2,'opp','faculty@example.invalid','Second email','Second original body');
 c2:=public.stage_contact_material(u,'36000000-0000-4000-9000-000000013003','36000000-0000-4000-a000-000000013003',event2,'opp','same.pdf',123,repeat('a',64));
 c2:=public.finalize_contact_material(u::uuid,u::uuid,(c2#>>'{artifact,material_id}')::uuid,(c2#>>'{upload,stage_token}')::uuid,123,repeat('a',64));second_before:=c2->'artifact';
 IF NOT (c->'artifact' ?& keys) OR (c->'artifact')-keys<>'{}'::jsonb THEN RAISE EXCEPTION 'contact receipt key contract changed'; END IF;
 keys:=array_replace(keys,'contact_event_id','application_event_id');
 IF NOT (a->'artifact' ?& keys) OR (a->'artifact')-keys<>'{}'::jsonb THEN RAISE EXCEPTION 'legacy application receipt key contract changed'; END IF;
 BEGIN PERFORM public.stage_application_material(u,(c#>>'{artifact,material_id}')::uuid,(c#>>'{artifact,record_id}')::uuid,u::uuid,'opp','same.pdf',123,repeat('a',64)); RAISE EXCEPTION 'application staged contact ID'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'application_material_conflict' THEN RAISE; END IF; END;
 BEGIN PERFORM public.stage_contact_material(u,(a#>>'{artifact,material_id}')::uuid,(a#>>'{artifact,record_id}')::uuid,u::uuid,'opp','same.pdf',123,repeat('a',64)); RAISE EXCEPTION 'contact staged application ID'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'contact_material_conflict' THEN RAISE; END IF; END;
 BEGIN PERFORM public.delete_application_material(u,(c#>>'{artifact,record_id}')::uuid,(c#>>'{artifact,material_id}')::uuid,u::uuid,'opp'); RAISE EXCEPTION 'application deleted contact ID'; EXCEPTION WHEN unique_violation THEN NULL; END;
 BEGIN PERFORM public.delete_contact_material(u,(a#>>'{artifact,record_id}')::uuid,(a#>>'{artifact,material_id}')::uuid,u::uuid,'opp'); RAISE EXCEPTION 'contact deleted application ID'; EXCEPTION WHEN unique_violation THEN NULL; END;
 IF public.get_application_material(u,(c#>>'{artifact,record_id}')::uuid,u::uuid,'opp')->'artifact'<>'null'::jsonb
   OR public.get_contact_material(u,(a#>>'{artifact,record_id}')::uuid,u::uuid,'opp')->'artifact'<>'null'::jsonb THEN RAISE EXCEPTION 'cross-kind get exposed receipt'; END IF;
 BEGIN PERFORM public.authorize_application_material_download(u,(c#>>'{artifact,record_id}')::uuid,u::uuid,'opp'); RAISE EXCEPTION 'application downloaded contact ID'; EXCEPTION WHEN no_data_found THEN NULL; END;
 BEGIN PERFORM public.authorize_contact_material_download(u,(a#>>'{artifact,record_id}')::uuid,u::uuid,'opp'); RAISE EXCEPTION 'contact downloaded application ID'; EXCEPTION WHEN no_data_found THEN NULL; END;
 BEGIN PERFORM public.finalize_application_material(u::uuid,u::uuid,(c#>>'{artifact,material_id}')::uuid,gen_random_uuid(),123,repeat('a',64)); RAISE EXCEPTION 'application finalized contact ID'; EXCEPTION WHEN no_data_found THEN NULL; END;
 BEGIN PERFORM public.finalize_contact_material(u::uuid,u::uuid,(a#>>'{artifact,material_id}')::uuid,gen_random_uuid(),123,repeat('a',64)); RAISE EXCEPTION 'contact finalized application ID'; EXCEPTION WHEN no_data_found THEN NULL; END;
 IF jsonb_array_length(public.list_contact_materials(u,u::uuid,'opp')->'items')<>1 OR jsonb_array_length(public.list_application_materials(u,u::uuid,'opp')->'items')<>1 THEN RAISE EXCEPTION 'cross-kind list mixed declarations'; END IF;
 BEGIN PERFORM public.stage_contact_material(u,other,(a#>>'{artifact,record_id}')::uuid,u::uuid,'opp','same.pdf',123,repeat('a',64)); RAISE EXCEPTION 'cross-kind record collision accepted'; EXCEPTION WHEN unique_violation THEN NULL; END;
 IF EXISTS(SELECT 1 FROM public.material_artifacts WHERE material_id=other) OR EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id=other) THEN RAISE EXCEPTION 'cross-kind conflict left reservation'; END IF;
 PERFORM public.delete_contact_material(u,(c#>>'{artifact,record_id}')::uuid,(c#>>'{artifact,material_id}')::uuid,u::uuid,'opp');
 IF (public.get_application_material(u,(a#>>'{artifact,record_id}')::uuid,u::uuid,'opp')->'artifact')<>app_before
   OR (public.get_contact_material(u,(c2#>>'{artifact,record_id}')::uuid,event2,'opp')->'artifact')<>second_before
   OR EXISTS(SELECT 1 FROM private.material_cleanup_outbox WHERE material_id IN ((a#>>'{artifact,material_id}')::uuid,(c2#>>'{artifact,material_id}')::uuid)) THEN RAISE EXCEPTION 'deleting equal bytes revoked another declaration'; END IF;
 PERFORM public.authorize_contact_material_download(u,(c2#>>'{artifact,record_id}')::uuid,event2,'opp');
 PERFORM public.authorize_application_material_download(u,(a#>>'{artifact,record_id}')::uuid,u::uuid,'opp');
 PERFORM pg_temp.login(14);PERFORM public.confirm_contact_event(auth.uid()::text,u::uuid,'opp','faculty@example.invalid','Foreign same UUID','Foreign body');
 IF public.get_contact_material(auth.uid()::text,(c2#>>'{artifact,record_id}')::uuid,u::uuid,'opp')->'artifact'<>'null'::jsonb THEN RAISE EXCEPTION 'same UUID foreign-owner read'; END IF;
 BEGIN PERFORM public.delete_contact_material(auth.uid()::text,(c#>>'{artifact,record_id}')::uuid,(c#>>'{artifact,material_id}')::uuid,u::uuid,'opp'); RAISE EXCEPTION 'same UUID foreign owner deleted'; EXCEPTION WHEN unique_violation THEN NULL; END;
 RAISE WARNING 'PASS exact receipts and all six RPCs reject crossed kinds with identical owner/event/opp; equal bytes remain independently deletable; shared UUID across owners stays private';
END$$;
DO $$DECLARE u text:=pg_temp.login(15);n int;BEGIN
 FOR n IN 1..4 LOOP BEGIN
  INSERT INTO public.material_artifacts(material_id,record_id,owner_id,artifact_kind,application_event_id,contact_event_id,opportunity_id,status,created_at,expires_at,deleted_at)
  VALUES(gen_random_uuid(),gen_random_uuid(),u::uuid,CASE WHEN n=4 THEN 'other' ELSE 'contact' END,CASE WHEN n IN (1,3) THEN u::uuid END,CASE WHEN n IN (1,2,4) THEN u::uuid END,'opp','deleted',now(),now(),now());
  IF n<>2 THEN RAISE EXCEPTION 'invalid kind/event pair accepted %',n; END IF;
 EXCEPTION WHEN check_violation THEN IF n=2 THEN RAISE; END IF; END; END LOOP;
 BEGIN UPDATE public.material_artifacts SET artifact_kind='application',application_event_id=contact_event_id,contact_event_id=NULL WHERE owner_id=u::uuid; RAISE EXCEPTION 'artifact kind mutable'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF (SELECT to_jsonb(e) FROM public.contact_events e WHERE device_id='36000000-0000-4000-8000-000000000001') IS DISTINCT FROM (SELECT v FROM original_contact_snapshot) THEN RAISE EXCEPTION 'archive changed original contact snapshot'; END IF;
 RAISE WARNING 'PASS kind/event check constraint, immutable artifact provenance and unchanged original contact recipient/body/subject/materials/send/confirmation times';
END$$;
DO $$DECLARE role_name text;f regprocedure;BEGIN
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  FOREACH f IN ARRAY ARRAY['private.stage_material(text,text,uuid,uuid,uuid,text,text,bigint,text)'::regprocedure,'private.get_material(text,text,uuid,uuid,text)'::regprocedure,'private.list_materials(text,text,uuid,text,timestamptz,uuid,integer)'::regprocedure,'private.authorize_material_download(text,text,uuid,uuid,text)'::regprocedure,'private.delete_material(text,text,uuid,uuid,uuid,text)'::regprocedure,'private.finalize_material(text,uuid,uuid,uuid,uuid,bigint,text)'::regprocedure,'private.material_event_for_kind(text,uuid,uuid,text)'::regprocedure] LOOP
   IF has_function_privilege(role_name,f,'EXECUTE') THEN RAISE EXCEPTION 'internal kind-switching helper exposed to %: %',role_name,f; END IF;
  END LOOP;
 END LOOP;
 RAISE WARNING 'PASS internal kind-switching helpers are unreachable to all API roles';
END$$;
