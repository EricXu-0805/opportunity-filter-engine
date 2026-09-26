\set ON_ERROR_STOP on
SET client_min_messages = warning;
\i :fixture_path
INSERT INTO auth.users(id) VALUES ('45000000-0000-4000-8000-000000000001');
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000001',false);
DO $$
DECLARE u text:='45000000-0000-4000-8000-000000000001'; d jsonb; p jsonb; r jsonb; p2 jsonb; v jsonb; q jsonb;
BEGIN
 d:=jsonb_set(pg_temp.prov_doc('research','原文简写🧪'),'{target_snapshot}','{"context_version":3}'::jsonb);
 p:=jsonb_set(pg_temp.prov(d,'paper-edit'),'{version}','2'::jsonb);
 p:=jsonb_set(p,'{events,0,kind}','"ai_rewrite"'::jsonb);
 p:=jsonb_set(p,'{events,0,changes,0,target_evidence}','[
  {"field":"paper_title","paper_index":0,"start":0,"end":3,"quote":"论文🧪"},
  {"field":"paper_abstract","paper_index":1,"start":4,"end":8,"quote":"具体方法"},
  {"field":"description","requirement_index":null,"start":0,"end":2,"quote":"研究"},
  {"field":"requirement","requirement_index":0,"start":0,"end":6,"quote":"Python"}]'::jsonb);
 r:=public.commit_target_resume_with_provenance_cas(u,'research',0,d,p);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->'doc'=d AND r->'provenance'=p,'v2 create exact pair');
 PERFORM pg_temp.require((SELECT provenance=p AND doc=d FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id='research'),'v2 current exact');
 PERFORM pg_temp.require((SELECT provenance=p AND doc=d FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='research' AND revision=1),'v2 history exact');
 RAISE WARNING 'PASS research V2 mixed target quote shapes and Unicode survive current/history/CAS';
 r:=public.commit_target_resume_with_provenance_cas(u,'research',0,d,p);
 PERFORM pg_temp.require(r->>'status'='unchanged' AND r->'provenance'=p,'v2 uncertain retry exact');
 p2:=jsonb_set(p,'{events,0,id}','"second-record"'::jsonb);
 r:=public.commit_target_resume_with_provenance_cas(u,'research',1,d,p2);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='2','changed record new revision');
 r:=public.commit_target_resume_with_provenance_cas(u,'research',1,d,p);
 PERFORM pg_temp.require(r->>'status'='conflict' AND r->'provenance'=p2,'stale research pair conflicts');
 RAISE WARNING 'PASS research V2 retry/no-op/record-only revision/conflict retain winning pair';
 r:=public.commit_target_resume_with_provenance_cas(u,'research',2,d,p);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='3' AND r->'provenance'=p,'restore exact historical research pair');
 PERFORM pg_temp.require((SELECT count(*)=3 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='research'),'restore appends history');
 RAISE WARNING 'PASS research historical pair restores by new CAS revision without rewriting old provenance';
 r:=public.commit_target_resume_cas(u,'research',2,d);
 PERFORM pg_temp.require(r->>'status'='unchanged' AND r->'provenance'=p,'old RPC retry preserves v2');
 r:=public.commit_target_resume_cas(u,'research',3,d);
 PERFORM pg_temp.require(r->>'status'='unchanged' AND r->'provenance'=p,'old RPC noop preserves v2');
 d:=jsonb_set(d,'{document,sections,0,blocks,0,lines,0,text}','"legacy edit"'::jsonb);
 r:=public.commit_target_resume_cas(u,'research',3,d);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->'provenance'='null'::jsonb,'old real edit clears v2');
 PERFORM pg_temp.require((SELECT provenance=p FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='research' AND revision=3),'old edit preserves prior v2 history');
 RAISE WARNING 'PASS legacy RPC keeps V2 metadata on retry/no-op and clears it only on changed document';
 -- All later invalid writes must leave the exact winning current/history pair alone.
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{version}','1'::jsonb),'paper shapes unavailable in v1');
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{version}','3'::jsonb),'unknown v3 sidecar');
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{version}','"2"'::jsonb),'string sidecar version');
 PERFORM pg_temp.reject_prov(jsonb_set(d,'{target_snapshot,context_version}','2'::jsonb),p,'v2 sidecar cannot bind v2 target');
 PERFORM pg_temp.reject_prov(jsonb_set(d,'{target_snapshot}','{}'::jsonb),p,'v2 sidecar cannot bind legacy target');
 RAISE WARNING 'PASS research sidecar version and target-context compatibility are explicit';
 q:=p#>'{events,0,changes,0,target_evidence,0}';
 FOREACH v IN ARRAY ARRAY[q-'paper_index',q||'{"paper_index":null}'::jsonb,q||'{"paper_index":true}'::jsonb,
 q||'{"paper_index":-1}'::jsonb,q||'{"paper_index":0.5}'::jsonb,q||'{"paper_index":9007199254740992}'::jsonb,
 q||'{"requirement_index":null}'::jsonb,q||'{"field":"paper_full_text"}'::jsonb,q||'{"start":3}'::jsonb,
 q||'{"quote":" "}'::jsonb,q||'{"end":"3"}'::jsonb] LOOP
  PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{events,0,changes,0,target_evidence,0}',v),'malformed paper quote');
 END LOOP;
 RAISE WARNING 'PASS research quotes reject mixed keys/unknown kind/bad indices/unsafe ranges/blank quotes';
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{events,0,changes,0,target_evidence,2,paper_index}','0'::jsonb),'paper index on old description shape');
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{events,0,changes,0,target_evidence,3,requirement_index}','null'::jsonb),'old requirement index remains required');
 p2:=jsonb_set(p,'{events,0,changes,0,target_evidence}','[]'::jsonb);
 p2:=jsonb_set(p2,'{version}','1'::jsonb);
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,p2),'v1 no-paper record remains readable on v3 target');
 PERFORM pg_temp.require(private.target_resume_provenance_valid(pg_temp.prov_doc('old','old'),pg_temp.prov(pg_temp.prov_doc('old','old'),'old-record')),'original v1 record unchanged');
 RAISE WARNING 'PASS old quote schema and V1 provenance validation remain compatible';
 p2:=jsonb_set(p,'{events,0,kind}','"manual"'::jsonb);
 PERFORM pg_temp.reject_prov(d,p2,'manual cannot acquire AI target quotes');
 PERFORM pg_temp.reject_prov(d,p||'{"server_verified":true}'::jsonb,'no implied server attestation');
 PERFORM pg_temp.require((SELECT provenance IS NULL AND doc=d FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id='research'),'invalid mutations preserve winning current pair');
 PERFORM pg_temp.require((SELECT count(*)=4 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='research'),'invalid mutations do not append history');
 RAISE WARNING 'PASS invalid research records leave prior current/history unchanged and cannot claim server verification';
END $$;
