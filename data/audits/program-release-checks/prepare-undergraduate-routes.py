"""Reuse the reviewed biology/history flows and compare three California pages at the released revision."""
import ast
from pathlib import Path
import subprocess
import sys

release = sys.argv[1]
assert len(release) == 40 and set(release) <= set("0123456789abcdef")
target = Path("data/audits/verify_m23_manual_20261126.py")
candidate = Path("data/audits/verify_bu_stars_rank_branch_20261126.py")
code = subprocess.check_output(["git", "show", f"dc30e482:{candidate}"], text=True)
code = code.replace("http://127.0.0.1:28149", "https://joinalab.com")
code = code.replace("location.hostname==='127.0.0.1'", "location.hostname==='joinalab.com'")
start = code.index('        receipt["local_backend"]')
end = code.index("        enter_results(page", start)
code = code[:start] + f'''        assert release == "{release}"
        homepage = ctx.request.get(site)
        assert homepage.ok and 'data-release-sha="{release}"' in homepage.text()
        receipt["frontend_release"] = receipt["backend_release"] = release
''' + code[end:]
# One production guest can update their own major and regenerate the results.
start = code.index("        history_context =")
end = code.index("        enter_results(history", start)
code = code[:start] + '''        history = page
        receipt["biology_guest_commit"] = receipt["profile_commit"]
        receipt["profile_commit"] = None
''' + code[end:]
before = subprocess.check_output(["git", "show", f"3d25976b:{target}"], text=True)
match = next(node for node in ast.parse(before).body if isinstance(node, ast.Assign)
             and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "cases")
cases = ast.literal_eval(match.value)
extra = '''
def california_details(page, context):
    for oid, host, qualifiers in CALIFORNIA:
        response = page.goto(host, wait_until="domcontentloaded")
        text = " ".join((page.locator("body").text_content() or "").lower().split())
        assert response.ok and all(phrase.lower() in text for phrase in qualifiers), oid
        detail = context.request.get(site + "/api/opportunities/" + oid)
        assert detail.ok
        row = detail.json()
        assert row["id"] == oid and row["is_rolling"] is False
        page.goto(site + "/opportunities/" + oid, wait_until="domcontentloaded")
        expect(page.get_by_role("heading", level=1)).to_have_text(row["title"], timeout=60000)
        body = page.locator("main").inner_text()
        apply_url = (row.get("application") or {}).get("application_url")
        if oid == "ucsb-45d0bef1a207":
            assert row["target_truth"]["actionable"] and row["deadline"] is None
            assert row["organization"] == "Cal-Bridge" and apply_url == host
            assert "Community College students transferring" in body and "Santa Barbara" not in row["location"]
        elif oid == "ucsd-c6d547c9321a":
            assert not row["target_truth"]["actionable"] and not apply_url
            assert row["deadline"] == "2026-11-20" and "2026-11-20" in body
        else:
            assert row["target_truth"]["reference_only"] and not row["target_truth"]["actionable"]
            assert not apply_url and row["eligibility"]["international_friendly"] == "unknown"
        receipt[oid] = {"deadline": row["deadline"], "rolling": row["is_rolling"],
                        "actionable": row["target_truth"]["actionable"], "source": host, "apply": apply_url}
        page.screenshot(path=out/(oid+"-verified-detail.png"))
'''
i = code.index("with sync_playwright()")
code = code[:i] + "CALIFORNIA = " + repr(cases) + "\n" + extra + "\n" + code[i:]
code = code.replace("        history_context.close()", "        california_details(page,ctx)")
assert "127.0.0.1" not in code and "history_context" not in code
target.write_text(code)
