"""Read the student-facing page and follow its in-page source reference in each locale."""
import json
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

CASES = {
    'Caltech': 'caltech-d8e1ba2c4a90',
    'Wharton': 'upenn-bd5e7b5c0d12',
}
for school, target in CASES.items():
    for locale in ('en','zh'):
        request=Request("https://joinalab.com/opportunities/"+target,headers={"User-Agent":"JoinALab/1.0 (public page check)", "Cookie":"ofe_lang="+locale, "Accept-Language":"zh-CN" if locale=="zh" else "en-US"})
        with urlopen(request,timeout=25) as response:
            page=BeautifulSoup(response.read(3_000_000),'html.parser')
        facet=page.select_one('[data-testid="fact-timing-deadline"]')
        window=page.select_one('[data-testid="fact-timing-application_window"]')
        link=facet.select_one('a[href^="#"]') if facet else None
        print(school,locale,json.dumps({
            "html_lang":page.html.get("lang"),"tab":page.title.get_text(strip=True)[:105] if page.title else None,
            "deadline":facet.get_text(" ",strip=True)[:135] if facet else None,
            "source_text":window.get_text(" ",strip=True)[:310] if window else None,
            "matched_target":bool(link and window and link["href"][1:]==window.get("id")),
            "external_link":bool(window and window.select_one('a[href^="https"]')),
        },ensure_ascii=False),flush=True)
