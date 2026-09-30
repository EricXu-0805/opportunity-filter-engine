\set ON_ERROR_STOP on
-- This targeted catalog audit is NOT a replacement for Supabase Advisors.
DO $$
DECLARE row record; name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['public.target_resumes','public.target_resume_versions'] LOOP
  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid=name::regclass)
    OR NOT has_table_privilege('authenticated',name,'SELECT')
    OR has_table_privilege('authenticated',name,'INSERT,UPDATE,DELETE,TRUNCATE')
    OR has_table_privilege('anon',name,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
  THEN RAISE EXCEPTION 'unexpected table ACL/RLS: %',name; END IF;
 END LOOP;
 FOR row IN SELECT p.oid,n.nspname,p.proname,p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE (n.nspname='private' AND p.proname IN ('commit_target_resume_cas','commit_target_resume_with_provenance_cas','commit_target_resume_pair','merge_target_resumes'))
     OR (n.nspname='public' AND p.proname IN ('commit_target_resume_cas','commit_target_resume_with_provenance_cas')) LOOP
  IF row.prosecdef IS DISTINCT FROM (row.nspname='private') OR row.proconfig IS DISTINCT FROM ARRAY['search_path=""']
    OR has_function_privilege('anon',row.oid,'EXECUTE') THEN RAISE EXCEPTION 'unexpected function security: %.%',row.nspname,row.proname; END IF;
 END LOOP;
 IF has_function_privilege('authenticated','private.commit_target_resume_pair(text,text,bigint,jsonb,jsonb,boolean)','EXECUTE')
   OR has_function_privilege('service_role','private.commit_target_resume_pair(text,text,bigint,jsonb,jsonb,boolean)','EXECUTE')
   OR has_function_privilege('authenticated','private.merge_target_resumes()','EXECUTE') THEN RAISE EXCEPTION 'internal function directly executable'; END IF;
 IF (SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename IN ('target_resumes','target_resume_versions') AND roles=ARRAY['authenticated']::name[] AND cmd='SELECT' AND qual LIKE '%auth.uid()%' AND qual LIKE '%target_resume_owner_active%')<>2 THEN RAISE EXCEPTION 'owner policies changed'; END IF;
 RAISE WARNING 'PASS targeted SQL ACL/SECURITY/search_path/RLS catalog audit (not Supabase Advisors)';
END $$;
