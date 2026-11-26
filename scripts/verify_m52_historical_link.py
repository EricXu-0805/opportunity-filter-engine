"""Run the real V1 share creator and recipient with disposable signed-in accounts."""
import asyncio, base64, json, sys, uuid
from urllib import request
from urllib.parse import parse_qs, urlsplit
from playwright.async_api import async_playwright, expect

site='http://127.0.0.1:3100'
db='http://127.0.0.1:54321'
settings=json.load(open(sys.argv[1]))
assert settings['API_URL']==db

def req(path, body=None, session=None):
    headers={'apikey':settings['ANON_KEY'],'content-type':'application/json'}
    if session: headers['authorization']='Bearer '+session['access_token']
    http=request.Request(db+path,headers=headers,data=None if body is None else json.dumps(body).encode())
    with request.urlopen(http,timeout=20) as response: return json.load(response)

def account(name,school,interests,*,college='Grainger College of Engineering',major='Computer Science'):
    s=req('/auth/v1/signup',{'email':str(uuid.uuid4())+'@example.com','password':str(uuid.uuid4())+'!a1'})
    user=s['user']; assert user['is_anonymous'] is False
    profile={'name':name,'home_school':school,'search_weight':50,'college':college,
      'major':major,'institution':school,'grade':'Sophomore','research_interests':interests,
      'skills':[{'name':'PyTorch','level':'experienced','source':'github','evidence':'private line from owner'}],
      'resume_text':'private résumé text from '+name,'coursework':[],'seeking_types':['research'],'is_international':False}
    response=req('/rest/v1/rpc/commit_profile_patch_cas',{'p_expected_device_id':user['id'],'p_expected_revision':0,'p_patch':profile},s)
    assert response['status']=='applied'
    return s
def row(s):return req('/rest/v1/profiles?select=profile_data,revision&id=eq.'+s['user']['id'],session=s)[0]

async def main():
    a=account('Author QA','uiuc','Original materials QA')
    b=account('Recipient QA','purdue','Private recipient interests')
    assert a['user']['id']!=b['user']['id']
    async with async_playwright() as pw:
        chrome=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        async def tab(s,school):
            ctx=await chrome.new_context(permissions=['clipboard-read','clipboard-write'],service_workers='block',locale='en-US')
            local={'ofe_auth':json.dumps(s),'ofe_lang':'en','ofe_onboarding_seen':'1',
                   'ofe_school_confirmed':json.dumps({'slug':school,'ts':'2026-11-26T00:00:00.000Z'})}
            await ctx.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('m52qa')){for(const [k,v] of Object.entries("+json.dumps(local)+"))localStorage.setItem(k,v);localStorage.setItem('m52qa','1')}")
            p=await ctx.new_page();await p.goto(site,wait_until='domcontentloaded')
            await expect(p.locator('#student_name')).to_have_value(row(s)['profile_data']['name'],timeout=60000)
            return p
        author=await tab(a,'uiuc')
        recipient=await tab(b,'purdue')
        share=author.get_by_role('button',name='Share profile',exact=True)
        await share.click()
        await author.wait_for_function("async ()=>(await navigator.clipboard.readText()).includes('?share=')")
        url=await author.evaluate('navigator.clipboard.readText()')
        parsed=urlsplit(url);assert parsed.hostname=='127.0.0.1' and parsed.path=='/'
        encoded=parse_qs(parsed.query)['share'][0]
        wire=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        assert wire['v']==1 and wire['interests']=='Original materials QA' and wire['skills']==[{'n':'PyTorch','l':'experienced'}]
        assert not any(k in wire for k in ['token','expires_at','name','resume_text','github_url'])
        assert 'private line from owner' not in str(wire)
        await author.locator('#research_interests').fill('Changed after issuing QA link')
        for _ in range(120):
            if row(a)['profile_data']['research_interests']=='Changed after issuing QA link':break
            await asyncio.sleep(.2)
        assert row(a)['profile_data']['research_interests']=='Changed after issuing QA link'
        before=row(b);await recipient.goto(url,wait_until='domcontentloaded')
        await expect(recipient.locator('#research_interests')).to_have_value('Original materials QA')
        await expect(recipient.get_by_role('button',name='Dismiss',exact=True)).to_be_visible()
        assert row(b)==before
        await recipient.get_by_role('button',name='Dismiss',exact=True).click()
        assert row(b)==before
        await recipient.goto(site,wait_until='domcontentloaded')
        await expect(recipient.locator('#research_interests')).to_have_value('Private recipient interests')
        await recipient.goto(url,wait_until='domcontentloaded')
        await expect(recipient.locator('#research_interests')).to_have_value('Original materials QA')
        writes=[]
        def observe(response):
            if response.request.method=='POST' and 'commit_profile_patch_cas' in response.url:
                data=response.request.post_data_json
                writes.append((response.status,data.get('p_expected_revision'),sorted(data.get('p_patch',{}))))
        recipient.on('response',observe)
        print('Old URL contains only the public fields; independent edit did not change old link; views/dismissal made zero writes.',flush=True)
        await recipient.get_by_test_id('generate-matches').click(timeout=40000)
        choices=0
        for _ in range(160):
            keep=recipient.get_by_test_id('conflict-keep-mine')
            if await keep.is_visible() and choices==0:
                await keep.click()
                choices+=1
            r=row(b)
            if r['profile_data']['research_interests']=='Original materials QA':break
            await asyncio.sleep(.2)
        if r['profile_data']['research_interests']!='Original materials QA':
            print('Recipient diagnostics:',recipient.url.split('?')[0],writes,
              await recipient.locator('[role=status],[role=alert]').all_inner_texts(),
              await recipient.get_by_test_id('conflict-keep-mine').count(),flush=True)
            print('Recipient synthetic displayed school/profile:', await recipient.locator('#research_interests').input_value() if await recipient.locator('#research_interests').count() else None,flush=True)
        assert r['profile_data']['research_interests']=='Original materials QA'
        assert r['profile_data']['home_school']=='purdue' and r['profile_data']['name']=='Recipient QA'
        assert r['profile_data']['resume_text']=='private résumé text from Recipient QA'
        assert r['profile_data']['skills']==[{'name':'PyTorch','level':'experienced','source':'shared'}]
        print('ISOLATED RECEIPT',json.dumps({'normal_creator':'Share profile button to Chromium clipboard','wire_version':1,'self_contained_keys':sorted(wire),'publisher_changed_after_copy':True,'original_link_remained_identical':True,'recipient_view_and_dismiss_stored_writes':0,'normal_accept_action':'Generate Matches','recipient_explicit_conflict_answers':choices,'recipient_home_school_retained':'purdue','recipient_name_and_resume_preserved':True,'shared_skill_requires_own_confirmation':True,'recipient_revisions':[before['revision'],r['revision']]}),flush=True)
        await chrome.close()
if __name__ == '__main__':
    asyncio.run(main())
