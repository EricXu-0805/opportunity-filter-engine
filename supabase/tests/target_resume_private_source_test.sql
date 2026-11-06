\set ON_ERROR_STOP on
SET client_min_messages = warning;
\i :fixture_path
-- A private résumé draft (context_version 5) with the browser's manual record (provenance V1).
CREATE FUNCTION pg_temp.private_doc(marker text) RETURNS jsonb LANGUAGE sql AS $$
 SELECT jsonb_set(pg_temp.prov_doc('private-import:a2000000-0000-4000-8000-000000000001',marker),'{target_snapshot}',
  jsonb_build_object('context_version',5,'opportunity_id','private-import:a2000000-0000-4000-8000-000000000001',
   'title','Private research note','organization','','source_url','','description',E'Study parsers and research tools.\r\n完整原文 😀',
   'requirements','[]'::jsonb,'private_source',jsonb_build_object('version',1,'purpose','resume','target_scope','private_import',
    'verification','unverified','owner_id','45000000-0000-4000-8000-000000000001','revision',1,
    'source_version','pit1:'||encode(sha256(convert_to('{"id":"private-import:a2000000-0000-4000-8000-000000000001","owner_id":"45000000-0000-4000-8000-000000000001","revision":1}','UTF8')),'hex'),
    'import_source',null)));
$$;
INSERT INTO auth.users(id) VALUES ('45000000-0000-4000-8000-000000000001'),('45000000-0000-4000-8000-000000000002');
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000001',false);
DO $$
DECLARE u text:='45000000-0000-4000-8000-000000000001'; target text:='private-import:a2000000-0000-4000-8000-000000000001';
 d jsonb:=pg_temp.private_doc('私有手改🧪'); p jsonb; r jsonb; edited jsonb; v integer;
BEGIN
 p:=pg_temp.prov(d,'private-manual');
 r:=public.commit_target_resume_with_provenance_cas(u,target,0,d,p);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->'doc'=d AND r->'provenance'=p,'private V1 exact save');
 PERFORM pg_temp.require((SELECT doc=d AND provenance=p FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id=target),'private current pair');
 PERFORM pg_temp.require((SELECT doc=d AND provenance=p FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id=target AND revision=1),'private history pair');
 r:=public.commit_target_resume_with_provenance_cas(u,target,0,d,p);
 PERFORM pg_temp.require(r->>'status'='unchanged','private same-pair retry');
 edited:=pg_temp.private_doc('second manual edit');
 r:=public.commit_target_resume_with_provenance_cas(u,target,1,edited,pg_temp.prov(edited,'private-second'));
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='2','private second version');
 r:=public.commit_target_resume_with_provenance_cas(u,target,2,d,p);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='3' AND r->'doc'=d AND r->'provenance'=p,'private historical restore');
 RAISE WARNING 'PASS private context 5 draft with a V1 manual record saves, retries, versions and restores exactly';
 FOREACH v IN ARRAY ARRAY[2,3,4] LOOP
  PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{version}',to_jsonb(v)),'V'||v||' does not bind a private context 5 draft');
 END LOOP;
 RAISE WARNING 'PASS provenance V2-V4 refuse a private context 5 draft';
END $$;
SET ROLE authenticated;
DO $$ BEGIN
 PERFORM pg_temp.require((SELECT count(*)=1 FROM public.target_resumes),'owner reads its private draft');
 PERFORM set_config('test.uid','45000000-0000-4000-8000-000000000002',false);
 PERFORM pg_temp.require((SELECT count(*)=0 FROM public.target_resumes),'other account cannot read the private current draft');
 PERFORM pg_temp.require((SELECT count(*)=0 FROM public.target_resume_versions),'other account cannot read the private history');
 BEGIN
  PERFORM public.commit_target_resume_with_provenance_cas('45000000-0000-4000-8000-000000000001',
    'private-import:a2000000-0000-4000-8000-000000000001',3,pg_temp.private_doc('foreign'),NULL);
  RAISE EXCEPTION 'foreign private write unexpectedly succeeded';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS private drafts stay owner-isolated';
END $$;
RESET ROLE;
