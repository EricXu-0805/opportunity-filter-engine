\set ON_ERROR_STOP on
SET client_min_messages=warning;
CREATE FUNCTION pg_temp.legacy_payload(label text) RETURNS jsonb LANGUAGE sql AS $$
 SELECT jsonb_build_object('doc',jsonb_build_object('sections',jsonb_build_array(jsonb_build_object('id','section','heading',label,'bullets','[]'::jsonb)),
   'method','ai','warnings','[]'::jsonb,'profile_sig','unknown-original','target_sig','unchanged-target'),
   'base_snapshot',jsonb_build_object('sections','[]'::jsonb,'original','完整源文🧪'), 'method',NULL,'warnings','[]'::jsonb);
$$;
INSERT INTO auth.users(id) SELECT ('88000000-0000-4000-8000-'||lpad(x::text,12,'0'))::uuid FROM generate_series(2,12) x;
-- 1. Real pre-migration records preserved; current gains revision, not new facts.
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000001'; r jsonb; old jsonb; n int;
BEGIN
 PERFORM set_config('test.uid',u,false); r:=public.read_renovation(u,'old-current');
 IF r#>>'{current,revision}'<>'1' OR r#>>'{current,payload,doc,resume_sig}'<>'unknown-original'
   OR r#>>'{current,payload,base_snapshot,source}'<>'旧原文🧪' OR r#>'{current,payload,method}'<>'null'::jsonb THEN RAISE EXCEPTION 'legacy current migration changed content'; END IF;
 old:=public.get_renovation_version(u,'old-current','88000000-0000-4000-8000-000000000099');
 IF old#>>'{version,snapshot_kind}'<>'legacy_doc' OR old#>'{version,revision}'<>'null'::jsonb
   OR old#>'{version,payload,base_snapshot}'<>'null'::jsonb OR old#>'{version,payload,warnings}'<>'null'::jsonb
   OR old#>>'{version,payload,doc,old}'<>'historic exact' THEN RAISE EXCEPTION 'old history invented provenance'; END IF;
 SELECT count(*) INTO n FROM public.resume_renovation_versions WHERE device_id=u AND snapshot_kind='complete' AND revision=1;
 IF n<>1 THEN RAISE EXCEPTION 'missing complete migration baseline'; END IF;
 IF (SELECT owner_id FROM public.resume_renovations WHERE device_id='acl-preserve-device') IS NOT NULL THEN RAISE EXCEPTION 'orphan device reassigned'; END IF;
 RAISE WARNING 'PASS legacy migration preservation + baseline + unknown history';
END $$;
-- 2. CAS and exact full-payload lost-response replay.
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000002'; a jsonb:=pg_temp.legacy_payload('first'); b jsonb:=pg_temp.legacy_payload('second'); r jsonb; n int;
BEGIN
 PERFORM set_config('test.uid',u,false);
 IF public.read_renovation(u,'opp')->>'status'<>'absent' THEN RAISE EXCEPTION 'new row not absent'; END IF;
 r:=public.save_renovation_cas(u,'opp',0,a);
 IF r->>'status'<>'saved' OR r#>>'{current,revision}'<>'1' OR r#>'{current,payload}'<>a OR r#>>'{current,owner_id}'<>u THEN RAISE EXCEPTION 'create receipt wrong'; END IF;
 IF public.save_renovation_cas(u,'opp',0,a)->>'status'<>'unchanged' OR public.save_renovation_cas(u,'opp',1,a)->>'status'<>'unchanged' THEN RAISE EXCEPTION 'same payload replay duplicated'; END IF;
 r:=public.save_renovation_cas(u,'opp',1,b); IF r#>>'{current,revision}'<>'2' THEN RAISE EXCEPTION 'update revision'; END IF;
 r:=public.save_renovation_cas(u,'opp',0,a); IF r->>'status'<>'conflict' OR r#>'{current,payload}'<>b THEN RAISE EXCEPTION 'late unknown replay not conflict'; END IF;
 r:=public.save_renovation_cas(u,'opp',2,a); IF r#>>'{current,revision}'<>'3' THEN RAISE EXCEPTION 'restore did not append'; END IF;
 SELECT count(*) INTO n FROM public.resume_renovation_versions WHERE device_id=u AND opportunity_id='opp';
 IF n<>3 THEN RAISE EXCEPTION 'history duplicate or missing'; END IF;
 r:=public.save_renovation_cas(u,'gone',1,a); IF r<>jsonb_build_object('status','missing') THEN RAISE EXCEPTION 'absent update resurrected'; END IF;
 -- Same doc with changed source metadata must be a real save, not unchanged.
 r:=public.save_renovation_cas(u,'opp',3,jsonb_set(a,'{base_snapshot,original}','"new source"'));
 IF r#>>'{current,revision}'<>'4' THEN RAISE EXCEPTION 'full payload comparison omitted base snapshot'; END IF;
 RAISE WARNING 'PASS legacy CAS create/update/restore/full-payload/replay/conflict/missing';
END $$;
-- 3. All four entrypoints enforce auth + owned namespace. Browser tables stay hidden.
SET ROLE authenticated;
SELECT set_config('test.uid','88000000-0000-4000-8000-000000000003',false);
DO $$ DECLARE me text:='88000000-0000-4000-8000-000000000003'; victim text:='88000000-0000-4000-8000-000000000002';
BEGIN
 IF public.read_renovation(me,'opp')->>'status'<>'absent' THEN RAISE EXCEPTION 'cross owner current exposed'; END IF;
 IF public.list_renovation_versions(me,'opp')->'items'<>'[]'::jsonb THEN RAISE EXCEPTION 'cross owner history exposed'; END IF;
 BEGIN PERFORM public.read_renovation(victim,'opp'); RAISE EXCEPTION 'wrong owner read'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.save_renovation_cas(victim,'opp',0,'{}'); RAISE EXCEPTION 'wrong owner save'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.list_renovation_versions(victim,'opp'); RAISE EXCEPTION 'wrong owner list'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.get_renovation_version(victim,'opp','88000000-0000-4000-8000-000000000099'); RAISE EXCEPTION 'wrong owner version'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM * FROM public.resume_renovations; RAISE EXCEPTION 'direct select reopened'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN INSERT INTO public.resume_renovations(device_id,opportunity_id)VALUES(me,'direct'); RAISE EXCEPTION 'direct insert reopened'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.resume_renovation_versions SET doc='{}'; RAISE EXCEPTION 'history update open'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
DO $$ DECLARE f regprocedure;
BEGIN
 FOREACH f IN ARRAY ARRAY['public.read_renovation(text,text)'::regprocedure,'public.save_renovation_cas(text,text,bigint,jsonb)'::regprocedure,
 'public.list_renovation_versions(text,text,timestamptz,uuid,integer)'::regprocedure,'public.get_renovation_version(text,text,uuid)'::regprocedure] LOOP
 IF has_function_privilege('anon',f,'EXECUTE') OR NOT has_function_privilege('authenticated',f,'EXECUTE') OR (SELECT prosecdef FROM pg_proc WHERE oid=f) THEN RAISE EXCEPTION 'public RPC ACL/definer unsafe'; END IF;
 END LOOP;
 PERFORM set_config('test.uid','',false);
 BEGIN PERFORM public.read_renovation(NULL,'opp'); RAISE EXCEPTION 'null identity accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid','88000000-0000-4000-8000-000000000404',false);
 BEGIN PERFORM public.read_renovation('88000000-0000-4000-8000-000000000404','opp'); RAISE EXCEPTION 'stale nonexistent account JWT accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS legacy four-RPC owner/auth guards + closed table ACL';
END $$;
-- 4. Safe bounded malformed rejection, no payload in exception messages.
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000002'; p jsonb; good jsonb:=pg_temp.legacy_payload('secret');
BEGIN
 PERFORM set_config('test.uid',u,false);
 FOREACH p IN ARRAY ARRAY['null'::jsonb,'[]'::jsonb,'{}'::jsonb,good||'{"extra":"secret"}',good-'method',
 jsonb_set(good,'{warnings}','[1]'),jsonb_set(good,'{method}','1'),jsonb_set(good,'{base_snapshot}','[]'),
 jsonb_set(good,'{doc}','{"kind":"full_resume","sections":[]}')] LOOP
 BEGIN PERFORM public.save_renovation_cas(u,'invalid',0,p); RAISE EXCEPTION 'malformed accepted'; EXCEPTION WHEN invalid_parameter_value THEN IF SQLERRM<>'invalid_renovation_payload' THEN RAISE EXCEPTION 'unsafe error message'; END IF; END;
 END LOOP;
 BEGIN PERFORM public.save_renovation_cas(u,'invalid',-1,good); RAISE EXCEPTION 'negative revision accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.read_renovation(u,repeat('x',201)); RAISE EXCEPTION 'long id accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.list_renovation_versions(u,'opp',NULL,NULL,51); RAISE EXCEPTION 'oversized page accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM public.list_renovation_versions(u,'opp',now(),NULL); RAISE EXCEPTION 'partial cursor accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 RAISE WARNING 'PASS legacy malformed/full-document-family/limit rejection';
END $$;
-- 5. Compact UTF8 exact boundary rather than jsonb::text whitespace/truncation.
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000002'; p jsonb:=pg_temp.legacy_payload('研🧪'); overhead int;
BEGIN
 PERFORM set_config('test.uid',u,false); p:=jsonb_set(p,'{doc,padding}','""'); overhead:=private.target_resume_json_bytes(p);
 p:=jsonb_set(p,'{doc,padding}',to_jsonb(repeat('x',2097152-overhead)));
 IF private.target_resume_json_bytes(p)<>2097152 THEN RAISE EXCEPTION 'bad boundary fixture'; END IF;
 IF public.save_renovation_cas(u,'capacity',0,p)->>'status'<>'saved' THEN RAISE EXCEPTION 'exact2MiB rejected'; END IF;
 BEGIN PERFORM public.save_renovation_cas(u,'capacity',1,jsonb_set(p,'{doc,padding}',to_jsonb((p#>>'{doc,padding}')||'x'))); RAISE EXCEPTION 'overlimit accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 IF (public.read_renovation(u,'capacity')#>'{current,payload}')<>p THEN RAISE EXCEPTION 'capacity text truncated'; END IF;
 RAISE WARNING 'PASS legacy exact 2MiB compact UTF8 + reject without truncation';
END $$;
-- 5b. Over twice the compact limit is refused before the per-node measure.
SET track_functions='all';
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000002'; p jsonb:=pg_temp.legacy_payload('huge'); before bigint; refused boolean:=false;
BEGIN
 PERFORM set_config('test.uid',u,false); p:=jsonb_set(p,'{doc,padding}',to_jsonb(repeat('x',4194305)));
 SELECT coalesce(sum(calls),0) INTO before FROM pg_stat_xact_user_functions WHERE schemaname='private' AND funcname='target_resume_json_bytes';
 BEGIN PERFORM public.save_renovation_cas(u,'huge',0,p); EXCEPTION WHEN invalid_parameter_value THEN refused:=SQLERRM='invalid_renovation_payload'; END;
 IF NOT refused OR (SELECT coalesce(sum(calls),0) FROM pg_stat_xact_user_functions WHERE schemaname='private' AND funcname='target_resume_json_bytes')<>before THEN
   RAISE EXCEPTION 'oversized legacy payload walked before refusal'; END IF;
 RAISE WARNING 'PASS legacy oversized payload refused before any node walk';
END $$;
-- 6. History failure rolls back the current row and revision.
CREATE FUNCTION pg_temp.fail_legacy_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_legacy_history_failure'; END $$;
CREATE TRIGGER test_legacy_history_failure BEFORE INSERT ON public.resume_renovation_versions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_legacy_history();
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000002'; before jsonb;
BEGIN
 PERFORM set_config('test.uid',u,false); before:=public.read_renovation(u,'opp');
 BEGIN PERFORM public.save_renovation_cas(u,'opp',4,pg_temp.legacy_payload('torn')); RAISE EXCEPTION 'failure not raised'; EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'synthetic_legacy_history_failure' THEN RAISE; END IF; END;
 IF public.read_renovation(u,'opp')<>before THEN RAISE EXCEPTION 'torn current/history'; END IF;
 RAISE WARNING 'PASS legacy atomic current/history rollback';
END $$;
DROP TRIGGER test_legacy_history_failure ON public.resume_renovation_versions;
-- 7. Tied timestamps use UUID tie-breaker; complete and unknown versions retain exact payloads.
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000003'; first jsonb; second jsonb; cur jsonb; got jsonb; x int;
BEGIN
 PERFORM set_config('test.uid',u,false);
 FOR x IN 1..3 LOOP
 INSERT INTO public.resume_renovation_versions(id,owner_id,device_id,opportunity_id,doc,created_at)
 VALUES(('88100000-0000-4000-8000-'||lpad(x::text,12,'0'))::uuid,u::uuid,u,'pages',jsonb_build_object('old',x),'2020-01-01T00:00:00.123456Z');
 END LOOP;
 first:=public.list_renovation_versions(u,'pages',NULL,NULL,2); cur:=first->'next_cursor';
 IF jsonb_array_length(first->'items')<>2 OR first#>>'{items,0,id}'<>'88100000-0000-4000-8000-000000000003' OR cur<>jsonb_build_object('created_at',first#>'{items,1,created_at}','id',first#>'{items,1,id}') THEN RAISE EXCEPTION 'first page/cursor incorrect'; END IF;
 second:=public.list_renovation_versions(u,'pages',(cur->>'created_at')::timestamptz,(cur->>'id')::uuid,2);
 IF jsonb_array_length(second->'items')<>1 OR second->'next_cursor'<>'null'::jsonb OR second#>>'{items,0,id}'<>'88100000-0000-4000-8000-000000000001' THEN RAISE EXCEPTION 'tied timestamp page skipped/duplicated'; END IF;
 got:=public.get_renovation_version(u,'pages','88100000-0000-4000-8000-000000000001');
 IF got#>'{version,payload,base_snapshot}'<>'null'::jsonb OR got#>>'{version,payload,doc,old}'<>'1' THEN RAISE EXCEPTION 'legacy history guessed fields'; END IF;
 IF public.get_renovation_version(u,'other','88100000-0000-4000-8000-000000000001')->>'status'<>'absent' THEN RAISE EXCEPTION 'version target isolation'; END IF;
 RAISE WARNING 'PASS legacy precise tuple pagination + complete/unknown history reads';
END $$;
-- 8. Actual Flow B: source current WITHOUT history must survive collision.
DO $$ DECLARE src text:='88000000-0000-4000-8000-000000000004'; dst text:='88000000-0000-4000-8000-000000000005'; tok uuid; r jsonb; v uuid;
BEGIN
 PERFORM set_config('test.uid',src,false); PERFORM public.save_renovation_cas(src,'both',0,pg_temp.legacy_payload('source-current'));
 DELETE FROM public.resume_renovation_versions WHERE device_id=src; -- historical torn-save simulation
 PERFORM public.save_renovation_cas(src,'solo',0,pg_temp.legacy_payload('source-solo'));
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('legacy-dst@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM public.save_renovation_cas(dst,'both',0,pg_temp.legacy_payload('destination'));
 PERFORM set_config('test.jwt','{"email":"legacy-dst@example.invalid"}',false); r:=public.redeem_merge_grant(tok);
 IF r->>'merged'<>'true' OR public.read_renovation(dst,'both')#>>'{current,revision}'<>'2'
 OR public.read_renovation(dst,'both')#>'{current,payload}'<>pg_temp.legacy_payload('destination')
 OR public.read_renovation(dst,'solo')#>'{current,payload}'<>pg_temp.legacy_payload('source-solo') THEN RAISE EXCEPTION 'merge working outcome wrong'; END IF;
 SELECT id INTO v FROM public.resume_renovation_versions WHERE device_id=dst AND opportunity_id='both' AND doc#>>'{sections,0,heading}'='source-current';
 IF v IS NULL OR public.get_renovation_version(dst,'both',v)#>'{version,payload}'<>pg_temp.legacy_payload('source-current')
   OR public.get_renovation_version(dst,'both',v)#>'{version,revision}'<>'null'::jsonb
   OR public.get_renovation_version(dst,'both',v)#>>'{version,source_revision}'<>'1' THEN RAISE EXCEPTION 'source current/provenance lost'; END IF;
 IF public.save_renovation_cas(dst,'both',1,pg_temp.legacy_payload('old-tab'))->>'status'<>'conflict' THEN RAISE EXCEPTION 'merge did not fence destination old tab'; END IF;
 IF EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id=src) OR EXISTS(SELECT 1 FROM public.resume_renovation_versions WHERE device_id=src) THEN RAISE EXCEPTION 'merge left source rows'; END IF;
 PERFORM set_config('test.uid',src,false);
 BEGIN PERFORM public.read_renovation(src,'both'); RAISE EXCEPTION 'merged read allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.save_renovation_cas(src,'both',0,pg_temp.legacy_payload('revive')); RAISE EXCEPTION 'merged resurrected'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.list_renovation_versions(src,'both'); RAISE EXCEPTION 'merged history allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.get_renovation_version(src,'both',v); RAISE EXCEPTION 'merged version allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS legacy real Flow B source-only/collision/history/provenance/old-tab/merged guards';
END $$;
-- 9. A preservation failure aborts the entire merge/grant/tombstone transaction.
DO $$ DECLARE src text:='88000000-0000-4000-8000-000000000006'; dst text:='88000000-0000-4000-8000-000000000007'; tok uuid;
BEGIN
 PERFORM set_config('test.uid',src,false); PERFORM public.save_renovation_cas(src,'rollback',0,pg_temp.legacy_payload('source'));
 DELETE FROM public.resume_renovation_versions WHERE device_id=src;
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('legacy-rollback@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"legacy-rollback@example.invalid"}',false);
 CREATE TRIGGER test_legacy_history_failure BEFORE INSERT ON public.resume_renovation_versions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_legacy_history();
 BEGIN PERFORM public.redeem_merge_grant(tok); RAISE EXCEPTION 'merge failure absent'; EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'synthetic_legacy_history_failure' THEN RAISE; END IF; END;
 IF EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src) OR (SELECT consumed_at FROM public.merge_grants WHERE token=tok) IS NOT NULL OR NOT EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id=src) OR EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id=dst) THEN RAISE EXCEPTION 'partial failed merge'; END IF;
 DROP TRIGGER test_legacy_history_failure ON public.resume_renovation_versions;
 RAISE WARNING 'PASS legacy merge rollback includes grant and tombstone';
END $$;
-- 10. Independent material survives profile deletion; account deletion cascades.
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000008';
BEGIN
 PERFORM set_config('test.uid',u,false); PERFORM public.save_renovation_cas(u,'kept',0,pg_temp.legacy_payload('kept'));
 INSERT INTO public.profiles(id,profile_data) VALUES(u,'{}'); DELETE FROM public.profiles WHERE id=u;
 IF public.read_renovation(u,'kept')->>'status'<>'found' THEN RAISE EXCEPTION 'profile deletion erased material'; END IF;
 PERFORM public.save_renovation_cas(u,'kept',1,pg_temp.legacy_payload('edited without profile'));
 DELETE FROM auth.users WHERE id=u::uuid;
 IF EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id=u) OR EXISTS(SELECT 1 FROM public.resume_renovation_versions WHERE device_id=u) THEN RAISE EXCEPTION 'auth account orphaned private content'; END IF;
 BEGIN PERFORM public.read_renovation(u,'kept'); RAISE EXCEPTION 'deleted JWT read accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.save_renovation_cas(u,'kept',0,pg_temp.legacy_payload('revive')); RAISE EXCEPTION 'deleted JWT write accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS legacy profile absence independent + account cascade/stale-JWT reject';
END $$;
-- 11. Revision bound is enforced before any history/current mutation.
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000009';
BEGIN
 PERFORM set_config('test.uid',u,false); PERFORM public.save_renovation_cas(u,'limit',0,pg_temp.legacy_payload('max'));
 UPDATE public.resume_renovations SET revision=9007199254740991 WHERE device_id=u;
 BEGIN PERFORM public.save_renovation_cas(u,'limit',9007199254740991,pg_temp.legacy_payload('overflow')); RAISE EXCEPTION 'revision overflow'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 IF (SELECT count(*) FROM public.resume_renovation_versions WHERE device_id=u)<>1 THEN RAISE EXCEPTION 'overflow wrote history'; END IF;
 RAISE WARNING 'PASS legacy safe-integer revision bound';
END $$;
-- 12. Successful calls work as the real browser database role, not postgres.
SET ROLE authenticated;
SELECT set_config('test.uid','88000000-0000-4000-8000-000000000010',false);
DO $$ DECLARE u text:='88000000-0000-4000-8000-000000000010'; p jsonb:='{"doc":{"sections":[],"profile_sig":"old-unknown","target_sig":"old-target"},"base_snapshot":{},"method":null,"warnings":[]}'; r jsonb; v uuid;
BEGIN
 r:=public.save_renovation_cas(u,'authenticated',0,p);
 IF r->>'status'<>'saved' OR r#>'{current,payload}'<>p THEN RAISE EXCEPTION 'authenticated save failed'; END IF;
 IF public.read_renovation(u,'authenticated')#>'{current,payload}'<>p THEN RAISE EXCEPTION 'authenticated read failed'; END IF;
 r:=public.list_renovation_versions(u,'authenticated'); v:=(r#>>'{items,0,id}')::uuid;
 IF public.get_renovation_version(u,'authenticated',v)#>'{version,payload}'<>p THEN RAISE EXCEPTION 'authenticated history failed'; END IF;
 IF public.save_renovation_cas(u,'authenticated',0,jsonb_set(p,'{warnings}','["new warning"]'))->>'status'<>'conflict' THEN RAISE EXCEPTION 'warning difference falsely replayed'; END IF;
 RAISE WARNING 'PASS legacy real authenticated role positive read/save/list/get + metadata conflict';
END $$;
RESET ROLE;
-- 13. History-only legacy rows follow actual merge without invented sources.
DO $$ DECLARE src text:='88000000-0000-4000-8000-000000000011'; dst text:='88000000-0000-4000-8000-000000000012'; tok uuid; v uuid:='88200000-0000-4000-8000-000000000001'; x jsonb;
BEGIN
 INSERT INTO public.resume_renovation_versions(id,owner_id,device_id,opportunity_id,doc,created_at)
 VALUES(v,src::uuid,src,'history-only','{"unknown":"exact"}','2020-01-01T00:00:00Z');
 PERFORM set_config('test.uid',src,false); PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('legacy-history-only@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"legacy-history-only@example.invalid"}',false); PERFORM public.redeem_merge_grant(tok);
 x:=public.get_renovation_version(dst,'history-only',v);
 IF x#>>'{version,snapshot_kind}'<>'legacy_doc' OR x#>'{version,payload,base_snapshot}'<>'null'::jsonb
   OR x#>'{version,source_revision}'<>'null'::jsonb OR x#>>'{version,payload,doc,unknown}'<>'exact' THEN RAISE EXCEPTION 'history-only source fabricated/lost'; END IF;
 IF public.read_renovation(dst,'history-only')->>'status'<>'absent' THEN RAISE EXCEPTION 'history-only invented current'; END IF;
 RAISE WARNING 'PASS legacy history-only merge + unchanged unknown provenance';
END $$;
-- 14. Backfilled old current/history also cascade, not just newly saved data.
DELETE FROM auth.users WHERE id='88000000-0000-4000-8000-000000000001';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id='88000000-0000-4000-8000-000000000001')
 OR EXISTS(SELECT 1 FROM public.resume_renovation_versions WHERE device_id='88000000-0000-4000-8000-000000000001') THEN RAISE EXCEPTION 'backfilled legacy owner did not cascade'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id='acl-preserve-device' AND owner_id IS NULL) THEN RAISE EXCEPTION 'unclaimed old device was deleted'; END IF;
 RAISE WARNING 'PASS legacy backfilled auth cascade + orphan preservation';
END $$;
