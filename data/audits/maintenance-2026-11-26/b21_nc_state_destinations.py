"""Follow the two disputed NC State reading links from the same production visitor."""
from playwright.sync_api import expect

SITE = "https://joinalab.com"
DIRECTORY = "https://chass.ncsu.edu/group/faculty/"
ROBIN = "https://chass.ncsu.edu/people/jrclayt2/"
JACOB_ID = "faculty-ncsu-chass-e417d225"
ROBIN_ID = "faculty-ncsu-chass-8026d528"
CASES = {
    JACOB_ID: ("Jacob Clayton", "View source", DIRECTORY),
    ROBIN_ID: ("Robin Clayton", "View faculty profile", ROBIN),
}


def verify_click(page, oid, sha):
    name, label, destination = CASES[oid]
    assert page.url == f"{SITE}/opportunities/{oid}"
    assert page.locator("html").get_attribute("data-release-sha") == sha
    main = page.get_by_role("main")
    expect(main.get_by_role("heading", name=name, exact=True, level=1)).to_be_visible()
    anchor = main.get_by_role("link", name=label, exact=True)
    expect(anchor).to_be_visible()
    expect(anchor).to_have_attribute("href", destination)
    if oid == JACOB_ID:
        expect(main.get_by_role("link", name="View faculty profile", exact=True)).to_have_count(0)
    def is_landing(response):
        return response.url == destination and response.request.resource_type == "document"
    with page.context.expect_event("response", predicate=is_landing, timeout=40000) as nav:
        with page.expect_popup(timeout=25000) as opened:
            anchor.click(timeout=25000)
    campus = opened.value
    try:
        assert nav.value.status == 200, f"NC State returned HTTP {nav.value.status}"
        campus.wait_for_load_state("domcontentloaded", timeout=40000)
        assert campus.url == destination, f"The clicked destination did not land on {destination}"
        if oid == JACOB_ID:
            # The directory includes the disputed personal URL under Robin's name.
            expect(campus.get_by_role("heading", name="People", exact=True).first).to_be_visible()
            addresses = campus.locator("a[href]").evaluate_all(
                "(links, target) => links.filter(a => a.href === target).map(a => a.textContent.trim())", ROBIN)
            assert not any("Jacob Clayton" in n for n in addresses), "The campus directory assigns Robin's URL to Jacob"
            evidence = {"heading": "People",
                        "directory_lists_disputed_link_under_robin": any("Robin Clayton" in n for n in addresses)}
        else:
            expect(campus.get_by_role("heading", name="Robin Clayton", exact=True).first).to_be_visible()
            evidence = {"heading": "Robin Clayton"}
        return {"original_id": oid, "origin": page.url, "original_heading": name,
                "visible_link_clicked": label, "campus_http": nav.value.status,
                "campus_landing": campus.url, **evidence}
    finally:
        campus.close()

