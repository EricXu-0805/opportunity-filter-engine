\set ON_ERROR_STOP on
-- Run against the old schema. Caller supplies the exact new migration path.
-- All fixtures and the migration roll back, so this can run after old-schema
-- regression suites without changing the following comparison phase.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
INSERT INTO auth.users(id,is_anonymous) VALUES('36000000-0000-4000-8000-000000999901',false);
INSERT INTO auth.sessions(id,user_id) VALUES('36000000-0000-4000-8000-000000999901','36000000-0000-4000-8000-000000999901');
DO $$DECLARE u text:='36000000-0000-4000-8000-000000999901';r jsonb;BEGIN
 PERFORM set_config('test.uid',u,true);
 PERFORM set_config('test.jwt',jsonb_build_object('session_id',u,'exp',floor(extract(epoch FROM now()+interval '1 hour')))::text,true);
 PERFORM public.confirm_application_event(u,u::uuid,'migration-compat','web_form','https://example.invalid/apply');
 FOR n IN 1..3 LOOP
  r:=public.stage_application_material(u,('36000000-0000-4000-9000-00000099990'||n)::uuid,('36000000-0000-4000-a000-00000099990'||n)::uuid,u::uuid,'migration-compat','existing.pdf',123,repeat('a',64));
  IF n=1 THEN PERFORM public.finalize_application_material(u::uuid,u::uuid,(r#>>'{artifact,material_id}')::uuid,(r#>>'{upload,stage_token}')::uuid,123,repeat('a',64)); END IF;
  IF n=3 THEN PERFORM public.delete_application_material(u,(r#>>'{artifact,record_id}')::uuid,(r#>>'{artifact,material_id}')::uuid,u::uuid,'migration-compat'); END IF;
 END LOOP;
 PERFORM public.delete_application_material(u,'36000000-0000-4000-a000-000000999904','36000000-0000-4000-9000-000000999904',u::uuid,'migration-compat');
END$$;
CREATE TEMP TABLE before_material_migration AS SELECT material_id,private.material_json(a) AS receipt,stage_token FROM public.material_artifacts a;

\i :contact_migration
DO $$DECLARE u text:='36000000-0000-4000-8000-000000999901'; r jsonb;BEGIN
 IF EXISTS(SELECT 1 FROM before_material_migration b JOIN public.material_artifacts a USING(material_id) WHERE b.receipt IS DISTINCT FROM private.material_json(a) OR a.artifact_kind IS DISTINCT FROM 'application' OR a.contact_event_id IS NOT NULL) THEN RAISE EXCEPTION 'migration changed application receipts or identities'; END IF;
 r:=public.finalize_application_material(u::uuid,u::uuid,'36000000-0000-4000-9000-000000999902',(SELECT stage_token FROM before_material_migration WHERE material_id='36000000-0000-4000-9000-000000999902'),123,repeat('a',64));
 IF r#>>'{artifact,status}'<>'ready' OR r->'artifact' ? 'artifact_kind' OR r->'artifact' ? 'contact_event_id' THEN RAISE EXCEPTION 'pre-migration pending upload broken'; END IF;
 r:=public.stage_application_material(u,'36000000-0000-4000-9000-000000999903','36000000-0000-4000-a000-000000999903',u::uuid,'migration-compat','existing.pdf',123,repeat('a',64));
 IF r->'artifact' IS DISTINCT FROM (SELECT receipt FROM before_material_migration WHERE material_id='36000000-0000-4000-9000-000000999903') OR r->'upload'<>'null'::jsonb THEN RAISE EXCEPTION 'pre-migration cancellation revived'; END IF;
 IF public.delete_application_material(u,'36000000-0000-4000-a000-000000999901','36000000-0000-4000-9000-000000999901',u::uuid,'migration-compat')#>>'{artifact,status}'<>'deleted' THEN RAISE EXCEPTION 'pre-migration archive deletion broken'; END IF;
 r:=public.stage_application_material(u,'36000000-0000-4000-9000-000000999904','36000000-0000-4000-a000-000000999904',u::uuid,'migration-compat','late.pdf',123,repeat('a',64));
 IF r->'artifact' IS DISTINCT FROM (SELECT receipt FROM before_material_migration WHERE material_id='36000000-0000-4000-9000-000000999904') OR r->'upload'<>'null'::jsonb
   OR r#>'{artifact,recorded_at}'<>'null'::jsonb THEN RAISE EXCEPTION 'old unknown-stage cancellation revived or fabricated association'; END IF;
 r:=public.finalize_application_material(u::uuid,u::uuid,'36000000-0000-4000-9000-000000999904',gen_random_uuid(),123,repeat('a',64));
 IF r->'artifact' IS DISTINCT FROM (SELECT receipt FROM before_material_migration WHERE material_id='36000000-0000-4000-9000-000000999904') THEN RAISE EXCEPTION 'late finalize changed old cancellation'; END IF;
 PERFORM public.confirm_contact_event(u,u::uuid,'migration-compat','faculty@example.invalid','Same event UUID','Separate contact body');
 FOR n IN 1..4 LOOP
  BEGIN PERFORM public.stage_contact_material(u,('36000000-0000-4000-9000-00000099990'||n)::uuid,('36000000-0000-4000-a000-00000099990'||n)::uuid,u::uuid,'migration-compat','existing.pdf',123,repeat('a',64)); RAISE EXCEPTION 'contact claimed old application archive'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'contact_material_conflict' THEN RAISE; END IF; END;
  BEGIN PERFORM public.delete_contact_material(u,('36000000-0000-4000-a000-00000099990'||n)::uuid,('36000000-0000-4000-9000-00000099990'||n)::uuid,u::uuid,'migration-compat'); RAISE EXCEPTION 'contact cancelled old application archive'; EXCEPTION WHEN unique_violation THEN IF SQLERRM<>'contact_material_conflict' THEN RAISE; END IF; END;
 END LOOP;
 IF public.list_contact_materials(u,u::uuid,'migration-compat')->'items'<>'[]'::jsonb THEN RAISE EXCEPTION 'old application archives appeared as contact records'; END IF;
 RAISE NOTICE 'PASS same-database upgrade: unchanged old receipts/keys, pending token finalize, ready deletion, unknown cancellation/late finalize and crossed-kind rejection';
END$$;
ROLLBACK;
