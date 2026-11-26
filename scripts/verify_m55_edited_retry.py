"""Capture lost receipts against disposable Auth and PostgREST using the normal feedback form."""
import asyncio
import json
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

from verify_m52_historical_link import account, req, site


async def main():
    owner = account("Feedback QA", "uiuc", "Quality checks")
    other = account("Second QA", "uiuc", "Quality checks")
    fields = "/rest/v1/feedback?select=id,message,category,email,subject,client_token&order=created_at.asc"
    def tickets(user):
        return req(fields, session=user)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path="/usr/bin/google-chrome")
        context = await browser.new_context(locale="en-US")
        local = {"ofe_auth":json.dumps(owner), "ofe_lang":"en", "ofe_onboarding_seen":"1",
                 "ofe_school_confirmed":json.dumps({"slug":"uiuc","ts":"2026-11-26T00:00:00.000Z"})}
        await context.add_init_script("if(location.origin==='http://127.0.0.1:3100'&&!localStorage.getItem('feedback-qa')){for(const [k,v] of Object.entries("+json.dumps(local)+"))localStorage.setItem(k,v);localStorage.setItem('feedback-qa','1');}")
        await context.route("**/*", lambda r:r.continue_() if urlsplit(r.request.url).hostname in ("127.0.0.1","localhost") else r.abort())
        page = await context.new_page()
        await page.goto(site, wait_until="domcontentloaded")
        await expect(page.locator("#student_name")).to_have_value("Feedback QA",timeout=75000)
        await page.get_by_test_id("feedback-open").click()
        message = page.locator("#site-feedback textarea")
        await message.fill("Original synthetic accessibility report")
        await page.get_by_test_id("feedback-category").select_option("bug")
        send = page.get_by_test_id("feedback-send")
        lost = []
        async def lose_receipt(route):
            if route.request.method != "POST":
                await route.continue_()
                return
            response = await route.fetch()
            lost.append(response.status)
            await route.fulfill(status=503,content_type="application/json",body='{"message":"test response lost after commit"}')
        pattern = "**/rest/v1/feedback?*"
        await page.route(pattern, lose_receipt)
        await send.click()
        await expect(page.get_by_test_id("feedback-error")).to_be_visible(timeout=30000)
        first, = tickets(owner)
        assert 201 in lost and first["message"] == "Original synthetic accessibility report"
        await page.unroute(pattern,lose_receipt)
        await message.fill("Edited synthetic accessibility report")
        await page.get_by_test_id("feedback-subject").fill("A second finding")
        await page.reload(wait_until="domcontentloaded")
        await expect(page.locator("#student_name")).to_have_value("Feedback QA",timeout=75000)
        await page.get_by_test_id("feedback-open").click()
        await expect(message).to_have_value("Edited synthetic accessibility report")
        await send.click()
        await expect(page.get_by_test_id("feedback-error")).to_contain_text("Your earlier feedback was received")
        await expect(message).to_have_value("Edited synthetic accessibility report")
        assert tickets(owner)==[first]
        await send.click()
        await expect(page.get_by_test_id("feedback-reference")).to_be_visible()
        old,new=tickets(owner)
        assert old==first and new["id"]!=old["id"] and new["client_token"]!=old["client_token"]
        assert (new["message"],new["subject"],new["category"],new["email"])==("Edited synthetic accessibility report","A second finding","bug",None)
        assert tickets(other)==[]
        print("Verified: first write committed and reply lost, edit survived document reload, previous ticket receipt shown accurately, edited retry created one independent ticket, two visible to the submitter and zero to the other account.",flush=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
