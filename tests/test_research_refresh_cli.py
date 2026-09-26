"""CLI recovery/export and imported-state tests, with no external requests."""
import json
from datetime import timedelta

import pytest

from scripts import research_refresh as cli
from src.collectors import openalex_enrich as oa
from tests.test_research_queue_acceptance import BASE, NOW, LocalTransport, no_http, people, run


def test_bootstrap_success_in_new_queue_including_empty(tmp_path):
    records = people(2)
    transport = LocalTransport(records, modes={'person-001': 'empty'})
    report = run(records, tmp_path / 'initial.sqlite', 'initial', transport)
    for target in report['targets']:
        assert oa.apply_research_refresh(records, target['patch'], now=NOW) == 1
    assert run(records, tmp_path / 'new.sqlite', 'imported', no_http)['targets'] == []


def test_newer_imported_success_moves_existing_queue_due_time(tmp_path):
    records = people(); state = tmp_path / 'queue.sqlite'
    failed = run(records, state, 'first', LocalTransport(records, modes={'person-000': 'server_error'}))
    assert failed['counts']['failed'] == 1
    later = NOW + timedelta(seconds=400)
    source = run(records, tmp_path / 'other.sqlite', 'other', LocalTransport(records), at=later)
    assert oa.apply_research_refresh(records, source['targets'][0]['patch'], now=later) == 1
    result = run(records, state, 'latest-import', no_http, at=later + timedelta(seconds=1))
    assert result['targets'] == []


@pytest.mark.parametrize('reason', ['request_failed', 'server_error', 'rate_limited', 'invalid_response', 'identity_revoked'])
def test_bootstrap_imported_failure_honors_cooldown_or_review(tmp_path, reason):
    records = people()
    records[0]['metadata']['research_refresh'] = {'checked_at': NOW.isoformat().replace('+00:00', 'Z'),
                                                'status': 'failed', 'reason': reason}
    result = run(records, tmp_path / 'queue.sqlite', 'initial', no_http)
    assert result['targets'] == []


def test_cli_run_status_replay_exports_without_network(tmp_path, monkeypatch, capsys):
    records = people(); source = tmp_path / 'corpus.json'; source.write_text(json.dumps(records))
    transport = LocalTransport(records)
    monkeypatch.setattr(oa, 'research_http_read', transport)
    state, output = tmp_path / 'queue.sqlite', tmp_path / 'run.json'
    args = ['run', '--input', str(source), '--state', str(state), '--run-id', 'example', '--base-sha', BASE,
            '--shard', 'uiuc', '--out', str(output)]
    assert cli.main(args) == 0
    report = json.loads(output.read_text())
    assert report['counts']['success_nonempty'] == 1
    assert json.loads(source.read_text()) == records
    assert len(transport.calls) == 2
    capsys.readouterr()
    monkeypatch.setattr(oa, 'research_http_read', no_http)
    again = tmp_path / 'again.json'
    assert cli.main(['status', '--state', str(state), '--run-id', 'example', '--out', str(again)]) == 0
    assert json.loads(again.read_text()) == report
    assert cli.main([*args[:-1], str(tmp_path / 'replay.json')]) == 0
    assert json.loads((tmp_path / 'replay.json').read_text()) == report
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    assert json.loads(output.read_text()) == report


def test_output_failure_does_not_erase_saved_run(tmp_path, monkeypatch):
    source = tmp_path / 'source.json'; source.write_text(json.dumps(people()))
    state = tmp_path / 'queue.sqlite'
    monkeypatch.setattr(oa, 'research_http_read', LocalTransport(people()))
    def failure(*args):
        raise OSError('disk full')
    monkeypatch.setattr(cli, '_write_new', failure)
    with pytest.raises(SystemExit) as error:
        cli.main(['run', '--input', str(source), '--state', str(state), '--run-id', 'saved', '--base-sha', BASE,
                  '--shard', 'uiuc', '--out', str(tmp_path / 'output.json')])
    assert error.value.code == 2 and not (tmp_path / 'output.json').exists()
    from src.collectors.research_queue import ResearchQueue
    with ResearchQueue(state) as queue:
        assert queue.load_run('saved')['status'] == 'completed'


@pytest.mark.parametrize('shard', ['', 'unknown', 'uiuc,uiuc', 'national,uiuc', 'UIUC'])
def test_invalid_shard_starts_no_http_or_state(tmp_path, monkeypatch, shard):
    source = tmp_path / 'corpus.json'; source.write_text(json.dumps(people()))
    state = tmp_path / 'queue.sqlite'
    monkeypatch.setattr(oa, 'research_http_read', no_http)
    with pytest.raises(SystemExit) as error:
        cli.main(['run', '--input', str(source), '--state', str(state), '--run-id', 'example', '--base-sha', BASE,
                  '--shard', shard, '--out', str(tmp_path / 'run.json')])
    assert error.value.code == 2 and not state.exists()


def test_national_is_honest_noop_not_faculty_success(tmp_path, monkeypatch):
    source = tmp_path / 'corpus.json'; source.write_text(json.dumps(people()))
    monkeypatch.setattr(oa, 'research_http_read', no_http)
    output = tmp_path / 'run.json'
    assert cli.main(['run', '--input', str(source), '--state', str(tmp_path / 'queue.sqlite'),
                     '--run-id', 'national', '--base-sha', BASE, '--shard', 'national', '--out', str(output)]) == 0
    report = json.loads(output.read_text())
    assert report['targets'] == [] and sum(report['counts'].values()) == 0 and report['request_count'] == 0


def test_export_does_not_overwrite_previous_file(tmp_path):
    output = tmp_path / 'existing.json'; output.write_text('preserve')
    with pytest.raises(ValueError):
        cli._write_new(output, {'new': True})
    assert output.read_text() == 'preserve'


def test_corrupt_queue_is_not_green(tmp_path, monkeypatch):
    state = tmp_path / 'queue.sqlite'; state.write_text('not sqlite')
    monkeypatch.setattr(oa, 'research_http_read', no_http)
    with pytest.raises(SystemExit) as error:
        cli.main(['status', '--state', str(state), '--run-id', 'bad', '--out', str(tmp_path / 'out.json')])
    assert error.value.code == 2 and not (tmp_path / 'out.json').exists()


def test_unrepresentable_provider_cooldown_still_stops_without_losing_receipt(tmp_path):
    records = people(2)
    def limited(*args, **kwargs):
        return None, 'rate_limited', {'http_status': 429, 'credits_used': 0,
            'retry_after_seconds': 2**53 - 1, 'reset_seconds': 1e100, 'remaining': 0}
    report = run(records, tmp_path / 'queue.sqlite', 'huge-header', limited)
    assert report['request_count'] == 1 and report['unknown_request_count'] == 0
    assert report['counts']['failed'] == 1 and report['counts']['deferred'] == 1
    assert report['cooldown_until'] == (NOW + timedelta(seconds=300)).isoformat().replace('+00:00', 'Z')


@pytest.mark.parametrize('options', [{'max_seconds': 10**1000}, {'min_remaining': 10**1000}])
def test_unbounded_integer_budgets_are_rejected_before_http(tmp_path, options):
    with pytest.raises(ValueError):
        run(people(), tmp_path / 'queue.sqlite', 'huge-budget', no_http, **options)
