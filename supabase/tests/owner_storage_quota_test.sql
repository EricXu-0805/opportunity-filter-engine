-- Per-account quotas on user-reported PDFs and private imports. Platform stubs
-- (test.uid/test.jwt); no Storage bytes or HTTP.
\set ON_ERROR_STOP on
SET client_min_messages=warning;
INSERT INTO auth.users(id) SELECT ('39000000-0000-4000-8000-'||lpad(n::text,12,'0'))::uuid FROM generate_series(1,8)n;
INSERT INTO auth.sessions(id,user_id) SELECT id,id FROM auth.users WHERE id::text LIKE '39000000-%';
CREATE FUNCTION pg_temp.login(n int) RETURNS text LANGUAGE plpgsql AS $$
DECLARE u text:='39000000-0000-4000-8000-'||lpad(n::text,12,'0');
BEGIN PERFORM set_config('test.uid',u,false); PERFORM set_config('test.jwt',jsonb_build_object('session_id',u,'exp',floor(extract(epoch FROM clock_timestamp()+interval '1 hour')))::text,false); RETURN u; END $$;
-- Event e of owner n: application events use the 'a' namespace, contact 'c'.
CREATE FUNCTION pg_temp.event(n int,e int,kind text DEFAULT 'application') RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE u text:=pg_temp.login(n); id uuid:=('39000000-0000-4000-'||CASE WHEN kind='contact' THEN 'c' ELSE 'a' END||lpad(n::text,3,'0')||'-'||lpad(e::text,12,'0'))::uuid;
BEGIN
 IF kind='contact' THEN PERFORM public.confirm_contact_event(u,id,'opp-'||e,'faculty@example.invalid','Subject','Body','[{"kind":"profile","version":"1"}]','2026-01-01');
 ELSE PERFORM public.confirm_application_event(u,id,'opp-'||e,'web_form','https://example.edu/apply'); END IF;
 RETURN id; END $$;
CREATE FUNCTION pg_temp.stage(n int,e int,bytes bigint DEFAULT 123,kind text DEFAULT 'application') RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE u text:=pg_temp.login(n); ev uuid:=('39000000-0000-4000-'||CASE WHEN kind='contact' THEN 'c' ELSE 'a' END||lpad(n::text,3,'0')||'-'||lpad(e::text,12,'0'))::uuid;
BEGIN
 IF kind='contact' THEN RETURN public.stage_contact_material(u,gen_random_uuid(),gen_random_uuid(),ev,'opp-'||e,'q.pdf',bytes,repeat('a',64)); END IF;
 RETURN public.stage_application_material(u,gen_random_uuid(),gen_random_uuid(),ev,'opp-'||e,'q.pdf',bytes,repeat('a',64));
END $$;
CREATE FUNCTION pg_temp.rejected(n int,e int,bytes bigint DEFAULT 123,kind text DEFAULT 'application') RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_temp.stage(n,e,bytes,kind); RETURN false;
EXCEPTION WHEN program_limit_exceeded THEN
 IF SQLERRM<>'material_quota_exceeded' THEN RAISE; END IF; RETURN true;
END $$;
CREATE FUNCTION pg_temp.target(n int,i int) RETURNS text LANGUAGE sql AS $$ SELECT 'private-import:39000000-0000-4000-b'||lpad(n::text,3,'0')||'-'||lpad(i::text,12,'0') $$;
CREATE FUNCTION pg_temp.payload(body text) RETURNS jsonb LANGUAGE sql AS $$ SELECT jsonb_build_object('source','text_parser','title','Quota','description_raw',body) $$;
CREATE FUNCTION pg_temp.save_refused(n int,i int,revision bigint,body text) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
 PERFORM public.save_private_import_target(pg_temp.login(n),pg_temp.target(n,i),revision,pg_temp.payload(body)); RETURN false;
EXCEPTION WHEN program_limit_exceeded THEN
 IF SQLERRM<>'private_target_quota_exceeded' THEN RAISE; END IF; RETURN true;
END $$;
DO $$BEGIN
 FOR n IN 1..8 LOOP FOR e IN 1..4 LOOP PERFORM pg_temp.event(n,e); PERFORM pg_temp.event(n,e,'contact'); END LOOP; END LOOP;
END$$;
SET ROLE authenticated;

-- Per event: ten live materials, then refusal. The same owner's other event
-- still has room; an exact retry of an existing stage never counts again.
DO $$DECLARE first jsonb; u text; BEGIN
 first:=pg_temp.stage(1,1);
 FOR i IN 2..10 LOOP PERFORM pg_temp.stage(1,1); END LOOP;
 IF NOT pg_temp.rejected(1,1) THEN RAISE EXCEPTION 'eleventh material on one event accepted'; END IF;
 u:=pg_temp.login(1);
 IF public.stage_application_material(u,(first#>>'{artifact,material_id}')::uuid,(first#>>'{artifact,record_id}')::uuid,
   (first#>>'{artifact,application_event_id}')::uuid,'opp-1','q.pdf',123,repeat('a',64))->>'replayed'<>'true' THEN RAISE EXCEPTION 'exact retry refused by quota'; END IF;
 IF pg_temp.rejected(1,2) THEN RAISE EXCEPTION 'event quota leaked to another event'; END IF;
 -- Deleting one frees a live slot on that event.
 PERFORM public.delete_application_material(u,(first#>>'{artifact,record_id}')::uuid,(first#>>'{artifact,material_id}')::uuid,
   (first#>>'{artifact,application_event_id}')::uuid,'opp-1');
 IF pg_temp.rejected(1,1) THEN RAISE EXCEPTION 'deleted material still held a live slot'; END IF;
 RAISE WARNING 'PASS per-event material cap, retry exempt, delete frees a live slot';
END$$;

-- Per owner bytes: four 64 MiB files fill 256 MiB; one more byte is refused,
-- across application and contact kinds alike.
DO $$BEGIN
 PERFORM pg_temp.stage(2,1,67108864); PERFORM pg_temp.stage(2,2,67108864);
 PERFORM pg_temp.stage(2,1,67108864,'contact'); PERFORM pg_temp.stage(2,2,67108864,'contact');
 IF NOT pg_temp.rejected(2,3,1) OR NOT pg_temp.rejected(2,3,1,'contact') THEN RAISE EXCEPTION 'owner byte quota not enforced'; END IF;
 IF pg_temp.rejected(3,1,67108864) THEN RAISE EXCEPTION 'byte quota leaked to another owner'; END IF;
 RAISE WARNING 'PASS per-owner byte quota spans both material kinds';
END$$;

-- Creation churn: 30 new materials per 24 hours, deleted ones included.
DO $$DECLARE r jsonb; u text; BEGIN
 FOR i IN 1..30 LOOP
  r:=pg_temp.stage(4,1+(i%4),123,CASE WHEN i%2=0 THEN 'contact' ELSE 'application' END);
  u:=pg_temp.login(4);
  IF i%2=1 THEN PERFORM public.delete_application_material(u,(r#>>'{artifact,record_id}')::uuid,(r#>>'{artifact,material_id}')::uuid,(r#>>'{artifact,application_event_id}')::uuid,'opp-'||(1+(i%4)));
  ELSE PERFORM public.delete_contact_material(u,(r#>>'{artifact,record_id}')::uuid,(r#>>'{artifact,material_id}')::uuid,(r#>>'{artifact,contact_event_id}')::uuid,'opp-'||(1+(i%4))); END IF;
 END LOOP;
 IF NOT pg_temp.rejected(4,1) THEN RAISE EXCEPTION 'delete/re-upload churn unbounded'; END IF;
 RAISE WARNING 'PASS daily creation cap counts deleted materials';
END$$;
RESET ROLE;
DO $$BEGIN
 IF (SELECT count(*) FROM public.material_artifacts WHERE owner_id='39000000-0000-4000-8000-000000000001' AND status<>'deleted')<>11 THEN RAISE EXCEPTION 'refused stage left a row'; END IF;
END$$;

-- Per owner count: 100 live materials (older than a day, so the churn cap is
-- not what refuses the next one).
INSERT INTO public.material_artifacts(material_id,record_id,owner_id,artifact_kind,application_event_id,opportunity_id,status,filename,byte_length,declared_sha256,created_at,expires_at,stage_token,stage_session_id,authorized_until)
SELECT gen_random_uuid(),gen_random_uuid(),'39000000-0000-4000-8000-000000000005','application',gen_random_uuid(),'old','staged','old.pdf',1,repeat('a',64),now()-interval '3 days',now()+interval '1 day',gen_random_uuid(),'39000000-0000-4000-8000-000000000005',now()+interval '1 hour' FROM generate_series(1,99);
SET ROLE authenticated;
DO $$BEGIN
 PERFORM pg_temp.stage(5,1);
 IF NOT pg_temp.rejected(5,2) THEN RAISE EXCEPTION 'owner live count quota not enforced'; END IF;
 RAISE WARNING 'PASS per-owner live material count';
END$$;

-- Private imports: 200 live targets per owner; updates of an existing one and
-- a slot freed by deletion still work.
DO $$DECLARE u text:=pg_temp.login(6); BEGIN
 FOR i IN 1..200 LOOP PERFORM public.save_private_import_target(u,pg_temp.target(6,i),0,pg_temp.payload('body '||i)); END LOOP;
 IF NOT pg_temp.save_refused(6,201,0,'one more') THEN RAISE EXCEPTION 'private target count quota not enforced'; END IF;
 IF pg_temp.save_refused(6,1,1,'edited') THEN RAISE EXCEPTION 'update of an existing target refused'; END IF;
 PERFORM public.delete_private_import_target(u,pg_temp.target(6,2),1);
 IF pg_temp.save_refused(6,201,0,'after delete') THEN RAISE EXCEPTION 'deleted target still held a slot'; END IF;
 IF pg_temp.save_refused(7,1,0,'other owner') THEN RAISE EXCEPTION 'count quota leaked to another owner'; END IF;
 RAISE WARNING 'PASS private import live count quota';
END$$;

-- Private import bytes: incompressible ~5 MB bodies are refused long before
-- the count cap, and the stored total stays within 64 MiB.
DO $$DECLARE body text; refused_at int; BEGIN
 SELECT string_agg(md5(random()::text||g::text),'') INTO body FROM generate_series(1,150000)g;
 FOR i IN 1..30 LOOP
  IF pg_temp.save_refused(8,i,0,left(body,4800000-i)||i) THEN refused_at:=i; EXIT; END IF;
 END LOOP;
 IF refused_at IS NULL THEN RAISE EXCEPTION 'private target byte quota not enforced (%)',refused_at; END IF;
 RAISE WARNING 'PASS private import byte quota (refused save %)',refused_at;
END$$;
RESET ROLE;
DO $$BEGIN
 IF (SELECT sum(pg_column_size(opportunity)) FROM public.private_import_targets WHERE owner_id='39000000-0000-4000-8000-000000000008')>67108864 THEN RAISE EXCEPTION 'stored bytes over quota'; END IF;
END$$;
