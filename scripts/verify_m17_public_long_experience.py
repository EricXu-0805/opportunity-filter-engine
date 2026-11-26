"""Production profile controls, one self-created guest, ten synthetic entries; no external messages or AI."""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright
import verify_public_matching_experience as app

BASE = 'f30443aa8654bd1c0d093ccd6fd9c067c3f4148a'
STUDENT = 'Synthetic Unicode materials check'
LABEL = 'Describe your contribution, methods and results'
OUTPUT = {'base': BASE, 'environment':'official site using one dedicated real anonymous guest', 'published_at':None}
TEXTS = []
for index in range(10):
    start = f'Example research project {index+1:02d}. I mapped public habitat records using GIS. '
    body = 'Design choices, open measurements, and synthetic notes. 实验文本🙂 '
    finish = f'·完整第{index+1:02d}条·🧭'
    TEXTS.append(start + (body * 160)[:6000-len(start)-len(finish)] + finish)
assert all(len(x)==6000 and len(x.encode('utf-16-le'))//2>6000 for x in TEXTS)


def release(request):
    backend=request.get(app.site+'/api/health').json()['release_sha']
    html=request.get(app.site+'/about').text()
    front=re.search('data-release-sha="([a-f0-9]{40})"',html).group(1)
    for commit in set([front,backend]):
        assert re.fullmatch('[a-f0-9]{40}',commit)
        if commit!=BASE:
            url=f'https://api.github.com/repos/EricXu-0805/opportunity-filter-engine/compare/{BASE}...{commit}'
            with urlopen(url,timeout=20) as res: data=json.load(res)
            assert data['merge_base_commit']['sha']==BASE and data['status'] in ('identical','ahead')
    return {'frontend':front,'backend':backend}


def main():
    ack=[]
    blocked=[]
    outage=False
    writes=[]
    post_status=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        http=pw.request.new_context()
        OUTPUT['before']=release(http)
        def fresh():
            c=app.cold(browser)
            reads=[]
            def guard(route):
                r=route.request
                u=urlsplit(r.url)
                if r.method in ('GET','HEAD','OPTIONS'):return route.fallback()
                if u.hostname==app.db and u.path=='/rest/v1/rpc/commit_profile_patch_cas':
                    data=r.post_data_json
                    assert app.auth and data['p_expected_device_id']==app.auth[0]['user']['id']
                    if outage and 'experience_entries' in data['p_patch']:
                        blocked.append(True)
                        return route.abort('internetdisconnected')
                    return route.fallback()
                if u.hostname==app.db and u.path in ('/auth/v1/signup','/auth/v1/token'):return route.fallback()
                if u.hostname=='joinalab.com' and u.path in ('/api/matches','/api/matches/view') and parse_qs(u.query).get('llm')==['false']:
                    return route.fallback()
                return route.abort()
            def record(r):
                u=urlsplit(r.url)
                if u.hostname!=app.db:return
                if u.path=='/rest/v1/rpc/commit_profile_patch_cas' and r.request.method=='POST':
                    patch=r.request.post_data_json['p_patch']
                    if 'experience_entries' in patch:
                        post_status.append(r.status)
                        if r.ok and r.json().get('status')=='applied':
                            rows=patch['experience_entries']
                            writes.append({'revision':r.json()['revision'],'rows':len(rows),'confirmed':sum(e['status']=='confirmed' for e in rows)})
                            ack.append(rows)
                if u.path=='/rest/v1/profiles' and r.request.method=='GET' and r.ok:
                    result=r.json()
                    if isinstance(result,list) and len(result)==1:result=result[0]
                    if isinstance(result,dict) and isinstance(result.get('profile_data'),dict):
                        assert app.auth
                        uid=app.auth[0]['user']['id']
                        assert result.get('id')==uid or parse_qs(u.query).get('id')==['eq.'+uid]
                        reads.append((result.get('revision'),result['profile_data']))
            c.route('**/*',guard)
            c.on('response',record)
            return c,reads
        def await_cloud(p,pred,stage):
            for _ in range(200):
                if ack and pred(ack[-1]):return
                p.wait_for_timeout(200)
            raise AssertionError((stage,'matching cloud acknowledgement missing',writes[-4:],post_status[-4:]))
        def view(expected):
            c,reads=fresh()
            p=app.home(c)
            expect(p.locator('#student_name')).to_have_value(STUDENT,timeout=65000)
            found=[(revision,data) for revision,data in reads if data.get('name')==STUDENT]
            assert found, ('expected owned cloud read',len(reads))
            revision,data=found[-1]
            rows=data.get('experience_entries',[])
            assert [e['text'] for e in rows]==[e['text'] for e in expected]
            assert rows==expected
            for i,e in enumerate(rows):
                detail=details(p,i)
                detail.locator('summary').first.click()
                assert detail.locator('textarea').input_value()==e['text']
                detail.locator('summary').first.click()
            return c,p,revision
        def details(p,i):
            title=f'Example research project {i+1:02d}.'
            return p.locator('#experience-library details').filter(has=p.locator('summary',has_text=title)).first
        def manual(p):
            library=p.locator('#experience-library')
            field=library.get_by_label(LABEL)
            if not field.is_visible():library.get_by_text('Add an experience',exact=True).click()
            return library,field,library.get_by_role('button',name='Add for review',exact=True)
        def confirm(p,i):
            detail=details(p,i)
            detail.locator('summary').first.click()
            assert detail.locator('textarea').input_value()==TEXTS[i]
            detail.get_by_role('button',name='Confirm facts',exact=True).click()
            expect(detail.locator('summary').first).to_contain_text('Confirmed')
        c,_=fresh()
        p=app.home(c)
        p.locator('#student_name').fill(STUDENT)
        p.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)')
        p.locator('#major').select_option(label='Integrative Biology')
        p.locator('#grade').select_option(label='Sophomore')
        library,field,add=manual(p)
        for i in range(9):
            field.fill(TEXTS[i])
            add.click()
            expect(field).to_have_value('')
            confirm(p,i)
        await_cloud(p,lambda rows:len(rows)==9 and all(e['status']=='confirmed' for e in rows),'first nine')
        originals=ack[-1]
        assert [e['text'] for e in originals]==TEXTS[:9]
        c.close()
        c,p,old_revision=view(originals)
        library,field,add=manual(p)
        writes_before=len(writes)
        field.fill(TEXTS[9]+'续')
        add.click()
        expect(library.get_by_role('alert')).to_contain_text('6,000')
        assert field.input_value()==TEXTS[9]+'续'
        p.wait_for_timeout(1100)
        assert len(writes)==writes_before
        field.fill(TEXTS[9])
        outage=True
        add.click()
        expect(field).to_have_value('')
        for _ in range(120):
            if blocked:break
            p.wait_for_timeout(200)
        assert blocked
        witness,_,unchanged_revision=view(originals)
        assert unchanged_revision==old_revision
        witness.close()
        outage=False
        retry=p.get_by_test_id('retry-sync')
        for _ in range(200):
            if ack and len(ack[-1])==10:break
            if retry.is_visible():retry.click()
            p.wait_for_timeout(250)
        await_cloud(p,lambda rows:len(rows)==10,'retry tenth')
        saved=ack[-1]
        assert saved[:9]==originals and saved[-1]['text']==TEXTS[-1] and saved[-1]['status']=='candidate'
        count=len(writes)
        field.fill('补')
        add.click()
        expect(library.get_by_role('alert')).to_contain_text('60,000')
        assert field.input_value()=='补'
        p.wait_for_timeout(1100)
        assert len(writes)==count
        c.close()
        c,p,saved_revision=view(saved)
        confirm(p,9)
        await_cloud(p,lambda rows:len(rows)==10 and all(e['status']=='confirmed' for e in rows),'final confirmation')
        final=ack[-1]
        assert final[:9]==originals and final[-1]['id']==saved[-1]['id'] and final[-1]['revision']>saved[-1]['revision']
        c.close()
        c,p,final_revision=view(final)
        assert final_revision>saved_revision>old_revision
        OUTPUT.update({
            'site':'https://joinalab.com/','inputs_entered_through_normal_form':10,
            'length_per_entry_unicode_codepoints':[len(s) for s in TEXTS],
            'length_per_entry_utf16_units':[len(s.encode('utf-16-le'))//2 for s in TEXTS],
            'final_codepoints':sum(map(len,TEXTS)), 'all_ten_confirmed':True,
            'cloud_revision_nine':old_revision,'unchanged_while_offline':unchanged_revision,
            'cloud_revision_tenth_candidate':saved_revision,'cloud_revision_all_confirmed':final_revision,
            'older_nine_rows_ids_revisions_and_entire_text_unchanged':True,
            'single_6001_and_total_60001_refused_with_input_and_cloud_preserved':True,
            'all_ten_exact_texts_read_in_normal_controls_after_clean_browser':True,
            'client_simulated_disconnect':{'mode':'blocked only owned CAS in browser before sending',
                'attempts_blocked':len(blocked),'production_server_failure_observed':False,
                'real_post_reconnect_CAS_and_clean_browser_read_passed':True},
            'observed_own_write_http_statuses':sorted(set(post_status)),
            'final_synthetic_text_sha256':[hashlib.sha256(s.encode()).hexdigest() for s in TEXTS],
        })
        print('PROFILE_BOUNDARIES '+json.dumps(OUTPUT),flush=True)
        # Matching is free and deterministic. Restrict this extra check to the normal first-party action.
        responses=[]
        def matched(r):
            u=urlsplit(r.url)
            if u.hostname=='joinalab.com' and u.path in ('/api/matches','/api/matches/view') and r.request.method=='POST' and r.ok:
                d=r.request.post_data_json
                profile=d.get('profile',d)
                if profile.get('name')==STUDENT and profile.get('match_experiences'):responses.append((r.status,profile))
        p.on('response',matched)
        p.get_by_role('button',name='Generate Matches',exact=True).click()
        p.wait_for_url('**/results**',timeout=90000)
        for _ in range(300):
            if responses:break
            p.wait_for_timeout(250)
        assert responses,'first-party deterministic matching did not acknowledge full material'
        status,profile=responses[-1]
        matched_rows=profile['match_experiences']
        assert [(e['id'],e['revision'],e['text']) for e in matched_rows]==[(e['id'],e['revision'],e['text']) for e in final]
        assert all(e['source']=='manual' and e['status']=='confirmed' for e in matched_rows)
        OUTPUT['normal_deterministic_matching_request']={'http':status,'confirmed_entries':len(matched_rows),
            'full_codepoints':sum(len(e['text']) for e in matched_rows),'same_ID_revision_and_full_text_all_ten':True}
        OUTPUT['after']=release(http)
        OUTPUT['published_at']=datetime.now(timezone.utc).isoformat()
        print('VERIFIED_LONG_EXPERIENCE '+json.dumps(OUTPUT),flush=True)
        c.close();browser.close();http.dispose()

if __name__=='__main__':
    main()
