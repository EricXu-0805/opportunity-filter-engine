"""Two signed-in Chromium contexts and real local Supabase. No provider calls."""
import asyncio, json
from urllib.parse import urlsplit
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright, expect
from verify_m52_historical_link import account, row, site


async def main():
    author = account('Author QA','uiuc','Original materials QA')
    recipient = account('Recipient QA','purdue','Private recipient interests',college='College of Engineering',major='Computer Engineering')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
        async def tab(session,school):
            context=await browser.new_context(service_workers='block',locale='en-US',timezone_id='UTC')
            data={'ofe_auth':json.dumps(session),'ofe_lang':'en','ofe_onboarding_seen':'1','ofe_school_confirmed':json.dumps({'slug':school,'ts':'2026-11-26T00:00:00.000Z'})}
            await context.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('m52-ui')){for(const [k,v] of Object.entries("+json.dumps(data)+"))localStorage.setItem(k,v);localStorage.setItem('m52-ui','1')}")
            p=await context.new_page();await p.goto(site,wait_until='domcontentloaded')
            await expect(p.locator('#student_name')).to_have_value(row(session)['profile_data']['name'],timeout=60000)
            return p
        send=await tab(author,'uiuc')
        recv=await tab(recipient,'purdue')
        await send.get_by_role('link',name='Share profile').click()
        await send.get_by_label('Research interests',exact=True).check()
        await send.get_by_label('Skill names and levels',exact=True).check()
        await send.get_by_role('button',name='Preview selected fields').click()
        await expect(send.get_by_text('Original materials QA',exact=True)).to_be_visible()
        await expect(send.get_by_text('Python (experienced)',exact=True)).to_have_count(0)
        await expect(send.get_by_text('PyTorch (experienced)',exact=True)).to_be_visible()
        await send.get_by_role('button',name='Create share link').click()
        link=send.get_by_role('textbox',name='Share link',exact=True)
        await expect(link).to_be_visible()
        url=await link.input_value()
        assert urlsplit(url).path=='/share' and urlsplit(url).query=='' and len(urlsplit(url).fragment)==36
        # Use the app's local-time control and a second, independently issued link.
        expiry_page=await send.context.new_page()
        await expiry_page.goto(site+'/share',wait_until='domcontentloaded')
        await expiry_page.get_by_label('Research interests',exact=True).check()
        expires=(datetime.now(timezone.utc)+timedelta(minutes=1,seconds=12)).replace(second=0,microsecond=0)
        await expiry_page.get_by_label('Expiry in your local time').fill(expires.strftime('%Y-%m-%dT%H:%M'))
        await expiry_page.get_by_role('button',name='Preview selected fields').click()
        await expiry_page.get_by_role('button',name='Create share link').click()
        expiry_link=expiry_page.get_by_role('textbox',name='Share link',exact=True)
        await expect(expiry_link).to_be_visible()
        expiry_url=await expiry_link.input_value()
        assert urlsplit(expiry_url).fragment!=urlsplit(url).fragment
        expiry_reader=await recv.context.new_page()
        await expiry_reader.goto(expiry_url,wait_until='domcontentloaded')
        await expect(expiry_reader.get_by_text('Original materials QA',exact=True)).to_be_visible()
        before=row(recipient)
        await recv.goto(url,wait_until='domcontentloaded')
        await expect(recv.get_by_text('Original materials QA',exact=True)).to_be_visible()
        await expect(recv.get_by_text('Author QA',exact=True)).to_have_count(0)
        await expect(recv.get_by_text('private line from owner',exact=True)).to_have_count(0)
        await recv.get_by_role('link',name='Decline and return to my profile').click()
        await expect(recv.locator('#research_interests')).to_have_value('Private recipient interests')
        assert row(recipient)['profile_data']==before['profile_data']
        await recv.goto(url,wait_until='domcontentloaded')
        await expect(recv.get_by_text('Original materials QA',exact=True)).to_be_visible()
        edit=await send.context.new_page()
        await edit.goto(site,wait_until='domcontentloaded')
        await expect(edit.locator('#student_name')).to_have_value('Author QA')
        await edit.locator('#research_interests').fill('Revised fields QA')
        for _ in range(80):
            if row(author)['profile_data']['research_interests']=='Revised fields QA':break
            await asyncio.sleep(.2)
        assert row(author)['profile_data']['research_interests']=='Revised fields QA'
        await send.get_by_role('button',name='Replace version').click()
        await send.get_by_role('button',name='Preview selected fields').click()
        await expect(send.get_by_text('Revised fields QA',exact=True)).to_be_visible()
        await send.get_by_role('button',name='Replace at the same link').click()
        await expect(link).to_have_value(url)
        await recv.get_by_role('button',name='Accept selected fields').click()
        await expect(recv.get_by_text('The author published a new version.',exact=False)).to_be_visible()
        await expect(recv.get_by_text('Revised fields QA',exact=True)).to_be_visible()
        assert row(recipient)['profile_data']==before['profile_data']
        await recv.get_by_role('button',name='Accept selected fields').click()
        await expect(recv.locator('#research_interests')).to_have_value('Revised fields QA',timeout=40000)
        await expect(recv.locator('#student_name')).to_have_value('Recipient QA')
        await recv.get_by_test_id('generate-matches').click(timeout=40000)
        answers=0
        for _ in range(140):
            if row(recipient)['profile_data']['research_interests']=='Revised fields QA':break
            keep=recv.get_by_test_id('conflict-keep-mine')
            if await keep.is_visible() and not answers: await keep.click(); answers+=1
            await asyncio.sleep(.23)
        final=row(recipient)
        assert final['profile_data']['research_interests']=='Revised fields QA'
        assert final['profile_data']['skills']==[{'name':'PyTorch','level':'experienced','source':'shared'}]
        for field in ('name','home_school','college','major','resume_text'):
            assert final['profile_data'][field]==before['profile_data'][field]
        await recv.goto(url,wait_until='domcontentloaded')
        await expect(recv.get_by_text('Revised fields QA',exact=True)).to_be_visible()
        await send.get_by_role('button',name='Revoke link').click()
        await expect(send.get_by_text('Link revoked.',exact=True)).to_be_visible()
        await recv.get_by_role('button',name='Accept selected fields').click()
        await expect(recv.get_by_text('This link is unavailable or has expired.',exact=True)).to_be_visible()
        await recv.reload(wait_until='domcontentloaded')
        await expect(recv.get_by_text('This link is unavailable or has expired.',exact=True)).to_be_visible()
        await asyncio.sleep(max(0,(expires-datetime.now(timezone.utc)).total_seconds())+.35)
        await expiry_reader.get_by_role('button',name='Accept selected fields').click()
        await expect(expiry_reader.get_by_text('This link is unavailable or has expired.',exact=True)).to_be_visible()
        assert row(recipient)['profile_data']==final['profile_data']
        print('MANAGED SHARE UI PASS',json.dumps({'initial_fields':['interests','skills'],'wire_url_fragment_only':True,'decline_account_writes':0,'replacement_safely_reprompted':True,'recipient_home_school':'purdue','recipient_skill_source':'shared','recipient_revision':final['revision'],'conflict_choices':answers,'in_flight_revocation_checked':True,'reopened_link_unavailable':True,'expired_link_rechecked_at_accept':True}),flush=True)
        await browser.close()

asyncio.run(main())
