"""Persistence-only acceptance of a synthetic pair created by the frontend.

This checks actual SQL CAS/history/RLS, not semantic grounding or signatures.
Run through run_target_resume_provenance_test.py --lab-context --material-fixture.
"""
import json


def material_roundtrip_sql(fixture):
    doc, provenance = fixture['doc'], fixture['provenance']
    assert isinstance(doc['base_snapshot'].get('research_interests'), str)
    assert doc['base_snapshot']['research_interests'].strip()
    assert any(len(change['source_evidence']) >= 2 for event in provenance['events'] for change in event['changes'])
    # String literals are safe under explicit standard_conforming_strings; all
    # dynamic values are JSON literals, never identifiers or executable SQL.
    def literal(value):
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    return """BEGIN;
SET standard_conforming_strings = on;
SET client_min_messages = warning;
INSERT INTO auth.users(id) VALUES ('52000000-0000-4000-8000-000000000001'),('52000000-0000-4000-8000-000000000002');
CREATE TEMP TABLE b52_fixture(doc jsonb, provenance jsonb);
INSERT INTO b52_fixture VALUES (""" + literal(doc) + ',' + literal(provenance) + """);
GRANT SELECT ON b52_fixture TO authenticated;
SET LOCAL ROLE authenticated;
SELECT set_config('test.uid','52000000-0000-4000-8000-000000000001',true);
DO $$
DECLARE u text := '52000000-0000-4000-8000-000000000001'; d jsonb; p jsonb; r jsonb; target text;
BEGIN
 SELECT doc, provenance INTO d,p FROM b52_fixture; target := d->>'opportunity_id';
 r := public.commit_target_resume_with_provenance_cas(u,target,0,d,p);
 IF r->>'status' IS DISTINCT FROM 'saved' OR r->'doc' IS DISTINCT FROM d OR r->'provenance' IS DISTINCT FROM p THEN RAISE EXCEPTION 'B52 initial pair differs'; END IF;
 IF NOT EXISTS (SELECT 1 FROM public.target_resumes WHERE owner_id=u::uuid AND opportunity_id=target AND doc=d AND provenance=p)
 OR NOT EXISTS (SELECT 1 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id=target AND revision=1 AND doc=d AND provenance=p)
 THEN RAISE EXCEPTION 'B52 current/history pair differs'; END IF;
 RAISE WARNING 'PASS B52 frontend interest and complete support citations persist exactly in current/history';
 r := public.commit_target_resume_with_provenance_cas(u,target,0,d,p);
 IF r->>'status' IS DISTINCT FROM 'unchanged' OR r->'provenance' IS DISTINCT FROM p OR (SELECT count(*) FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id=target) <> 1
 THEN RAISE EXCEPTION 'B52 retry changed pair/history'; END IF;
 RAISE WARNING 'PASS B52 same-pair retry keeps one history version';
END $$;
SELECT set_config('test.uid','52000000-0000-4000-8000-000000000002',true);
DO $$
DECLARE d jsonb; p jsonb;
BEGIN
 SELECT doc, provenance INTO d,p FROM b52_fixture;
 IF EXISTS (SELECT 1 FROM public.target_resumes WHERE owner_id='52000000-0000-4000-8000-000000000001')
 OR EXISTS (SELECT 1 FROM public.target_resume_versions WHERE owner_id='52000000-0000-4000-8000-000000000001') THEN RAISE EXCEPTION 'B52 cross-owner source disclosure'; END IF;
 BEGIN
  PERFORM public.commit_target_resume_with_provenance_cas('52000000-0000-4000-8000-000000000001',d->>'opportunity_id',1,d,p);
  RAISE EXCEPTION 'B52 cross-owner write accepted';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 RAISE WARNING 'PASS B52 added direction and support records remain owner-isolated';
END $$;
SELECT set_config('test.uid','52000000-0000-4000-8000-000000000001',true);
DO $$
DECLARE u text := '52000000-0000-4000-8000-000000000001'; d jsonb; p jsonb; r jsonb; target text; edited jsonb;
BEGIN
 SELECT doc, provenance INTO d,p FROM b52_fixture; target := d->>'opportunity_id';
 edited := jsonb_set(d,'{document,sections,0,blocks,0,lines,0,text}',to_jsonb((d#>>'{document,sections,0,blocks,0,lines,0,text}') || ' [manual edit]'));
 r := public.commit_target_resume_with_provenance_cas(u,target,1,edited,NULL);
 IF r->>'status' IS DISTINCT FROM 'saved' OR r->>'revision' IS DISTINCT FROM '2' THEN RAISE EXCEPTION 'B52 second version not saved'; END IF;
 r := public.commit_target_resume_with_provenance_cas(u,target,1,d,p);
 IF r->>'status' IS DISTINCT FROM 'conflict' OR r->'doc' IS DISTINCT FROM edited THEN RAISE EXCEPTION 'B52 stale write lost winning draft'; END IF;
 RAISE WARNING 'PASS B52 stale prior support pair cannot overwrite a later edit';
 r := public.commit_target_resume_with_provenance_cas(u,target,2,d,p);
 IF r->>'status' IS DISTINCT FROM 'saved' OR r->>'revision' IS DISTINCT FROM '3' OR r->'doc' IS DISTINCT FROM d OR r->'provenance' IS DISTINCT FROM p
 OR NOT EXISTS (SELECT 1 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id=target AND revision=1 AND doc=d AND provenance=p)
 OR NOT EXISTS (SELECT 1 FROM public.target_resume_versions WHERE owner_id=u::uuid AND opportunity_id=target AND revision=3 AND doc=d AND provenance=p)
 THEN RAISE EXCEPTION 'B52 restore lost direction/support or changed history'; END IF;
 RAISE WARNING 'PASS B52 explicit restore appends exact direction/support pair without rewriting prior history';
END $$;
ROLLBACK;
"""
