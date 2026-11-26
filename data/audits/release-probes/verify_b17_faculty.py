"""Read public details on one deployed SHA, using B17's previously verified original IDs."""
import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import TimeoutError as BrowserTimeout, async_playwright

SITE = "https://joinalab.com"
QUERY = urlencode({"_release_scope": "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
CASES = Path(__file__).with_name("b17-georgetown-indiana-cases.json")


async def check_release(context, page, expected):
    health = await context.request.get(SITE + "/api/health")
    assert health.ok and (await health.json())["release_sha"] == expected, "backend SHA"
    await page.goto(SITE + "/about", wait_until="domcontentloaded")
    assert await page.locator("html").get_attribute("data-release-sha") == expected, "frontend SHA"


async def inspect(context, page, case, expected):
    path = "/opportunities/" + case["id"]
    api = await context.request.get(SITE + "/api" + path + "?" + QUERY)
    result = {"id": case["id"], "status": api.status, "checks": {}}
    checks = result["checks"]
    checks["public_api"] = api.ok
    if not api.ok:
        return result
    data = await api.json()
    truth = data.get("target_truth") or {}
    observed = {"id": data["id"], "name": data.get("pi_name"), "actionable": truth.get("actionable"),
                "profile": data.get("url"), "roster": data.get("source_url"), "current": data.get("current_faculty_id"),
                "contact_status": data.get("contact_email_status")}
    result["api"] = observed
    for key in observed:
        if key in case:
            checks["api_" + key] = observed[key] == case[key]
    response = await page.goto(SITE + path, wait_until="domcontentloaded")
    result["html_status"] = response.status if response else None
    heading = page.get_by_role("heading", level=1).filter(has_text=case["name"]).first
    try:
        await heading.wait_for(state="visible", timeout=15000)
    except BrowserTimeout:
        pass
    observed_headings = await page.get_by_role("heading", level=1).all_text_contents()
    result["page_headings"] = observed_headings[:3]
    checks["visible_details"] = bool(response and response.ok and await heading.is_visible())
    checks["frontend_release"] = await page.locator("html").get_attribute("data-release-sha") == expected
    if case.get("current"):
        target = "/opportunities/" + case["current"]
        checks["current_link"] = await page.locator(f'main a[href="{target}"]').first.is_visible()
    if not case["actionable"]:
        # A student can still log an earlier application in their private history.
        # The header must show the inactive state and withhold current outreach.
        checks["inactive_banner"] = await page.get_by_role("status").filter(has_text="This record is no longer active.").first.is_visible()
        checks["no_email_draft"] = not await page.get_by_role("button", name="Draft email", exact=True).first.is_visible()
        checks["no_apply_link"] = not await page.get_by_role("link", name="Apply now", exact=True).first.is_visible()
    if case.get("roster"):
        action = page.get_by_role("link", name="View faculty profile", exact=True).first
        try:
            await action.wait_for(state="visible", timeout=8000)
        except BrowserTimeout:
            pass
        result["observed_action_href"] = await action.get_attribute("href") if await action.is_visible() else None
        checks["personal_action"] = await action.is_visible() and await action.get_attribute("href") == case["profile"]
        source_links = await page.locator("main a[href]").evaluate_all("(els) => els.map(el => el.href)")
        checks["roster_citation_in_page"] = case["roster"] in source_links
    return result


async def run(args):
    cases = json.loads(CASES.read_text())["cases"]
    if args.id:
        chosen = set(args.id)
        cases = [c for c in cases if c["id"] in chosen]
        assert len(cases) == len(chosen)
    checked = []
    async with async_playwright() as browser_api:
        browser = await browser_api.chromium.launch(channel=args.channel, headless=True)
        context = await browser.new_context(locale="en-US")
        control = await context.new_page()
        await check_release(context, control, args.sha)
        queue = iter(cases)

        async def worker():
            page = await context.new_page()
            for case in queue:
                try:
                    row = await inspect(context, page, case, args.sha)
                except Exception as exc:
                    row = {"id": case["id"], "checks": {"completed": False}, "error": str(exc)}
                checked.append(row)
                await asyncio.sleep(0.5)
            await page.close()

        await asyncio.gather(worker(), worker())
        await check_release(context, control, args.sha)
        await browser.close()
    failures = [r["id"] for r in checked if not all(r["checks"].values())]
    receipt = {"observed_utc": datetime.now(UTC).isoformat(), "deployed_sha": args.sha,
               "stage": "before" if args.before else "after", "checked": len(checked), "failures": failures,
               "details": sorted(checked, key=lambda r: r["id"])}
    Path(args.out).write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    print(f'{len(checked)} original IDs, {len(failures)} differ from expected B17 behavior')
    if not args.before and failures:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--id", action="append")
    parser.add_argument("--before", action="store_true")
    asyncio.run(run(parser.parse_args()))
