"""Observe the closed JoinALab program and follow its source as a regular visitor."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import json
from playwright.sync_api import sync_playwright

expected='743e6fa6e6b8d56c39e5c2eb29a92a4fcdc16d7f';url='https://joinalab.com/opportunities/wlu-88e9e20591ba';source='https://mga1.wlu.edu/campusnotices/view/web.php?id=9865&view=web';out=Path('evidence');out.mkdir(exist_ok=True);report={'checked_utc':datetime.now(timezone.utc).isoformat(),'program_url':url}
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome');context=browser.new_context(locale='en-US');page=context.new_page();responses=[]
        context.on('response',lambda response:responses.append((response.url,response.status)) if response.request.is_navigation_request() else None)
        page.goto(url,wait_until='domcontentloaded');page.get_by_role('heading',name='DART Research Fellowship — Summer 2026 (Washington and Lee)',exact=True).wait_for()
        tag=page.locator('html').get_attribute('data-release-sha');assert tag==expected
        closed=page.get_by_text('This listing is closed and is no longer accepting applications.',exact=False).first;closed.wait_for(state='visible')
        apply=page.get_by_role('link',name='Apply now',exact=True);assert apply.count()==0
        link=page.get_by_role('link',name='View source',exact=True);link.wait_for(state='visible');assert link.first.get_attribute('href')==source
        report.update(release=tag,closed_banner=closed.inner_text(),apply_controls=apply.count(),source_href=link.first.get_attribute('href'))
        if link.first.get_attribute('target')=='_blank':
            with context.expect_page(timeout=20000) as popup:link.first.click()
            official=popup.value
        else:
            link.first.click();official=page
        official.wait_for_load_state('domcontentloaded');official.get_by_text('DART Fellowship Program - Participant Recruitment for Summer 2026!!',exact=True).first.wait_for(state='visible');assert official.url==source
        title=official.title();assert 'DART Fellowship Program' in title
        text=official.locator('body').inner_text();hosts={school:school in text for school in ['Illinois','Florida','Michigan']};assert all(hosts.values());assert any(u==source and code==200 for u,code in responses)
        report.update(official_url=official.url,official_title=title,official_http=200,public_notice_mentions_host_states=hosts,result='passed')
        official.screenshot(path=str(out/'dart-official-notice.png'));browser.close()
finally:
    (out/'dart-click.json').write_text(json.dumps(report,indent=2)+'\n')
