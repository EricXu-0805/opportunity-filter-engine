"""Official-site matching/receipt QA; one dedicated anonymous account, one synthetic work file, free drafts only."""
import json
import os
from urllib.parse import urlencode, urlsplit
from playwright.sync_api import expect, sync_playwright

site = 'https://joinalab.com'
db = 'mjpirkyduibkakvlbdko.supabase.co'
target = 'faculty-ib-78788e71'
public_title = 'Mark Jason Lara'
student = 'Synthetic habitat mapping check'
fact = 'I mapped public habitat survey records using GIS.'
csv = 'Company Name,Title,Started On,Finished On,Description,Results\nFictional Habitat Archive,Mapping assistant,2024,2025,"'+fact+'",Checked 30 synthetic map cells\n'
release = os.environ['OFE_EXPECTED_SITE_SHA']
auth = []
revisions = []

def record(r):
    p=urlsplit(r.url)
    if p.hostname!=db or not r.ok:return
    if p.path=='/auth/v1/signup':
        s=r.json();assert s['user']['is_anonymous'] is True and not auth;auth.append(s)
    elif p.path=='/rest/v1/rpc/commit_profile_patch_cas':
        ack=r.json()
        if ack.get('status')=='applied':revisions.append(ack['revision'])

def guard(route):
    r=route.request;p=urlsplit(r.url)
    if p.hostname not in ('joinalab.com',db):return route.abort()
    if r.method in ('GET','HEAD','OPTIONS'):return route.continue_()
    data=r.post_data_json or {}
    if r.method=='POST' and p.hostname==db:
        if p.path=='/auth/v1/signup' and not auth and not data.get('email'):return route.continue_()
        if p.path=='/auth/v1/token':return route.continue_()
        if p.path=='/rest/v1/rpc/commit_profile_patch_cas' and auth and data.get('p_expected_device_id')==auth[0]['user']['id']:
            return route.continue_()
    if r.method=='POST' and p.hostname=='joinalab.com':
        if p.path=='/api/matches/view' and 'llm=false' in p.query:return route.continue_()
        if p.path=='/api/cold-email/variants' and data.get('opportunity_id')==target and data.get('profile',{}).get('name')==student:return route.continue_()
    return route.abort()

def cold(browser):
    c=browser.new_context(locale='en-US',viewport={'width':1200,'height':850},service_workers='block')
    c.add_cookies([{'name':'ofe_lang','value':'en','url':site}])
    init={'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00.000Z'})}
    if auth:init['ofe_auth']=json.dumps(auth[0])
    c.add_init_script("if(location.origin==='https://joinalab.com'&&!localStorage.getItem('guest_test_ready')){for (const [k,v] of Object.entries("+json.dumps(init)+"))localStorage.setItem(k,v);localStorage.setItem('guest_test_ready','1')}")
    c.route('**/*',guard);c.on('response',record);return c

def home(ctx):
    p=ctx.new_page();p.goto(site,wait_until='domcontentloaded');p.locator('#student_name').wait_for(timeout=60000)
    for _ in range(180):
        if auth and not p.get_by_test_id('hydration-note').is_visible():break
        p.wait_for_timeout(300)
    assert auth
    choice=p.get_by_test_id('university-card-uiuc')
    if choice.is_visible():choice.click();p.get_by_test_id('switcher-confirm').click()
    return p

def results(ctx,confirmed):
    p=ctx.new_page()
    with p.expect_response(lambda r:urlsplit(r.url).path=='/api/matches/view' and r.ok and r.request.post_data_json['profile']['name']==student,timeout=125000) as seen:
        p.goto(site+'/results?'+urlencode({'tab':'all','q':public_title}),wait_until='domcontentloaded')
    res=seen.value;payload=res.request.post_data_json['profile'];listing={r['opportunity_id']:r for r in res.json()['results']}
    item=listing[target];basis=item.get('experience_basis')
    if confirmed:
        assert len(payload['match_experiences'])==1 and fact in payload['match_experiences'][0]['text']
        assert basis['entry_id']==payload['match_experiences'][0]['id'] and basis['revision']==payload['match_experiences'][0]['revision'] and basis['method']=='GIS' and basis['target_source']=='research_area'
        receipt=p.get_by_text('Experience used for this match · GIS');receipt.click()
        expect(p.get_by_text(payload['match_experiences'][0]['text'],exact=True)).to_be_visible()
        expect(p.get_by_text('LinkedIn · Confirmed by you',exact=False)).to_be_visible()
    else:
        assert not payload.get('match_experiences') and not basis
        expect(p.get_by_text('Experience used for this match · GIS')).to_have_count(0)
    p.close()
    return [item['final_score'],item['readiness_score'],item['eligibility_score']],(payload.get('match_experiences') or [None])[0]

def free_drafts(ctx,confirmed,entry=None):
    p=ctx.new_page();p.goto(site+'/opportunities/'+target,wait_until='domcontentloaded');results=[]
    p.on('response',lambda r:results.append(r) if urlsplit(r.url).path=='/api/cold-email/variants' else None)
    p.get_by_role('button',name='Draft email',exact=True).click(timeout=60000)
    for _ in range(150):
        if results:break
        regen=p.get_by_role('button',name='Regenerate from updated materials',exact=True)
        if not confirmed and regen.is_visible():regen.click();break
        p.wait_for_timeout(300)
    for _ in range(200):
        if results:break
        p.wait_for_timeout(300)
    assert len(results)==1 and results[0].ok, [r.status for r in results]
    variants=results[0].json()['variants'];assert len(variants)==3
    for v in variants:
        receipt=v['experience_usage']
        if confirmed:
            assert entry['text'] in v['body'] and any(row['id']==entry['id'] and row['excerpt']==entry['text'] for row in receipt['selected'])
        else:
            assert fact not in v['body'] and not receipt['selected'] and any(row['id']==entry['id'] and row['reason']=='rejected' for row in receipt['excluded'])
    p.close();return [v['id'] for v in variants]

with sync_playwright() as pw:
    b=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
    # Check deployment before creating the first-party anonymous QA account.
    probe=pw.request.new_context();assert probe.get(site+'/api/health').json()['release_sha']==release
    assert 'data-release-sha="'+release+'"' in probe.get(site+'/about').text();probe.dispose()
    c=cold(b);p=home(c);p.locator('#student_name').fill(student)
    p.locator('#college').select_option(label='Liberal Arts & Sciences (LAS)');p.locator('#major').select_option(label='Integrative Biology')
    p.locator('#grade').select_option(label='Junior');p.locator('#research_interests').fill('Ecology, wetlands, geospatial analysis.')
    p.wait_for_function("s=>Object.values(localStorage).some(v=>v.includes(s))",arg=student);p.wait_for_timeout(2500);c.close()
    c=cold(b);baseline,_=results(c,False);p=home(c);expect(p.locator('#student_name')).to_have_value(student)
    p.get_by_text('Import LinkedIn experience',exact=True).click()
    p.get_by_label('Positions.csv',exact=True).set_input_files({'name':'Positions.csv','mimeType':'text/csv','buffer':csv.encode()})
    p.get_by_role('button',name='Preview experiences').click();p.get_by_label('Choose what to save').select_option('new')
    latest=len(revisions);p.get_by_role('button',name='Confirm selected experiences').click()
    for _ in range(150):
        if len(revisions)>latest:break
        p.wait_for_timeout(250)
    assert len(revisions)>latest;c.close();c=cold(b)
    accepted,entry=results(c,True);assert accepted[0]>baseline[0] and accepted[1]>baseline[1] and accepted[2]==baseline[2]
    p=home(c)
    details=p.locator('#experience-library details').filter(has=p.locator('summary',has_text='Fictional Habitat Archive')).first
    details.locator('summary').first.click();entry_text=details.locator('textarea').input_value()
    assert all(x in entry_text for x in ['Fictional Habitat Archive','Mapping assistant','2024','2025',fact,'Checked 30 synthetic map cells'])
    assert entry['text']==entry_text
    accepted_drafts=free_drafts(c,True,entry)
    latest=len(revisions);details.get_by_role('button',name='Do not use',exact=True).click()
    for _ in range(150):
        if len(revisions)>latest:break
        p.wait_for_timeout(250)
    assert len(revisions)>latest;c.close();c=cold(b);after,_=results(c,False);assert after==baseline
    withdrawn_drafts=free_drafts(c,False,entry);assert set(accepted_drafts)==set(withdrawn_drafts)
    print(json.dumps({'release_sha':release,'live_actual_results_and_cloud_auth':True,'synthetic_own_linkedin_file':True,'target':target,'score_readiness_eligibility':[baseline,accepted,after],'confirmed_templates_with_entire_source':accepted_drafts,'new_templates_after_withdrawal_without_source':withdrawn_drafts,'own_cloud_revisions':revisions,'external_messages_sent':0}))
    c.close();b.close()
