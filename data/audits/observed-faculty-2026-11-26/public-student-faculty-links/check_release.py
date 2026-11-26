"""Read all six ordinary student routes after the fixed commit reaches public main."""
import json
import os
import re
import subprocess
from pathlib import Path

import check as probe

SOURCE = '2c2a6cc58ad105582d89f3a5b71dacc380ad8212'
REPO = 'EricXu-0805/opportunity-filter-engine'
release = json.loads(Path(__file__).with_name('release-request.json').read_text())['release_sha']
assert re.fullmatch('[0-9a-f]{40}', release)
def compare(base, head):
    return subprocess.check_output(['gh','api',f'repos/{REPO}/compare/{base}...{head}','--jq','.status'],text=True).strip()

assert compare(SOURCE, release) in ('identical','ahead'), 'The release must include the real source fix'
assert compare(release, 'main') in ('identical','ahead'), 'The release must be on main'
assert list(probe.version().values()) == [release]*2, 'Wait for the same release on both production services'
if probe.CAMPUS == 'msu':
    probe.CASES = probe.CASES[:1]
probe.receipt.update(expected_release=release, source_revision=SOURCE)
try:
    probe.run()
    assert list(probe.receipt['end'].values()) == [release]*2
    row = probe.receipt['records'][0]
    for kind in ('detail','favorites','matches_all'):
        assert row[kind]['points_to'] == 'stored person URL', (row['id'],kind)
        assert row[kind]['landed_url'].rstrip('/') == row['person_url'].rstrip('/'), (row['id'],kind)
finally:
    probe.save()
