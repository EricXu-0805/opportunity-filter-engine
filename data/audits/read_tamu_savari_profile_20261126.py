"""Record what a normal visitor can read at the saved TAMU link and two official campus sources."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

pages = {'current_catalog': 'https://catalog.tamu.edu/graduate/colleges-schools-interdisciplinary/engineering/electrical-computer/'}
root = Path('evidence')
root.mkdir(exist_ok=True)
record = {'observed_at': datetime.now(timezone.utc).isoformat(), 'earlier_product_and_scholars_check': 'https://github.com/EricXu-0805/opportunity-filter-engine/actions/runs/45869355231', 'pages': {}}
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='chrome')
    context = browser.new_context(locale='en-US')
    for name, url in pages.items():
        page = context.new_page()
        try:
            resp = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            if resp.ok:
                page.locator('a[href="#faculty"]').click(timeout=15000)
                page.get_by_text('Savari, Serap A, Associate Professor', exact=False).first.wait_for(timeout=15000)
            text = ' '.join(page.locator('body').inner_text(timeout=15000).split())
            snippets = [m.group(0) for m in re.finditer(r'.{0,35}(?:Savari, Serap(?: A)?|Serap(?: A\.?)? Savari).{0,115}',text, re.I)]
            record['pages'][name] = {'http': resp.status, 'requested': url, 'final': page.url, 'title':page.title(), 'matched':snippets[:3], 'frontend_release': page.locator('html').get_attribute('data-release-sha'), 'faculty_profile_destination': page.get_by_role('link',name='View faculty profile',exact=True).get_attribute('href') if name=='opportunity' and page.get_by_role('link',name='View faculty profile',exact=True).count() else None}
        except Exception as exc:
            record['pages'][name]={'requested':url,'error':str(exc)[:300]}
        finally:
            page.close()
    browser.close()
(root/'tamu-savari.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(record,indent=2,ensure_ascii=False))
assert record['pages']['current_catalog'].get('matched'), 'No matching person visible after opening the official Faculty tab'
