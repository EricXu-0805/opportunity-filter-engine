"""Compare all October 23 original IDs, then verify the two Thursday nickname fixes in the scheduled per-unit ledgers."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import subprocess
slug='EricXu-0805/opportunity-filter-engine'
run_id='45861578824'
source='1fd5e131be5c22e96f77838038ddef7cbca7dd60'
keyed={'faculty-vanderbilt-math-1d5fbacf':('vanderbilt','math'), 'faculty-utexas-linguistics-ab991fd0':('utexas','linguistics')}
arg=argparse.ArgumentParser(description=__doc__);arg.add_argument('pr',type=int);arg.add_argument('--repo',type=Path,default=Path.cwd());arg.add_argument('--baseline',type=Path,default=Path(__file__).with_name('m140.json'));arg.add_argument('--output-dir',type=Path,default=Path.cwd());cfg=arg.parse_args()
def cmd(*args):return subprocess.check_output(args,text=True).strip()
def git(*args):return cmd('git','-C',str(cfg.repo),*args)
def gh(*args):return json.loads(cmd('gh',*args,'--repo',slug))
def get(rev,path):return json.loads(git('show',rev+':'+path))
job=gh('run','view',run_id,'--json','event,headSha,status,conclusion,createdAt,url')
pr=gh('pr','view',str(cfg.pr),'--json','number,headRefName,headRefOid,state,mergedAt,url,mergeCommit')
assert job['event']=='schedule' and re.fullmatch(rf'auto/refresh-data-{run_id}(?:-r[0-9]+)?',pr['headRefName'])
git('fetch','origin',f'refs/pull/{cfg.pr}/head');head=pr['headRefOid'];start=job['headSha'];assert git('rev-parse','FETCH_HEAD')==head
assert subprocess.run(['git','-C',str(cfg.repo),'merge-base','--is-ancestor',source,start]).returncode==0
prior=json.loads(cfg.baseline.read_text())['baseline_216'];assert len(prior)==216
def fields(r):
 if not r:return {'status':'missing'}
 m=r.get('metadata',{});last=(m.get('last_seen_at') or '')[:10]
 return {'status':('inactive' if m.get('is_active') is False else ('observed_since_fix' if last>='2026-10-24' else 'active_date_old')),'name':r.get('pi_name'),'profile':r.get('url'),'last_seen_at':last,'active':m.get('is_active'),'duplicate_of':m.get('duplicate_of'),'deactivation_reason':m.get('deactivation_reason')}
def snapshot(rev):
 selected={}
 for school in sorted({r['school'] for r in prior}):
  wanted={r['id'] for r in prior if r['school']==school}
  selected.update({r['id']:fields(r) for r in get(rev,f'data/processed/shards/{school}.json') if r['id'] in wanted})
 return selected
a,b=snapshot(start),snapshot(head);rows=[{'id':r['id'],'school':r['school'],'before':a.get(r['id'],fields(None)),'after':b.get(r['id'],fields(None))} for r in prior]
ledgers=get(head,'data/processed/collector_status.json')['sources'];observed={}
for key,(school,unit) in keyed.items():
 s=ledgers[school+'_faculty']; units=s['stale_unit_ledger']; old=get('983d208c2e5d60b150ff968ff41a5a0155e7df85','data/processed/collector_status.json')['sources'][school+'_faculty']['stale_unit_ledger']
 chosen=next((u for u in units if u.lower()==unit),None)
 if chosen is None:
  chosen=next((u for u in units if key in (units[u].get('observed_entity_ids') or []) or (a.get(key,{}).get('profile') and any(a[key]['profile'].replace('https://','').replace('http://','').strip('/') in x for x in (units[u].get('observed_identities') or [])))),None)
 if chosen is None: raise ValueError((school,unit,sorted(units)))
 cur,previous=units[chosen],old.get(chosen,{})
 assert cur['completed_at'].startswith('2026-11-26T')
 old_ids=set(previous.get('observed_entity_ids') or []); ids=set(cur.get('observed_entity_ids') or [])
 observed[key]={'school':school,'unit_key':chosen,'school_fetched':s.get('fetched'),'previous_unit_count':previous.get('observed_count'),'run_unit_count':cur.get('observed_count'),'previously_present_original':key in old_ids,'observed_original':key in ids,'old_ids_missing_from_current':sorted(old_ids-ids),'new_ids_in_current':sorted(ids-old_ids),'unit_coverage':cur.get('coverage'),'new_row':b.get(key),'matched_ids_count':cur.get('matched_identity_count'),'mismatches':cur.get('missed_present_identities'),'published_on_the_original':key in ids and b.get(key,{}).get('last_seen_at')=='2026-11-26'}
result={'now':datetime.now(timezone.utc).isoformat(),'run':job,'data_pr':pr,'pre_run_base':start,'data_head':head,'source_pr':'https://github.com/EricXu-0805/opportunity-filter-engine/pull/1251','total_originals':len(rows),'before':dict(Counter(x['before']['status'] for x in rows)),'after':dict(Counter(x['after']['status'] for x in rows)),'two_due_aliases':observed,'all_originals':rows,'scope':'Real scheduled input and resulting data head; verify eventual main merge, deployment and public details separately.'}
f=cfg.output_dir/f'm140-thursday-real-{run_id}-{head[:8]}.json';f.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(f,result['before'],result['after'],[(k,v['published_on_the_original']) for k,v in observed.items()])
