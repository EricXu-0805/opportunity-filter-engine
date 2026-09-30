-- Test-only functions; these never enter application migrations.
CREATE FUNCTION pg_temp.prov_doc(opp text, marker text) RETURNS jsonb LANGUAGE sql AS $$
 SELECT jsonb_build_object('kind','full_resume','version',1,'id','doc-'||opp,'opportunity_id',opp,
 'base',jsonb_build_object('master_id','master','master_revision',1,'profile_signature','v1:sha256:'||repeat('a',64),'source_signature',repeat('b',64),'target_signature','v1:sha256:'||repeat('c',64)),
 'base_snapshot','{}'::jsonb,'target_snapshot','{}'::jsonb,'document',jsonb_build_object('sections',jsonb_build_array(jsonb_build_object('id','s','kind','activities','heading','Projects','included',true,
 'blocks',jsonb_build_array(jsonb_build_object('id','b','included',true,'lines',jsonb_build_array(jsonb_build_object('id','l','role','description','label','Work','original','原文🧪','text',marker,'included',true,'evidence',jsonb_build_object('kind','experience','id','e','revision',1)))))))));
$$;
CREATE FUNCTION pg_temp.prov(doc jsonb, event_id text) RETURNS jsonb LANGUAGE sql AS $$
 SELECT jsonb_build_object('version',1,'document_id',doc->'id','opportunity_id',doc->'opportunity_id','base',doc->'base','events',jsonb_build_array(jsonb_build_object('id',event_id,'kind','manual','changes',jsonb_build_array(jsonb_build_object(
 'section_id','s','block_id','b','line_id','l','field','text','before','原文🧪','after',doc#>'{document,sections,0,blocks,0,lines,0,text}',
 'reason',null,'target_evidence','[]'::jsonb,'source_evidence','[]'::jsonb,'check',null)))));
$$;
CREATE FUNCTION pg_temp.require(ok boolean, label text) RETURNS void LANGUAGE plpgsql AS $$
 BEGIN IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'assertion_failed: %',label; END IF; END;
$$;
CREATE FUNCTION pg_temp.reject_prov(doc jsonb, value jsonb, label text) RETURNS void LANGUAGE plpgsql AS $$
 DECLARE rejected boolean := false; old_rows jsonb; new_rows jsonb;
 BEGIN
 SELECT jsonb_agg(to_jsonb(t) ORDER BY revision) INTO old_rows FROM public.target_resume_versions t WHERE owner_id='45000000-0000-4000-8000-000000000001';
 BEGIN
   PERFORM public.commit_target_resume_with_provenance_cas('45000000-0000-4000-8000-000000000001',doc->>'opportunity_id',0,doc,value);
 EXCEPTION WHEN invalid_parameter_value THEN rejected := true; END;
 PERFORM pg_temp.require(rejected,label);
 SELECT jsonb_agg(to_jsonb(t) ORDER BY revision) INTO new_rows FROM public.target_resume_versions t WHERE owner_id='45000000-0000-4000-8000-000000000001';
 PERFORM pg_temp.require(old_rows IS NOT DISTINCT FROM new_rows,'rejected mutation changed history: '||label);
 END;
$$;
