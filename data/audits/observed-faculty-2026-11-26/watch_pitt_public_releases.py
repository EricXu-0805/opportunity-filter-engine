"""Run the original Pitt scripts once, only on their merged, same-version public release."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import importlib.util
import time
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading

import requests


ROOT = Path(__file__).resolve().parent
REPO = 'EricXu-0805/opportunity-filter-engine'
SITE = 'https://joinalab.com'
SCOPE = 'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
BATCHES = [
    (21, 1474, [('phil23', 'pitt-philosophy-primary/check_published.py', '57b86bcb555166852f6f7e0e70096d894343f93c')]),
    (22, 1484, [('ling28', 'pitt-linguistics-monthly/check_published.py', '6a9570cdfff9d45e9d8f2da7c4319ff249a6588c'),
                ('cs59', 'pitt-computer-science/check_released_details.py', '95dc2ace7617bf7d0f2dbed76375e7b7d11fcc9d')]),
]
wakeup = threading.Event()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def log(*text):
    print(now(), *text, flush=True)


def store(path, body):
    tmp = path.with_name(path.name + '.new')
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def git(*args):
    return subprocess.run(['git',*args], cwd=ROOT, text=True, capture_output=True, timeout=90)


def version(session):
    health = session.get(SITE + '/api/health', timeout=40)
    health.raise_for_status()
    about = session.get(SITE + '/about', timeout=40)
    about.raise_for_status()
    front = re.search(r'data-release-sha="([0-9a-f]{40})"',about.text)
    return [front[1] if front else None, health.json()['release_sha']]


def merged(pr):
    flags = ['--repo',REPO,'--json','state,baseRefName,headRefOid,mergeCommit,mergedAt,url']
    run = subprocess.run(['gh','pr','view',str(pr),*flags],cwd=ROOT,check=True,text=True,capture_output=True,timeout=80)
    return json.loads(run.stdout)


def proof(path):
    if not path.exists():
        return {'receipt':str(path),'response':'missing'}
    data = json.loads(path.read_text())
    rows = data.get('details', data.get('appointments', []))
    return {'receipt':str(path),'start':data.get('start'),'end':data.get('end'),
            'read_rows':len(rows),'saved_ids':len(data.get('saved_ids',[])),
            'errors':[r for r in rows if 'error' in r]}


def finish_incomplete(label, script, path, sha):
    """Resume partial university checks and re-read only original failed IDs once."""
    spec=importlib.util.spec_from_file_location(label,ROOT/script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    session=requests.Session()
    if version(session)!=[sha,sha]:
        raise RuntimeError('The original production release is no longer deployed.')
    data=json.loads(path.read_text())
    if data['start']!=[sha,sha]:
        raise RuntimeError('Previous receipt belongs to a different version.')
    folder=(ROOT/script).parent
    previous=path.with_name(path.stem+'-first-attempt.json')
    if not previous.exists():
        store(previous,data)
    def load(name):
        return json.loads((folder/name).read_text())
    if label=='phil23':
        roster=load('official-and-before.json')['records']
        candidates={r['id']:r for r in load('candidate-details.json')['results']}
        checks={r['original_id']:(r,candidates[r['original_id']]) for r in roster}
        read=lambda key:module.check_one(session,*checks[key],SCOPE)
    elif label=='cs59':
        records=load('directory-comparison-and-person-destinations.json')['identities']
        replay=load('source-retries-and-restoration.json')
        owners={v['name']:v['current_id'] for v in replay['runs']['repaired'][-1]['contacts']}
        checks={}
        for r in records:
            r['current_id']=owners[r['school_name']]
            for ident in r['published_ids']:
                checks[ident]=r
        read=lambda key:module.check(session,SITE,SCOPE,checks[key],key,False)
    else:
        expected=load('eight-candidate-details.json')['results']
        checks={r['id']:r for r in expected if r['id'] in module.CORRECTED}
        read=lambda key:module.appointment(session,SITE,SCOPE,checks[key])
    field='appointments' if label=='ling28' else 'details'
    by_id={r['id']:r for r in data.get(field,[])}
    attempt=[]
    for ident in checks:
        if ident in by_id and 'error' not in by_id[ident]:
            continue
        try:
            row=read(ident)
        except (requests.RequestException,AssertionError,ValueError,KeyError) as exc:
            row={'id':ident,'error':str(exc)}
        by_id[ident]=row
        attempt.append(row)
        data[field]=[by_id[k] for k in checks if k in by_id]
        store(path,data)
        time.sleep(13)
    data['end']=version(session)
    data['completed_or_retried_at']=now()
    data['first_attempt']=previous.name
    data['reread_ids']=[r['id'] for r in attempt]
    store(path,data)
    store(path.with_name(path.stem+'-retry.json'),{'expected_release':sha,'rows':attempt,'end':data['end']})
    return 0 if (data['end']==data['start'] and len(by_id)==len(checks) and
                 not any('error' in r for r in by_id.values()) and
                 (label!='ling28' or len(data.get('saved_ids',[]))==28)) else 1


def wait(seconds):
    wakeup.wait(seconds)
    wakeup.clear()


def run(output):
    output.mkdir(exist_ok=True, parents=True)
    with (output/'process.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('The same Pitt release observer is already active.',flush=True)
            return
        lock.seek(0); lock.truncate()
        lock.write(str(os.getpid())+'\n'); lock.flush()
        signal.signal(signal.SIGUSR1, lambda *unused:wakeup.set())
        session=requests.Session()
        state_path=output/'state.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else {'batches':{}}
        state['active_pid']=os.getpid()
        state['started_or_resumed_at']=now()
        store(state_path,state)
        for number,pr,scripts in BATCHES:
            key=str(number)
            entry=state['batches'].setdefault(key,{'pr':pr,'scripts':{}})
            if entry.get('finished_at'):
                continue
            verified_merge=None
            previous=None
            while True:
                delay=180
                try:
                    meta=merged(pr)
                    sha=(meta['mergeCommit'] or {}).get('oid')
                    ready=(meta['state']=='MERGED' and meta['baseRefName']=='main' and sha)
                    if not ready:
                        reading=[meta['state'],meta['baseRefName'],meta['headRefOid']]
                    else:
                        delay=35
                        if verified_merge!=sha:
                            fetched=git('fetch','origin','refs/heads/main')
                            if fetched.returncode:
                                raise RuntimeError(fetched.stderr.strip())
                            for orig in [sha]+[s[2] for s in scripts]:
                                target='FETCH_HEAD' if orig==sha else sha
                                if git('merge-base','--is-ancestor',orig,target).returncode:
                                    raise RuntimeError(f'merge ancestry pending: {orig} -> {target}')
                            verified_merge=sha
                        serving=version(session)
                        reading=[sha,*serving]
                        if serving==[sha,sha]:
                            entry.update(release=sha,pull_request=meta,observed_start=serving)
                            store(state_path,state)
                            break
                    entry.update(last_checked=now(),waiting=reading)
                    if reading!=previous:
                        log('Waiting for B'+key,reading)
                        previous=reading
                    store(state_path,state)
                except (requests.RequestException, subprocess.SubprocessError,RuntimeError, ValueError, KeyError) as exc:
                    log('Temporary release read problem, B'+key,str(exc)[:300])
                wait(delay)
            for label,script,commit in scripts:
                if label in entry['scripts'] and entry['scripts'][label].get('completed_at'):
                    continue
                file=output/f'B{number}-{label}-{sha[:8]}.json'
                entry['scripts'][label]={'source':commit,'file':str(file),'started_at':now()}
                store(state_path,state)
                code=1
                if not file.exists():
                    log('Starting',label,'on',sha)
                    with (output/f'{label}.log').open('a') as stream:
                        job=subprocess.run([sys.executable,str(ROOT/script),'--sha',sha,'--scope',SCOPE,'--out',str(file)],
                                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
                        code=job.returncode
                if code and file.exists():
                    try:
                        log('Checking incomplete IDs only',label)
                        code=finish_incomplete(label,script,file,sha)
                    except (requests.RequestException,RuntimeError,ValueError,KeyError, subprocess.SubprocessError) as exc:
                        log('Could not complete the same-version retry',label,str(exc)[:350])
                info=proof(file)
                entry['scripts'][label].update(completed_at=now(),exit_code=code,**info)
                store(state_path,state)
                log('Finished',label,'exit',code,'errors',len(info.get('errors',[])))
            entry['finished_at']=now()
            entry['all_checks_passed']=all(x.get('exit_code')==0 for x in entry['scripts'].values())
            store(state_path,state)
        state['finished_at']=now()
        state['active_pid']=None
        store(state_path,state)
        log('Both deployment windows recorded.', {k:b['all_checks_passed'] for k,b in state['batches'].items()})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outdir',required=True,type=Path)
    run(parser.parse_args().outdir)
