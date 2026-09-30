-- Runs against the full migration chain inside its own rollback; all sources
-- are synthetic and no HTTP occurs.
\set ON_ERROR_STOP on
BEGIN;
INSERT INTO auth.users(id,is_anonymous) VALUES
 ('a1000000-0000-4000-8000-000000000001',false),('a1000000-0000-4000-8000-000000000002',false),
 ('a1000000-0000-4000-8000-000000000003',true),('a1000000-0000-4000-8000-000000000004',false);
INSERT INTO auth.sessions(id,user_id) SELECT replace(id::text,'a1000000','a3000000')::uuid,id FROM auth.users WHERE id::text LIKE 'a1000000-%';
CREATE FUNCTION pg_temp.set_owner(n text) RETURNS void LANGUAGE sql AS $$
 SELECT set_config('test.uid','a1000000-0000-4000-8000-'||lpad(n,12,'0'),false);
 SELECT set_config('test.jwt',jsonb_build_object('session_id','a3000000-0000-4000-8000-'||lpad(n,12,'0'),'exp',extract(epoch from now()+interval '1 hour')::bigint)::text,false);
$$;
CREATE FUNCTION pg_temp.expect_error(statement text, expected text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE actual text;
BEGIN
 BEGIN EXECUTE statement; EXCEPTION WHEN OTHERS THEN GET STACKED DIAGNOSTICS actual=RETURNED_SQLSTATE; END;
 IF actual IS DISTINCT FROM expected THEN RAISE EXCEPTION 'expected SQLSTATE %, actual %',expected,actual; END IF;
END; $$;
CREATE FUNCTION pg_temp.payload() RETURNS jsonb LANGUAGE sql AS $$
 SELECT jsonb_build_object('source','text_parser','title','Private original','description_raw','GPA < 3.0 needs review; scores > 80 preferred. END 私人正文',
 'source_url','','url','','extra_fields',jsonb_build_object('description_source','pasted_text','ai_input_scope','full_source','llm_enriched',true,
 'suggested_skills',jsonb_build_array('InventedSkill'),'target_truth',jsonb_build_object('actionable',true)));
$$;
SET ROLE authenticated;
SELECT pg_temp.set_owner('1');
DO $$ DECLARE r jsonb; retry jsonb; BEGIN
 r:=public.save_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001',0,pg_temp.payload());
 IF r->'target'->'opportunity' IS DISTINCT FROM pg_temp.payload() OR r->'target'->>'revision'<>'1' OR r->>'replayed'<>'false' THEN RAISE EXCEPTION 'create roundtrip'; END IF;
 retry:=public.save_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001',0,pg_temp.payload());
 IF retry->'target' IS DISTINCT FROM r->'target' OR retry->>'replayed'<>'true' THEN RAISE EXCEPTION 'exact retry'; END IF;
 IF (public.read_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001'))->'target' IS DISTINCT FROM r->'target' THEN RAISE EXCEPTION 'read'; END IF;
 RAISE NOTICE 'PASS create/read/full original/exact retry';
END $$;
SELECT pg_temp.expect_error($q$SELECT public.save_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001',0,pg_temp.payload()||'{"title":"stale"}')$q$,'23505');
SELECT public.save_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001',1,pg_temp.payload()||'{"title":"Updated"}');
SELECT pg_temp.expect_error($q$SELECT * FROM public.private_import_targets$q$,'42501');
SELECT pg_temp.expect_error($q$UPDATE public.private_import_targets SET revision=9$q$,'42501');
SELECT pg_temp.expect_error($q$DELETE FROM public.private_import_targets$q$,'42501');
DO $$ BEGIN RAISE NOTICE 'PASS CAS conflict/update/no direct table privileges'; END $$;
SELECT pg_temp.set_owner('2');
DO $$ BEGIN
 IF public.read_private_import_target('a1000000-0000-4000-8000-000000000002','private-import:a2000000-0000-4000-8000-000000000001')->'target' <> 'null'::jsonb THEN RAISE EXCEPTION 'cross owner leaked'; END IF;
 IF public.list_private_import_targets('a1000000-0000-4000-8000-000000000002')->'items'<>'[]'::jsonb THEN RAISE EXCEPTION 'list owner leak'; END IF;
END $$;
SELECT pg_temp.expect_error($q$SELECT public.save_private_import_target('a1000000-0000-4000-8000-000000000002','private-import:a2000000-0000-4000-8000-000000000001',0,pg_temp.payload())$q$,'P0002');
SELECT pg_temp.expect_error($q$SELECT public.delete_private_import_target('a1000000-0000-4000-8000-000000000002','private-import:a2000000-0000-4000-8000-000000000001',2)$q$,'P0002');
SELECT pg_temp.expect_error($q$SELECT public.read_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001')$q$,'42501');
DO $$ BEGIN RAISE NOTICE 'PASS cross-owner indistinguishable/mismatched owner'; END $$;
SELECT pg_temp.set_owner('3');
SELECT pg_temp.expect_error($q$SELECT public.list_private_import_targets('a1000000-0000-4000-8000-000000000003')$q$,'42501');
SELECT pg_temp.set_owner('1');
SELECT set_config('test.jwt','{"session_id":"a3000000-0000-4000-8000-000000000099","exp":9999999999}',false);
SELECT pg_temp.expect_error($q$SELECT public.list_private_import_targets('a1000000-0000-4000-8000-000000000001')$q$,'42501');
SELECT set_config('test.jwt','{"session_id":"a3000000-0000-4000-8000-000000000001","exp":1}',false);
SELECT pg_temp.expect_error($q$SELECT public.list_private_import_targets('a1000000-0000-4000-8000-000000000001')$q$,'42501');
SELECT pg_temp.set_owner('1');
DO $$ BEGIN RAISE NOTICE 'PASS anonymous/revoked session/expired token'; END $$;
DO $$ DECLARE value jsonb; i int; BEGIN
 value:=pg_temp.payload();
 FOR i IN 1..34 LOOP value:=jsonb_build_object('nested',value); END LOOP;
 PERFORM pg_temp.expect_error(format('SELECT public.save_private_import_target(%L,%L,0,%L::jsonb)','a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000099',(pg_temp.payload()||jsonb_build_object('extra_fields',value))::text),'22023');
 PERFORM pg_temp.expect_error(format('SELECT public.save_private_import_target(%L,%L,0,%L::jsonb)','a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000099',(pg_temp.payload()||jsonb_build_object('extra_fields',jsonb_build_object('large',repeat('x',262145))))::text),'54000');
 PERFORM pg_temp.expect_error(format('SELECT public.save_private_import_target(%L,%L,0,%L::jsonb)','a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000099',(pg_temp.payload()||jsonb_build_object('description_raw',repeat('x',5242881)))::text),'54000');
 RAISE NOTICE 'PASS source shape/depth/explicit field budgets';
END $$;
SELECT pg_temp.expect_error($q$SELECT public.save_private_import_target('a1000000-0000-4000-8000-000000000001','public-id',0,pg_temp.payload())$q$,'22023');
SELECT pg_temp.expect_error($q$SELECT public.save_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000099',0,pg_temp.payload()||'{"source":"faculty"}')$q$,'22023');
SELECT public.save_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000002',0,pg_temp.payload());
DO $$ DECLARE first_page jsonb; second_page jsonb; BEGIN
 first_page:=public.list_private_import_targets('a1000000-0000-4000-8000-000000000001',NULL,NULL,1);
 IF jsonb_array_length(first_page->'items')<>1 OR first_page->'next_cursor'='null'::jsonb OR first_page->'items'->0 ? 'opportunity' THEN RAISE EXCEPTION 'list summary'; END IF;
 second_page:=public.list_private_import_targets('a1000000-0000-4000-8000-000000000001',(first_page->'next_cursor'->>'updated_at')::timestamptz,first_page->'next_cursor'->>'id',1);
 IF jsonb_array_length(second_page->'items')<>1 OR second_page->'items'->0->>'id'=first_page->'items'->0->>'id' THEN RAISE EXCEPTION 'pagination lost record'; END IF;
 RAISE NOTICE 'PASS summary list bounded/pagination';
END $$;
DO $$ DECLARE r jsonb; retry jsonb; BEGIN
 r:=public.delete_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001',2);
 retry:=public.delete_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001',2);
 IF r->'target'->'opportunity'<>'null'::jsonb OR r->'target'->'deleted_at'='null'::jsonb OR retry->'target'<>r->'target' OR retry->>'replayed'<>'true' THEN RAISE EXCEPTION 'delete'; END IF;
 RAISE NOTICE 'PASS tombstone clears source/exact delete retry';
END $$;
SELECT pg_temp.expect_error($q$SELECT public.save_private_import_target('a1000000-0000-4000-8000-000000000001','private-import:a2000000-0000-4000-8000-000000000001',3,pg_temp.payload())$q$,'55000');
RESET ROLE;
SELECT pg_temp.set_owner('2');
INSERT INTO public.merged_devices VALUES('a1000000-0000-4000-8000-000000000001','a1000000-0000-4000-8000-000000000002');
SET ROLE authenticated;
DO $$ DECLARE r jsonb; BEGIN
 r:=public.read_private_import_target('a1000000-0000-4000-8000-000000000002','private-import:a2000000-0000-4000-8000-000000000002');
 IF r->'target'->>'owner_id'<>'a1000000-0000-4000-8000-000000000002' OR r->'target'->'opportunity'<>pg_temp.payload() THEN RAISE EXCEPTION 'merge failed'; END IF;
END $$;
SELECT pg_temp.set_owner('1');
SELECT pg_temp.expect_error($q$SELECT public.list_private_import_targets('a1000000-0000-4000-8000-000000000001')$q$,'42501');
DO $$ BEGIN RAISE NOTICE 'PASS proof-bound merge preservation/retired account refusal'; END $$;
RESET ROLE;
-- Catalog ACL probes avoid cross-role execution of pg_temp helpers. The first
-- native run crashed in that harness path on local PG17.6; do not rerun it.
DO $$ DECLARE signature text; role_name text; BEGIN
 FOREACH signature IN ARRAY ARRAY[
 'public.save_private_import_target(text,text,bigint,jsonb)',
 'public.read_private_import_target(text,text)',
 'public.delete_private_import_target(text,text,bigint)',
 'public.list_private_import_targets(text,timestamp with time zone,text,integer)',
 'private.save_private_import_target(text,text,bigint,jsonb)',
 'private.read_private_import_target(text,text)',
 'private.delete_private_import_target(text,text,bigint)',
 'private.list_private_import_targets(text,timestamp with time zone,text,integer)'] LOOP
  FOREACH role_name IN ARRAY ARRAY['anon','service_role'] LOOP
   IF has_function_privilege(role_name,signature,'EXECUTE') THEN RAISE EXCEPTION 'unintended RPC execute grant'; END IF;
  END LOOP;
  IF NOT has_function_privilege('authenticated',signature,'EXECUTE') THEN RAISE EXCEPTION 'missing authenticated RPC grant'; END IF;
 END LOOP;
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  IF has_table_privilege(role_name,'public.private_import_targets','SELECT,INSERT,UPDATE,DELETE') THEN RAISE EXCEPTION 'unintended direct table grant'; END IF;
 END LOOP;
END $$;
DELETE FROM auth.users WHERE id='a1000000-0000-4000-8000-000000000002';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.private_import_targets WHERE owner_id='a1000000-0000-4000-8000-000000000002') THEN RAISE EXCEPTION 'delete cascade'; END IF;
 RAISE NOTICE 'PASS ACL and actual account deletion';
END $$;
ROLLBACK;
