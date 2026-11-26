"""Compare the exact M65 candidate to its original scorer on the full release.

Run at e0f0eb17 from a checkout that also contains base 50d4aca1. Example:
    PYTHONPATH=. python replay_m65_similar_projection.py
The script prints deidentified totals, output hashes and local CPU workload timings.
"""
from __future__ import annotations

import ast
import hashlib
import json
import statistics
import subprocess
import time

from backend.data_loader import load_opportunities
from backend.routes import matches, opportunities

BASE = '50d4aca1e4db82610e2c1483a4aa24b50f75b439'
CASES = (
    ('simplify-intern-fc6751c5-e093-4970-8fe5-90af5713b9e4', 1),
    ('faculty-cs-321c7f13', 5),
    ('faculty-cincinnati-cs-00772f54', 20),
    ('faculty-emory-rsph-6e024408', 5),
    ('faculty-uconn-pols-739644c6', 3),
    ('faculty-uconn-pols-840e7c22', 20),
)


def original_scorer():
    path = f'{BASE}:backend/routes/opportunities.py'
    source = subprocess.check_output(['git', 'show', path], text=True)
    node = next(n for n in ast.parse(source).body if getattr(n, 'name', '') == 'get_similar_opportunities')
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    scope = dict(vars(opportunities))
    exec(compile(module, path, 'exec'), scope)
    return scope[node.name]


def main():
    baseline = original_scorer()
    corpus = load_opportunities()
    assert len(corpus) == 149774
    matches._activate_corpus_generation(corpus)
    matches._match_universe = None
    rows = []
    for number, (record_id, limit) in enumerate(CASES):
        implementations = [('baseline', baseline), ('candidate', opportunities.get_similar_opportunities)]
        if number % 2:
            implementations.reverse()
        responses = {}
        elapsed = {}
        for name, handler in implementations:
            start = time.perf_counter()
            responses[name] = handler(record_id, limit)
            elapsed[name] = time.perf_counter() - start
        assert responses['baseline'] == responses['candidate'], record_id
        response = responses['candidate']
        canonical = json.dumps(response, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        rows.append({'id': record_id, 'limit': limit, 'total': response['total'], 'time': elapsed,
                     'sha256': hashlib.sha256(canonical.encode()).hexdigest()})
    print(json.dumps(rows, indent=2))
    for name in ('baseline', 'candidate'):
        print(name, 'warm wall median seconds', statistics.median(row['time'][name] for row in rows[1:]))


if __name__ == '__main__':
    main()
