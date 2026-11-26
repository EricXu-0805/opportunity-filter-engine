"""Local production paths, two disposable Auth identities and generated PDFs; first-party network only."""
import asyncio
import hashlib
import json
import re
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
from verify_m52_historical_link import account, row, site

TARGET='e2e-actionable-research'
OTHER='e2e-related-research'
FACT='I implemented Python checks for a public dataset.'
PRIVATE='Private synthetic footer for the original roster.'
REPLACEMENT='Revised synthetic footer with identical experience line.'


async def main():
    a=account('Experience Match QA','uiuc','Data analysis and campus computing QA')
    other=account('Separate Profile QA','uiuc','Unrelated coursework')
    assert a['user']['id'] != other['user']['id']
    async with async_playwright() as pw:
        b=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        async def fresh(s=a):
            c=await b.new_context(locale='en-US',service_workers='block')
            info={'ofe_auth':json.dumps(s),'ofe_lang':'en','ofe_onboarding_seen':'1',
                  'ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00.000Z'})}
            await c.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('m17pdf')){for(const [k,v] of Object.entries("+json.dumps(info)+"))localStorage.setItem(k,v);localStorage.setItem('m17pdf','1')}")
            async def private(route):
                u=urlsplit(route.request.url)
                if u.scheme in ('http','https') and u.hostname not in ('localhost','127.0.0.1'):return await route.abort()
                return await route.continue_()
            await c.route('**/*',private)
            return c
        async def home(c,name='Experience Match QA'):
            p=await c.new_page()
            await p.goto(site,wait_until='domcontentloaded')
            await expect(p.locator('#student_name')).to_have_value(name,timeout=70000)
            return p
        async def state(test):
            for _ in range(150):
                record=row(a)
                if test(record['profile_data']):return record
                await asyncio.sleep(.25)
            raise AssertionError('Expected own cloud revision did not arrive')
        async def upload(p,footer):
            doc=await b.new_page()
            await doc.set_content('<h1>Experiences</h1><p>'+FACT+'</p><p>'+footer+'</p>')
            pdf=await doc.pdf()
            await doc.close()
            await p.locator('input[type=file][accept*="pdf"]').first.set_input_files({'name':'synthetic-research.pdf','mimeType':'application/pdf','buffer':pdf})
            await expect(p.get_by_role('button',name='Remove file',exact=True)).to_be_visible(timeout=65000)
            await state(lambda d: footer in (d.get('resume_text') or ''))
        async def results(c,entry=None,name='Experience Match QA'):
            p=await home(c,name)
            await p.get_by_role('button',name='Generate Matches',exact=True).click()
            await p.wait_for_url('**/results**',timeout=70000)
            async with p.expect_response(lambda r:'/api/matches/view?' in r.url and r.ok and r.request.post_data_json['view'].get('tab')=='all',timeout=90000) as seen:
                await p.get_by_role('tab',name=re.compile(r'^All(?:\s|$)')).first.click()
            response=await seen.value
            assert 'llm=false' in response.url
            req=response.request.post_data_json['profile']
            records={r['opportunity_id']:r for r in (await response.json())['results']}
            one,control=records[TARGET],records[OTHER]
            assert not any(k in req for k in ('resume_text','resume_master','experience_entries'))
            assert PRIVATE not in json.dumps(req) and REPLACEMENT not in json.dumps(req)
            assert not control.get('experience_basis')
            if entry:
                reference='pdf:'+hashlib.sha256(entry['id'].encode()).hexdigest()
                assert req['match_experiences']==[{'id':reference,'revision':entry['revision'],'source':'resume','status':'confirmed','text':FACT}]
                assert entry['source']['signature'] not in json.dumps(req)
                assert one.get('experience_basis')=={'entry_id':reference,'revision':entry['revision'],'method':'Python','target_source':'stated_requirement'}
                await p.get_by_text('Experience used for this match · Python').click()
                await expect(p.get_by_text(FACT,exact=True)).to_be_visible()
                await expect(p.get_by_text('Current résumé · Confirmed by you',exact=False)).to_be_visible()
            else:
                assert not req.get('match_experiences') and not one.get('experience_basis')
                await expect(p.get_by_text('Experience used for this match · Python')).to_have_count(0)
            await p.close()
            return [one['final_score'],one['readiness_score'],one['eligibility_score'],control['final_score']]
        def entry_from(d):
            return next((e for e in d.get('experience_entries',[]) if e['text']==FACT),{})
        async def mark(c,label,status):
            p=await home(c)
            detail=p.locator('#experience-library details').filter(has=p.locator('summary',has_text=FACT)).first
            await detail.locator('summary').first.click()
            await detail.get_by_role('button',name=label,exact=True).click()
            d=await state(lambda d:entry_from(d).get('status')==status)
            await p.close()
            return d
        c=await fresh()
        p=await home(c)
        await upload(p,PRIVATE)
        await p.get_by_role('button',name='Prepare excerpts for review',exact=True).click()
        pending=await state(lambda d:entry_from(d).get('status')=='candidate')
        await c.close()
        c=await fresh()
        before=await results(c)
        saved=await mark(c,'Confirm facts','confirmed')
        accepted=entry_from(saved['profile_data'])
        raw=saved['profile_data']['resume_text']
        source=accepted['source']
        assert hashlib.sha256(raw.encode()).hexdigest()==source['signature'] and raw[source['start']:source['end']]==source['quote']==FACT
        await c.close()
        c=await fresh()
        after=await results(c,accepted)
        assert after[0]>before[0] and after[1]>before[1] and after[2:]==before[2:]
        rejected=await mark(c,'Do not use','rejected')
        await c.close()
        c=await fresh()
        withdrawn=await results(c)
        assert withdrawn==before
        confirmed_again=await mark(c,'Confirm facts','confirmed')
        assert entry_from(confirmed_again['profile_data'])['revision']>accepted['revision']
        await c.close()
        c=await fresh()
        p=await home(c)
        await upload(p,REPLACEMENT)
        new=await state(lambda d: REPLACEMENT in (d.get('resume_text') or '') and PRIVATE not in d['resume_text'])
        assert FACT in new['profile_data']['resume_text'] and hashlib.sha256(new['profile_data']['resume_text'].encode()).hexdigest()!=source['signature']
        await c.close()
        c=await fresh()
        replaced=await results(c)
        assert replaced==before
        p=await home(c)
        await p.get_by_role('button',name='Remove file',exact=True).click()
        removed=await state(lambda d:not d.get('resume_text'))
        await c.close()
        c=await fresh()
        await results(c)
        await c.close()
        c=await fresh(other)
        await results(c,name='Separate Profile QA')
        assert not row(other)['profile_data'].get('experience_entries')
        print(json.dumps({'actual_chromium_gotrue_postgrest_fastapi':True,'generated_pdf':True,
                          'current_quote_digest_and_no_other_pdf_text_sent':True,'visible_current_resume_source_receipt':True,
                          'controlled_opportunities':[TARGET,OTHER],'scores_target_readiness_eligibility_control':[before,after,withdrawn,replaced],
                          'withdrawal_reconfirmation_replacement_removal_and_other_owner':True,
                          'own_database_revisions':[r['revision'] for r in [pending,saved,rejected,confirmed_again,new,removed]],
                          'network':'loopback only'}),flush=True)
        await c.close()
        await b.close()

asyncio.run(main())
