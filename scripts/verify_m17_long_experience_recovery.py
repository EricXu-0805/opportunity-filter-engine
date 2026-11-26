"""Existing cloud entries plus one 6000-code-point UI edit; disposable real Auth/PostgREST only."""
import asyncio
import json
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
from verify_m52_historical_link import account, req, row, site

def text_at_limit(i):
    start=f'Record {i}. I mapped the project using GIS. '
    return start+'😀'*(5999-len(start))+'界'

async def main():
    owner=account('Unicode materials QA','uiuc','Public habitat research')
    original=[{'id':f'old-{i}','revision':1,'status':'confirmed','source':{'kind':'manual'},'text':text_at_limit(i)} for i in range(9)]
    ack=req('/rest/v1/rpc/commit_profile_patch_cas',
        {'p_expected_device_id':owner['user']['id'],'p_expected_revision':row(owner)['revision'],'p_patch':{'experience_entries':original}},owner)
    assert ack['status']=='applied'
    prior=row(owner)
    assert prior['profile_data']['experience_entries']==original
    final=text_at_limit(9)
    assert len(final)==6000 and len(final.encode('utf-16-le'))//2>6000
    failed=[]
    outage=False
    async with async_playwright() as pw:
        b=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        async def fresh():
            c=await b.new_context(locale='en-US',service_workers='block')
            info={'ofe_auth':json.dumps(owner),'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00.000Z'})}
            await c.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('m17long')){for(const [k,v] of Object.entries("+json.dumps(info)+"))localStorage.setItem(k,v);localStorage.setItem('m17long','1')}")
            async def guard(route):
                r=route.request
                u=urlsplit(r.url)
                if u.scheme in ('http','https') and u.hostname not in ('127.0.0.1','localhost'):return await route.abort()
                if outage and u.path.endswith('/commit_profile_patch_cas') and r.method=='POST':
                    assert r.post_data_json['p_expected_device_id']==owner['user']['id']
                    failed.append(True)
                    return await route.fulfill(status=503,headers={'access-control-allow-origin':site.rstrip('/')},json={'message':'temporary isolated write outage'})
                return await route.continue_()
            await c.route('**/*',guard)
            p=await c.new_page()
            await p.goto(site,wait_until='domcontentloaded')
            await expect(p.locator('#student_name')).to_have_value('Unicode materials QA',timeout=65000)
            return c,p
        c,p=await fresh()
        library=p.locator('#experience-library')
        await library.get_by_text('Add an experience',exact=True).click()
        field=library.get_by_label('Describe your contribution, methods and results')
        add=library.get_by_role('button',name='Add for review')
        await field.fill(final+'续')
        await add.click()
        await expect(library.get_by_role('alert')).to_contain_text('6,000')
        assert await field.input_value()==final+'续' and row(owner)['profile_data']['experience_entries']==original
        await field.fill(final)
        outage=True
        await add.click()
        for _ in range(90):
            if failed:break
            await asyncio.sleep(.25)
        assert failed and row(owner)['profile_data']['experience_entries']==original
        outage=False
        retry=p.get_by_test_id('retry-sync')
        for _ in range(120):
            saved=row(owner)
            if len(saved['profile_data']['experience_entries'])==10:break
            if await retry.is_visible():await retry.click()
            await asyncio.sleep(.3)
        saved_rows=saved['profile_data']['experience_entries']
        assert len(saved_rows)==10 and saved_rows[:9]==original and saved_rows[-1]['text']==final and saved_rows[-1]['status']=='candidate'
        await field.fill('补')
        await add.click()
        await expect(library.get_by_role('alert')).to_contain_text('60,000')
        assert await field.input_value()=='补' and row(owner)['profile_data']['experience_entries']==saved_rows
        await c.close()
        c,p=await fresh()
        detail=p.locator('#experience-library details').filter(has=p.locator('summary',has_text='Record 9.')).first
        await detail.locator('summary').first.click()
        assert await detail.locator('textarea').input_value()==final
        await detail.get_by_role('button',name='Confirm facts',exact=True).click()
        for _ in range(120):
            committed=row(owner)
            if committed['profile_data']['experience_entries'][-1]['status']=='confirmed':break
            await asyncio.sleep(.25)
        official=committed['profile_data']['experience_entries']
        assert official[:9]==original and sum(len(e['text']) for e in official)==60000 and official[-1]['text']==final
        assert official[-1]['status']=='confirmed' and official[-1]['revision']>saved_rows[-1]['revision']
        print(json.dumps({'boundary':'actual form and loopback real registered Auth / PostgREST',
                          'nine_historical_entries_preserved':True,'total_confirmed_codepoints':sum(len(e['text']) for e in official),
                          '6001_rejected_original_input_retained':True,'60001_rejected_original_input_retained':True,
                          '6000_astral_unicode_recovered_after_write_503':True,'clean_browser_readback_and_explicit_confirmation':True,
                          'revisions':[prior['revision'],saved['revision'],committed['revision']]}),flush=True)
        await c.close()
        await b.close()

asyncio.run(main())
