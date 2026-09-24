\set ON_ERROR_STOP on
SET client_min_messages = warning;
CREATE FUNCTION pg_temp.target_doc(opp text, marker text) RETURNS jsonb LANGUAGE sql AS $$
 SELECT jsonb_build_object('kind','full_resume','version',1,'id',marker,'opportunity_id',opp,
   'base','{}'::jsonb,'base_snapshot','{}'::jsonb,'target_snapshot','{}'::jsonb,
   'document',jsonb_build_object('sections','[]'::jsonb));
$$;
INSERT INTO auth.users(id) VALUES
 ('77000000-0000-4000-8000-000000000001'),('77000000-0000-4000-8000-000000000002'),
 ('77000000-0000-4000-8000-000000000003'),('77000000-0000-4000-8000-000000000004'),
 ('77000000-0000-4000-8000-000000000005'),('77000000-0000-4000-8000-000000000006');
DO $$
DECLARE u text := '77000000-0000-4000-8000-000000000001'; r jsonb; d jsonb := pg_temp.target_doc('opp','first'); n int;
BEGIN
 PERFORM set_config('test.uid',u,false);
 r := public.commit_target_resume_cas(u,'opp',0,d);
 IF r->>'status' <> 'saved' OR r->>'revision' <> '1' THEN RAISE EXCEPTION 'create failed %',r; END IF;
 r := public.commit_target_resume_cas(u,'opp',0,d);
 IF r->>'status' <> 'unchanged' THEN RAISE EXCEPTION 'lost-response retry not unchanged'; END IF;
 r := public.commit_target_resume_cas(u,'opp',1,d);
 IF r->>'status' <> 'unchanged' THEN RAISE EXCEPTION 'same-revision no-op not unchanged'; END IF;
 r := public.commit_target_resume_cas(u,'opp',1,pg_temp.target_doc('opp','second'));
 IF r->>'revision' <> '2' THEN RAISE EXCEPTION 'edit failed'; END IF;
 r := public.commit_target_resume_cas(u,'opp',1,d);
 IF r->>'status' <> 'conflict' THEN RAISE EXCEPTION 'stale edit not conflict'; END IF;
 r := public.commit_target_resume_cas(u,'opp',2,d);
 IF r->>'revision' <> '3' THEN RAISE EXCEPTION 'restore did not create new version'; END IF;
 SELECT count(*) INTO n FROM public.target_resume_versions WHERE owner_id=u::uuid;
 IF n <> 3 THEN RAISE EXCEPTION 'history count %',n; END IF;
 IF (SELECT doc FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='opp' AND revision=2) <> pg_temp.target_doc('opp','second') THEN RAISE EXCEPTION 'historical document mutated'; END IF;
 r := public.commit_target_resume_cas(u,'absent',1,pg_temp.target_doc('absent','x'));
 IF r->>'status' <> 'missing' THEN RAISE EXCEPTION 'missing stale row recreated'; END IF;
 r := public.commit_target_resume_cas(u,'other',0,pg_temp.target_doc('other','x'));
 IF r->>'revision' <> '1' THEN RAISE EXCEPTION 'different target not independent'; END IF;
 BEGIN PERFORM public.commit_target_resume_cas('77000000-0000-4000-8000-000000000002','opp',3,d); RAISE EXCEPTION 'wrong owner accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.commit_target_resume_cas(u,'other',1,d); RAISE EXCEPTION 'target mismatch accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 PERFORM set_config('test.uid','',false);
 BEGIN PERFORM public.commit_target_resume_cas(u,'opp',3,d); RAISE EXCEPTION 'null uid accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS target CAS create/retry/conflict/restore/missing/owner/target';
END $$;
-- Real grants and RLS, not just predicates inspected as postgres.
SET ROLE authenticated;
SELECT set_config('test.uid','77000000-0000-4000-8000-000000000002',false);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.target_resumes) OR EXISTS(SELECT 1 FROM public.target_resume_versions) THEN RAISE EXCEPTION 'RLS cross-owner read'; END IF;
 BEGIN DELETE FROM public.target_resumes; RAISE EXCEPTION 'direct DML accepted'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF has_table_privilege(current_user,'public.target_resume_versions','UPDATE') OR has_table_privilege(current_user,'public.target_resume_versions','INSERT') THEN RAISE EXCEPTION 'history browser DML granted'; END IF;
END $$;
SELECT set_config('test.uid','77000000-0000-4000-8000-000000000001',false);
DO $$ BEGIN IF (SELECT count(*) FROM public.target_resumes) <> 2 THEN RAISE EXCEPTION 'owner SELECT missing'; END IF; END $$;
RESET ROLE;
DO $$ BEGIN
 IF has_function_privilege('anon','public.commit_target_resume_cas(text,text,bigint,jsonb)','EXECUTE') THEN RAISE EXCEPTION 'anon RPC open'; END IF;
 IF (SELECT prosecdef FROM pg_proc WHERE oid='public.commit_target_resume_cas(text,text,bigint,jsonb)'::regprocedure) THEN RAISE EXCEPTION 'public RPC privileged'; END IF;
 IF has_table_privilege('authenticated','public.resume_renovations','SELECT') THEN RAISE EXCEPTION 'legacy table reopened'; END IF;
 BEGIN UPDATE public.target_resume_versions SET source_updated_at=now(), source_revision=NULL WHERE opportunity_id='opp'; RAISE EXCEPTION 'partial origin null pair accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
 RAISE WARNING 'PASS target ACL/RLS/legacy revoked';
END $$;
-- Exact compact size, including multibyte strings and escaped control chars.
DO $$
DECLARE u text := '77000000-0000-4000-8000-000000000001'; d jsonb; overhead bigint;
BEGIN
 IF private.target_resume_json_bytes('{"a":"研🧪","b":"\u0001","c":[1,true,null]}'::jsonb) <> octet_length('{"a":"研🧪","b":"\u0001","c":[1,true,null]}') THEN RAISE EXCEPTION 'UTF8 compact measure mismatch'; END IF;
 d := pg_temp.target_doc('limit','x') || '{"padding":""}'::jsonb;
 overhead := private.target_resume_json_bytes(d);
 d := jsonb_set(d,'{padding}',to_jsonb(repeat('x',(2097152-overhead)::int)));
 IF private.target_resume_json_bytes(d) <> 2097152 THEN RAISE EXCEPTION 'exact limit fixture'; END IF;
 PERFORM set_config('test.uid',u,false);
 PERFORM public.commit_target_resume_cas(u,'limit',0,d);
 BEGIN PERFORM public.commit_target_resume_cas(u,'limit',1,jsonb_set(d,'{padding}',to_jsonb((d->>'padding')||'x'))); RAISE EXCEPTION 'over limit accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 RAISE WARNING 'PASS target exact 2MiB/over byte/multibyte/escape';
END $$;
-- A failed history insert must roll the current update back as well.
CREATE FUNCTION pg_temp.fail_target_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_history_failure'; END $$;
CREATE TRIGGER target_test_fail_history BEFORE INSERT ON public.target_resume_versions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_target_history();
DO $$
DECLARE u text := '77000000-0000-4000-8000-000000000001'; failed boolean := false;
BEGIN
 PERFORM set_config('test.uid',u,false);
 BEGIN PERFORM public.commit_target_resume_cas(u,'opp',3,pg_temp.target_doc('opp','lost')); EXCEPTION WHEN raise_exception THEN failed := SQLERRM = 'synthetic_history_failure'; END;
 IF NOT failed OR (SELECT revision FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id='opp') <> 3 THEN RAISE EXCEPTION 'torn current/history transaction'; END IF;
 RAISE WARNING 'PASS target history-failure rollback';
END $$;
DROP TRIGGER target_test_fail_history ON public.target_resume_versions;
-- Actual Flow B: source-only and same-opportunity collision retain all docs.
DO $$
DECLARE src text := '77000000-0000-4000-8000-000000000003'; dst text := '77000000-0000-4000-8000-000000000004'; tok uuid; r jsonb;
BEGIN
 PERFORM set_config('test.uid',src,false);
 PERFORM public.commit_target_resume_cas(src,'solo',0,pg_temp.target_doc('solo','source-only'));
 PERFORM public.commit_target_resume_cas(src,'both',0,pg_temp.target_doc('both','source-v1'));
 PERFORM public.commit_target_resume_cas(src,'both',1,pg_temp.target_doc('both','source-v2'));
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok := public.mint_merge_grant('target-test@example.invalid');
 PERFORM set_config('test.uid',dst,false);
 PERFORM public.commit_target_resume_cas(dst,'both',0,pg_temp.target_doc('both','target-current'));
 PERFORM set_config('test.jwt','{"email":"target-test@example.invalid"}',false); r := public.redeem_merge_grant(tok);
 IF r->>'merged' <> 'true' THEN RAISE EXCEPTION 'Flow B failed %',r; END IF;
 IF (SELECT doc FROM public.target_resumes WHERE owner_id=dst::uuid AND opportunity_id='solo') <> pg_temp.target_doc('solo','source-only') THEN RAISE EXCEPTION 'source-only lost'; END IF;
 IF (SELECT doc FROM public.target_resumes WHERE owner_id=dst::uuid AND opportunity_id='both') <> pg_temp.target_doc('both','target-current') THEN RAISE EXCEPTION 'target current overwritten'; END IF;
 IF (SELECT revision FROM public.target_resumes WHERE owner_id=dst::uuid AND opportunity_id='both') <> 4 OR (SELECT count(*) FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both') <> 4 THEN RAISE EXCEPTION 'both histories not retained'; END IF;
 IF (SELECT doc FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both' AND revision=2) <> pg_temp.target_doc('both','source-v1') OR (SELECT doc FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both' AND revision=3) <> pg_temp.target_doc('both','source-v2') THEN RAISE EXCEPTION 'imported history docs changed'; END IF;
 IF (SELECT source_revision FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both' AND revision=2) <> 1 OR (SELECT source_updated_at FROM public.target_resume_versions WHERE owner_id=dst::uuid AND opportunity_id='both' AND revision=2) IS NULL THEN RAISE EXCEPTION 'merge origin metadata lost'; END IF;
 r := public.commit_target_resume_cas(dst,'both',1,pg_temp.target_doc('both','old-tab'));
 IF r->>'status' <> 'conflict' THEN RAISE EXCEPTION 'old target tab not conflict'; END IF;
 PERFORM set_config('test.uid',src,false);
 r := public.commit_target_resume_cas(src,'solo',0,pg_temp.target_doc('solo','revived'));
 IF r->>'status' <> 'missing' THEN RAISE EXCEPTION 'merged source resurrected'; END IF;
 RAISE WARNING 'PASS target Flow B source-only/conflict/history/stale CAS';
END $$;
-- Failure inside our trigger rolls the whole actual merge RPC back.
CREATE TRIGGER target_test_fail_history BEFORE INSERT ON public.target_resume_versions FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_target_history();
ALTER TABLE public.target_resume_versions DISABLE TRIGGER target_test_fail_history;
DO $$
DECLARE src text := '77000000-0000-4000-8000-000000000005'; dst text := '77000000-0000-4000-8000-000000000006'; tok uuid; failed boolean := false;
BEGIN
 PERFORM set_config('test.uid',src,false);
 PERFORM public.commit_target_resume_cas(src,'rollback',0,pg_temp.target_doc('rollback','source'));
 PERFORM set_config('test.jwt','{"is_anonymous":true}',false); tok := public.mint_merge_grant('rollback@example.invalid');
 PERFORM set_config('test.uid',dst,false); PERFORM set_config('test.jwt','{"email":"rollback@example.invalid"}',false);
 ALTER TABLE public.target_resume_versions ENABLE TRIGGER target_test_fail_history;
 BEGIN PERFORM public.redeem_merge_grant(tok); EXCEPTION WHEN raise_exception THEN failed := SQLERRM = 'synthetic_history_failure'; END;
 IF NOT failed OR EXISTS(SELECT 1 FROM public.merged_devices WHERE source_device_id=src) OR (SELECT consumed_at FROM public.merge_grants WHERE token=tok) IS NOT NULL OR NOT EXISTS(SELECT 1 FROM public.target_resumes WHERE owner_id=src::uuid) OR EXISTS(SELECT 1 FROM public.target_resumes WHERE owner_id=dst::uuid) THEN RAISE EXCEPTION 'merge partial commit'; END IF;
 RAISE WARNING 'PASS target Flow B trigger-failure atomic rollback';
END $$;
DROP TRIGGER target_test_fail_history ON public.target_resume_versions;
-- Old merged sessions see no rows even if an ops process left a row behind.
INSERT INTO public.target_resumes VALUES ('77000000-0000-4000-8000-000000000003','hidden',1,pg_temp.target_doc('hidden','ops-only'),now());
SET ROLE authenticated;
SELECT set_config('test.uid','77000000-0000-4000-8000-000000000003',false);
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.target_resumes) THEN RAISE EXCEPTION 'merged-away SELECT allowed'; END IF; END $$;
RESET ROLE;
DELETE FROM auth.users WHERE id='77000000-0000-4000-8000-000000000001';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.target_resumes WHERE owner_id='77000000-0000-4000-8000-000000000001') OR EXISTS(SELECT 1 FROM public.target_resume_versions WHERE owner_id='77000000-0000-4000-8000-000000000001') THEN RAISE EXCEPTION 'auth deletion failed to cascade'; END IF;
 RAISE WARNING 'PASS target merged-read guard/auth deletion cascade';
END $$;
