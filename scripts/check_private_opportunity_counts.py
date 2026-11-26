"""Seed a single disposable account through the public application API, reopen in a clean real browser."""
import asyncio
import json
import os
import sys
import uuid
from urllib import request
from urllib.parse import quote
from playwright.async_api import async_playwright, expect
from verify_m52_historical_link import account, site

async def verify():
    s=account('Saved Count QA','uiuc','Archive systems')
    owner=s['user']['id'];pk='private-import:'+str(uuid.uuid4());title='Independent archive catalog count fixture'
    payload={'expected_owner_id':owner,'expected_revision':0,'opportunity':{'title':title,'description_raw':'Test archive: no external application.','source':'text_parser','url':'','source_url':''}}
    with request.urlopen(request.Request('http://127.0.0.1:8100/api/private-import-targets/'+quote(pk,safe=''),method='PUT',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+s['access_token'],'content-type':'application/json'}),timeout=20) as result:
        assert json.load(result)['target']['revision']==1
    async with async_playwright() as pw:
        b=await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        c=await b.new_context(locale='en-US',service_workers='block')
        vals={'ofe_auth':json.dumps(s),'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':'uiuc','ts':'2026-11-26T00:00:00.000Z'})}
        await c.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('saved-count-init')){for(const[k,v]of Object.entries("+json.dumps(vals)+"))localStorage.setItem(k,v);localStorage.setItem('saved-count-init','1')}")
        p=await c.new_page();await p.goto(site,wait_until='domcontentloaded')
        await expect(p.locator('#student_name')).to_have_value('Saved Count QA',timeout=75000)
        await p.goto(site+'/favorites',wait_until='domcontentloaded');await expect(p.get_by_role('heading',name=title)).to_be_visible(timeout=60000)
        no_saved="You haven't starred any opportunities yet."
        listed=await p.get_by_role('link',name='View records',exact=True).count()
        stated_empty=await p.get_by_text(no_saved,exact=True).count()
        explicit_count=await p.get_by_text('1 saved',exact=True).count()
        await p.goto(site+'/dashboard',wait_until='domcontentloaded')
        box=p.get_by_test_id('saved-summary')
        await expect(box).to_have_attribute('data-state','ready',timeout=60000)
        val=int((await box.locator('p').first.inner_text()).strip())
        result={'owned_cloud_targets':1,'device_imports':0,'listed_private_links':listed,'favorites_empty_claims':stated_empty,'favorites_correct_count_labels':explicit_count,'dashboard_saved':val}
        print('PRIVATE COUNT RECEIPT',json.dumps(result),flush=True)
        if os.environ.get('OFE_EXPECT_COUNT_FIX')=='1':assert listed==1 and stated_empty==0 and explicit_count==1 and val==1
        else:assert listed==1 and stated_empty==1 and explicit_count==0 and val==0
        await b.close()
asyncio.run(verify())
