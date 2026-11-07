\set ON_ERROR_STOP on
SET client_min_messages = warning;
\i :fixture_path
CREATE FUNCTION pg_temp.generation_record(pipeline text DEFAULT 'full-target-v6') RETURNS jsonb LANGUAGE sql AS $$
 SELECT jsonb_build_object('version','target-resume-generation-v1:'||repeat('a',64),'pipeline_version',pipeline,
  'document_signature','v1:sha256:'||repeat('d',64),'request_ids',jsonb_build_array('request-one','request-two'));
$$;
CREATE FUNCTION pg_temp.generation_prov(doc jsonb) RETURNS jsonb LANGUAGE sql AS $$
 SELECT jsonb_set(jsonb_set(jsonb_set(pg_temp.prov(doc,'generated'),'{version}','4'::jsonb),
  '{events,0,kind}','"ai_rewrite"'::jsonb),'{events,0,generation}',pg_temp.generation_record());
$$;
INSERT INTO auth.users(id) VALUES ('45000000-0000-4000-8000-000000000001'),('45000000-0000-4000-8000-000000000002');
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000001',false);
DO $$
DECLARE u text:='45000000-0000-4000-8000-000000000001'; d jsonb; p jsonb; r jsonb; p2 jsonb; bad jsonb; atom jsonb; q jsonb; key text;
BEGIN
 d:=jsonb_set(pg_temp.prov_doc('generation','已接受的改写🧪'),'{target_snapshot}','{"context_version":4}'::jsonb);
 p:=pg_temp.generation_prov(d);
 p:=jsonb_set(p,'{events,0,changes,0,check}',jsonb_build_object('version','target-resume-source-checks-v6',
  'pipeline_version','full-target-v6','request_id','request-one','document_signature','v1:sha256:'||repeat('d',64),
  'original','原文🧪','evidence',jsonb_build_object('kind','experience','id','e','revision',1)));
 r:=public.commit_target_resume_with_provenance_cas(u,'generation',0,d,p);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->'provenance'=p AND r->'doc'=d,'v4 exact save');
 PERFORM pg_temp.require((SELECT provenance=p FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id='generation'),'v4 current');
 PERFORM pg_temp.require((SELECT provenance=p FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='generation' AND revision=1),'v4 history');
 RAISE WARNING 'PASS V4 generation and review metadata survive exact current/history persistence';
 p2:=jsonb_set(p,'{events,0,generation,version}',to_jsonb('target-resume-generation-v1:'||repeat('b',64)));
 r:=public.commit_target_resume_with_provenance_cas(u,'generation',1,d,p2);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='2' AND r->'provenance'=p2,'config-only new revision');
 r:=public.commit_target_resume_with_provenance_cas(u,'generation',1,d,p2);
 PERFORM pg_temp.require(r->>'status'='unchanged' AND r->'provenance'=p2,'uncertain retry exact');
 r:=public.commit_target_resume_with_provenance_cas(u,'generation',1,d,p);
 PERFORM pg_temp.require(r->>'status'='conflict' AND r->'provenance'=p2,'stale config loses');
 r:=public.commit_target_resume_with_provenance_cas(u,'generation',2,d,p);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->>'revision'='3' AND r->'provenance'=p,'restore original config without relabeling');
 PERFORM pg_temp.require((SELECT provenance=p2 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id='generation' AND revision=2),'intermediate history unchanged');
 RAISE WARNING 'PASS V4 metadata-only CAS, retry, conflict and historical restore preserve exact configurations';
 -- Without a text check, so only the record's own rules can refuse it.
 q:=jsonb_set(p,'{events,0,changes,0,check}','null'::jsonb);
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,q),'record without a text check');
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,jsonb_set(q,'{events,0,generation,request_ids}',
  (SELECT jsonb_agg(i::text) FROM generate_series(1,1023) i)||to_jsonb(repeat('😀',80)))),'1024 request ids, 80 characters each at most');
 FOR atom IN SELECT x FROM jsonb_array_elements(jsonb_build_array(
  'null'::jsonb,'{}'::jsonb,pg_temp.generation_record()||'{"secret":"unexpected"}'::jsonb,
  jsonb_set(pg_temp.generation_record(),'{version}',to_jsonb('target-resume-generation-v1:'||repeat('a',64)||chr(10))),
  jsonb_set(pg_temp.generation_record(),'{document_signature}','"bad"'::jsonb),
  pg_temp.generation_record('full-target-plan-v6'),pg_temp.generation_record('full-target-v6'||chr(10)),
  pg_temp.generation_record('full-target-v6'||chr(13)),pg_temp.generation_record('full-target-v6'||chr(8232)),pg_temp.generation_record('full-target-v6'||chr(8233)),
  jsonb_set(pg_temp.generation_record(),'{request_ids}','[]'::jsonb),
  jsonb_set(pg_temp.generation_record(),'{request_ids}','["duplicate","duplicate"]'::jsonb),
  jsonb_set(pg_temp.generation_record(),'{request_ids}',jsonb_build_array(E'\t\n')),
  jsonb_set(pg_temp.generation_record(),'{request_ids}',jsonb_build_array('request-one',chr(12288))),
  jsonb_set(pg_temp.generation_record(),'{request_ids}',jsonb_build_array(repeat('x',81))),
  jsonb_set(pg_temp.generation_record(),'{request_ids}',(SELECT jsonb_agg(i::text) FROM generate_series(1,1025) i)),
  jsonb_set(pg_temp.generation_record(),'{request_ids}','null'::jsonb),
  jsonb_set(pg_temp.generation_record(),'{request_ids}','["request-one",7]'::jsonb),
  jsonb_set(pg_temp.generation_record(),'{version}','null'::jsonb),
  jsonb_set(pg_temp.generation_record(),'{pipeline_version}','null'::jsonb),
  jsonb_set(pg_temp.generation_record(),'{document_signature}','null'::jsonb))) AS a(x) LOOP
   PERFORM pg_temp.reject_prov(d,jsonb_set(q,'{events,0,generation}',atom),'malformed configuration');
 END LOOP;
 q:=jsonb_set(pg_temp.prov(d,'typed'),'{version}','4'::jsonb);
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,q),'manual V4 event without a record');
 PERFORM pg_temp.reject_prov(d,jsonb_set(q,'{events,0,generation}',pg_temp.generation_record()),'manual must not claim a generation');
 q:=jsonb_set(q,'{events,0}',jsonb_build_object('id','ordered','kind','target_order','changes',jsonb_build_array(jsonb_build_object(
  'section_id','s','block_id',null,'line_id',null,'field','order','before','["b","c"]'::jsonb,'after','["c","b"]'::jsonb,
  'reason',null,'target_evidence','[]'::jsonb,'source_evidence','[]'::jsonb,'check',null))));
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,q),'target order V4 event without a record');
 PERFORM pg_temp.reject_prov(d,jsonb_set(q,'{events,0,generation}',pg_temp.generation_record()),'target order must not claim a generation');
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{version}','3'::jsonb),'no V4 field smuggled into V3');
 RAISE WARNING 'PASS V4 rejects malformed, oversized, duplicate, mismatched-kind and legacy-smuggled metadata atomically';
 FOREACH key IN ARRAY ARRAY['request_id','pipeline_version','document_signature'] LOOP
  bad:=jsonb_set(p,ARRAY['events','0','changes','0','check',key],
    to_jsonb(CASE WHEN key='document_signature' THEN 'v1:sha256:'||repeat('e',64) ELSE 'other' END));
  PERFORM pg_temp.reject_prov(d,bad,'review metadata from another generation');
 END LOOP;
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,jsonb_set(p,'{events,0,changes,0,check,request_id}','"request-two"'::jsonb)),
  'a text check may name a later request of its record');
 RAISE WARNING 'PASS V4 review records must match generation request, pipeline and source draft';
 q:=jsonb_set(p,'{events,0,changes,0,target_evidence}','[
  {"field":"lab_heading","page_index":0,"section_index":0,"start":0,"end":3,"quote":"官网🧪"},
  {"field":"paper_title","paper_index":0,"start":0,"end":3,"quote":"论文🧪"}]'::jsonb);
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,q),'V4 keeps V2 paper and V3 lab quote shapes');
 PERFORM pg_temp.reject_prov(jsonb_set(d,'{target_snapshot,context_version}','3'::jsonb),p,'V4 binds only a V4 target');
 RAISE WARNING 'PASS V4 keeps V2/V3 quote shapes and binds only a V4 target';
 q:=p #- '{events,0,generation}';
 PERFORM pg_temp.require(private.target_resume_provenance_valid(d,q),'older event remains unknown in V4 history');
 PERFORM pg_temp.require(NOT (q#>'{events,0}' ? 'generation'),'absence not filled');
 r:=public.commit_target_resume_cas(u,'generation',3,d);
 PERFORM pg_temp.require(r->>'status'='unchanged' AND r->'provenance'=p,'legacy noop preserves V4');
 RAISE WARNING 'PASS missing generation stays unknown and legacy no-op preserves known V4 metadata';
 d:=jsonb_set(pg_temp.prov_doc('generation-plan','原文🧪'),'{target_snapshot}','{"context_version":4}'::jsonb);
 p:=jsonb_set(pg_temp.generation_prov(d),'{events,0,kind}','"plan"'::jsonb);
 p:=jsonb_set(p,'{events,0,generation}',pg_temp.generation_record('full-target-plan-v6'));
 p:=jsonb_set(p,'{events,0,changes,0}',jsonb_build_object('section_id','s','block_id','b','line_id',null,
  'field','included','before',true,'after',false,'reason',null,'target_evidence','[]'::jsonb,'source_evidence','[]'::jsonb,'check',null));
 d:=jsonb_set(d,'{document,sections,0,blocks,0,included}','false'::jsonb);
 r:=public.commit_target_resume_with_provenance_cas(u,'generation-plan',0,d,p);
 PERFORM pg_temp.require(r->>'status'='saved' AND r->'provenance'=p,'plan selection records config without a prose check');
 PERFORM pg_temp.reject_prov(d,jsonb_set(p,'{events,0,generation}',pg_temp.generation_record('full-target-v6')),'plan record names the plan pipeline');
 RAISE WARNING 'PASS V4 content choices retain configuration without inventing a text-review check';
END $$;
SET ROLE authenticated;
DO $$ BEGIN
 PERFORM pg_temp.require((SELECT count(*)=2 FROM public.target_resumes),'owner can read its V4 pairs');
 PERFORM set_config('test.uid','45000000-0000-4000-8000-000000000002',false);
 PERFORM pg_temp.require((SELECT count(*)=0 FROM public.target_resumes),'other account cannot read V4 current');
 PERFORM pg_temp.require((SELECT count(*)=0 FROM public.target_resume_versions),'other account cannot read V4 history');
 BEGIN
  PERFORM public.commit_target_resume_with_provenance_cas('45000000-0000-4000-8000-000000000001','generation',3,
    pg_temp.prov_doc('generation','foreign'),'{}'::jsonb);
  RAISE EXCEPTION 'foreign write unexpectedly succeeded';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 RAISE WARNING 'PASS V4 account isolation rejects cross-owner reads and writes';
END $$;
RESET ROLE;
