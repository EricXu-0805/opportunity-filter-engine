"""Review the published Boston calendar, eligibility, or ordinary matched results against its recorded release."""
import re
import subprocess
import sys
from pathlib import Path

sha, stage = sys.argv[1:]
assert re.fullmatch(r'[a-f0-9]{40}', sha) and stage in {'eligibility', 'results'}
dst = Path('data/audits/verify_m23_manual_20261126.py')
def previous(commit, path):
    return subprocess.check_output(['git', 'show', f'{commit}:{path}'], text=True)
if stage == 'eligibility':
    script = previous('0f8d8d5f', dst)
    script = script.replace('PHASE = "baseline"', 'PHASE = "after"').replace('EXPECTED = None', f'EXPECTED = "{sha}"')
else:
    candidate = previous('8443dca8', 'data/audits/verify_bu_stars_rank_branch_20261126.py')
    script = candidate.replace('site="http://127.0.0.1:28149"', 'site="https://joinalab.com"').replace("location.hostname==='127.0.0.1'", "location.hostname==='joinalab.com'")
    script = script.replace('receipt["local_backend"] = "real FastAPI, assembled 149810 records"', f'''assert release == "{sha}"
        assert f'data-release-sha="{{release}}"' in ctx.request.get(site).text()''')
    script = script.replace('isolated local session storage', 'ordinary new production guest')
    # Revisit the same external undergraduate profile used on the prior release.
    script = script.replace("College of Computing, Data Science, and Society", "College of Letters and Science")
    script = script.replace('enter_results(page,"bu",major="Biology"', 'enter_results(page,"ucb",major="Integrative Biology"')
    script = script.replace('        q="Summer', '''        receipt["student"] = {"school":"UC Berkeley","major":"Integrative Biology","year":"Junior"}
        q="Summer''')
    script = script.replace("        # The ordinary browser", '''        originals = ["bu-bbc659c6ac92", "sro-60f60fbd", "sro-bc33bc08"]
        response = ctx.request.post(site+"/api/opportunities/batch", data={"ids": originals})
        assert response.ok and response.json()["found"] == len(originals)
        records = {row["id"]:row for row in response.json()["opportunities"]}
        assert set(records) == set(originals)
        links = receipt["original_links"] = {}
        for oid in originals:
            page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
            expect(page.get_by_role("heading",level=1)).to_have_text(records[oid]["title"],timeout=70000)
            button = page.get_by_role("link",name=re.compile(r"^Apply\\b",re.I)).first
            expect(button).to_have_attribute("href", "https://www.bumc.bu.edu/gms/students/summer-training-as-research-scholars-program/")
            links[oid] = {"status":200, "page":page.url, "student_deadline":records[oid]["deadline"], "host":button.get_attribute("href")}
            assert links[oid]["student_deadline"] == "2027-01-15"
        # The ordinary browser''')
dst.write_text(script)
