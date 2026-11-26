from pathlib import Path
from datetime import datetime, timezone
import json, re
from playwright.sync_api import sync_playwright
urls={'US_ETAP':'https://etap.nsf.gov/award/8325/opportunity/12125','India':'https://www.gw.iucaa.in/ligo-surf-program/','host':'https://ligosurf.caltech.edu/apply','product':'https://joinalab.com/opportunities/caltech-acdbfe29c21d'}
out=Path('evidence'); out.mkdir(exist_ok=True)
record={'observed_at':datetime.now(timezone.utc).isoformat(),'pages':{}}
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='chrome')
    for name,url in urls.items():
        page=browser.new_page(locale='en-US')
        try:
            res=page.goto(url,wait_until='domcontentloaded',timeout=45000)
            if name=='US_ETAP':
                try:page.get_by_text(re.compile('LIGO|Application deadline|Application period',re.I)).first.wait_for(timeout=20000)
                except Exception:pass
            if name=='product':page.get_by_role('heading',name=re.compile('LIGO SURF')).first.wait_for(timeout=24000)
            body=page.locator('body').inner_text()
            lines=[v.strip() for v in body.splitlines() if re.search(r'2027|apply by|due date|citizen|rolling|applications reviewed|deadline|foreign institutions|ligo surf',v,re.I)]
            record['pages'][name]={'url':page.url,'http':res.status,'title':page.title(),'frontend_release':page.locator('html').get_attribute('data-release-sha'),'text':lines[:40],'empty_match':not bool(lines)}
            page.screenshot(path=str(out/(name+'.png')))
        except Exception as e:record['pages'][name]={'url':url,'error':str(e)[:300]}
        finally:page.close()
    browser.close()
(out/'ligo.json').write_text(json.dumps(record,indent=2)+'\n')
