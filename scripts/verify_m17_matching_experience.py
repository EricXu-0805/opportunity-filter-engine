"""Real local Auth / revision writes / React / ranking engine / free email generation; deliberately no model."""
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

if '--serve' in sys.argv:
    import uvicorn
    from backend import data_loader
    # Existing two artificial UI listings, with the single stated method as the controlled difference.
    root = Path('product')
    records=json.loads((root/'frontend/e2e/fixtures/actionable-listing.json').read_text())
    for index,rec in enumerate(records):
        rec['eligibility']['skills_required']=['Python' if index==0 else 'JavaScript']
        rec['application']['contact_method']='email'
        rec['application'].setdefault('email','test-contact@example.test')
    directory=tempfile.TemporaryDirectory()
    data_loader.DATA_DIR=Path(directory.name)
    (data_loader.DATA_DIR/'opportunities.json').write_text(json.dumps(records))
    from backend.main import app
    uvicorn.run(app,host='127.0.0.1',port=8100,log_level='warning')
    sys.exit()

from playwright.async_api import async_playwright,expect
from verify_m52_historical_link import account,row,site

TARGET='e2e-actionable-research'
OTHER='e2e-related-research'
FACT='I implemented Python checks for a public dataset.'
CSV='Company Name,Title,Started On,Finished On,Description,Results\nExample Archives,Research Assistant,2024,2025,"'+FACT+'",Validated 30 files\n'

async def main():
    s=account('Experience Match QA','uiuc','Data analysis and campus computing QA')
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        async def fresh():
            c=await browser.new_context(locale='en-US',service_workers='block')
            info={'ofe_auth':json.dumps(s),'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00.000Z'})}
            await c.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('m17qa')){for(const [k,v] of Object.entries("+json.dumps(info)+"))localStorage.setItem(k,v);localStorage.setItem('m17qa','1')}")
            return c
        async def results(ctx):
            page=await ctx.new_page()
            await page.goto(site,wait_until='domcontentloaded')
            await expect(page.locator('#student_name')).to_have_value('Experience Match QA',timeout=60000)
            # The normal Generate Matches action first persists the hydrated cloud
            # profile to this new device. A bare results deep link is not that action.
            await page.get_by_role('button',name='Generate Matches',exact=True).click()
            await page.wait_for_url('**/results**',timeout=70000)
            async with page.expect_response(lambda r:'/api/matches/view?' in r.url and r.ok and r.request.post_data_json['view'].get('tab')=='all',timeout=90000) as seen:
                await page.get_by_role('button',name=re.compile(r'^All(?:\s|$)')).first.click()
            event=await seen.value
            assert 'llm=false' in event.url
            payload=event.request.post_data_json['profile']
            listing={r['opportunity_id']:r for r in (await event.json())['results']}
            assert TARGET in listing and OTHER in listing, list(listing)
            return page,listing,payload
        async def letter(p,record,confirmed):
            # Open the normal draft action on the target whose score and profile
            # were just read from this account. This also retains its source binding.
            seen_api=[]; errors=[]
            def api(r):
                path=urlsplit(r.url).path
                if path.startswith('/api/') or path=='/rest/v1/profiles':
                    seen_api.append((path,r.status))
            p.on('response',api)
            p.on('pageerror',lambda e: errors.append(str(e)[:300]))
            async def diagnose(stage):
                dialog=p.get_by_role('dialog')
                visible=(await dialog.first.inner_text()) if await dialog.count() else (await p.locator('body').inner_text())
                return (stage,confirmed,visible[-2500:],seen_api[-22:],errors)
            generation=asyncio.get_running_loop().create_future()
            def capture(r):
                if '/api/cold-email/variants' in r.url and not generation.done():
                    generation.set_result(r)
            p.on('response',capture)
            action=p.locator('#match-card-'+TARGET).get_by_role('button',name='Draft email',exact=True)
            try:await action.click(timeout=30000)
            except Exception:raise AssertionError(await diagnose('target card draft control')) from None
            regen=p.get_by_role('button',name='Regenerate from updated materials',exact=True)
            if not confirmed:
                # The normal editor deliberately restores a previous saved draft.
                # Request a new one before assessing the new material.
                show=asyncio.create_task(regen.wait_for(state='visible',timeout=45000))
                done,_=await asyncio.wait([generation,show],timeout=55,return_when=asyncio.FIRST_COMPLETED)
                if show in done and not show.exception():
                    await regen.click()
                elif not show.done():
                    show.cancel()
                if not done:
                    raise AssertionError('Neither generation nor the normal regeneration control appeared')
            try:
                response=await asyncio.wait_for(generation,45)
            except asyncio.TimeoutError:
                raise AssertionError(await diagnose('no variant request')) from None
            assert response.ok, (response.status, (await response.text())[:500])
            variants=(await response.json())['variants']
            await expect(p.locator('#cold-email-body')).not_to_have_value('',timeout=30000)
            await p.close()
            for v in variants:
                usage=v['experience_usage']
                if confirmed:
                    assert record['text'] in v['body'], (v['id'],v['body'])
                    assert any(r['id']==record['id'] and r['revision']==record['revision'] and r['source']['kind']=='manual' and r['excerpt']==record['text'] for r in usage['selected']), (v['id'],usage)
                else:
                    assert FACT not in v['body'] and not usage['selected'], (v['id'],usage)
                    assert any(r['id']==record['id'] and r['reason']=='rejected' for r in usage['excluded']), (v['id'],usage)
            return [(v['id'],FACT in v['body']) for v in variants]
        ctx=await fresh()
        pg,baseline,old_request=await results(ctx);await pg.close()
        assert not old_request.get('match_experiences') and not baseline[TARGET].get('experience_basis')
        home=await ctx.new_page();await home.goto(site,wait_until='domcontentloaded')
        await expect(home.locator('#student_name')).to_have_value('Experience Match QA',timeout=60000)
        await home.get_by_text('Import LinkedIn experience',exact=True).click()
        await home.get_by_label('Positions.csv',exact=True).set_input_files({'name':'Positions.csv','mimeType':'text/csv','buffer':CSV.encode()})
        await home.get_by_role('button',name='Preview experiences').click()
        await home.get_by_label('Choose what to save').select_option('new')
        assert not (row(s)['profile_data'].get('experience_entries') or [])
        await home.get_by_role('button',name='Confirm selected experiences').click()
        for _ in range(150):
            if row(s)['profile_data'].get('experience_entries'):break
            await asyncio.sleep(.2)
        saved=row(s);entry=saved['profile_data']['experience_entries'][0]
        assert entry['status']=='confirmed' and entry['id'].startswith('li:') and all(part in entry['text'] for part in ('Example Archives','Research Assistant','2024','2025',FACT,'Validated 30 files'))
        await ctx.close();ctx=await fresh()
        pg,admitted,request=await results(ctx)
        basis=admitted[TARGET]['experience_basis'];assert basis=={'entry_id':entry['id'],'revision':entry['revision'],'method':'Python','target_source':'stated_requirement'},basis
        assert admitted[TARGET]['final_score']>baseline[TARGET]['final_score']
        assert admitted[TARGET]['eligibility_score']==baseline[TARGET]['eligibility_score']
        assert admitted[OTHER]['final_score']==baseline[OTHER]['final_score'] and not admitted[OTHER]['experience_basis']
        assert request['match_experiences'][0]['text']==entry['text']
        receipt=pg.get_by_text('Experience used for this match · Python')
        await receipt.click();await expect(pg.get_by_text(entry['text'],exact=True)).to_be_visible()
        accepted_mail=await letter(pg,entry,True)
        assert len(accepted_mail)==3 and all(v[1] for v in accepted_mail),accepted_mail
        await ctx.close();ctx=await fresh()
        home=await ctx.new_page();await home.goto(site,wait_until='domcontentloaded')
        summary=home.locator('summary').filter(has_text='Example Archives').first
        await summary.click(timeout=60000);await home.get_by_role('button',name='Do not use',exact=True).click()
        for _ in range(150):
            if row(s)['profile_data']['experience_entries'][0]['status']=='rejected':break
            await asyncio.sleep(.2)
        rejected=row(s);assert rejected['profile_data']['experience_entries'][0]['status']=='rejected'
        await ctx.close();ctx=await fresh()
        pg,after,new_request=await results(ctx)
        assert not new_request.get('match_experiences') and not after[TARGET]['experience_basis']
        assert baseline[TARGET]['final_score']==after[TARGET]['final_score']
        assert await pg.get_by_text('Experience used for this match · Python').count()==0
        withdrawn_mail=await letter(pg,entry,False)
        assert len(withdrawn_mail)==3 and not any(v[1] for v in withdrawn_mail),withdrawn_mail
        print(json.dumps({'controlled_target_fixture':True,'real_chromium_gotrue_postgrest_fastapi':True,
                          'confirmed_from_user_positions_csv':True,'full_entry_in_matches_and_current_receipt':True,'complete_organization_role_dates_duties_results_in_three_free_variant_bodies_and_receipts':True,'source':'LinkedIn file, individually confirmed',
                          'scores':[baseline[TARGET]['final_score'],admitted[TARGET]['final_score'],after[TARGET]['final_score']],
                          'eligibility_score_unchanged':True,'unrelated_target_score_unchanged':True,'profile_revisions':[saved['revision'],rejected['revision']],
                          'free_variants_with_fact':[v[0] for v in accepted_mail if v[1]],'after_withdrawal_variants_with_fact':[v[0] for v in withdrawn_mail if v[1]],'external_messages_sent':0}))
        await browser.close()
asyncio.run(main())
