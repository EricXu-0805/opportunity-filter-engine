\set ON_ERROR_STOP on
SET client_min_messages = warning;
\i :fixture_path
INSERT INTO auth.users(id) SELECT ('45000000-0000-4000-8000-'||lpad(i::text,12,'0'))::uuid FROM generate_series(1,10) i;
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000001',false);
DO $$
DECLARE u text:='45000000-0000-4000-8000-000000000001'; d jsonb:=pg_temp.prov_doc('pair','first'); p jsonb:=pg_temp.prov(d,'event-first'); r jsonb; p2 jsonb;
BEGIN
 r:=public.commit_target_resume_with_provenance_cas(u,'pair',0,d,p);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='1' AND r->'provenance'=p,'create returns exact pair');
 PERFORM pg_temp.require((SELECT doc=d AND provenance=p FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id='pair'),'current exact pair');
 PERFORM pg_temp.require((SELECT doc=d AND provenance=p FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='pair' AND revision=1),'history exact pair');
 r:=public.commit_target_resume_with_provenance_cas(u,'pair',0,d,p);
 PERFORM pg_temp.require(r->>'status'='unchanged' AND r->'provenance'=p,'uncertain response retry exact pair');
 r:=public.commit_target_resume_with_provenance_cas(u,'pair',1,d,p);
 PERFORM pg_temp.require(r->>'status'='unchanged','same revision pair no-op');
 RAISE WARNING 'PASS provenance atomic create/exact pair/no-op/uncertain retry';
 p2:=pg_temp.prov(d,'event-second');
 r:=public.commit_target_resume_with_provenance_cas(u,'pair',1,d,p2);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='2' AND r->'provenance'=p2,'metadata-only edit is a new version');
 r:=public.commit_target_resume_with_provenance_cas(u,'pair',1,d,p);
 PERFORM pg_temp.require(r->>'status'='conflict' AND r->'doc'=d AND r->'provenance'=p2,'stale identical text with wrong provenance conflicts');
 PERFORM pg_temp.require((SELECT count(*)=2 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='pair'),'exact history count');
 RAISE WARNING 'PASS provenance same document/different provenance/CAS conflict';
 r:=public.commit_target_resume_cas(u,'pair',1,d);
 PERFORM pg_temp.require(r->>'status'='unchanged' AND r->'provenance'=p2,'legacy retry preserves metadata');
 r:=public.commit_target_resume_cas(u,'pair',2,d);
 PERFORM pg_temp.require(r->>'status'='unchanged' AND r->'provenance'=p2,'legacy no-op preserves metadata');
 d:=pg_temp.prov_doc('pair','legacy changed');
 r:=public.commit_target_resume_cas(u,'pair',2,d);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='3' AND r->'provenance'='null'::jsonb,'legacy changed text clears metadata');
 PERFORM pg_temp.require((SELECT provenance IS NULL FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id='pair'),'legacy current unknown');
 PERFORM pg_temp.require((SELECT provenance IS NULL FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='pair' AND revision=3),'legacy history unknown');
 PERFORM pg_temp.require((SELECT provenance=p2 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='pair' AND revision=2),'legacy does not mutate prior provenance');
 RAISE WARNING 'PASS provenance legacy no-op keeps/changed document clears/history preserved';
 p:=pg_temp.prov(d,'known-again');
 PERFORM public.commit_target_resume_with_provenance_cas(u,'pair',3,d,p);
 r:=public.commit_target_resume_with_provenance_cas(u,'pair',4,d,NULL);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='5' AND r->'provenance'='null'::jsonb,'explicit new-client null clears metadata');
 r:=public.commit_target_resume_with_provenance_cas(u,'pair',4,d,NULL);
 PERFORM pg_temp.require(r->>'status'='unchanged','null retry is idempotent');
 RAISE WARNING 'PASS provenance explicit null and null retry';
END $$;
DO $$
DECLARE u text:='45000000-0000-4000-8000-000000000001'; d jsonb:=pg_temp.prov_doc('invalid','x'); p jsonb:=pg_temp.prov(d,'base'); v jsonb; i int;
BEGIN
 FOREACH v IN ARRAY ARRAY['null'::jsonb,'[]'::jsonb,'true'::jsonb,p-'version',p||'{"extra":true}'::jsonb,p||'{"version":2}'::jsonb,p||'{"version":"1"}'::jsonb,
 p||'{"document_id":"another"}'::jsonb,p||'{"opportunity_id":"another"}'::jsonb,jsonb_set(p,'{base,master_revision}','2'::jsonb),
 p||'{"events":null}'::jsonb,p||'{"events":[]}'::jsonb,jsonb_set(p,'{events,0}','null'::jsonb),jsonb_set(p,'{events,0,id}','""'::jsonb),
 jsonb_set(p,'{events,0,kind}','"invented"'::jsonb),jsonb_set(p,'{events,0,changes}','[]'::jsonb),jsonb_set(p,'{events,0,changes}','{}'::jsonb)] LOOP
   PERFORM pg_temp.reject_prov(d,v,'invalid envelope/event '||coalesce(i,0)); i:=coalesce(i,0)+1;
 END LOOP;
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{events}',jsonb_build_array(p#>'{events,0}',p#>'{events,0}')),'duplicate event ids');
 RAISE WARNING 'PASS provenance rejects malformed/unknown envelope and events';
 FOREACH v IN ARRAY ARRAY[
 jsonb_set(p,'{events,0,changes,0,field}','"invented"'::jsonb),jsonb_set(p,'{events,0,changes,0,after}','true'::jsonb),
 jsonb_set(p,'{events,0,changes,0,line_id}','null'::jsonb),jsonb_set(p,'{events,0,changes,0,section_id}','null'::jsonb),
 jsonb_set(p,'{events,0,changes,0,block_id}','3'::jsonb),jsonb_set(p,'{events,0,changes,0,reason}','3'::jsonb),
 jsonb_set(p,'{events,0,changes,0,target_evidence}','{}'::jsonb),jsonb_set(p,'{events,0,changes,0,source_evidence}','false'::jsonb),
 jsonb_set(p,'{events,0,changes,0}',(p#>'{events,0,changes,0}')||'{"extra":true}'::jsonb),
 jsonb_set(p,'{events,0,changes,0,reason}','"manual cannot claim AI"'::jsonb)] LOOP
   PERFORM pg_temp.reject_prov(d,v,'invalid change shape/type/path');
 END LOOP;
 RAISE WARNING 'PASS provenance rejects malformed change types/paths/manual AI metadata';
END $$;
DO $$
DECLARE d jsonb:=pg_temp.prov_doc('nested','short'); p jsonb:=pg_temp.prov(d,'ai'); v jsonb; q jsonb;
BEGIN
 p:=jsonb_set(p,'{events,0,kind}','"ai_rewrite"'::jsonb);
 p:=jsonb_set(p,'{events,0,changes,0,target_evidence}','[{"field":"description","requirement_index":null,"start":0,"end":2,"quote":"研究"}]'::jsonb);
 p:=jsonb_set(p,'{events,0,changes,0,source_evidence}','[{"unit_id":"l","start":0,"end":3,"quote":"原文🧪"}]'::jsonb);
 p:=jsonb_set(p,'{events,0,changes,0,check}',jsonb_build_object('version','attribution-v1','pipeline_version','full-target-v2','request_id','req-1','document_signature','v1:sha256:'||repeat('d',64),'original','原文🧪','evidence',jsonb_build_object('kind','experience','id','e','revision',1)));
 PERFORM public.commit_target_resume_with_provenance_cas('45000000-0000-4000-8000-000000000001','nested',0,d,p);
 RAISE WARNING 'PASS provenance stores Unicode quoted check records without certifying AI execution';
 FOREACH v IN ARRAY ARRAY[
 jsonb_set(p,'{events,0,changes,0,target_evidence,0,start}','-1'::jsonb),jsonb_set(p,'{events,0,changes,0,target_evidence,0,end}','0'::jsonb),
 jsonb_set(p,'{events,0,changes,0,target_evidence,0,start}','0.5'::jsonb),jsonb_set(p,'{events,0,changes,0,target_evidence,0,end}','9007199254740992'::jsonb),
 jsonb_set(p,'{events,0,changes,0,target_evidence,0,requirement_index}','0'::jsonb),jsonb_set(p,'{events,0,changes,0,target_evidence,0,quote}','" "'::jsonb),
 jsonb_set(p,'{events,0,changes,0,source_evidence,0,unit_id}','false'::jsonb),jsonb_set(p,'{events,0,changes,0,source_evidence,0,start}','null'::jsonb),
 jsonb_set(p,'{events,0,changes,0,check,version}','""'::jsonb),jsonb_set(p,'{events,0,changes,0,check,evidence,kind}','"fact"'::jsonb),
 jsonb_set(p,'{events,0,changes,0,check,evidence,revision}','true'::jsonb),jsonb_set(p,'{events,0,changes,0,check,document_signature}','"bad"'::jsonb),
 jsonb_set(p,'{events,0,changes,0,check}',(p#>'{events,0,changes,0,check}')||'{"certified":true}'::jsonb)] LOOP
   PERFORM pg_temp.reject_prov(d,v,'invalid nested quote/check');
 END LOOP;
 RAISE WARNING 'PASS provenance nested evidence/check strict types and safe offsets';
END $$;
DO $$
DECLARE u text:='45000000-0000-4000-8000-000000000001'; d jsonb:=pg_temp.prov_doc('limits','x'); p jsonb:=pg_temp.prov(d,'limit'); events jsonb; changes jsonb; overhead bigint;
BEGIN
 SELECT jsonb_agg(jsonb_set(p#>'{events,0}','{id}',to_jsonb('event-'||i))) INTO events FROM generate_series(1,512) i;
 p:=jsonb_set(p,'{events}',events);
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,p),'512 event boundary');
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{events}',events||jsonb_build_array(jsonb_set(events->0,'{id}','"event-513"'::jsonb))),'513 event limit');
 p:=pg_temp.prov(d,'changes');
 SELECT jsonb_agg(jsonb_set(p#>'{events,0,changes,0}','{line_id}',to_jsonb('l-'||i))) INTO changes FROM generate_series(1,1024) i;
 p:=jsonb_set(p,'{events,0,changes}',changes);
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,p),'1024 change boundary');
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{events,0,changes}',changes||jsonb_build_array(changes->0)),'1025 change limit');
 RAISE WARNING 'PASS provenance exact event/change count limits';
 p:=pg_temp.prov(d,'byte-limit'); p:=jsonb_set(p,'{events,0,kind}','"plan"'::jsonb);
 p:=jsonb_set(p,'{events,0,changes,0,reason}','""'::jsonb);
 overhead:=private.target_resume_json_bytes(p);
 p:=jsonb_set(p,'{events,0,changes,0,reason}',to_jsonb(repeat('x',(262144-overhead)::int)));
 PERFORM pg_temp.require(private.target_resume_json_bytes(p)=262144,'exact 256KiB fixture');
 PERFORM public.commit_target_resume_with_provenance_cas(u,'limits',0,d,p);
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{events,0,changes,0,reason}',to_jsonb((p#>>'{events,0,changes,0,reason}')||'x')),'256KiB+1 rejected');
 PERFORM pg_temp.require((SELECT provenance=p FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id='limits'),'over-limit did not replace prior pair');
 RAISE WARNING 'PASS provenance independent exact 256KiB byte limit preserves old pair';
 d:=pg_temp.prov_doc('document-limit','x')||'{"padding":""}'::jsonb;
 overhead:=private.target_resume_json_bytes(d);
 d:=jsonb_set(d,'{padding}',to_jsonb(repeat('x',(2097152-overhead)::int)));
 p:=pg_temp.prov(d,'full-document');
 PERFORM public.commit_target_resume_with_provenance_cas(u,'document-limit',0,d,p);
 PERFORM pg_temp.reject_prov(jsonb_set(d,'{padding}',to_jsonb((d->>'padding')||'x')),p,'document 2MiB+1 rejected');
 RAISE WARNING 'PASS provenance does not consume existing 2MiB document allowance';
END $$;
CREATE FUNCTION pg_temp.fail_provenance_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_provenance_history_failure'; END $$;
CREATE TRIGGER b45_fail_history BEFORE INSERT ON public.target_resume_versions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_provenance_history();
DO $$
DECLARE u text:='45000000-0000-4000-8000-000000000001'; d jsonb:=pg_temp.prov_doc('pair','must roll back'); failed boolean:=false; before_row jsonb;
BEGIN
 SELECT to_jsonb(r) INTO before_row FROM public.target_resumes r WHERE owner_id=u::uuid AND opportunity_id='pair';
 BEGIN PERFORM public.commit_target_resume_with_provenance_cas(u,'pair',5,d,pg_temp.prov(d,'rollback')); EXCEPTION WHEN raise_exception THEN failed:=SQLERRM='synthetic_provenance_history_failure'; END;
 PERFORM pg_temp.require(failed,'history failure reached');
 PERFORM pg_temp.require((SELECT to_jsonb(r)=before_row FROM public.target_resumes r WHERE owner_id=u::uuid AND opportunity_id='pair'),'current pair rolled back');
 PERFORM pg_temp.require((SELECT count(*)=5 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='pair'),'no partial history');
 RAISE WARNING 'PASS provenance history insert failure rolls back whole pair';
END $$;
DROP TRIGGER b45_fail_history ON public.target_resume_versions;
SET ROLE authenticated;
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000002',false);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.target_resumes) OR EXISTS(SELECT 1 FROM public.target_resume_versions) THEN RAISE EXCEPTION 'cross owner RLS leaked'; END IF;
 BEGIN INSERT INTO public.target_resumes(owner_id,opportunity_id,revision,doc,provenance) VALUES ('45000000-0000-4000-8000-000000000002','raw',1,'{}','{}'); RAISE EXCEPTION 'direct insert allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN UPDATE public.target_resume_versions SET provenance=NULL; RAISE EXCEPTION 'direct history edit allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN DELETE FROM public.target_resumes; RAISE EXCEPTION 'direct delete allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 END $$;
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000001',false);
DO $$ DECLARE d jsonb:=pg_temp.prov_doc('authenticated-save','from real authenticated role'); r jsonb;
 BEGIN IF NOT EXISTS(SELECT 1 FROM public.target_resumes WHERE provenance IS NOT NULL) THEN RAISE EXCEPTION 'owner provenance read denied'; END IF;
 r:=public.commit_target_resume_with_provenance_cas('45000000-0000-4000-8000-000000000001','authenticated-save',0,d,pg_temp.prov(d,'authenticated-origin'));
 IF r->>'status'<>'saved' OR r->'provenance'<>pg_temp.prov(d,'authenticated-origin') THEN RAISE EXCEPTION 'authenticated RPC could not save exact pair'; END IF;
 RAISE WARNING 'PASS provenance authenticated RPC/owner SELECT/RLS/direct DML denied'; END $$;
RESET ROLE;
DO $$
DECLARE r jsonb; u text:='45000000-0000-4000-8000-000000000001'; d jsonb:=pg_temp.prov_doc('identity','x');
BEGIN
 PERFORM pg_temp.require(NOT has_function_privilege('anon','public.commit_target_resume_with_provenance_cas(text,text,bigint,jsonb,jsonb)','EXECUTE'),'anon RPC denied');
 PERFORM pg_temp.require(NOT has_function_privilege('authenticated','private.commit_target_resume_pair(text,text,bigint,jsonb,jsonb,boolean)','EXECUTE'),'internal legacy flag denied');
 PERFORM pg_temp.require(NOT has_function_privilege('authenticated','private.target_resume_provenance_valid(jsonb,jsonb)','EXECUTE'),'private validator denied');
 PERFORM pg_temp.require(NOT (SELECT prosecdef FROM pg_proc WHERE oid='public.commit_target_resume_with_provenance_cas(text,text,bigint,jsonb,jsonb)'::regprocedure),'public wrapper invoker');
 PERFORM pg_temp.require(NOT has_table_privilege('authenticated','public.resume_renovations','SELECT'),'legacy capability remains closed');
 BEGIN PERFORM public.commit_target_resume_with_provenance_cas('45000000-0000-4000-8000-000000000002','identity',0,d,NULL); RAISE EXCEPTION 'wrong owner accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid','',false);
 BEGIN PERFORM public.commit_target_resume_with_provenance_cas(u,'identity',0,d,NULL); RAISE EXCEPTION 'signed out accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM set_config('test.uid',u,false);
 r:=public.commit_target_resume_with_provenance_cas(u,'absent',1,pg_temp.prov_doc('absent','x'),NULL);
 PERFORM pg_temp.require(r->>'status'='missing','stale missing row cannot recreate');
 RAISE WARNING 'PASS provenance RPC/helper ACL/identity/missing guards';
END $$;
DO $$
DECLARE src text:='45000000-0000-4000-8000-000000000003'; dst text:='45000000-0000-4000-8000-000000000004'; tok uuid; r jsonb; d jsonb;
BEGIN
 PERFORM set_config('test.uid',src,false);
 d:=pg_temp.prov_doc('solo','source-only'); PERFORM public.commit_target_resume_with_provenance_cas(src,'solo',0,d,pg_temp.prov(d,'solo-origin'));
 d:=pg_temp.prov_doc('both','unknown-old'); PERFORM public.commit_target_resume_cas(src,'both',0,d);
 d:=pg_temp.prov_doc('both','source-v2'); PERFORM public.commit_target_resume_with_provenance_cas(src,'both',1,d,pg_temp.prov(d,'source-origin'));
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('b45-merge@fixture.invalid');
 PERFORM set_config('test.uid',dst,false);
 d:=pg_temp.prov_doc('both','target-current'); PERFORM public.commit_target_resume_with_provenance_cas(dst,'both',0,d,pg_temp.prov(d,'target-origin'));
 PERFORM set_config('test.jwt','{"email":"b45-merge@fixture.invalid"}',false); r:=public.redeem_merge_grant(tok);
 PERFORM pg_temp.require(r->>'merged'='true','actual Flow B merge succeeded');
 PERFORM pg_temp.require((SELECT provenance=pg_temp.prov(doc,'solo-origin') AND doc=pg_temp.prov_doc('solo','source-only') FROM public.target_resumes WHERE owner_id=dst::uuid AND opportunity_id='solo'),'source-only current pair copied');
 PERFORM pg_temp.require((SELECT provenance=pg_temp.prov(doc,'solo-origin') FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='solo' AND revision=1),'source-only history pair copied');
 RAISE WARNING 'PASS provenance actual Flow B source-only current/history copied';
 PERFORM pg_temp.require((SELECT revision=4 AND provenance=pg_temp.prov(doc,'target-origin') AND doc=pg_temp.prov_doc('both','target-current') FROM public.target_resumes WHERE owner_id=dst::uuid AND opportunity_id='both'),'target wins exact pair');
 PERFORM pg_temp.require((SELECT count(*)=4 FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both'),'all four merge versions');
 PERFORM pg_temp.require((SELECT provenance IS NULL AND source_revision=1 AND source_updated_at IS NOT NULL FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both' AND revision=2),'unknown historical version stays unknown');
 PERFORM pg_temp.require((SELECT provenance=pg_temp.prov(doc,'source-origin') AND source_revision=2 FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both' AND revision=3),'source provenance bound to imported revision');
 PERFORM pg_temp.require((SELECT provenance=pg_temp.prov(doc,'target-origin') FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both' AND revision=4),'target final history exact pair');
 RAISE WARNING 'PASS provenance merge collision preserves both histories and old origin revisions';
 r:=public.commit_target_resume_with_provenance_cas(dst,'both',1,pg_temp.prov_doc('both','stale'),NULL);
 PERFORM pg_temp.require(r->>'status'='conflict' AND r->'provenance'=pg_temp.prov(r->'doc','target-origin'),'old target tab sees winning pair');
 PERFORM set_config('test.uid',src,false);
 r:=public.commit_target_resume_with_provenance_cas(src,'solo',0,pg_temp.prov_doc('solo','resurrect'),NULL);
 PERFORM pg_temp.require(r->>'status'='missing','merged source cannot resurrect');
 RAISE WARNING 'PASS provenance merge stale target/source writer fences';
END $$;
DO $$
DECLARE src text:='45000000-0000-4000-8000-000000000005'; dst text:='45000000-0000-4000-8000-000000000006'; tok uuid; failed boolean:=false; d jsonb;
BEGIN
 PERFORM set_config('test.uid',src,false); d:=pg_temp.prov_doc('rollback','source');
 PERFORM public.commit_target_resume_with_provenance_cas(src,'rollback',0,d,pg_temp.prov(d,'must-survive'));
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok:=public.mint_merge_grant('b45-rollback@fixture.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"b45-rollback@fixture.invalid"}',false);
 CREATE TRIGGER b45_fail_history BEFORE INSERT ON public.target_resume_versions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_provenance_history();
 BEGIN PERFORM public.redeem_merge_grant(tok); EXCEPTION WHEN raise_exception THEN failed:=SQLERRM='synthetic_provenance_history_failure'; END;
 DROP TRIGGER b45_fail_history ON public.target_resume_versions;
 PERFORM pg_temp.require(failed AND NOT EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src) AND (SELECT consumed_at IS NULL FROM public.merge_grants WHERE token=tok),'merge identity/grant rolled back');
 PERFORM pg_temp.require((SELECT provenance=pg_temp.prov(doc,'must-survive') FROM public.target_resumes WHERE owner_id=src::uuid AND opportunity_id='rollback'),'source pair survived rollback');
 PERFORM pg_temp.require(NOT EXISTS(SELECT 1 FROM public.target_resumes WHERE owner_id=dst::uuid),'no partial destination');
 RAISE WARNING 'PASS provenance merge failure rolls back pair/history/grant/tombstone';
END $$;
SET ROLE authenticated;
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000003',false);
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.target_resumes) OR EXISTS(SELECT 1 FROM public.target_resume_versions) THEN RAISE EXCEPTION 'merged owner can read provenance'; END IF; END $$;
RESET ROLE;
DELETE FROM auth.users WHERE id='45000000-0000-4000-8000-000000000001';
DO $$ BEGIN
 PERFORM pg_temp.require(NOT EXISTS(SELECT 1 FROM public.target_resumes WHERE owner_id='45000000-0000-4000-8000-000000000001') AND NOT EXISTS(SELECT 1 FROM public.target_resume_versions WHERE owner_id='45000000-0000-4000-8000-000000000001'),'auth deletion cascades doc and provenance');
 RAISE WARNING 'PASS provenance merged-owner reads fenced/auth deletion cascades both tables';
END $$;
