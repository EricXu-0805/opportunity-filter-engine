"""Check the Delaware Materials originals and the two older campus appointments."""
import argparse,json,re,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
import requests
from bs4 import BeautifulSoup

opts=argparse.ArgumentParser()
opts.add_argument('--sha',required=True)
opts.add_argument('--phase',choices=['before','after'],required=True)
opts.add_argument('--cases',required=True)
opts.add_argument('--out',required=True)
args=opts.parse_args()
root='https://joinalab.com'
cases=json.loads(Path(args.cases).read_bytes())
def get(url):
    for attempt in range(3):
        try:
            r=requests.get(url,timeout=(7,22))
            if r.status_code in (429,502,503,504) and attempt<2:
                time.sleep(max(5,int(r.headers.get('Retry-After',5))));continue
            return r
        except requests.RequestException:
            if attempt==2:raise
            time.sleep(2)
def versions():
    home=get(root);health=get(root+'/api/health')
    home.raise_for_status();health.raise_for_status()
    return [re.search(r'data-release-sha="([a-f0-9]{40})"',home.text)[1],health.json()['release_sha']]
start=versions(); assert start==[args.sha]*2,start
def check(case):
    oid=case['id']
    html=get(root+'/opportunities/'+oid)
    api=get(root+'/api/opportunities/'+oid+'?_release_scope=mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2')
    d=BeautifulSoup(html.content,'html.parser')
    h=[el.get_text(' ',strip=True) for el in d.select('h1')]
    data=api.json() if api.status_code==200 else {}
    target=data.get('target_truth') or {}
    row={'id':oid,'name':case['name'],'group':case['group'],'web_status':html.status_code,'public_api_status':api.status_code,'expected_heading_visible':case['name'] in h,'api_id_matches':data.get('id')==oid,'api_name_matches':data.get('pi_name')==case['name'],'role':(data.get('metadata') or {}).get('faculty_title'),'contact_state':data.get('contact_email_status'),'can_act':target.get('actionable'),'published_link':data.get('url')}
    if case['group']=='new' and args.phase=='before':
        row['verified']=api.status_code==404 and not row['expected_heading_visible']
    else:
        row['verified']=row['expected_heading_visible'] and row['api_id_matches'] and row['api_name_matches'] and html.status_code==api.status_code==200
        if args.phase=='after' and case['group']=='new':row['verified'] &= row['contact_state']!='unavailable' and row['published_link']==case['url'] and any(a.get('href')==case['url'] for a in d.select('a[href]'))
        if case['group']=='departed' or (args.phase=='after' and case['group']=='retired'):
            row['verified'] &= row['contact_state']=='unavailable' and not row['can_act']
        if args.phase=='after' and case['group']=='retired':row['verified'] &= row['role']=='Professor Emeritus'
    return row
with ThreadPoolExecutor(max_workers=2) as pool: rows=list(pool.map(check,cases))
end=versions()
receipt={'release':args.sha,'phase':args.phase,'checked_at':datetime.now(timezone.utc).isoformat(),'versions_before':start,'versions_after':end,'public_rows':rows}
Path(args.out).write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
assert start==end
print(len(rows),[(r['id'],r['web_status'],r['public_api_status'],r['contact_state']) for r in rows if not r['verified']])
assert all(r['verified'] for r in rows)
