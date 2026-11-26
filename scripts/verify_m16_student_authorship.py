"""Run the normal student profile UI against a disposable GoTrue and PostgREST database."""
import asyncio
import json
from playwright.async_api import async_playwright, expect
from verify_m52_historical_link import account, row, site

SCHOLAR = 'https://scholar.google.com/citations?user=QADemoM16'
ORCID = '0000-0002-1825-0097'

def slot(author_id, name, campus, orcid=None):
    return {'author': {'id': 'https://openalex.org/' + author_id, 'display_name': name, 'orcid': orcid},
            'institutions': [{'display_name': campus}]}

def work(work_id, title, *authors):
    return {'id': 'https://openalex.org/' + work_id, 'display_name': title, 'authorships': authors}

async def main():
    session = account('Student Publication QA', 'uiuc', 'Student publications and methods QA')
    initial = row(session)
    first = slot('A911', 'Alex Example', 'Former campus', ORCID)
    transfer = slot('A911', 'A. Example', 'New campus', 'https://orcid.org/' + ORCID)
    other = slot('A922', 'Alex Example', 'Former campus')
    data = {'results': [work('W901', 'Prior-campus example', first), work('W902', 'Transfer example', other, transfer),
                        work('W903', 'Namesake example', other), work('W904', 'Inconsistent signatures', first, transfer)]}
    async with async_playwright() as pw:
        chrome = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
        async def clean_tab():
            ctx = await chrome.new_context(locale='en-US', service_workers='block')
            seed = {'ofe_auth': json.dumps(session), 'ofe_lang': 'en', 'ofe_onboarding_seen': '1',
                    'ofe_school_confirmed': json.dumps({'slug':'uiuc', 'ts':'2026-11-26T00:00:00.000Z'})}
            await ctx.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('m16-qa')){ for(const [k,v] of Object.entries("+json.dumps(seed)+"))localStorage.setItem(k,v);localStorage.setItem('m16-qa','1')}")
            tab = await ctx.new_page()
            await tab.goto(site, wait_until='domcontentloaded')
            await expect(tab.locator('#student_name')).to_have_value('Student Publication QA', timeout=60000)
            return tab
        async def panel(tab):
            await tab.get_by_text('Open full résumé editor', exact=True).click()
            await tab.get_by_text('Import my publications from OpenAlex', exact=True).click()
        async def upload(tab):
            assert await tab.get_by_text('Check authorships', exact=True).count() == 0
            await tab.get_by_label('Your OpenAlex author ID or ORCID').fill(ORCID)
            await tab.get_by_label('I confirm that these author profiles are mine.').check()
            await tab.get_by_label('Paste your public OpenAlex Works JSON export',exact=False).fill(json.dumps(data))
            await tab.get_by_role('button',name='Check authorships').click()
            await expect(tab.get_by_text('Matching works · 2 / Skipped · 2')).to_be_visible()
            assert await tab.get_by_role('link', name='Namesake example').count() == 0
            assert await tab.get_by_role('link', name='Inconsistent signatures').count() == 0
        tab = await clean_tab()
        await tab.locator('#scholar_url').fill(SCHOLAR)
        for _ in range(100):
            if row(session)['profile_data'].get('scholar_url') == SCHOLAR: break
            await asyncio.sleep(.2)
        confirmed_link = row(session)
        assert confirmed_link['profile_data']['scholar_url'] == SCHOLAR
        await panel(tab)
        await upload(tab)
        assert not row(session)['profile_data'].get('resume_master')
        await tab.get_by_role('listitem').filter(has=tab.get_by_role('link',name='Transfer example')).get_by_role('button').click()
        assert not row(session)['profile_data'].get('resume_master')
        await tab.get_by_role('button',name='Apply changes').click()
        for _ in range(150):
            if row(session)['profile_data'].get('resume_master'): break
            await asyncio.sleep(.2)
        saved = row(session)
        papers = saved['profile_data']['resume_master']['publications']
        assert len(papers) == 1
        paper = papers[0]
        assert paper['student_authorship'] == {'scholar_id':'QADemoM16','author_id':'A911','work_id':'W902','orcid':ORCID}
        assert paper['title']['value'] == 'Transfer example' and paper['title']['status'] == 'confirmed' and 'authors' not in paper
        assert paper['url']['value'] == 'https://openalex.org/W902'
        assert saved['profile_data']['resume_text'] == initial['profile_data']['resume_text']
        await tab.context.close()
        fresh = await clean_tab()
        await panel(fresh)
        await expect(fresh.get_by_role('textbox',name='Publication title')).to_have_value('Transfer example')
        await upload(fresh)
        await expect(fresh.get_by_role('button',name='Already in résumé')).to_be_disabled()
        assert row(session)['revision'] == saved['revision']
        print(json.dumps({'synthetic_public_format_export':True,'disposable_named_account':True,'real_chromium':True,
                          'rows':4,'matched':2,'ambiguous_or_namesake_skipped':2,'saved_explicitly':1,
                          'private_receipt':paper['student_authorship'],'no_write_during_preview':True,
                          'fresh_context_deduplicated':True,'revisions':[initial['revision'],confirmed_link['revision'],saved['revision']]}))
        await chrome.close()
asyncio.run(main())
