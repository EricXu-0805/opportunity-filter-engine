"""Normal first-party anonymous profile upload and fresh 390px read. Synthetic data only."""
from datetime import datetime, timezone
import json, time, sys
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

site = 'https://joinalab.com'
db_host = 'mjpirkyduibkakvlbdko.supabase.co'
marker = 'I checked synthetic sensor measurements.'
skill_case = '--independent-github-skill' in sys.argv
repo_evidence = []
email_case = '--historical-email' in sys.argv
template_reads = 0
listing_id = 'simplify-intern-3ea65aaa-0297-4b8f-9378-51e35478fb95'
if skill_case: marker += ' PyTorch'
receipt = {'site':site,'only_synthetic_guest':True,'viewports':[],'started':datetime.now(timezone.utc).isoformat()}
records = []
auth_sessions = []
commits = []
own_case = '--own-removal' in sys.argv
conflict_case = own_case or '--retain-resume' in sys.argv
allow_synthetic_removal = False
protected_text = None
protected_courses = None
baseline_entry = 'I recorded an independent synthetic control measurement.'
protect_entry = False
local_outage = False
blocked = 0

def capture(r):
    u=urlsplit(r.url)
    if u.hostname=='joinalab.com' and r.status==200 and u.path=='/api/resume/github/pytorch':
        repo_evidence.extend(e for e in r.json().get('skill_evidence',[]) if e['skill']=='PyTorch')
    if u.hostname != db_host or r.status!=200: return
    if u.path.endswith('/auth/v1/signup'):
        session=r.json()
        assert session.get('user',{}).get('is_anonymous')==True
        auth_sessions.append(session)
    if u.path=='/rest/v1/profiles' and r.request.method=='GET':
        rows=r.json()
        row=rows[0] if isinstance(rows,list) and rows else rows
        if isinstance(row,dict) and row.get('profile_data'):
            records.append((row.get('revision'),row['profile_data']))
    if u.path.endswith('/rpc/commit_profile_patch_cas') and r.request.method=='POST':
        a=r.json()
        if a.get('status')=='applied': commits.append(a['revision'])

def guard(route):
    global blocked,template_reads
    r=route.request; u=urlsplit(r.url)
    if u.hostname not in ('joinalab.com',db_host): return route.abort()
    if r.method in ('GET','HEAD','OPTIONS'):return route.continue_()
    if u.hostname==db_host and u.path in ('/auth/v1/signup','/auth/v1/token','/rest/v1/rpc/commit_profile_patch_cas'):
        if u.path.endswith('signup'):assert not auth_sessions and not (r.post_data_json or {}).get('email')
        if u.path.endswith('/rpc/commit_profile_patch_cas'):
            assert auth_sessions and r.post_data_json['p_expected_device_id']==auth_sessions[0]['user']['id']
            d=r.post_data_json['p_patch']
            if local_outage:
                return route.fulfill(status=503,headers={'access-control-allow-origin':site},json={'message':'temporary local outage'})
            allowed_text = (protected_text, None, '') if allow_synthetic_removal else (protected_text,)
            allowed_courses = (protected_courses, []) if allow_synthetic_removal else (protected_courses,)
            if protected_text is not None and (('resume_text' in d and d['resume_text'] not in allowed_text) or ('coursework' in d and d['coursework'] not in allowed_courses) or (protect_entry and 'experience_entries' in d and not any(x.get('text')==baseline_entry for x in d['experience_entries']))):
                blocked+=1
                return route.abort()
        return route.continue_()
    if u.hostname=='joinalab.com' and r.method=='POST':
        if u.path=='/api/events':return route.continue_()
        if email_case and u.path=='/api/cold-email/variants':
            body=r.post_data_json
            assert body['opportunity_id']==listing_id and body['profile']['name']=='Synthetic PDF check'
            template_reads+=1
            return route.continue_()
    return route.abort()

def prepare(ctx, lang, session=None):
    ctx.add_cookies([{'name':'ofe_lang','value':lang,'url':site}])
    values={'ofe_onboarding_seen':'1','ofe_lang':lang}
    if session is not None: values['ofe_auth']=json.dumps(session)
    ctx.add_init_script("if(location.origin==='https://joinalab.com'&&!localStorage.getItem('receipt_context')){for(const [k,v] of Object.entries("+json.dumps(values)+"))localStorage.setItem(k,v);localStorage.setItem('receipt_context','1')}")
    ctx.route('**/*',guard)
    ctx.on('response',capture)
def go(p):
    p.goto(site+'/',wait_until='domcontentloaded',timeout=65000)
    p.locator('#student_name').wait_for(timeout=55000)

with sync_playwright() as pw:
    b=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
    ctx=b.new_context(viewport={'width':390,'height':844},locale='en-US',service_workers='block')
    prepare(ctx,'en')
    p=ctx.new_page();p.set_default_timeout(30000)
    try:
        go(p)
        for _ in range(80):
            p.wait_for_timeout(200)
            if auth_sessions and not p.get_by_test_id('hydration-note').is_visible(): break
        assert len(auth_sessions)==1
        uiuc=p.get_by_test_id('university-card-uiuc')
        if uiuc.is_visible():
            uiuc.click();p.get_by_test_id('switcher-confirm').click()
        p.locator('#student_name').fill('Synthetic PDF check')
        p.locator('#college').select_option(label='Grainger College of Engineering')
        p.locator('#major').select_option(label='Computer Science')
        p.locator('#grade').select_option(label='Sophomore')
        doc=b.new_page();doc.set_content('<p>Research assistant</p><p>'+marker+'</p><p>Coursework: ECE 220</p>')
        pdf=doc.pdf();doc.close()
        up=p.locator('input[type=file][accept*="pdf"]').first
        up.set_input_files({'name':'synthetic-research-resume.pdf','mimeType':'application/pdf','buffer':pdf})
        expect(p.get_by_role('button',name='Remove file',exact=True)).to_be_visible(timeout=55000)
        for _ in range(40):
            p.wait_for_timeout(350)
            if commits: break
        assert commits
        print('An anonymous guest registered through the site and used the PDF picker',flush=True)
        for lang in ('en','zh'):
            cold=b.new_context(viewport={'width':390,'height':844},locale='en-US' if lang=='en' else 'zh-CN',service_workers='block')
            prepare(cold,lang,auth_sessions[0])
            records.clear()
            pg=cold.new_page();go(pg)
            expect(pg.locator('#student_name')).to_have_value('Synthetic PDF check',timeout=35000)
            expect(pg.get_by_role('button',name='Remove file' if lang=='en' else '移除文件',exact=True)).to_be_visible(timeout=35000)
            assert pg.evaluate('innerWidth')==390
            matched=[(rev,d) for rev,d in records if marker in (d.get('resume_text') or '') and '220' in str(d.get('coursework'))]
            assert matched,'fresh browser did not read PDF and ECE 220 from production'
            receipt['viewports'].append({'language':lang,'width':390,'profile_revision':matched[-1][0],'synthetic_pdf_text':True,'coursework_read':True,'attachment_badge':True})
            if (conflict_case or skill_case) and lang=='zh':
                protected_text=matched[-1][1]['resume_text']
                protected_courses=matched[-1][1]['coursework']
                actual_headers={}
                def observe(r):
                    u=urlsplit(r.url)
                    if r.method=='GET' and u.hostname==db_host and u.path=='/rest/v1/profiles':
                        actual_headers.update({k:v for k,v in r.headers.items() if k in ('authorization','apikey')})
                cold.on('request',observe)
                pg.reload(wait_until='domcontentloaded')
                expect(pg.get_by_role('button',name='移除文件',exact=True)).to_be_visible()
                def read_owned():
                    assert len(actual_headers)==2
                    target='https://'+db_host+'/rest/v1/profiles?select=profile_data,revision&id=eq.'+auth_sessions[0]['user']['id']
                    row=cold.request.get(target,headers=actual_headers)
                    assert row.status==200
                    return row.json()[0]
                def select_campus_if_needed(tab):
                    tab.bring_to_front()
                    selection=tab.get_by_test_id('university-card-uiuc')
                    if selection.is_visible():
                        selection.click(); tab.get_by_test_id('switcher-confirm').click()
                        expect(selection).to_be_hidden()
                def add_entry(tab,text):
                    select_campus_if_needed(tab)
                    entry=tab.locator('#experience-library details').last
                    if not entry.locator('textarea').is_visible():entry.locator('summary').click()
                    expect(entry.locator('textarea')).to_be_visible()
                    entry.locator('textarea').fill(text)
                    entry.get_by_role('button').click()
                    expect(tab.locator('#experience-library summary').get_by_text(text,exact=True)).to_be_visible()
                if skill_case:
                    select_campus_if_needed(pg)
                    def by_name(d,n):return next((x for x in d.get('skills',[]) if x['name']==n),None)
                    before=read_owned()['profile_data']
                    assert by_name(before,'PyTorch')['source']=='resume' and before['name']=='Synthetic PDF check' and marker in before['resume_text']
                    github=pg.locator('#github_url')
                    github.fill('https://github.com/pytorch')
                    github.locator('..').get_by_role('button').click()
                    for _ in range(80):
                        pg.wait_for_timeout(250)
                        mid=read_owned()
                        if repo_evidence and by_name(mid['profile_data'],'Python'):break
                    assert repo_evidence and by_name(mid['profile_data'],'Python')['source']=='github'
                    assert not by_name(mid['profile_data'],'PyTorch').get('confirmed')
                    historical='--historical-tailor' in sys.argv
                    if historical:
                        sample='I manually documented a second synthetic experiment.'
                        active_target='/opportunities/simplify-intern-3ea65aaa-0297-4b8f-9378-51e35478fb95'
                        def draft():
                            target=cold.new_page()
                            target.goto(site+active_target,wait_until='domcontentloaded')
                            target.get_by_role('button',name='定制简历',exact=True).click(timeout=35000)
                            editor=target.locator('#tailor-bullets-input')
                            expect(editor).to_be_visible(timeout=30000)
                            return target,editor
                        target,editor=draft()
                        editor.fill(sample)
                        target.wait_for_function("v=>Object.values(localStorage).filter(s=>s.includes(v)).some(s=>{try{const d=JSON.parse(s);return d.text===v && Boolean(d.origin?.binding)}catch{return false}})",arg=sample,timeout=30000)
                        target.close()
                        old,editor=draft()
                        expect(editor).to_have_value(sample)
                        expect(old.get_by_text('正在核对草稿来源…')).to_have_count(0,timeout=30000)
                        expect(old.get_by_test_id('tailor-draft-review')).to_have_count(0)
                        expect(old.get_by_test_id('tailor-stale-draft')).to_have_count(0)
                        old.close()
                    if email_case:
                        subject='Synthetic historical subject'
                        message='I wrote these three lines myself for an unsent synthetic draft.'
                        changed='资料或目标信息已更新，主题、正文和收件人已保留。点击重新生成才会替换文稿。'
                        def email():
                            target=cold.new_page()
                            target.goto(site+'/opportunities/'+listing_id,wait_until='domcontentloaded')
                            target.get_by_role('button',name='起草邮件',exact=True).click(timeout=35000)
                            expect(target.locator('#cold-email-body')).to_be_visible(timeout=35000)
                            return target
                        letter=email()
                        letter.locator('#cold-email-subject').fill(subject)
                        letter.locator('#cold-email-body').fill(message)
                        letter.wait_for_function('v=>Object.values(localStorage).some(s=>s.includes(v))',arg=message,timeout=12000)
                        letter.close()
                        letter=email()
                        expect(letter.locator('#cold-email-subject')).to_have_value(subject)
                        expect(letter.locator('#cold-email-body')).to_have_value(message)
                        expect(letter.get_by_text(changed,exact=True)).to_have_count(0)
                        letter.close()
                    allow_synthetic_removal=True
                    pg.get_by_role('button',name='移除文件',exact=True).click()
                    expect(pg.get_by_role('button',name='移除文件',exact=True)).to_have_count(0)
                    for _ in range(60):
                        pg.wait_for_timeout(200)
                        final=read_owned()
                        if not final['profile_data'].get('resume_text'):break
                    assert not final['profile_data'].get('resume_text') and by_name(final['profile_data'],'Python')
                    pg.reload(wait_until='domcontentloaded')
                    expect(pg.locator('#student_name')).to_have_value('Synthetic PDF check')
                    raw=read_owned()
                    assert raw==final
                    surviving=by_name(raw['profile_data'],'PyTorch')
                    if '--expect-retained' in sys.argv:
                        assert surviving and surviving['source']=='github' and repo_evidence[0]['repo'] in surviving['evidence'] and not surviving.get('confirmed'),surviving
                    else: assert surviving is None,surviving
                    if historical:
                        target,editor=draft()
                        expect(editor).to_have_value(sample)
                        expect(target.get_by_text('正在核对草稿来源…')).to_have_count(0,timeout=30000)
                        expect(target.get_by_test_id('tailor-stale-draft')).to_be_visible(timeout=15000)
                        receipt['historical_tailor']={'target':active_target,'author_text_unchanged':True,'before_removal_stale_badges':0,'after_removal_stale_badges':1,'ai_generations':0,'handwritten_text_entered_in_form':True}
                        target.close()
                    if email_case:
                        letter=email()
                        expect(letter.locator('#cold-email-subject')).to_have_value(subject)
                        expect(letter.locator('#cold-email-body')).to_have_value(message)
                        expect(letter.get_by_text(changed,exact=True)).to_be_visible(timeout=20000)
                        receipt['historical_email']={'subject_and_handwritten_body_retained':True,'revision_before_pdf_removal':mid['revision'],'revision_after_pdf_removal':raw['revision'],'newly_shown_review_notice':True,'free_template_reads':template_reads,'email_open_or_send_actions':0}
                        letter.close()
                    receipt['independent_skill']={'legacy_source':'resume','github_import':repo_evidence[0],'detail_after_import':by_name(mid['profile_data'],'PyTorch'),'other_github_skill_retained':'Python','after_removal':surviving,'revision_after_import':mid['revision'],'revision_after_removal':raw['revision'],'fresh_read':True}
                    cold.close()
                    continue
                add_entry(pg,baseline_entry)
                for _ in range(50):
                    row=read_owned()
                    if any(e.get('text')==baseline_entry for e in row['profile_data'].get('experience_entries',[])):break
                    pg.wait_for_timeout(250)
                assert any(e.get('text')==baseline_entry for e in row['profile_data']['experience_entries'])
                protect_entry=True
                initial_revision=row['revision']
                other=cold.new_page();go(other)
                remove=other.get_by_role('button',name='移除文件',exact=True);expect(remove).to_be_visible()
                select_campus_if_needed(other)
                local_outage=True
                cold.set_offline(True)
                add_entry(pg,'I independently rechecked the synthetic sensor calibration.')
                remove.click();expect(remove).to_be_hidden()
                cold.set_offline(False)
                local_outage=False
                for tab in (pg,other):
                    tab.bring_to_front()
                    retry=tab.get_by_test_id('retry-sync')
                    if not tab.get_by_test_id('conflict-keep-mine').is_visible() and retry.is_visible():retry.click(timeout=2500)
                if own_case:
                    use=other.get_by_test_id('conflict-keep-mine')
                else:
                    use=pg.get_by_test_id('conflict-use-cloud')
                expect(use).to_be_visible(timeout=25000)
                before=read_owned()['profile_data']
                assert before['name']=='Synthetic PDF check' and marker in before['resume_text'] and before['resume_text']==protected_text
                assert before['coursework']==protected_courses and auth_sessions[0]['user']['is_anonymous']
                allow_synthetic_removal=own_case
                use.click()
                for tab in (pg,other):
                    expect(tab.get_by_test_id('conflict-keep-mine')).to_have_count(0,timeout=25000)
                    badge=tab.get_by_role('button',name='移除文件',exact=True)
                    if own_case: expect(badge).to_have_count(0,timeout=25000)
                    else: expect(badge).to_be_visible(timeout=25000)
                follow='I repeated a synthetic control measurement after resolving the conflict.'
                add_entry(pg if own_case else other,follow)
                for _ in range(50):
                    final=read_owned()
                    if any(e.get('text')==follow for e in final['profile_data']['experience_entries']):break
                    pg.wait_for_timeout(250)
                if own_case:
                    assert not final['profile_data'].get('resume_text') and not final['profile_data'].get('coursework')
                else:
                    assert final['profile_data']['resume_text']==protected_text and final['profile_data']['coursework']==protected_courses
                assert final['profile_data']['name']=='Synthetic PDF check'
                assert all(any(e.get('text')==n for e in final['profile_data']['experience_entries']) for n in (follow,baseline_entry))
                for tab in (pg,other):
                    tab.reload(wait_until='domcontentloaded')
                    expect(tab.locator('#student_name')).to_have_value('Synthetic PDF check')
                    badge=tab.get_by_role('button',name='移除文件',exact=True)
                    if own_case: expect(badge).to_have_count(0)
                    else: expect(badge).to_be_visible()
                    expect(tab.locator('#experience-library summary').get_by_text(follow,exact=True)).to_be_visible()
                assert read_owned()==final
                receipt['own_resume_conflict' if own_case else 'retain_conflict']={'language':'zh','width':390,'first_choice':'keep my removal' if own_case else 'use cloud','initial_revision':initial_revision,'final_revision':final['revision'],'expected_text_and_courses_after_choice':True,'unrelated_prior_manual_entry_retained':True,'peer_badge_before_reload':True,'reloads':2,'blocked_online_clears':blocked}
            cold.close()
        assert len(auth_sessions)==1
        receipt['applied_revisions']=commits
        print('PUBLIC RECEIPT',json.dumps(receipt),flush=True)
    finally:
        b.close()
