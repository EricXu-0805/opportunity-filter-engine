"""Independent B47 acceptance at the public durable-runner boundary.

All HTTP is injected. The process-lock case launches only local Python/SQLite;
no provider, production corpus, or scheduled workflow is used.
"""
from __future__ import annotations

import os
import select
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.collectors import openalex_enrich as oa
from src.collectors.research_queue import ResearchQueue, run_refresh

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
BASE = 'a' * 40
ROOT = Path(__file__).resolve().parents[1]


def people(count=1):
    return [
        {'id': f'person-{i:03d}', 'school': 'uiuc', 'pi_name': f'Pat{i} Lee',
         'source_type': 'faculty_research', 'department': 'Computer Science',
         'source_url': f'https://example.edu/faculty/{i}',
         'metadata': {'publication_author_id': f'https://openalex.org/A{1000+i}',
                      'publication_attribution_status': 'verified_author_id', 'works_gate': 3}}
        for i in range(count)
    ]


class LocalTransport:
    def __init__(self, records, *, modes=None):
        self.records = {row['metadata']['publication_author_id']: row for row in records}
        self.modes = modes or {}
        self.calls = []

    def __call__(self, params, *, url, timeout=20, session=None):
        assert session is None
        assert 0 < timeout <= 20
        self.calls.append((deepcopy(params), url, timeout))
        telemetry = {'http_status': 200, 'retry_after_seconds': None,
                     'credits_used': 1.0, 'remaining': 1000.0, 'reset_seconds': None}
        if url == oa._WORKS_API:
            ids = params['filter'].split(':', 1)[1].split('|')
            assert len(ids) == 1, 'Runner checkpoints one record before moving on.'
            aid = 'https://openalex.org/' + ids[0]
            row = self.records[aid]
            mode = self.modes.get(row['id'])
            if mode == 'empty':
                return {'results': [], 'meta': {'count': 0}}, None, telemetry
            if mode == 'incomplete':
                return {'results': [], 'meta': {'count': 100}}, None, telemetry
            work = {'id': 'https://openalex.org/W' + aid.rsplit('A', 1)[1],
                    'display_name': f"Full study for {row['pi_name']}",
                    'publication_year': 2026, 'publication_date': '2026-08-01',
                    'primary_topic': {'field': {'display_name': 'Computer Science'}},
                    'authorships': [{'author': {'id': aid}}],
                    'doi': 'https://doi.org/10.1234/fixture',
                    'abstract_inverted_index': {'Complete': [0], 'abstract.': [1]},
                    'updated_date': '2026-09-01T12:00:00'}
            return {'results': [work], 'meta': {'count': 1}}, None, telemetry
        aid = 'https://openalex.org/' + url.rsplit('/', 1)[-1]
        row = self.records[aid]
        mode = self.modes.get(row['id'])
        if mode == 'server_error':
            return None, 'server_error', {**telemetry, 'http_status': 503}
        author = {'id': aid, 'display_name': 'A Different Person' if mode == 'revoked' else row['pi_name'],
                  'affiliations': [{'institution': {'id': 'https://openalex.org/I157725225'}}],
                  'topics': [{'field': {'display_name': 'Computer Science'}}]}
        return author, None, telemetry


def run(records, state, run_id, transport, *, at=NOW, **options):
    return run_refresh(records, state_path=state, run_id=run_id, base_sha=BASE,
                       now=at, clock=lambda: at.timestamp(), transport=transport, **options)


def no_http(*args, **kwargs):
    pytest.fail('This operation must not start an HTTP request.')


def assert_counts(result):
    actual = Counter(item['outcome'] for item in result['targets'] if item['outcome'] is not None)
    assert {key: value for key, value in result['counts'].items() if value} == dict(actual)
    assert sum(result['counts'].values()) == len(result['targets'])


def test_sixty_people_rotate_25_25_10_without_rewriting_source(tmp_path):
    records = people(60); before = deepcopy(records)
    state = tmp_path / 'queue.sqlite'; transport = LocalTransport(records)
    reports = [run(records, state, f'round-{i}', transport) for i in range(3)]
    assert [len(item['targets']) for item in reports] == [25, 25, 10]
    ids = [target['record_id'] for report in reports for target in report['targets']]
    assert len(ids) == len(set(ids)) == 60
    assert set(ids) == {row['id'] for row in records}
    for report in reports:
        assert report['status'] == 'completed'
        assert report['counts']['success_nonempty'] == len(report['targets'])
        assert report['request_count'] == 2 * len(report['targets'])
        assert report['credit_accounting_complete'] is True
        assert report['credits_observed'] == report['request_count']
        assert_counts(report)
    assert len(transport.calls) == 120 and records == before
    assert run(records, state, 'nothing-due', no_http)['targets'] == []


def test_success_and_successful_empty_have_same_thirty_day_cooldown(tmp_path):
    records = people(2); state = tmp_path / 'queue.sqlite'
    transport = LocalTransport(records, modes={'person-001': 'empty'})
    initial = run(records, state, 'initial', transport)
    assert [t['outcome'] for t in initial['targets']] == ['success_nonempty', 'success_empty']
    assert run(records, state, 'before-due', no_http, at=NOW + timedelta(days=30, seconds=-1))['targets'] == []
    due = run(records, state, 'after-due', transport, at=NOW + timedelta(days=30, seconds=1))
    assert len(due['targets']) == 2 and due['counts']['success_empty'] == 1
    assert len(transport.calls) == 8


@pytest.mark.parametrize('position', [1, 2])
def test_first_429_stops_author_or_works_and_cooldown_survives_restart(tmp_path, position):
    records = people(3); state = tmp_path / 'queue.sqlite'; transport = LocalTransport(records)
    calls = []
    def limited(params, *, url, **kwargs):
        calls.append(url)
        if len(calls) == position:
            return None, 'rate_limited', {'http_status': 429, 'retry_after_seconds': 90.0,
                'credits_used': None, 'remaining': None, 'reset_seconds': 120.0}
        return transport(params, url=url, **kwargs)
    result = run(records, state, 'limited', limited)
    assert len(calls) == position and result['request_count'] == position
    assert result['status'] == 'deferred'
    assert result['targets'][0]['reason'] == 'rate_limited'
    assert result['targets'][0]['attempted'] is True
    assert all(t['outcome'] == 'deferred' and not t['attempted'] and t['patch'] is None for t in result['targets'][1:])
    assert result['credit_accounting_complete'] is False
    assert datetime.fromisoformat(result['cooldown_until'].replace('Z', '+00:00')) >= NOW + timedelta(seconds=120)
    run(records, state, 'during-cooldown', no_http, at=NOW + timedelta(seconds=60))
    assert_counts(result)


def test_remaining_credit_floor_stops_before_second_request(tmp_path):
    records = people(2); transport = LocalTransport(records)
    def at_floor(params, *, url, **kwargs):
        data, error, telemetry = transport(params, url=url, **kwargs)
        return data, error, {**telemetry, 'remaining': 2.0}
    result = run(records, tmp_path / 'queue.sqlite', 'floor', at_floor, min_remaining=2)
    assert len(transport.calls) == result['request_count'] == 1
    assert result['status'] == 'deferred'
    assert all(t['outcome'] == 'deferred' and t['patch'] is None for t in result['targets'])
    assert_counts(result)


class SimulatedPowerLoss(BaseException):
    pass


def test_reserved_request_is_not_refunded_when_process_loses_response(tmp_path):
    records = people(2); state = tmp_path / 'queue.sqlite'; started = []
    def crash(*args, **kwargs):
        started.append(True)
        raise SimulatedPowerLoss()
    with pytest.raises(SimulatedPowerLoss):
        run(records, state, 'power-loss', crash, max_requests=1)
    with ResearchQueue(state) as queue:
        interrupted = queue.load_run('power-loss')
    assert interrupted['request_count'] == 1
    assert interrupted['unknown_request_count'] == 1
    assert interrupted['credit_accounting_complete'] is False
    resumed = run(records, state, 'power-loss', no_http, max_requests=1)
    assert resumed['status'] == 'deferred' and resumed['request_count'] == 1
    assert resumed['unknown_request_count'] == 1
    assert len(started) == 1
    assert all(t['patch'] is None for t in resumed['targets'])
    assert_counts(resumed)


def test_original_deadline_survives_interrupted_run(tmp_path):
    records = people(1); state = tmp_path / 'queue.sqlite'
    with pytest.raises(SimulatedPowerLoss):
        run(records, state, 'deadline', lambda *a, **k: (_ for _ in ()).throw(SimulatedPowerLoss()), max_seconds=10)
    resumed = run(records, state, 'deadline', no_http, at=NOW + timedelta(seconds=11), max_seconds=10)
    assert resumed['status'] == 'deferred' and resumed['request_count'] == 1
    assert resumed['started_at'] == NOW.isoformat().replace('+00:00', 'Z')
    assert_counts(resumed)


def test_completed_run_replay_is_identical_without_http_or_extra_count(tmp_path):
    records = people(2); state = tmp_path / 'queue.sqlite'; transport = LocalTransport(records)
    first = run(records, state, 'replay', transport)
    replay = run(records, state, 'replay', no_http, at=NOW + timedelta(days=40))
    assert replay == first
    assert len(transport.calls) == 4


@pytest.mark.parametrize('change', ['limit', 'max_requests', 'max_seconds', 'min_remaining', 'schools', 'base_sha', 'corpus'])
def test_same_run_id_rejects_changed_frozen_input_before_http(tmp_path, change):
    records = people(2); state = tmp_path / 'queue.sqlite'
    original = run(records, state, 'frozen', LocalTransport(records))
    options = {'state_path': state, 'run_id': 'frozen', 'base_sha': BASE,
               'now': NOW, 'clock': lambda: NOW.timestamp(), 'transport': no_http}
    if change == 'corpus':
        records[0]['department'] = 'Mathematics'
    else:
        options[change] = {'limit': 1, 'max_requests': 3, 'max_seconds': 30,
                           'min_remaining': 2, 'schools': ['uiuc'], 'base_sha': 'b' * 40}[change]
    with pytest.raises(ValueError):
        run_refresh(records, **options)
    with ResearchQueue(state) as queue:
        assert queue.load_run('frozen') == original


def test_revoked_binding_cannot_be_resurrected_by_old_verified_input(tmp_path):
    records = people(1); before = deepcopy(records); state = tmp_path / 'queue.sqlite'
    revoked = run(records, state, 'revoke', LocalTransport(records, modes={'person-000': 'revoked'}))
    assert revoked['targets'][0]['outcome'] == 'identity_revoked'
    assert records == before and records[0]['metadata']['publication_attribution_status'] == 'verified_author_id'
    # Deliberately feed the unmodified old corpus; the durable revoked task wins.
    resumed = run(records, state, 'old-corpus-replay', no_http, at=NOW + timedelta(days=60))
    assert not any(t['outcome'] in {'success_nonempty', 'success_empty'} for t in resumed['targets'])
    assert records == before


def test_mixed_outcomes_have_exact_non_overlapping_counts(tmp_path):
    records = people(5)
    transport = LocalTransport(records, modes={'person-001': 'empty', 'person-002': 'server_error',
                                               'person-003': 'incomplete', 'person-004': 'revoked'})
    result = run(records, tmp_path / 'queue.sqlite', 'mixed', transport)
    assert [t['outcome'] for t in result['targets']] == ['success_nonempty', 'success_empty', 'failed', 'incomplete', 'identity_revoked']
    assert all(t['attempted'] for t in result['targets'])
    assert result['request_count'] == len(transport.calls) == 8
    assert_counts(result)


def test_transient_retry_waits_then_stops_after_three_attempts(tmp_path):
    records = people(1); state = tmp_path / 'queue.sqlite'
    transport = LocalTransport(records, modes={'person-000': 'server_error'})
    first = run(records, state, 'retry-1', transport)
    assert first['targets'][0]['outcome'] == 'failed'
    run(records, state, 'too-early-1', no_http, at=NOW + timedelta(seconds=299))
    second = run(records, state, 'retry-2', transport, at=NOW + timedelta(seconds=301))
    assert second['targets'][0]['outcome'] == 'failed'
    run(records, state, 'too-early-2', no_http, at=NOW + timedelta(seconds=900))
    third = run(records, state, 'retry-3', transport, at=NOW + timedelta(seconds=902))
    assert third['targets'][0]['outcome'] == 'needs_review'
    run(records, state, 'no-automatic-fourth', no_http, at=NOW + timedelta(days=60))
    assert len(transport.calls) == 3


def test_actual_second_process_is_busy_then_os_exit_releases_lock(tmp_path):
    state = tmp_path / 'queue.sqlite'
    env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
    holder_code = 'from src.collectors.research_queue import ResearchQueue\nimport sys\nwith ResearchQueue(sys.argv[1]):\n print("LOCKED", flush=True)\n sys.stdin.read()\n'
    contender_code = 'from src.collectors.research_queue import ResearchQueue\nimport sys\ntry:\n with ResearchQueue(sys.argv[1]): pass\nexcept RuntimeError as error:\n print(str(error))\n sys.exit(23)\n'
    holder = subprocess.Popen([sys.executable, '-c', holder_code, str(state)], cwd=ROOT, env=env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([holder.stdout], [], [], 10)[0], 'Holder never reported acquiring the lock.'
        assert holder.stdout.readline().strip() == 'LOCKED'
        loser = subprocess.run([sys.executable, '-c', contender_code, str(state)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=10)
        assert loser.returncode == 23 and loser.stdout.strip() == 'research_queue_busy'
    finally:
        holder.kill(); holder.communicate(timeout=10)
    winner = subprocess.run([sys.executable, '-c', contender_code, str(state)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=10)
    assert winner.returncode == 0, winner.stderr
    assert winner.stdout == ''


def test_restart_keeps_completed_target_and_unknown_request_accounting(tmp_path):
    records = people(2); state = tmp_path / 'queue.sqlite'; transport = LocalTransport(records)
    initiated = []
    def interrupted(params, *, url, **kwargs):
        initiated.append(url)
        if len(initiated) == 3:
            raise SimulatedPowerLoss()
        return transport(params, url=url, **kwargs)
    with pytest.raises(SimulatedPowerLoss):
        run(records, state, 'partial', interrupted, max_requests=6)
    with ResearchQueue(state) as queue:
        pending = queue.load_run('partial')
    assert pending['targets'][0]['outcome'] == 'success_nonempty'
    assert pending['targets'][1]['outcome'] is None
    assert pending['request_count'] == 3 and pending['credit_accounting_complete'] is False
    assert pending['unknown_request_count'] == 1
    resumed = run(records, state, 'partial', transport, max_requests=6)
    assert resumed['counts']['success_nonempty'] == 2
    assert resumed['request_count'] == 5
    assert resumed['credits_observed'] == 4 and resumed['credit_accounting_complete'] is False
    assert resumed['unknown_request_count'] == 1
    author_urls = [url for _, url, _ in transport.calls if url != oa._WORKS_API]
    assert sum(url.endswith('/A1000') for url in author_urls) == 1
    assert_counts(resumed)


def test_repeated_crashes_exhaust_attempts_without_unlimited_same_run_replay(tmp_path):
    records = people(1); state = tmp_path / 'queue.sqlite'; started = []
    def crash(*args, **kwargs):
        started.append(True)
        raise SimulatedPowerLoss()
    for _ in range(3):
        with pytest.raises(SimulatedPowerLoss):
            run(records, state, 'crash-cap', crash, max_requests=10)
    final = run(records, state, 'crash-cap', no_http, max_requests=10)
    assert len(started) == final['request_count'] == 3
    assert final['unknown_request_count'] == 3
    assert final['targets'][0]['outcome'] == 'needs_review'
    assert final['targets'][0]['patch'] is None
    assert final['credit_accounting_complete'] is False
    assert_counts(final)


def test_sqlite_result_write_failure_is_not_a_successful_checkpoint(tmp_path, monkeypatch):
    import sqlite3

    records = people(1); state = tmp_path / 'queue.sqlite'
    original = ResearchQueue.save_run
    def fail_after_result_write(self, report):
        original(self, report)
        if any(t['outcome'] == 'success_nonempty' for t in report['targets']):
            raise sqlite3.OperationalError('injected transaction failure')
    with monkeypatch.context() as patch:
        patch.setattr(ResearchQueue, 'save_run', fail_after_result_write)
        with pytest.raises(sqlite3.OperationalError, match='injected transaction failure'):
            run(records, state, 'write-failure', LocalTransport(records), max_requests=2)
    with ResearchQueue(state) as queue:
        persisted = queue.load_run('write-failure')
    assert persisted['status'] == 'running'
    assert persisted['request_count'] == 2
    assert persisted['targets'][0]['outcome'] is None and persisted['targets'][0]['patch'] is None
    assert sum(persisted['counts'].values()) == 0
    resumed = run(records, state, 'write-failure', no_http, max_requests=2)
    assert resumed['status'] == 'deferred'
    assert resumed['counts']['success_nonempty'] == 0


@pytest.mark.parametrize('field', ['department', 'publication_attribution_status'])
def test_observed_changed_binding_retires_old_task_even_if_old_corpus_returns(tmp_path, field):
    records = people(1); state = tmp_path / 'queue.sqlite'
    run(records, state, 'old-attempt', LocalTransport(records, modes={'person-000': 'server_error'}))
    changed = deepcopy(records)
    if field == 'department':
        changed[0]['department'] = 'Mathematics'
    else:
        changed[0]['metadata']['publication_attribution_status'] = 'name_match'
    run(changed, state, 'changed-base', LocalTransport(changed, modes={'person-000': 'server_error'}))
    old = run(records, state, 'stale-base', no_http, at=NOW + timedelta(days=60))
    assert old['targets'] == []


def test_transport_changes_record_preimage_result_is_conflict_without_patch(tmp_path):
    records = people(1); transport = LocalTransport(records)
    def changed_during_read(params, *, url, **kwargs):
        response = transport(params, url=url, **kwargs)
        if url == oa._WORKS_API:
            records[0]['description'] = 'Source updated while this request was in flight.'
        return response
    result = run(records, tmp_path / 'queue.sqlite', 'changed-midflight', changed_during_read)
    assert result['targets'][0]['outcome'] == 'conflict'
    assert result['targets'][0]['reason'] == 'record_changed'
    assert result['targets'][0]['patch'] is None
    assert result['request_count'] == len(transport.calls) == 2
    assert 'research_snapshot' not in records[0]['metadata']
    assert_counts(result)


def test_older_interrupted_run_cannot_overwrite_newer_run_success(tmp_path):
    records = people(1); state = tmp_path / 'queue.sqlite'
    with pytest.raises(SimulatedPowerLoss):
        run(records, state, 'older', lambda *a, **k: (_ for _ in ()).throw(SimulatedPowerLoss()), max_seconds=1000)
    assert run(records, state, 'cooling-down', no_http, at=NOW + timedelta(seconds=1))['targets'] == []
    newer = run(records, state, 'newer', LocalTransport(records), at=NOW + timedelta(seconds=301))
    assert newer['targets'][0]['outcome'] == 'success_nonempty'
    old = run(records, state, 'older', no_http, at=NOW + timedelta(seconds=302), max_seconds=1000)
    assert old['targets'][0]['patch'] is None
    assert old['targets'][0]['outcome'] == 'conflict'
    assert old['targets'][0]['reason'] == 'task_superseded'
    assert run(records, state, 'freshness-preserved', no_http, at=NOW + timedelta(seconds=601))['targets'] == []


def test_new_valid_external_snapshot_updates_existing_task_cooldown(tmp_path):
    records = people(1); state = tmp_path / 'queue.sqlite'
    run(records, state, 'failed-old', LocalTransport(records, modes={'person-000': 'server_error'}))
    updated = deepcopy(records); external_time = NOW + timedelta(seconds=10)
    transport = LocalTransport(updated)
    def collector_request(params, *, url):
        data, error, _telemetry = transport(params, url=url)
        return data, error
    patch = oa.harvest_research_snapshots(updated, selected_ids=[updated[0]['id']], limit=1,
                                         now=external_time, request=collector_request)
    assert oa.apply_research_refresh(updated, patch, now=external_time) == 1
    refreshed = run(updated, state, 'external-current', no_http, at=NOW + timedelta(seconds=301))
    assert refreshed['targets'] == []


def test_hardlinked_database_cannot_bypass_existing_process_lock(tmp_path):
    state = tmp_path / 'queue.sqlite'; alias = tmp_path / 'alias.sqlite'
    with ResearchQueue(state):
        os.link(state, alias)
        with pytest.raises((RuntimeError, ValueError)):
            with ResearchQueue(alias):
                pass


def test_replacing_record_object_during_transport_cannot_publish_old_patch(tmp_path):
    records = people(1); transport = LocalTransport(records)
    def replace_during_read(params, *, url, **kwargs):
        response = transport(params, url=url, **kwargs)
        if url == oa._WORKS_API:
            records[0] = {**records[0], 'description': 'A replacement source object.'}
        return response
    result = run(records, tmp_path / 'queue.sqlite', 'replacement-midflight', replace_during_read)
    assert result['targets'][0]['outcome'] == 'conflict'
    assert result['targets'][0]['patch'] is None


def test_missing_credit_header_is_not_an_unknown_http_response(tmp_path):
    records = people(1); transport = LocalTransport(records)
    def no_credit_header(params, *, url, **kwargs):
        data, error, telemetry = transport(params, url=url, **kwargs)
        return data, error, {**telemetry, 'credits_used': None}
    result = run(records, tmp_path / 'queue.sqlite', 'credit-unknown', no_credit_header)
    assert result['counts']['success_nonempty'] == 1
    assert result['request_count'] == 2
    assert result['credit_accounting_complete'] is False
    assert result['unknown_request_count'] == 0


def test_bad_verified_faculty_is_reviewed_without_blocking_valid_record(tmp_path):
    records = people(2); records[0].pop('source_url')
    before = deepcopy(records); state = tmp_path / 'queue.sqlite'; transport = LocalTransport(records)
    result = run(records, state, 'mixed-source-quality', transport)
    assert [t['record_id'] for t in result['targets']] == ['person-000', 'person-001']
    bad, good = result['targets']
    assert bad['outcome'] == 'needs_review' and bad['reason'] == 'invalid_research_target'
    assert bad['attempted'] is False and bad['patch'] is None
    assert good['outcome'] == 'success_nonempty' and good['attempted'] is True
    assert result['request_count'] == len(transport.calls) == 2
    assert all(not url.endswith('/A1000') for _, url, _ in transport.calls)
    assert result['counts']['needs_review'] == result['counts']['success_nonempty'] == 1
    assert records == before
    assert run(records, state, 'same-bad-not-requeued', no_http, at=NOW + timedelta(seconds=1))['targets'] == []
    assert_counts(result)


def test_bad_source_does_not_hide_a_cross_person_author_collision(tmp_path):
    records = people(2); records[0].pop('source_url')
    records[0]['pi_name'] = 'Alice Smith'; records[1]['pi_name'] = 'Bob Jones'
    records[1]['metadata']['publication_author_id'] = records[0]['metadata']['publication_author_id']
    before = deepcopy(records)
    result = run(records, tmp_path / 'queue.sqlite', 'bad-source-collision', no_http)
    assert [t['outcome'] for t in result['targets']] == ['needs_review', 'identity_revoked']
    assert all(t['attempted'] is False for t in result['targets'])
    assert result['targets'][0]['patch'] is None
    assert result['targets'][1]['reason'] == 'identity_revoked'
    assert result['request_count'] == 0 and records == before
    assert_counts(result)


def test_explicit_source_correction_creates_a_new_eligible_binding(tmp_path):
    records = people(1); records[0].pop('source_url'); state = tmp_path / 'queue.sqlite'
    bad = run(records, state, 'bad-source', no_http)
    assert bad['targets'][0]['outcome'] == 'needs_review'
    corrected = deepcopy(records); corrected[0]['source_url'] = 'https://example.edu/verified-person'
    transport = LocalTransport(corrected)
    good = run(corrected, state, 'corrected-source', transport, at=NOW + timedelta(seconds=1))
    assert good['targets'][0]['outcome'] == 'success_nonempty'
    assert good['targets'][0]['binding_key'] != bad['targets'][0]['binding_key']
    assert good['request_count'] == len(transport.calls) == 2
    assert run(records, state, 'old-source-returned', no_http, at=NOW + timedelta(days=60))['targets'] == []
