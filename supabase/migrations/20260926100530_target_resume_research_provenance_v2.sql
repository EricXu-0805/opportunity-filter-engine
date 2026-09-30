-- V2 editing provenance can record exact paper-title/abstract quotes from a
-- V3 target snapshot. Existing V1 sidecars keep their original schema and bytes.
-- This remains client-recorded provenance, not a server-signed fact attestation.
-- Only shape/type/document binding is checked here; the client additionally
-- checks research status, exact Unicode quotes and reverse replay of changes.
-- No rows, RPC signatures, ownership checks, limits or grants are changed.

CREATE OR REPLACE FUNCTION private.target_resume_provenance_valid(doc jsonb, value jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path = '' AS $$
DECLARE event jsonb; change jsonb; quote jsonb; check_record jsonb; atom jsonb;
  key text; ids text[] := ARRAY[]::text[];
BEGIN
 IF value IS NULL THEN RETURN true; END IF;
 IF octet_length(value::text) > 524288 THEN RETURN false; END IF;
 IF NOT private.target_resume_provenance_shape(value, ARRAY['version','document_id','opportunity_id','base','events'])
   OR (value->'version' IS DISTINCT FROM '1'::jsonb AND value->'version' IS DISTINCT FROM '2'::jsonb)
   OR (value->'version' = '2'::jsonb AND doc#>'{target_snapshot,context_version}' IS DISTINCT FROM '3'::jsonb)
   OR NOT private.target_resume_provenance_string(value->'document_id')
   OR NOT private.target_resume_provenance_string(value->'opportunity_id')
   OR length(value->>'document_id') > 200 OR length(value->>'opportunity_id') > 200
   OR value->'document_id' IS DISTINCT FROM doc->'id'
   OR value->'opportunity_id' IS DISTINCT FROM doc->'opportunity_id'
   OR value->'base' IS DISTINCT FROM doc->'base'
   OR NOT private.target_resume_provenance_shape(value->'base', ARRAY['master_id','master_revision','profile_signature','source_signature','target_signature'])
   OR jsonb_typeof(value->'events') IS DISTINCT FROM 'array'
   OR private.target_resume_json_bytes(value) > 262144 THEN RETURN false; END IF;
 IF jsonb_array_length(value->'events') NOT BETWEEN 1 AND 512 THEN RETURN false; END IF;
 FOREACH key IN ARRAY ARRAY['master_id','profile_signature','source_signature','target_signature'] LOOP
   IF NOT private.target_resume_provenance_string(value->'base'->key) THEN RETURN false; END IF;
 END LOOP;
 IF NOT private.target_resume_provenance_integer(value->'base'->'master_revision', 1) THEN RETURN false; END IF;
 FOR event IN SELECT x FROM jsonb_array_elements(value->'events') AS e(x) LOOP
   IF NOT private.target_resume_provenance_shape(event, ARRAY['id','kind','changes'])
     OR NOT private.target_resume_provenance_string(event->'id') OR length(event->>'id') > 200
     OR event->>'id' = ANY(ids)
     OR jsonb_typeof(event->'kind') IS DISTINCT FROM 'string'
     OR event->>'kind' NOT IN ('manual','ai_rewrite','plan','target_order')
     OR jsonb_typeof(event->'changes') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
   ids := array_append(ids, event->>'id');
   IF jsonb_array_length(event->'changes') NOT BETWEEN 1 AND 1024 THEN RETURN false; END IF;
   FOR change IN SELECT x FROM jsonb_array_elements(event->'changes') AS c(x) LOOP
     IF NOT private.target_resume_provenance_shape(change, ARRAY['section_id','block_id','line_id','field','before','after','reason','target_evidence','source_evidence','check'])
       OR jsonb_typeof(change->'field') IS DISTINCT FROM 'string'
       OR change->>'field' NOT IN ('text','included','order')
       OR jsonb_typeof(change->'target_evidence') IS DISTINCT FROM 'array'
       OR jsonb_typeof(change->'source_evidence') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
     FOREACH key IN ARRAY ARRAY['section_id','block_id','line_id'] LOOP
       IF change->key <> 'null'::jsonb AND (NOT private.target_resume_provenance_string(change->key)
         OR length(change->>key) > 200) THEN RETURN false; END IF;
     END LOOP;
     IF change->'reason' <> 'null'::jsonb AND jsonb_typeof(change->'reason') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
     IF (change->'block_id' <> 'null'::jsonb AND change->'section_id' = 'null'::jsonb)
       OR (change->'line_id' <> 'null'::jsonb AND change->'block_id' = 'null'::jsonb)
       OR (change->>'field' = 'text' AND change->'line_id' = 'null'::jsonb)
       OR (change->>'field' = 'included' AND change->'section_id' = 'null'::jsonb)
       OR (change->>'field' = 'order' AND change->'line_id' <> 'null'::jsonb)
       OR (event->>'kind' = 'target_order' AND change->>'field' <> 'order')
       OR (event->>'kind' = 'ai_rewrite' AND change->>'field' = 'included')
       OR (event->>'kind' = 'plan' AND change->>'field' = 'order')
       OR (event->>'kind' <> 'manual' AND change->'before' = change->'after') THEN RETURN false; END IF;
     IF event->>'kind' IN ('manual','target_order') AND (change->'reason' <> 'null'::jsonb
       OR change->'target_evidence' <> '[]'::jsonb OR change->'source_evidence' <> '[]'::jsonb
       OR change->'check' <> 'null'::jsonb) THEN RETURN false; END IF;
     IF change->>'field' = 'text' THEN
       IF jsonb_typeof(change->'before') IS DISTINCT FROM 'string' OR jsonb_typeof(change->'after') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
     ELSIF change->>'field' = 'included' THEN
       IF jsonb_typeof(change->'before') IS DISTINCT FROM 'boolean' OR jsonb_typeof(change->'after') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
     ELSE
       IF jsonb_typeof(change->'before') IS DISTINCT FROM 'array' OR jsonb_typeof(change->'after') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
       IF (SELECT count(*) <> count(DISTINCT x) FROM jsonb_array_elements(change->'before') AS a(x))
         OR (SELECT count(*) <> count(DISTINCT x) FROM jsonb_array_elements(change->'after') AS a(x)) THEN RETURN false; END IF;
       FOR atom IN SELECT x FROM jsonb_array_elements((change->'before') || (change->'after')) AS a(x) LOOP
         IF NOT private.target_resume_provenance_string(atom) OR length(atom #>> '{}') > 200 THEN RETURN false; END IF;
       END LOOP;
     END IF;
     FOR quote IN SELECT x FROM jsonb_array_elements(change->'target_evidence') AS q(x) LOOP
       IF jsonb_typeof(quote->'field') IS DISTINCT FROM 'string'
         OR NOT private.target_resume_provenance_integer(quote->'start',0)
         OR NOT private.target_resume_provenance_integer(quote->'end',1)
         OR NOT private.target_resume_provenance_string(quote->'quote') THEN RETURN false; END IF;
       IF (quote->>'end')::numeric <= (quote->>'start')::numeric THEN RETURN false; END IF;
       IF quote->>'field' IN ('description','requirement') THEN
         IF NOT private.target_resume_provenance_shape(quote, ARRAY['field','requirement_index','start','end','quote']) THEN RETURN false; END IF;
         IF quote->>'field' = 'description' THEN
           IF quote->'requirement_index' IS DISTINCT FROM 'null'::jsonb THEN RETURN false; END IF;
         ELSIF NOT private.target_resume_provenance_integer(quote->'requirement_index',0) THEN RETURN false;
         END IF;
       ELSIF quote->>'field' IN ('paper_title','paper_abstract') THEN
         IF value->'version' IS DISTINCT FROM '2'::jsonb
           OR NOT private.target_resume_provenance_shape(quote, ARRAY['field','paper_index','start','end','quote'])
           OR NOT private.target_resume_provenance_integer(quote->'paper_index',0) THEN RETURN false; END IF;
       ELSE RETURN false;
       END IF;
     END LOOP;
     FOR quote IN SELECT x FROM jsonb_array_elements(change->'source_evidence') AS q(x) LOOP
       IF NOT private.target_resume_provenance_shape(quote, ARRAY['unit_id','start','end','quote'])
         OR NOT private.target_resume_provenance_string(quote->'unit_id') OR length(quote->>'unit_id') > 200
         OR NOT private.target_resume_provenance_integer(quote->'start',0)
         OR NOT private.target_resume_provenance_integer(quote->'end',1)
         OR NOT private.target_resume_provenance_string(quote->'quote') THEN RETURN false; END IF;
       IF (quote->>'end')::numeric <= (quote->>'start')::numeric THEN RETURN false; END IF;
     END LOOP;
     check_record := change->'check';
     IF check_record <> 'null'::jsonb THEN
       IF change->>'field' <> 'text' OR event->>'kind' NOT IN ('ai_rewrite','plan')
         OR NOT private.target_resume_provenance_shape(check_record, ARRAY['version','pipeline_version','request_id','document_signature','original','evidence'])
         OR NOT private.target_resume_provenance_shape(check_record->'evidence', ARRAY['kind','id','revision'])
         OR check_record->'evidence'->'kind' IS DISTINCT FROM '"experience"'::jsonb
         OR NOT private.target_resume_provenance_string(check_record->'evidence'->'id')
         OR length(check_record->'evidence'->>'id') > 200
         OR NOT private.target_resume_provenance_integer(check_record->'evidence'->'revision',1)
         OR jsonb_typeof(check_record->'original') IS DISTINCT FROM 'string'
         OR (check_record->>'document_signature') !~ '^v1:sha256:[a-f0-9]{64}$' THEN RETURN false; END IF;
       FOREACH key IN ARRAY ARRAY['version','pipeline_version','request_id','document_signature'] LOOP
         IF NOT private.target_resume_provenance_string(check_record->key) THEN RETURN false; END IF;
       END LOOP;
     END IF;
   END LOOP;
 END LOOP;
 RETURN true;
END;
$$;
