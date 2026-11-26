"""Read actual Thursday run/PR objects, faculty source ledger, and original IDs. No writes to git or production."""
import argparse
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import subprocess

REPO = Path.cwd()
SLUG = 'EricXu-0805/opportunity-filter-engine'
RUN = '45861578824'
PREVIOUS_SOURCE = '983d208c2e5d60b150ff968ff41a5a0155e7df85'
ROLE_FIX = '9c898b990cab0e1a9fbe93baf79eab53705183cf'
REDIRECT_FIX = '3ca46d67d891a23cc863829308e3ae7f347b2f41'
ROSS = 'faculty-vt-che-e1d3b3cb'
COHORT = {
    'faculty-vt-che-be391032': 'retired_title', 'faculty-vt-che-762a80d6': 'retired_title',
    'faculty-vt-che-8d99f667': 'retired_title', 'faculty-vt-che-23e0354e': 'retired_title',
    'faculty-vt-che-2b84e643': 'trainee_title', 'faculty-vt-che-b0225752': 'trainee_title',
    'faculty-vt-che-31a343a7': None, 'faculty-vt-che-ee55f0de': None,
}

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def gh(*args):
    return json.loads(run('gh', *args, '--repo', SLUG))

def git(*args):
    return run('git', '-C', str(REPO), *args)

def ancestor(a, b):
    return subprocess.call(['git','-C',str(REPO),'merge-base','--is-ancestor',a,b]) == 0

def snapshot(commit, path):
    return json.loads(git('show',f'{commit}:{path}'))

def raw_people(commit):
    rows = snapshot(commit,'data/processed/shards/vt.json')
    return {r['id']:r for r in rows}

def extract(row):
    if row is None:
        return None
    m = row['metadata']
    return {'id':row['id'],'name':row.get('pi_name'),'faculty_title':m.get('faculty_title'),'url':row.get('url'),
            'raw_is_active':m.get('is_active'),'deactivation_reason':m.get('deactivation_reason'),
            'last_seen_at':row.get('last_seen_at'),'last_seen_listed_at':row.get('last_seen_listed_at'),
            'profile_source':(m.get('faculty_profile_review') or {}).get('source_url')}

def ledger_info(doc):
    source=doc['sources']['vt_faculty'];u=source['stale_unit_ledger']['che'];keys=('observed_count','baseline_active_count','baseline_identity_count','matched_identity_count','new_identity_count','missed_present_identities','roster_source_confirmed','coverage','retirement_authorized','unit_name','unit_url','fetch_status','parse_status','completeness_status','started_at','completed_at','observed_entity_ids')
    return {'school_fetched':source.get('fetched'),'school_new':source.get('new'),'school_updated':source.get('updated'),'school_status':source.get('status'),'unit':{k:u.get(k) for k in keys}}

def main():
    global REPO
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument('pr', type=int)
    arg.add_argument('--repo', type=Path, default=Path.cwd())
    arg.add_argument('--output-dir', type=Path, default=Path.cwd())
    args = arg.parse_args()
    REPO = args.repo
    job=gh('run','view',RUN,'--json','databaseId,headSha,event,status,conclusion,createdAt,updatedAt,url')
    pr=gh('pr','view',str(args.pr),'--json','number,headRefName,headRefOid,baseRefOid,state,mergedAt,mergeCommit,url')
    assert job['event']=='schedule' and job['createdAt'].startswith('2026-11-26T')
    assert re.fullmatch(rf'auto/refresh-data-{RUN}(?:-r[0-9]+)?', pr['headRefName'])
    start,head=job['headSha'],pr['headRefOid']
    git('fetch','origin',f'refs/pull/{args.pr}/head');assert git('rev-parse','FETCH_HEAD')==head
    assert ancestor(ROLE_FIX,start) and not ancestor(REDIRECT_FIX,start)
    baseline=ledger_info(snapshot(PREVIOUS_SOURCE,'data/processed/collector_status.json'))
    actual=ledger_info(snapshot(head,'data/processed/collector_status.json'))
    assert actual['unit']['completed_at'].startswith('2026-11-26T')
    old,new=raw_people(start),raw_people(head)
    ids=set(actual['unit'].get('observed_entity_ids') or [])
    details=[]
    for original,reason in COHORT.items():
        fresh=extract(new.get(original))
        details.append({'id':original,'expected_reason':reason,'listed_on_actual_run':original in ids,'run_start':extract(old.get(original)),'published_candidate':fresh,
                        'cohort_matches':bool(fresh and fresh['raw_is_active'] is (reason is None) and fresh['deactivation_reason']==reason)})
    candidate={'observed_at':datetime.now(timezone.utc).isoformat(),'run':job,'pr':pr,'previous_natural':baseline,'thursday_natural':actual,
               'originals':details,'separate_julia_ross':{'release_contains_fix':False,'observed':ROSS in ids,'candidate':extract(new.get(ROSS))},
               'unit_original_id_diff':{'observed_previously_lost':sorted(set(baseline['unit']['observed_entity_ids'])-ids),'observed_now_only':sorted(ids-set(baseline['unit']['observed_entity_ids']))},
               'raw_vt_shard':{'prior_count':len(old),'new_count':len(new),'lost_ids':sorted(old.keys()-new.keys()),'added_ids':sorted(new.keys()-old.keys())},
               'scope':'Scheduled collector/per-unit ledger and serialized candidate only. Production HTML/API and any resulting PR merge require independent checks.'}
    output=args.output_dir/f'vt-natural-{RUN}-pr-{args.pr}-{head[:8]}.json';output.write_text(json.dumps(candidate,indent=2)+'\n')
    print(output, actual['unit']['observed_count'],len(ids),'in cohort',sum(r['listed_on_actual_run'] for r in details),'matches',sum(r['cohort_matches'] for r in details))

if __name__=='__main__':
    main()
