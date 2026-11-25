import asyncio, json, subprocess, os, urllib.request, urllib.error, time
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect

stub = "http://127.0.0.1:51432"


def fetch(u, data=None, h=None, method="GET"):
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(u, data=data, headers=h or {}, method=method),
            timeout=24,
        )
    except urllib.error.HTTPError as ex:
        r = ex
    with r:
        return r.status, r.headers.get("Content-Type", "application/json"), r.read()


def rpc(path, data, auth={}):
    return json.loads(
        fetch(
            stub + path,
            json.dumps(data).encode(),
            {"Content-Type": "application/json", **auth},
            "POST",
        )[2]
    )


async def main():
    proc = subprocess.Popen(
        ["node", "frontend/e2e/supabase-stub.mjs"],
        env={**os.environ, "E2E_SUPABASE_PORT": "51432"},
        stdout=subprocess.DEVNULL,
    )
    try:
        for i in range(40):
            try:
                fetch(stub + "/health")
                break
            except OSError:
                await asyncio.sleep(0.1)
        session = rpc("/auth/v1/signup", {})
        uid = session["user"]["id"]
        auth = {"Authorization": "Bearer " + session["access_token"]}
        old = {"name": "PyTorch", "source": "github", "level": "beginner"}
        other = {"name": "Git", "level": "expert", "confirmed": True}
        profile = {
            "name": "Synthetic M212",
            "institution": "UIUC",
            "college": "Grainger College of Engineering",
            "grade": "Sophomore",
            "major": "Computer Science",
            "research_interests": "computing",
            "github_url": "https://github.com/m212-fixture",
            "skills": [old],
            "coursework": [],
            "seeking_types": ["Research"],
            "is_international": False,
        }

        def save(rev, patch):
            r = rpc(
                "/rest/v1/rpc/commit_profile_patch_cas",
                {
                    "p_expected_device_id": uid,
                    "p_expected_revision": rev,
                    "p_patch": patch,
                },
                auth,
            )
            assert r["status"] == "applied", r["status"]
            return r

        save(0, profile)
        for rev in range(1, 7):
            save(rev, {"name": "Synthetic M212 " + str(rev)})
        commits = []
        done = asyncio.Event()
        async with async_playwright() as pw:
            b = await pw.chromium.launch(
                executable_path="/usr/bin/google-chrome",
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            c = await b.new_context(service_workers="block")
            await c.add_init_script(
                "if(location.hostname==='joinalab.com'&&!localStorage.getItem('ofe_auth')){localStorage.setItem('ofe_auth',"
                + json.dumps(json.dumps(session))
                + ");localStorage.setItem('ofe_lang','en');localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_school_confirmed',JSON.stringify({slug:'uiuc',ts:new Date().toISOString()}))}"
            )

            async def intercept(route):
                req = route.request
                u = urlsplit(req.url)
                path = u.path + ("?" + u.query if u.query else "")
                try:
                    if u.hostname == "mjpirkyduibkakvlbdko.supabase.co":
                        if req.method == "OPTIONS":
                            return await route.fulfill(
                                status=204,
                                headers={
                                    "Access-Control-Allow-Origin": "https://joinalab.com",
                                    "Access-Control-Allow-Headers": req.headers.get(
                                        "access-control-request-headers", "*"
                                    ),
                                    "Access-Control-Allow-Methods": "GET,POST,OPTIONS,PATCH,DELETE",
                                },
                            )
                        h = {"Content-Type": "application/json"}
                        for k in ["authorization", "accept", "prefer", "range"]:
                            if req.headers.get(k):
                                h[k] = req.headers[k]
                        if "commit_profile_patch_cas" in u.path:
                            if not commits:
                                save(7, {"skills": [old, other]})
                        code, ct, body = fetch(
                            stub + path, req.post_data_buffer, h, req.method
                        )
                        if "commit_profile_patch_cas" in u.path:
                            result = json.loads(body)
                            commits.append(
                                (result.get("status"), result.get("revision"))
                            )
                            print("CAS", commits, flush=True)
                            if result.get("status") == "applied":
                                done.set()
                    elif u.hostname == "joinalab.com" and u.path.startswith(
                        "/api/resume/github/"
                    ):
                        code, ct, body = (
                            200,
                            "application/json",
                            json.dumps(
                                {
                                    "username": "m212-fixture",
                                    "repo_count": 1,
                                    "extracted_skills": ["PyTorch"],
                                    "skill_evidence": [
                                        {
                                            "skill": "PyTorch",
                                            "repo": "vision",
                                            "field": "topic",
                                            "value": "pytorch",
                                        }
                                    ],
                                }
                            ).encode(),
                        )
                    elif u.hostname == "joinalab.com" and req.method == "GET":
                        return await route.continue_()
                    else:
                        return await route.abort()
                    await route.fulfill(
                        status=code,
                        body=body,
                        content_type=ct,
                        headers={"Access-Control-Allow-Origin": "*"},
                    )
                except Exception as e:
                    print("route failure", u.path[:80], type(e).__name__, flush=True)
                    try:
                        await route.abort()
                    except Exception:
                        pass

            await c.route_web_socket("**/*", lambda ws: ws.close())
            await c.route("**/*", intercept)
            page = await c.new_page()
            await page.goto(
                "https://joinalab.com/", wait_until="domcontentloaded", timeout=80000
            )
            await expect(page.locator("#github_url")).to_have_value("https://github.com/m212-fixture", timeout=70000)
            await (
                page.locator("#github_url")
                .locator("..")
                .get_by_role("button")
                .click(timeout=20000)
            )
            await asyncio.wait_for(done.wait(), 25)
            read = lambda: json.loads(
                fetch(
                    stub
                    + "/rest/v1/profiles?select=profile_data,revision&id=eq."
                    + uid,
                    h=auth,
                )[2]
            )[0]
            r = read()
            print("re-read", r["revision"], r["profile_data"]["skills"], flush=True)
            assert commits == [("conflict", 8), ("applied", 9)] and r["revision"] == 9
            assert r["profile_data"]["skills"] == [
                {**old, "evidence": "repo vision: topic pytorch"},
                other,
            ]
            await page.reload(wait_until="domcontentloaded")
            await expect(page.locator("#github_url")).to_have_value("https://github.com/m212-fixture", timeout=40000)
            print("fresh page loaded revision 9", read()["revision"], flush=True)
            await b.close()
    finally:
        proc.terminate()
        proc.wait()


asyncio.run(main())
