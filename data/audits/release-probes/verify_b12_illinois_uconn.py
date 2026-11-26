"""Read the existing public records and the named papers on the deployed B12 frontend."""
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import async_playwright

SHA = '91140c465b5cd546e129c04f5097064b91fddb57'
SITE = 'https://joinalab.com'
SCOPE = '?_release_scope=mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
ARCHIVED = {'faculty-anthropology-aec66c90', 'faculty-anthropology-3ec19539'}
UCONN = 'faculty-uconn-cee-5374953b'
EVIDENCE = json.loads(Path(__file__).with_name('b12-illinois-uconn.json').read_text())


async def health(context):
    response = await context.request.get(SITE + '/api/health')
    assert response.ok and (await response.json())['release_sha'] == SHA


async def get_record(context, oid):
    api = SITE + '/api/opportunities/' + oid + SCOPE
    for attempt in range(2):
        r = await context.request.get(api, timeout=30000)
        if r.status not in (429, 502, 503, 504) or attempt:
            return r
        await asyncio.sleep(min(int(r.headers.get('retry-after', 4)), 30))
    raise RuntimeError(api)


async def run():
    result = {'release_sha': SHA, 'checked_utc': datetime.now(UTC).isoformat(), 'originals': [], 'rendered': {}}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path='/usr/bin/google-chrome')
        context = await browser.new_context(locale='en-US')
        await health(context)
        queue = iter(EVIDENCE['original_ids'])
        async def read():
            for row in queue:
                r = await get_record(context, row['id'])
                o = await r.json() if r.ok else {}
                result['originals'].append({'id':row['id'],'http':r.status,'name':o.get('pi_name'),'profile':o.get('url'),
                    'actionable':(o.get('target_truth') or {}).get('actionable'),'reason':(o.get('target_truth') or {}).get('reason_code'),
                    'matches_storage':o.get('id') == row['id'] and o.get('pi_name') == row['name'] and o.get('url') == row['url']
                    and ((o.get('target_truth') or {}).get('reason_code') == 'inactive') == (not row['active'])})
                await asyncio.sleep(.5)
        await asyncio.gather(read(),read())
        result['originals'].sort(key=lambda r:r['id'])
        duplicate = await get_record(context,EVIDENCE['historical_duplicate'])
        result['unpublished_duplicate_http'] = duplicate.status
        page = await context.new_page()
        for oid in [*sorted(ARCHIVED),UCONN]:
            r = await page.goto(SITE+'/opportunities/'+oid,wait_until='domcontentloaded')
            heading = page.get_by_role('heading',level=1).first
            await heading.wait_for()
            view = {'http':r.status,'frontend_sha':await page.locator('html').get_attribute('data-release-sha'),'heading':await heading.inner_text()}
            if oid in ARCHIVED:
                view['inactive_banner'] = await page.get_by_role('status').filter(has_text='This record is no longer active.').first.is_visible()
                view['apply_now'] = await page.get_by_role('link',name='Apply now',exact=True).first.is_visible()
                view['draft_email'] = await page.get_by_role('button',name='Draft email',exact=True).first.is_visible()
            else:
                api=await get_record(context,oid)
                assert api.ok
                data=await api.json()
                view['visible_publications']=[{'title':w['title'],'href':await page.get_by_role('link',name=w['title'],exact=True).first.get_attribute('href',timeout=12000)} for w in EVIDENCE['uconn_publications']]
                view['api_titles']=[w['title'] for w in data['metadata']['recent_works']]
                view['source_expectations']=EVIDENCE['uconn_publications']
            result['rendered'][oid]=view
        await health(context)
        await browser.close()
    Path('b12-illinois-uconn-public.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    assert len(result['originals'])==49 and all(r['matches_storage'] for r in result['originals'])
    assert result['unpublished_duplicate_http']==404
    assert all(v['frontend_sha']==SHA and v['http']==200 for v in result['rendered'].values())
    assert all(result['rendered'][i]['inactive_banner'] and not result['rendered'][i]['apply_now'] and not result['rendered'][i]['draft_email'] for i in ARCHIVED)
    assert result['rendered'][UCONN]['api_titles']==[w['title'] for w in EVIDENCE['uconn_publications']]
    print('Verified 49 Illinois original IDs, two historical UI controls, an unpublished duplicate and three named UConn publications on',SHA)

asyncio.run(run())
