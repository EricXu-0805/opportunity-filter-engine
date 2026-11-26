"""Actual browser -> app -> GoTrue/PostgREST. Only the extraction provider uses synthetic answers."""
import asyncio
import json
import re
import sys
from urllib.parse import urlsplit, unquote, quote
from urllib import request

TITLE = 'Synthetic campus archive fellowship'
ORG = 'Fictional Campus Archive'
SOURCE1 = TITLE + ' at ' + ORG + '. Review historical catalog records and learn to document archives. First source sentence.'
SOURCE2 = TITLE + ' at ' + ORG + '. Second revision. ' + ('Archive catalog calibration notes. ' * 150) + 'Distinct final source sentence.'

if '--serve' in sys.argv:
    import tempfile
    from pathlib import Path
    import uvicorn
    from backend import data_loader
    from backend.lib import llm
    # Private imports are owned by the real local account database. The public
    # matching corpus is irrelevant to these flows; use the existing public fixture.
    corpus=tempfile.TemporaryDirectory()
    data_loader.DATA_DIR=Path(corpus.name)
    (data_loader.DATA_DIR/'opportunities.json').write_bytes(Path('product/frontend/e2e/fixtures/actionable-listing.json').read_bytes())
    def extract(messages, **options):
        assert len(messages) == 2 and TITLE in messages[1]['content']
        return json.dumps({'title': TITLE, 'organization': ORG, 'description': 'Archive work, unverified.', 'opportunity_type':'fellowship'})
    llm.is_configured = lambda: True
    llm.chat_completion = extract
    from backend.main import app
    uvicorn.run(app, host='127.0.0.1', port=8100, log_level='warning')
    sys.exit()

from playwright.async_api import async_playwright, expect
from verify_m52_historical_link import account, req, site

async def audit():
    owner = account('Private Opportunity QA', 'uiuc', 'Archive databases and documentary research')
    def records(session=owner):
        # The table is intentionally not a browser surface. Read the ordinary owner's API.
        base='http://127.0.0.1:8100/api/private-import-targets'
        query='?expected_owner_id='+session['user']['id']
        def get(path):
            with request.urlopen(request.Request(base+path+query,headers={'Authorization':'Bearer '+session['access_token']}),timeout=12) as res:
                return json.load(res)
        return [get('/'+quote(item['id'],safe=''))['target'] for item in get('')['items']]
    async with async_playwright() as pw:
        b=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        async def fresh(session,name):
            ctx=await b.new_context(locale='en-US',service_workers='block')
            local={'ofe_auth':json.dumps(session),'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00.000Z'})}
            await ctx.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('qa-import-init')){for(const [k,v] of Object.entries("+json.dumps(local)+"))localStorage.setItem(k,v);localStorage.setItem('qa-import-init','1')}")
            await ctx.route('**/*',lambda r:r.continue_() if urlsplit(r.request.url).hostname in ('localhost','127.0.0.1') else r.abort())
            p=await ctx.new_page();await p.goto(site,wait_until='domcontentloaded')
            await expect(p.locator('#student_name')).to_have_value(name,timeout=75000)
            return ctx,p
        c,p=await fresh(owner,'Private Opportunity QA')
        events=[]
        def listen(p):
            p.on('response',lambda r:events.append((r.request.method,urlsplit(r.url).path,r.status)) if '/api/' in r.url else None)
        listen(p)
        def stage(label):print('STAGE',label,flush=True)
        button=lambda s:p.get_by_role('button',name=s,exact=True)
        async def imports():
            return await p.evaluate("JSON.parse(localStorage.getItem('ofe_custom_imports')||'[]')")
        async def paste(source,scope):
            await p.goto(site+'/import',wait_until='domcontentloaded')
            tab=p.get_by_role('tab',name='By text',exact=True)
            box=p.get_by_placeholder('Paste the full posting',exact=False)
            # In Next development the account's first hydration can remount this
            # tab; wait for the actual mode control to respond before entering input.
            for _ in range(8):
                await tab.click(timeout=25000)
                try:
                    await expect(box).to_be_visible(timeout=1700)
                    break
                except AssertionError:pass
            await box.fill(source)
            async with p.expect_response(lambda r:urlsplit(r.url).path=='/api/import-text',timeout=50000) as got:
                await button('Extract with AI').click()
            r=await got.value;payload=await r.json()
            assert r.ok and payload['ok'],(r.status,payload)
            item=payload['opportunity']
            assert item['title']==TITLE and item['organization']==ORG and item['description_raw']==source
            assert item['extra_fields']['ai_input_scope']==scope,(item['extra_fields'],len(source))
        try:
            stage('normal paste, browser save and cloud create')
            assert records()==[]
            await paste(SOURCE1,'full_source')
            await button('Save in this browser').click()
            await expect(button('Review save to account')).to_be_visible()
            local=(await imports())[0]
            assert records()==[] and local['opportunity']['description_raw']==SOURCE1
            await button('Review save to account').click()
            await button('Save to account').click(timeout=35000)
            dest=p.get_by_role('link',name='View records',exact=True).first
            await expect(dest).to_be_visible(timeout=45000)
            path=await dest.get_attribute('href')
            first,=records();uid=first['id'];assert unquote(path.split('/')[-1])==uid and first['revision']==1
            stage('count only one on device with both copies of that same opportunity')
            await p.goto(site+'/favorites',wait_until='domcontentloaded')
            await expect(p.get_by_text('1 saved',exact=True)).to_be_visible(timeout=40000)
            await expect(p.get_by_role('link',name='View records',exact=True)).to_be_visible()
            await p.goto(site+'/dashboard',wait_until='domcontentloaded')
            await expect(p.get_by_test_id('saved-summary').locator('p').first).to_have_text('1',timeout=40000)
            stage('reimport preserves browser and account provenance until confirmation')
            await paste(SOURCE2,'source_excerpt')
            await button('Review saved import update').click()
            await expect(button('Confirm update')).to_be_visible()
            assert (await imports())[0]['opportunity']['description_raw']==SOURCE1 and records()==[first]
            await button('Confirm update').click()
            await expect(button('Review save to account')).to_be_visible()
            revised,=await imports()
            assert revised['id']==local['id'] and revised['opportunity']['description_raw']==SOURCE2 and records()==[first]
            await button('Review save to account').click()
            failure=[]
            async def fail_once(route):
                if route.request.method=='PUT' and not failure:
                    failure.append(True);await route.fulfill(status=503,content_type='application/json',body='{"detail":"simulated unavailable before persistence"}')
                else:await route.continue_()
            await p.route('**/api/private-import-targets/**',fail_once)
            await button('Update account copy').click(timeout=30000)
            await expect(button('Read current copies again')).to_be_visible(timeout=35000)
            assert failure==[True] and records()==[first] and (await imports())[0]==revised
            await button('Read current copies again').click()
            await button('Update account copy').click(timeout=35000)
            await expect(p.get_by_role('link',name='View records',exact=True).first).to_be_visible(timeout=40000)
            latest,=records()
            assert latest['id']==uid and latest['revision']==2 and latest['opportunity']['description_raw']==SOURCE2
            # An independent live writer on this disposable account now changes
            # the exact revision the open UI reviewed. Raw source must survive
            # the losing request until the person explicitly rereads and confirms.
            proposed=SOURCE2+' New offline note to review.'
            await paste(proposed,'source_excerpt')
            await button('Review saved import update').click()
            await button('Confirm update').click()
            await button('Review save to account').click()
            await expect(button('Update account copy')).to_be_visible(timeout=40000)
            other_source=dict(latest['opportunity']);other_source['description_raw']=SOURCE1+' Other authorized device revision.'
            conflict_body={'expected_owner_id':owner['user']['id'],'expected_revision':2,'opportunity':other_source}
            competing=request.Request('http://127.0.0.1:8100/api/private-import-targets/'+quote(uid,safe=''),method='PUT',data=json.dumps(conflict_body).encode(),headers={'Authorization':'Bearer '+owner['access_token'],'Content-Type':'application/json'})
            with request.urlopen(competing,timeout=20) as res:
                rival=json.load(res)['target'];assert rival['revision']==3
            await button('Update account copy').click()
            await expect(p.get_by_text('This account copy changed. Read it again before confirming.',exact=True)).to_be_visible(timeout=45000)
            assert records()==[rival] and (await imports())[0]['opportunity']['description_raw']==proposed
            await button('Read current copies again').click()
            await button('Update account copy').click(timeout=40000)
            await expect(p.get_by_role('link',name='View records',exact=True).first).to_be_visible(timeout=40000)
            latest,=records();assert latest['revision']==4 and latest['id']==uid and latest['opportunity']['description_raw']==proposed
            stage('fresh browser, account list, original source, free private draft')
            await c.close();c,p=await fresh(owner,'Private Opportunity QA');listen(p)
            assert (await imports())==[]
            await p.goto(site+'/favorites',wait_until='domcontentloaded')
            await expect(p.get_by_role('heading',name='Imports in your account')).to_be_visible()
            link=p.get_by_role('link',name='View records',exact=True)
            await expect(link).to_have_attribute('href',path,timeout=60000)
            await link.click()
            await expect(p.get_by_role('heading',name=TITLE,exact=True)).to_be_visible(timeout=60000)
            await p.get_by_text('Full imported text',exact=True).click()
            await expect(p.get_by_text(proposed,exact=True)).to_be_visible()
            await expect(p.get_by_text('Imported content — not independently verified.',exact=False)).to_be_visible()
            async with p.expect_response(lambda r:'/cold-email/variants' in r.url,timeout=65000) as gen:
                await button('Prepare email').click(timeout=35000)
            r=await gen.value;draft=await r.json()
            assert r.ok and 'private-import-targets/' in r.url,(r.status,draft)
            v,=draft['variants'];assert v['id']=='private-first-contact' and v['subject'] and v['body']
            await expect(p.locator('#cold-email-body')).not_to_have_value('')
            recipient=draft['recipient_status'];assert recipient=='unavailable' and not draft['recipient_email'] and not v['mailto_link'] and draft['method']=='template'
            hand_edit='Personal draft for disposable records. No email was sent.'
            await p.locator('#cold-email-body').fill(hand_edit)
            await expect(p.get_by_test_id('cold-email-draft-status')).to_contain_text('Saved on this browser',timeout=45000)
            await button('Close email editor').click()
            await button('Prepare email').click()
            await expect(p.locator('#cold-email-body')).to_have_value(hand_edit,timeout=45000)
            stage('private résumé workspace')
            await p.goto(site+path,wait_until='domcontentloaded')
            await button('Prepare résumé').click(timeout=45000)
            dlg=p.get_by_role('dialog');await expect(dlg).to_be_visible(timeout=55000)
            await expect(dlg).to_contain_text(TITLE,timeout=60000)
            stage('disposable submitted application record')
            await p.goto(site+path,wait_until='domcontentloaded')
            await button('Record an application').click(timeout=45000)
            await p.get_by_label('Submission method').select_option('other')
            await p.get_by_label('Where you submitted it',exact=False).fill('Disposable QA campus desk')
            await p.get_by_label('I confirm I already submitted this application.').check()
            await button('Save application record').click()
            await expect(p.locator('#tracker-records').get_by_role('status').filter(has_text=re.compile(r'^(Application record saved|Record saved)')).first).to_be_visible(timeout=45000)
            await p.reload(wait_until='domcontentloaded')
            await expect(p.locator('#tracker-records')).to_contain_text('Disposable QA campus desk',timeout=45000)
            await p.goto(site+'/tracker',wait_until='domcontentloaded')
            await expect(p.get_by_text(TITLE,exact=True).first).to_be_visible(timeout=50000)
            stage('second real user has its own favorites and cannot see the record')
            other=account('Other Private QA','uiuc','Synthetic history')
            assert records(other)==[]
            c2,p2=await fresh(other,'Other Private QA')
            await p2.goto(site+path,wait_until='domcontentloaded')
            await expect(p2.get_by_text('This import is not available in this account.',exact=True)).to_be_visible(timeout=45000)
            assert records()==[latest]
            print('ISOLATED RECEIPT',json.dumps({'product':'91da71d0d2052ffaf0988fb6639346a26cc244c2','test_users':2,'real_auth_postgrest_browser':True,'model_provider':'controlled synthetic extraction result only','source_lengths':[len(SOURCE1),len(SOURCE2)],'source_scopes':['full_source','source_excerpt'],'explicit_browser_and_account_confirmations':True,'one_failed_update_before_write':True,'account_revisions':[1,1,2,3,3,4],'competing_real_revision_preserved':True,'both_copies_counted_once':True,'hand_edited_draft_restored':True,'same_browser_and_account_ids':True,'clean_browser_account_restore':True,'private_template':v['id'],'recipient_status':recipient,'private_resume_workspace_opened':True,'tracker_record_survives_reload':True,'second_user_cannot_read_owner_record':True,'messages_sent':0}),flush=True)
            await c2.close()
        except Exception:
            print('Last synthetic app response statuses:',events[-16:],flush=True)
            print('Visible UI:',(await p.locator('body').inner_text())[-2700:],flush=True)
            raise
        finally:await b.close()
asyncio.run(audit())
