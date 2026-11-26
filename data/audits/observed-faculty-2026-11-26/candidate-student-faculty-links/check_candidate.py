"""Apply the two production student cases unchanged to a specific isolated build."""
from importlib import util
import os
from pathlib import Path

location = Path(__file__).resolve().parents[1] / 'public-student-faculty-links' / 'check.py'
spec = util.spec_from_file_location('student_faculty_links', location)
probe = util.module_from_spec(spec)
spec.loader.exec_module(probe)
probe.SITE = 'http://127.0.0.1:3000'
if probe.CAMPUS == 'msu':
    probe.CASES = probe.CASES[:1]
probe.receipt.update(site=probe.SITE, environment='isolated candidate, actual local account DB and production-sized corpus')
try:
    assert list(probe.version().values()) == [os.environ['CANDIDATE']] * 2
    probe.run()
    for row in probe.receipt['records']:
        assert row.get('matches_all') or row.get('matches_starred'), row['id']
        for kind in ('detail','favorites','matches_all','matches_starred'):
            if kind in row:
                assert row[kind]['points_to'] == 'stored person URL', (row['id'],kind)
                assert row[kind]['landed_url'].rstrip('/') == row['person_url'].rstrip('/'), (row['id'],kind,row[kind]['landed_url'])
finally:
    probe.save()
