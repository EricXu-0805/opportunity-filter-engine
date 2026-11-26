"""Offline navigation controls. No actual campus or production request is allowed."""
from playwright.sync_api import sync_playwright
from b21_nc_state_destinations import CASES,JACOB_ID,ROBIN_ID,ROBIN,DIRECTORY,SITE, verify_click
sha='f'*40
with sync_playwright() as pw:
    browser=pw.chromium.launch()
    context=browser.new_context()
    context.route("**/*", lambda route: route.abort())
    for oid, (name,label,url) in CASES.items():
        original=f'{SITE}/opportunities/{oid}'
        context.route(original,lambda route, *, n=name,l=label,u=url:route.fulfill(content_type='text/html',body=f'<html data-release-sha="{sha}"><main><h1>{n}</h1><a target="_blank" href="{u}">{l}</a></main></html>'))
    context.route(DIRECTORY,lambda route:route.fulfill(content_type='text/html',body=f'<h1>People</h1><a href="{ROBIN}">Robin Clayton</a>'))
    context.route(ROBIN,lambda route:route.fulfill(content_type='text/html',body='<h1>Robin Clayton</h1>'))
    for oid in CASES:
        page=context.new_page()
        page.goto(f'{SITE}/opportunities/{oid}')
        out=verify_click(page,oid,sha)
        assert out['campus_http']==200 and out['campus_landing']==CASES[oid][2]
        if oid==JACOB_ID: assert out['directory_lists_disputed_link_under_robin']
        page.close()
    context.route(ROBIN,lambda route:route.fulfill(status=404,content_type='text/html',body='<h1>Not found</h1>'))
    page=context.new_page()
    page.goto(f'{SITE}/opportunities/{ROBIN_ID}')
    try:
        verify_click(page,ROBIN_ID,sha)
    except AssertionError as err:
        assert '404' in str(err)
    else:
        raise AssertionError('A dead campus link was accepted')
    browser.close()
print('Offline only: two destination links passed and a campus 404 was correctly refused.')
