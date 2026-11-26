"""Read two original opportunity IDs in the live bilingual public site and follow official sources."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
from playwright.sync_api import TimeoutError, sync_playwright

SITE = "https://joinalab.com"
RELEASE = "77603b9e0afac651bcd82428e6c59494aaa5b1ce"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
FACULTY_ID = "faculty-ucb-stat-5558a1b1"
PROGRAM_ID = "ext-usc-ict"
PROFILE = "https://statistics.berkeley.edu/people/rasmus-nielsen"
LAB = "https://nielsen-lab.github.io/"
TEAM = LAB + "team/"
RESEARCH = LAB + "research/"
OUT = Path("evidence")
OUT.mkdir(exist_ok=True)
report = {
    "observed_utc": datetime.now(timezone.utc).isoformat(),
    "action_run": "https://github.com/" + os.environ["GITHUB_REPOSITORY"] + "/actions/runs/" + os.environ["GITHUB_RUN_ID"],
    "release": RELEASE, "cases": {}
}


def original_detail(context, page, record_id, case):
    resp = page.goto(f"{SITE}/opportunities/{record_id}", wait_until="domcontentloaded")
    assert resp and resp.status == 200
    assert page.locator("html").get_attribute("data-release-sha") == RELEASE
    response = context.request.get(
        f"{SITE}/api/opportunities/{record_id}", params={"_release_scope": SCOPE}
    )
    assert response.ok
    data = response.json()
    assert data["id"] == record_id
    case.update(original_id=record_id, url=page.url, detail_http=resp.status,
                api_http=response.status, title=data["title"], source=data["source"],
                source_url=data["source_url"])
    return data


def onboarding(page):
    dialog = page.get_by_role("dialog", name="Welcome to JoinALab")
    try:
        dialog.wait_for(state="visible", timeout=6500)
    except TimeoutError:
        return
    dialog.get_by_role("button", name="Skip tour", exact=True).click()
    school = dialog.get_by_test_id("onboarding-school-ucb")
    school.click()
    assert school.get_attribute("aria-pressed") == "true"
    dialog.get_by_test_id("onboarding-primary").click()
    dialog.wait_for(state="hidden", timeout=30000)


def follow(page, link, url, responses):
    link.wait_for(state="visible")
    if link.get_attribute("target") == "_blank":
        with page.context.expect_page() as popup:
            link.click()
        destination = popup.value
    else:
        link.click()
        destination = page
    destination.wait_for_url(url, wait_until="domcontentloaded")
    assert any(address == url and status == 200 for address, status in responses)
    return destination


def berkeley(context, case):
    page = context.new_page()
    data = original_detail(context, page, FACULTY_ID, case)
    heading = page.get_by_role("heading", name="Rasmus Nielsen", exact=True).first
    heading.wait_for(state="visible")
    onboarding(page)
    case["visible_heading"] = heading.inner_text()
    assert data["source_url"] == PROFILE and data["title"] == "Rasmus Nielsen"
    lab = data["lab_context"]
    case["public_lab_status"] = lab["status"]
    assert lab["status"] == "available"
    snap = lab["snapshot"]
    assert snap["record_id"] == FACULTY_ID and snap["identity_name"] == "Rasmus Nielsen"
    cases = {v["source_url"]: len(v["sections"]) for v in snap["pages"]}
    assert cases == {PROFILE:3, RESEARCH:10}
    chain = {d["role"]: d["source_url"] for d in snap["source_chain"]["documents"]}
    assert chain == {"profile":PROFILE,"home":LAB,"team":TEAM,"research":RESEARCH}
    identity = snap["source_chain"]["identity"]
    assert identity["full_name"] == "Rasmus Nielsen" and identity["source_url"] == TEAM
    case.update(section_counts=cases, attributed_sources=chain, identity_name=identity["full_name"],
                checked_at=snap["checked_at"], snapshot_version=snap["snapshot_version"])
    case["visible_draft_buttons"] = page.get_by_role("button",name="Draft email",exact=True).count()
    faculty_link = page.get_by_role("link", name="View faculty profile", exact=True).first
    assert faculty_link.get_attribute("href") == PROFILE
    page.screenshot(path=str(OUT / "berkeley-original-detail.png"),full_page=True)
    nav = []
    context.on("response", lambda r: nav.append((r.url, r.status)) if r.request.is_navigation_request() else None)
    profile = follow(page, faculty_link, PROFILE, nav)
    assert "Rasmus Nielsen" in profile.title()
    home_link = profile.locator('a[href="https://nielsen-lab.github.io"],a[href="https://nielsen-lab.github.io/"]').first
    home = follow(profile, home_link, LAB, nav)
    assert "Nielsen Lab" in home.title()
    team = follow(home, home.get_by_role("link",name="Team",exact=True).first, TEAM, nav)
    team.get_by_text("Rasmus Nielsen",exact=True).first.wait_for(state="visible")
    research = follow(team, team.get_by_role("link",name="Research",exact=True).first, RESEARCH, nav)
    assert "research" in research.title().lower()
    case.update(browser_navigation=[{"url":u,"http":s} for u,s in nav if u in chain.values()], team_member_visible=True,
                public_research_page_title=research.title(), snapshot_display_location="Formal site opportunity detail API")


def national(context, case):
    page = context.new_page()
    data = original_detail(context, page, PROGRAM_ID, case)
    onboarding(page)
    assert data["source"] == "manual" and data["source_url"] == "https://ict.usc.edu/reu/"
    for language, label in [("en","Manually curated"),("zh","人工整理")]:
        if language == "zh":
            page.locator('button[aria-label="切换到中文"]:visible').first.click()
        box = page.get_by_text(label, exact=False).first
        box.wait_for(state="visible")
        content = box.inner_text()
        assert label in content and "UIUC" not in content
        box.scroll_into_view_if_needed()
        box.screenshot(path=str(OUT / f"national-label-{language}.png"))
        case[language] = {"visible": content, "lang": page.locator("html").get_attribute("lang")}
    case["official_usc_link"] = page.locator('a[href="https://ict.usc.edu/reu/"]').count()
    assert case["official_usc_link"] > 0


with sync_playwright() as engine:
    browser = engine.chromium.launch(channel="chrome")
    for name, scenario in [("berkeley_faculty", berkeley), ("manual_national_program", national)]:
        case = report["cases"][name] = {}
        context = browser.new_context(locale="en-US",viewport={"width":1280,"height":920})
        context.set_default_timeout(18000)
        try:
            version = context.request.get(SITE + "/api/health").json()["release_sha"]
            origin = context.request.get("https://opportunity-filter-engine-api.onrender.com/api/health").json()["release_sha"]
            case.update(site_backend_sha=version,render_origin_sha=origin)
            assert version == RELEASE == origin
            scenario(context, case)
            case["passed"] = True
        except Exception as exc:
            case.update(passed=False,error=type(exc).__name__ + ": " + str(exc)[:1000])
            print(name, case["error"])
            for i,p in enumerate(context.pages):
                if p.url.startswith(SITE):
                    try:
                        p.screenshot(path=str(OUT/f"{name}-failure-{i}.png"),timeout=5000)
                        (OUT/f"{name}-failure-{i}.txt").write_text(p.locator("body").inner_text(timeout=5000))
                    except Exception:
                        pass
        finally:
            context.close()
            (OUT/"b7-berkeley-manual.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    browser.close()
assert all(c["passed"] for c in report["cases"].values()), str({k:v["passed"] for k,v in report["cases"].items()})
