"""Offline navigation controls. No actual campus or production request is allowed."""

from b21_nc_state_destinations import CASES, DIRECTORY, JACOB_ID, ROBIN, ROBIN_ID, SITE, verify_click
from playwright.sync_api import sync_playwright


def run_controls():
    sha = "f" * 40
    responses = {}
    for oid, (name, label, url) in CASES.items():
        body = f'<html data-release-sha="{sha}"><main><h1>{name}</h1><a target="_blank" href="{url}">{label}</a></main></html>'
        responses[f"{SITE}/opportunities/{oid}"] = (200, body)
    responses[DIRECTORY] = (200, f'<h1>People</h1><a href="{ROBIN}">Robin Clayton</a>')
    responses[ROBIN] = (200, "<h1>Robin Clayton</h1>")

    def serve_fixture(route):
        url = route.request.url
        if url not in responses:
            return route.abort()
        status, body = responses[url]
        return route.fulfill(status=status, content_type="text/html", body=body)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context()
        context.route("**/*", serve_fixture)
        for oid in CASES:
            page = context.new_page()
            page.goto(f"{SITE}/opportunities/{oid}")
            result = verify_click(page, oid, sha)
            assert result["campus_http"] == 200 and result["campus_landing"] == CASES[oid][2]
            if oid == JACOB_ID:
                assert result["directory_lists_disputed_link_under_robin"]
            page.close()
        responses[ROBIN] = (404, "<h1>Not found</h1>")
        page = context.new_page()
        page.goto(f"{SITE}/opportunities/{ROBIN_ID}")
        try:
            verify_click(page, ROBIN_ID, sha)
        except AssertionError as err:
            assert "404" in str(err)
        else:
            raise AssertionError("A dead campus link was accepted")
        browser.close()


if __name__ == "__main__":
    run_controls()
    print("Two offline opening checks passed, and a 404 correctly failed.")
