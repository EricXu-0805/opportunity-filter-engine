"""Run one scoped real first-party browser verification after a release."""
import json
import os
from pathlib import Path
import subprocess
import sys

directory = Path(__file__).parent
selection = {'scenario':os.environ.get('INPUT_SCENARIO'), 'expectation':os.environ.get('INPUT_EXPECTATION')}
if not selection['scenario']:
    selection=json.loads((directory/'next.json').read_text())
script={'unmapped':'unmapped.py','positions':'positions.py','courses':'check.py','publication':'publication.py','layouts':'layouts.py','unreadable':'unreadable.py'}[selection['scenario']]
expected=selection['expectation']
if expected not in ('baseline','fixed'):
    raise ValueError('Expected baseline or fixed.')
subprocess.run([sys.executable,'-u',str(directory/script)],env={**os.environ,'PDF_ACCEPTANCE_MODE':expected},check=True)
