"""Run inside release 0741df3b with --runs pointing at the public Actions run list (TSV)."""
import argparse, collections, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from scripts.release_gate import corpus_freshness_report, _parse_stamp
from src.evidence import faculty_verification_scope, legacy_file_roster, source_last_seen_at
from src.collectors import source_health
parser=argparse.ArgumentParser()
parser.add_argument('--runs',required=True); parser.add_argument('--output',required=True)
args=parser.parse_args()
now=datetime.fromisoformat('2026-11-26T09:19:50.138525+00:00')
report=corpus_freshness_report(now=now)
ledger=source_health.load_ledger(Path('data/processed/source_health.json'))
sourcereport=source_health.corpus_report(ledger,now=now)
cutoff=now-timedelta(days=report['stale_days'])
def tally():return dict(active=0,fresh=0,seen_outside_window=0,without_usable_sighting=0)
per=collections.defaultdict(tally); classes=collections.defaultdict(tally)
for p in sorted(Path('data/processed/shards').glob('*.json')):
 for row in json.load(p.open()):
  m=row.get('metadata') or {}
  if not m.get('is_active'):continue
  src=row.get('source') or '(none)'; key=src
  if src=='manual': category='manual'
  elif legacy_file_roster(src,row.get('id','')):category='four_known_file_roster_units'
  elif faculty_verification_scope(row)=='curated': category='other_curated_faculty'
  elif src=='cmu_uro_projects':category='CMU_project_snapshot'
  else:category='other'
  t=_parse_stamp(source_last_seen_at(row))
  for box in (per[key],classes[category]):
   box['active']+=1
   box['without_usable_sighting' if t is None else ('fresh' if t>=cutoff else 'seen_outside_window')]+=1
assert sum(v['active'] for v in per.values())==report['active_records']
assert sum(v['fresh'] for v in per.values())==report['fresh_records']
hist=[json.loads(x) for x in open('data/processed/collector_status_history.jsonl')]
runs=[]
for line in open(args.runs):
 rid,created,result,event,url,head=line.rstrip().split('\t')
 if event!='schedule' or created>now.isoformat() or len(runs)>=7: continue
 # Runner timestamps include microseconds; identify the first started inside the run window.
 matches=[x for x in hist if 0<=(datetime.fromisoformat(x['t']).replace(tzinfo=timezone.utc)-datetime.fromisoformat(created.replace('Z','+00:00'))).total_seconds()<3600]
 assert len(matches)==1
 row=matches[0]
 runs.append(dict(id=rid,url=url,workflow_sha=head,created_at=created,collector_start=row['t'],result=result,
                 duration_minutes=round(row['duration_seconds']/60,2),sources=len(row['sources']),
                 deferred_deadline=[k for k,v in row['sources'].items() if v.get('status')=='deferred_deadline'],
                 partial_deadline=[k for k,v in row['sources'].items() if v.get('status')=='partial_deadline'],
                 suspicious_zero=[k for k,v in row['sources'].items() if v.get('status')=='suspicious_zero']))
base='0741df3be2d6ccd50e40789f0833f9d21dd0d041'
national=report['schools']['national']
out=dict(release=base,observed_at=now.isoformat(),window='14 days; policy threshold >=95%. Only source sightings at or after cutoff count. Every active row is included in the denominator. Inactive rows are excluded.',production='https://joinalab.com/api/health',cutoff=cutoff.isoformat(),report=report,
         school_only=dict(active=report['active_records']-national['active'],fresh=report['fresh_records']-national['fresh']), national=national,
         categories=dict(sorted(classes.items())), by_record_source=dict(sorted(per.items())),source_health=dict(fully_stale_schools=sourcereport['fully_stale_schools'],no_fresh_faculty_schools=sourcereport['no_fresh_faculty_schools'],source_age_limit_days=sourcereport['stale_days']),
         notes=['The four file-backed faculty units are JHU BSPH/SOM and Northwestern Kellogg/Feinberg. A directory clock on a legacy file roster is not a sighting. A genuine later source sighting is eligible. The other_curated_faculty category is not equivalent to a known frozen file.','Record-source names in by_record_source refer to actual stored record source labels. The operational source ledger reports different units and its separate threshold is applied to producer health.','The seven runs below are the latest scheduled runs; manual runs are excluded. They fall outside the monthly enrichment week and cannot accept M176.'],M176_scheduled_runs=runs)
Path(args.output).write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
print(out['categories'],out['source_health'],[(r['id'],r['duration_minutes']) for r in runs])
