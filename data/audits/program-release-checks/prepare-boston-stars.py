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
dst.write_text(script)
