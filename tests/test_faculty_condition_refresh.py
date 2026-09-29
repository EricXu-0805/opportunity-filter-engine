"""Offline request-count, due-time, identity and checkpoint regressions."""
import json
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
import requests

from src.collectors import faculty_graph as fg
from src.collectors import url_parser
from src.collectors.faculty_condition_refresh import refresh_faculty_condition_sources
from src.contact_instructions import (
    CAPTURE_KEY,
    SOURCE_KEY,
    capture_from_html,
    capture_metadata,
    contact_instruction_pages,
)


class Response:
    def __init__(self, url, html='', status=200, headers=None):
        self.url, self.status_code = url, status
        self.headers = headers or {}
        self.content = html.encode()
        self.is_redirect = status in (301, 302, 303, 307, 308)
        self.closed = False
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)
    def iter_content(self, _size):
        yield self.content
    def close(self):
        self.closed = True


def html(name='Ada Example', text='Undergraduate students should email a CV.'):
    return f'<html><body><h1>{name}</h1><h2>Undergraduate applicants</h2><p>{text}</p></body></html>'


def records(count=1):
    people = [fg.faculty(name=f'Ada Example{chr(97+i)}', title='Professor',
                         url=f'https://example.edu/profile-{i}', email=f'person{i}@example.edu',
                         research_areas='Robotics; controls') for i in range(count)]
    school = {'school_slug': 'example', 'source': 'example_faculty', 'organization': 'Example University',
              'location': 'Example', 'id_prefix': 'example',
              'departments': [{'short': 'CS', 'name': 'Computer Science', 'faculty': people}]}
    return fg.fetch_and_normalize(school, deep=False)


def source(record, *, days=20, text='Undergraduate students should email a CV.', url=None):
    target = url or record['url']
    result = capture_from_html(html(record['pi_name'], text), source_url=target,
                               requested_source_url=target, record_source_url=record['url'],
                               identity_name=record['pi_name'],
                               checked_at=(datetime.now(UTC)-timedelta(days=days)).isoformat())
    record['metadata'].update(capture_metadata(result))
    return result


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(url_parser, '_host_resolves_to_blocked_ip', lambda host: False)
    calls = []
    def install(handler):
        def get(url, **kwargs):
            calls.append(url)
            assert kwargs['allow_redirects'] is False
            return handler(url)
        monkeypatch.setattr(url_parser.requests, 'get', get)
        return calls
    return install


def test_complete_normalized_profile_gets_missing_source_and_checkpoint_roundtrip(transport, tmp_path):
    rows = records(); before = deepcopy(rows[0]); path = tmp_path/'corpus.json'
    calls = transport(lambda url: Response(url, html(rows[0]['pi_name'])))
    checkpoints = []
    def persist():
        path.write_text(json.dumps(rows)); checkpoints.append(json.loads(path.read_text()))
    stats = refresh_faculty_condition_sources(rows, max_requests=1, persist=persist)
    assert stats['due'] == stats['attempted'] == stats['requests'] == stats['updated'] == 1
    assert stats['backlog'] == 0 and len(calls) == len(checkpoints) == 1
    saved = json.loads(path.read_text())[0]
    assert contact_instruction_pages(saved)[0]['receipt']['status'] == 'captured'
    for key in ('contact_email', 'title', 'keywords', 'description_raw'):
        assert saved[key] == before[key]
    assert saved['metadata']['last_verified'] == before['metadata']['last_verified']


@pytest.mark.parametrize('age, expected', [(0,0),(13,0),(14,1),(61,1)])
def test_success_ttl_uses_source_checked_time_not_general_profile_date(transport, age, expected):
    rows=records(); source(rows[0], days=age)
    rows[0]['metadata']['last_verified'] = datetime.now(UTC).isoformat()
    calls=transport(lambda url: Response(url,html(rows[0]['pi_name'])))
    stats=refresh_faculty_condition_sources(rows,max_requests=1)
    assert stats['requests']==expected and len(calls)==expected
    assert stats['stale']==int(age>=60)


def test_complete_empty_is_fresh_then_due_and_can_clear_previous_source(transport):
    rows=records(); source(rows[0],days=15)
    calls=transport(lambda url: Response(url,html(rows[0]['pi_name'],'My work studies robot motion.').replace('Undergraduate applicants','Research')))
    stats=refresh_faculty_condition_sources(rows,max_requests=1)
    assert stats['condition_capture_counts']['empty']==1
    assert rows[0]['metadata'][SOURCE_KEY]==[]
    again=refresh_faculty_condition_sources(rows,max_requests=1)
    assert again['fresh']==1 and again['attempted']==0 and len(calls)==1


def test_failed_old_source_keeps_date_and_retries_after_wait(transport):
    rows=records(); source(rows[0],days=20)
    original=deepcopy(rows[0]['metadata'][SOURCE_KEY])
    calls=transport(lambda url: Response(url,status=503))
    first=refresh_faculty_condition_sources(rows,max_requests=1)
    assert first['condition_capture_counts']['failed']==1
    assert rows[0]['metadata'][SOURCE_KEY]==original
    again=refresh_faculty_condition_sources(rows,max_requests=1)
    assert again['retry_deferred']==1 and again['attempted']==0
    later=refresh_faculty_condition_sources(rows,max_requests=1,now=datetime.now(UTC)+timedelta(hours=25))
    assert later['attempted']==1 and len(calls)==2
    assert rows[0]['metadata'][SOURCE_KEY]==original


def test_failed_first_record_does_not_starve_later_records_across_saved_runs(transport, tmp_path):
    rows=records(3); path=tmp_path/'records.json'
    calls=transport(lambda url: Response(url,status=503))
    order=[]
    for _ in range(3):
        stat=refresh_faculty_condition_sources(rows,max_requests=1,persist=lambda rows=rows: path.write_text(json.dumps(rows)))
        assert stat['attempted']==1
        order.append(calls[-1]); rows=json.loads(path.read_text())
    assert len(set(order))==3
    assert order==[row['url'] for row in sorted(records(3),key=lambda row: row['id'])]


@pytest.mark.parametrize('kind', ['zero','deadline','page_cap'])
def test_zero_budget_expired_deadline_and_page_cap_make_no_http(transport,kind):
    rows=records(); before=deepcopy(rows)
    calls=transport(lambda url: Response(url,html(rows[0]['pi_name'])))
    kwargs={'max_requests':0} if kind=='zero' else ({'deadline':time.monotonic()-1} if kind=='deadline' else {'max_pages':0})
    stats=refresh_faculty_condition_sources(rows,**kwargs)
    assert not calls and stats['attempted']==0 and stats['deferred']==1
    assert rows==before


def test_each_redirect_hop_consumes_budget_and_no_later_get_starts(transport):
    rows=records(2)
    calls=transport(lambda url: Response(url,status=302,headers={'Location':url+'/'}))
    stats=refresh_faculty_condition_sources(rows,max_requests=1)
    assert len(calls)==stats['requests']==stats['attempted']==1
    assert stats['stop_reason']=='request_budget' and stats['deferred']==1
    checked=next(row for row in rows if CAPTURE_KEY in row['metadata'])
    assert checked['metadata'][CAPTURE_KEY]['reason']=='request_budget'
    assert not checked['metadata'].get(SOURCE_KEY)


def test_safe_same_page_redirect_retains_actual_final_url(transport):
    rows=records()
    def handler(url):
        return Response(url,html(rows[0]['pi_name'])) if url.endswith('/') else Response(url,status=301,headers={'Location':url+'/'})
    calls=transport(handler)
    stats=refresh_faculty_condition_sources(rows,max_requests=2)
    assert len(calls)==stats['requests']==2
    page=contact_instruction_pages(rows[0])[0]
    assert page['requested_source_url']==rows[0]['url']
    assert page['source_url']==rows[0]['url']+'/'
    assert page['receipt']['status']=='captured'


def test_wrong_redirect_and_identity_revoke_only_checked_page(transport):
    rows=records(); source(rows[0],days=20)
    def handler(url):
        if url==rows[0]['url']:
            return Response(url,status=302,headers={'Location':'https://example.edu/admissions'})
        return Response(url,html(rows[0]['pi_name']))
    transport(handler)
    stats=refresh_faculty_condition_sources(rows,max_requests=2)
    assert stats['condition_capture_counts']['failed']==1
    assert rows[0]['metadata'][SOURCE_KEY]==[]
    assert rows[0]['metadata'][CAPTURE_KEY]['reason']=='redirect_mismatch'


@pytest.mark.parametrize('page_html,reason',[(html('Other Professor'),'identity_mismatch'),('<body><h1>Sign in</h1><p>Password</p></body>','access_page')])
def test_unverified_page_cannot_be_source(transport,page_html,reason):
    rows=records(); transport(lambda url: Response(url,page_html))
    stats=refresh_faculty_condition_sources(rows,max_requests=1)
    assert stats['condition_capture_counts']['failed']==1
    assert rows[0]['metadata'][CAPTURE_KEY]['reason']==reason
    assert not rows[0]['metadata'].get(SOURCE_KEY)


def test_429_stops_run_and_preserves_retry_after_across_reload(transport,tmp_path):
    rows=records(2); path=tmp_path/'records.json'
    calls=transport(lambda url:Response(url,status=429,headers={'Retry-After':'172800'}))
    stats=refresh_faculty_condition_sources(rows,max_requests=20,persist=lambda:path.write_text(json.dumps(rows)))
    assert len(calls)==1 and stats['stop_reason']=='rate_limited' and stats['deferred']==1
    saved=json.loads(path.read_text())
    checked=next(row for row in saved if CAPTURE_KEY in row['metadata'])
    assert datetime.fromisoformat(checked['metadata'][CAPTURE_KEY]['next_retry_at']) > datetime.now(UTC)+timedelta(hours=47)
    later=refresh_faculty_condition_sources([checked],max_requests=1,now=datetime.now(UTC)+timedelta(hours=25))
    assert later['retry_deferred']==1 and later['requests']==0


def test_checkpoint_failure_stops_before_next_http_and_restores_memory(transport):
    rows=records(2); before=deepcopy(rows)
    by_url={row['url']:row for row in rows}
    calls=transport(lambda url:Response(url,html(by_url[url]['pi_name'])))
    def persist(): raise OSError('controlled local checkpoint failure')
    with pytest.raises(OSError):
        refresh_faculty_condition_sources(rows,max_requests=2,persist=persist)
    assert len(calls)==1 and rows==before


def test_safe_fetch_private_redirect_never_requests_private_target(transport):
    rows=records()
    calls=transport(lambda url:Response(url,status=302,headers={'Location':'http://127.0.0.1/internal'}))
    stats=refresh_faculty_condition_sources(rows,max_requests=10)
    assert len(calls)==stats['requests']==1
    assert stats['condition_capture_counts']['failed']==1
    assert not rows[0]['metadata'].get(SOURCE_KEY)


def test_nonfaculty_inactive_and_missing_profile_skipped(transport):
    rows=records(3)
    rows[0]['source_type']='summer_program'; rows[1]['metadata']['is_active']=False; rows[2]['url']=''
    calls=transport(lambda url:Response(url,html()))
    stats=refresh_faculty_condition_sources(rows)
    assert not calls and stats['skipped_records']==3 and stats['due']==0


def test_malformed_metadata_is_skipped_with_school_counts(transport):
    rows=records(); rows[0]['metadata']=None
    calls=transport(lambda url:Response(url,html()))
    stats=refresh_faculty_condition_sources(rows)
    assert not calls and stats['skipped_records']==1
    assert stats['by_school']['example']['skipped_records']==1


def test_reference_now_controls_failure_attempt_and_retry_after(transport):
    rows=records(); reference=datetime.now(UTC)-timedelta(minutes=2)
    transport(lambda url:Response(url,status=429,headers={'Retry-After':'172800'}))
    refresh_faculty_condition_sources(rows,max_requests=1,now=reference)
    receipt=rows[0]['metadata'][CAPTURE_KEY]
    assert datetime.fromisoformat(receipt['attempted_at'])==reference
    assert datetime.fromisoformat(receipt['next_retry_at'])==reference+timedelta(seconds=172800)


def test_per_school_stats_sum_to_global_and_use_source_defaults(transport):
    rows=records(3)
    rows[0]['school']='uiuc'; rows[1].pop('school',None); rows[1]['source']='umich_faculty'
    rows[2]['school']=None; rows[2]['source']='unregistered'; rows[2]['metadata']=None
    calls=transport(lambda url:Response(url,status=503))
    stats=refresh_faculty_condition_sources(rows,max_requests=1)
    for key in ('records','due','backlog','attempted','requests','deferred','updated','retry_deferred','source_limit','skipped_records'):
        assert stats[key]==sum(item[key] for item in stats['by_school'].values())
    assert set(stats['by_school'])=={'uiuc','umich','unknown'}


def test_refresh_current_page_preserves_another_fresh_bound_source(transport):
    rows=records(); record=rows[0]
    old=source(record,days=20)['sources'][0]
    other=source(record,days=0,url='https://example.edu/ada-lab')['sources'][0]
    record['metadata'].pop(CAPTURE_KEY,None)
    record['metadata'][SOURCE_KEY]=[old,other]
    calls=transport(lambda url:Response(url,html(record['pi_name'],'I study robot motion.').replace('Undergraduate applicants','Research')))
    stats=refresh_faculty_condition_sources(rows,max_requests=1)
    assert calls==[record['url']]
    assert stats['fresh']==1 and stats['due']==1 and stats['backlog']==0
    assert record['metadata'][SOURCE_KEY]==[other]


def test_source_limit_does_not_discard_old_pages_or_restart_same_page_immediately(transport):
    rows=records(); record=rows[0]
    sources=[source(record,days=0,url=f'https://example.edu/lab-{index}')['sources'][0] for index in range(8)]
    record['metadata'].pop(CAPTURE_KEY,None)
    record['metadata'][SOURCE_KEY]=deepcopy(sources)
    calls=transport(lambda url:Response(url,html(record['pi_name'])))
    first=refresh_faculty_condition_sources(rows,max_requests=1)
    assert first['source_limit']==1 and first['backlog']==1
    assert record['metadata'][SOURCE_KEY]==sources
    again=refresh_faculty_condition_sources(rows,max_requests=1)
    assert again['attempted']==0 and again['retry_deferred']==1
    assert len(calls)==1


def test_unsupported_structure_is_failed_refresh_not_new_success(transport):
    rows=records(); source(rows[0],days=20)
    original=deepcopy(rows[0]['metadata'][SOURCE_KEY])
    page=f'<body><h1>{rows[0]["pi_name"]}</h1><h2>Minimum GPA</h2><div>3.0</div></body>'
    transport(lambda url:Response(url,page))
    stats=refresh_faculty_condition_sources(rows,max_requests=1)
    assert stats['condition_capture_counts']['unsupported']==1
    assert rows[0]['metadata'][SOURCE_KEY]==original
    assert refresh_faculty_condition_sources(rows,max_requests=1)['retry_deferred']==1


def full_page_ledger(record):
    from src.collectors.uiuc_faculty import carry_forward_contact_instruction_sources
    from src.contact_instructions import PAGES_KEY
    for index in range(32):
        url=f'https://example.edu/known-page-{index}'
        result=capture_from_html(html(record['pi_name'],'My research studies motion.').replace('Undergraduate applicants','Research'),
                                 source_url=url,requested_source_url=url,record_source_url=record['url'],
                                 identity_name=record['pi_name'],checked_at=datetime.now(UTC).isoformat())
        incoming=deepcopy(record)
        for key in (CAPTURE_KEY,SOURCE_KEY,PAGES_KEY): incoming['metadata'].pop(key,None)
        incoming['metadata'].update(capture_metadata(result))
        carry_forward_contact_instruction_sources(record,incoming)
        record['metadata']=incoming['metadata']
    assert len(record['metadata'][PAGES_KEY]['pages'])==32


def test_full_ledger_defers_new_page_without_blocking_other_record(transport):
    rows=records(2); full_page_ledger(rows[0])
    names={row['url']:row['pi_name'] for row in rows}
    calls=transport(lambda url:Response(url,html(names[url])))
    stats=refresh_faculty_condition_sources(rows,max_requests=1)
    assert calls==[rows[1]['url']]
    assert stats['capacity_blocked']==1 and stats['backlog']==1 and stats['deferred']==1
    assert stats['minimum_runs_at_request_budget'] is None
    assert stats['attempted']==1


def test_full_ledger_extra_rejected_page_and_current_profile_are_only_scheduling(transport):
    from src.contact_instructions import PAGES_KEY, capture_failure
    rows=records(); full_page_ledger(rows[0])
    rows[0]['metadata'][CAPTURE_KEY]=capture_metadata(capture_failure(
        source_url='https://example.edu/rejected-lab',requested_source_url='https://example.edu/rejected-lab',
        record_source_url=rows[0]['url'],identity_name=rows[0]['pi_name'],
        status='unsupported',reason='page_limit'))[CAPTURE_KEY]
    calls=transport(lambda url:Response(url,html(rows[0]['pi_name'])))
    stats=refresh_faculty_condition_sources(rows,max_requests=10)
    assert not calls and stats['capacity_blocked']==2
    assert stats['fresh']+stats['due']+stats['retry_deferred']==34
    assert len(rows[0]['metadata'][PAGES_KEY]['pages'])==32
    assert rows[0]['metadata'][SOURCE_KEY]==[]
    assert stats['minimum_runs_at_request_budget'] is None


@pytest.mark.parametrize('ledger', [None, {'version': 1, 'pages': None}, {'version': 1, 'pages': 7}])
def test_malformed_ledger_shape_is_skipped_without_fetch_or_mutation(transport, ledger):
    from src.contact_instructions import PAGES_KEY
    rows = records(); rows[0]['metadata'][PAGES_KEY] = ledger
    before = deepcopy(rows)
    calls = transport(lambda url: Response(url, html(rows[0]['pi_name'])))
    stats = refresh_faculty_condition_sources(rows)
    assert not calls and rows == before
    assert stats['skipped_records'] == 1 and stats['due'] == 0
    assert stats['by_school']['example']['skipped_records'] == 1
