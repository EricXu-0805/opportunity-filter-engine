"""Source evidence must survive an unattempted refresh without inventing freshness."""
import json
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from backend.data_loader import _canonicalize_corpus
from backend.lib.public_opportunity_detail import project_public_detail
from src.collectors import faculty_graph as fg
from src.collectors import ucb_common
from src.collectors.uiuc_faculty import _carry_forward_enrichment
from src.contact_instructions import SOURCE_KEY, source_from_html
from src.normalizers.normalizer import normalize

CAPTURE_KEY = 'contact_instruction_capture'
URL = 'https://example.edu/people/jane-scientist'
SCHOOL = {'school_slug':'sample', 'source':'sample_faculty', 'organization':'Sample University', 'location':'Sample', 'id_prefix':'sample'}
DEPT = {'short':'CS', 'name':'Computer Science', 'majors':['Computer Science']}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *_a, **_k: pytest.fail('No external network permitted'))


def stamp(days=0):
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def source(text='Please email us. Applicants must submit a resume.', checked_at=None):
    return source_from_html(f'<body><h2>Undergraduate applicants</h2><p>{text}</p></body>',
                            source_url=URL, identity_name='Jane Scientist', checked_at=checked_at or stamp(2))


def record():
    return fg._normalize(SCHOOL, DEPT, fg.faculty('Jane Scientist', title='Professor', url=URL))


def receipt(status, attempted_at=None, **changes):
    return {'version':1, 'status':status, 'reason':None if isinstance(status, str) and status in {'captured','empty'} else 'fetch_failed',
            'attempted_at':attempted_at or stamp(), 'source_url':URL, 'record_source_url':URL,
            'identity_name':'Jane Scientist', **changes}


def test_directory_only_refresh_preserves_detached_source_and_original_observation_date():
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    before = deepcopy(prior)
    _carry_forward_enrichment(prior, incoming)
    assert incoming['metadata'][SOURCE_KEY] == before['metadata'][SOURCE_KEY]
    assert incoming['metadata'][SOURCE_KEY] is not prior['metadata'][SOURCE_KEY]
    assert prior == before


@pytest.mark.parametrize('status', ['failed', 'unsupported'])
def test_failed_capture_preserves_old_source_without_claiming_it_was_checked_now(status):
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    incoming['metadata'][CAPTURE_KEY] = receipt(status)
    _carry_forward_enrichment(prior, incoming)
    assert incoming['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]
    assert incoming['metadata'][SOURCE_KEY][0]['checked_at'] != incoming['metadata'][CAPTURE_KEY]['attempted_at']
    assert incoming['metadata'][CAPTURE_KEY]['status'] == status


def test_successful_empty_capture_persists_as_an_explicit_empty_source():
    person = fg.faculty('Jane Scientist', title='Professor', url=URL)
    person['_contact_instruction_sources'] = []
    person['_contact_instruction_capture'] = receipt('empty')
    out = fg._normalize(SCHOOL, DEPT, person)
    assert out['metadata'][SOURCE_KEY] == []
    assert out['metadata'][CAPTURE_KEY] == person['_contact_instruction_capture']


def test_generic_normalizer_keeps_receipt_even_when_successful_source_is_empty():
    value = receipt('empty')
    out = normalize({'source':'sample', 'source_url':URL, 'url':URL, 'title':'Sample program', 'description_raw':'',
                     'extra_fields':{SOURCE_KEY:[], CAPTURE_KEY:value}})
    assert out['metadata'][SOURCE_KEY] == [] and out['metadata'][CAPTURE_KEY] == value


def test_real_faculty_merge_storage_loader_and_public_roundtrip(tmp_path, monkeypatch):
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    path = tmp_path/'opportunities.json'; path.write_text(json.dumps([prior]))
    monkeypatch.setattr(ucb_common, 'PROCESSED_FILE', path)
    assert fg.merge_into_processed([incoming]) == (0,1)
    stored = json.loads(path.read_text())[0]
    loaded = _canonicalize_corpus([deepcopy(stored)])[0]
    public = project_public_detail(loaded)
    assert stored['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY] == loaded['metadata'][SOURCE_KEY]
    assert public['contact_instructions']['email_policy'] == 'allowed'
    assert any(c['field']=='application.requires_resume' and c['status']=='stated' for c in public['target_conditions']['conditions'])
    assert SOURCE_KEY not in public.get('metadata', {})


@pytest.mark.parametrize('status', [['captured'], {'bad':'failed'}, 42, None])
def test_malformed_receipt_status_cannot_crash_or_use_legacy_sources(status):
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    incoming['metadata'][CAPTURE_KEY] = receipt(status)
    incoming['metadata'][SOURCE_KEY] = [source('Do not email us.', stamp())]
    _carry_forward_enrichment(prior, incoming)
    assert incoming['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]
    assert CAPTURE_KEY not in incoming['metadata']


@pytest.mark.parametrize('reason', [None, 'identity_mismatch', 'source_revoked', 'url_changed', 'redirect_mismatch', 'ambiguous_program_scope'])
@pytest.mark.parametrize('incoming_format', ['captured', 'legacy'])
@pytest.mark.parametrize('age', [2, 1])
def test_empty_or_revoked_sources_cannot_revive_at_or_before_tombstone(reason, incoming_format, age):
    barrier = stamp(1)
    observed = barrier if age == 1 else stamp(age)
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = []
    prior['metadata'][CAPTURE_KEY] = receipt('failed' if reason else 'empty', barrier, reason=reason)
    incoming['metadata'][SOURCE_KEY] = [source(checked_at=observed)]
    if incoming_format == 'captured':
        incoming['metadata'][CAPTURE_KEY] = receipt('captured', observed)
    _carry_forward_enrichment(prior, incoming)
    assert incoming['metadata'][SOURCE_KEY] == []
    assert incoming['metadata'][CAPTURE_KEY] == prior['metadata'][CAPTURE_KEY]


@pytest.mark.parametrize('reason', ['identity_mismatch', 'source_revoked', 'url_changed', 'redirect_mismatch', 'ambiguous_program_scope'])
def test_explicit_revocation_removes_old_sources_and_is_durable_across_no_attempt_and_failure(reason):
    prior, revoked_record = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    revoked_record['metadata'][CAPTURE_KEY] = receipt('failed', stamp(1), reason=reason)
    _carry_forward_enrichment(prior, revoked_record)
    assert revoked_record['metadata'][SOURCE_KEY] == []
    skipped = record()
    _carry_forward_enrichment(revoked_record, skipped)
    assert skipped['metadata'][SOURCE_KEY] == []
    assert skipped['metadata'][CAPTURE_KEY] == revoked_record['metadata'][CAPTURE_KEY]
    failed = record()
    failed['metadata'][CAPTURE_KEY] = receipt('failed', stamp())
    failed['metadata'][SOURCE_KEY] = [source()]
    _carry_forward_enrichment(skipped, failed)
    assert failed['metadata'][SOURCE_KEY] == []
    newer = record()
    checked = stamp()
    newer['metadata'][CAPTURE_KEY] = receipt('captured', checked)
    newer['metadata'][SOURCE_KEY] = [source(checked_at=checked)]
    _carry_forward_enrichment(failed, newer)
    assert len(newer['metadata'][SOURCE_KEY]) == 1
    assert newer['metadata'][CAPTURE_KEY]['status'] == 'captured'


@pytest.mark.parametrize('status', ['failed', 'unsupported'])
@pytest.mark.parametrize('has_prior', [False, True])
def test_failed_receipt_never_adopts_attached_new_sources(status, has_prior):
    prior, incoming = record(), record()
    if has_prior:
        prior['metadata'][SOURCE_KEY] = [source()]
    incoming['metadata'][CAPTURE_KEY] = receipt(status)
    incoming['metadata'][SOURCE_KEY] = [source('Do not email us.', stamp())]
    _carry_forward_enrichment(prior, incoming)
    assert incoming['metadata'].get(SOURCE_KEY) == prior['metadata'].get(SOURCE_KEY)
    assert incoming['metadata'][CAPTURE_KEY]['status'] == status


@pytest.mark.parametrize('malformed', [None, {}, {'version':1}])
@pytest.mark.parametrize('has_prior', [False, True])
def test_explicit_invalid_receipt_cannot_enter_legacy_compatibility(malformed, has_prior):
    prior, incoming = record(), record()
    if has_prior:
        prior['metadata'][SOURCE_KEY] = [source()]
    incoming['metadata'][CAPTURE_KEY] = malformed
    incoming['metadata'][SOURCE_KEY] = [source('Do not email us.', stamp())]
    _carry_forward_enrichment(prior, incoming)
    assert incoming['metadata'].get(SOURCE_KEY) == prior['metadata'].get(SOURCE_KEY)
    assert CAPTURE_KEY not in incoming['metadata']


@pytest.mark.parametrize('field,value', [('url','https://example.edu/another'), ('pi_name','Other Scientist'), ('organization','Another University'), ('id','different-id')])
def test_changed_identity_does_not_inherit_sources(field, value):
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    incoming[field] = value
    _carry_forward_enrichment(prior, incoming)
    assert SOURCE_KEY not in incoming['metadata']
    assert CAPTURE_KEY not in incoming['metadata']


@pytest.mark.parametrize('case', ['future', 'naive', 'different_source_date', 'different_source_url', 'different_identity'])
def test_invalid_successful_bundle_cannot_replace_prior_observation(case):
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    checked = stamp(1)
    new_source = source('Do not email us.', checked)
    new_receipt = receipt('captured', checked)
    if case == 'future':
        new_receipt['attempted_at'] = stamp(-1)
    elif case == 'naive':
        new_receipt['attempted_at'] = '2026-09-28T12:30:00'
    elif case == 'different_source_date':
        new_source['checked_at'] = stamp()
    elif case == 'different_source_url':
        new_source['source_url'] = 'https://example.edu/other'
    else:
        new_source['identity_name'] = 'Other Scientist'
    incoming['metadata'].update({CAPTURE_KEY:new_receipt, SOURCE_KEY:[new_source]})
    _carry_forward_enrichment(prior, incoming)
    assert incoming['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]


def test_dedup_does_not_scan_source_identity_when_duplicate_has_no_bundle(monkeypatch):
    from src.normalizers import ucb_dedup
    old, new = record(), record()
    new['id'] = 'different-id'
    monkeypatch.setattr(ucb_dedup, '_same_source_target', lambda *_: pytest.fail('No source bundle: do not scan for evidence transfer'))
    assert ucb_dedup.dedupe_against_existing([new], [old]) == ([], 1)


@pytest.mark.parametrize('prior_in_batch', [False, True])
def test_dedup_updates_only_exact_entity_source_under_canonical_id(prior_in_batch):
    from src.normalizers.ucb_dedup import dedupe_against_existing
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    incoming['id'] = 'new-feed-id'
    incoming['description_raw'] = 'This field must not replace the canonical record.'
    observed = stamp(1)
    incoming['metadata'].update({CAPTURE_KEY:receipt('captured', observed), SOURCE_KEY:[source('Do not email us. Submit the application form.', observed)]})
    before = deepcopy(prior)
    kept, dropped = dedupe_against_existing([prior, incoming] if prior_in_batch else [incoming], [] if prior_in_batch else [prior])
    assert dropped == 1 and len(kept) == 1
    updated = kept[0]
    assert updated['id'] == prior['id'] and updated['description_raw'] == prior['description_raw']
    assert updated['metadata'][SOURCE_KEY] == incoming['metadata'][SOURCE_KEY]
    assert prior == before


@pytest.mark.parametrize('field,value', [('title','Other Project'), ('organization','Other University'), ('pi_name','Other Scientist')])
def test_dedup_shared_url_does_not_transfer_source_between_entities(field, value):
    from src.normalizers.ucb_dedup import dedupe_against_existing
    prior, incoming = record(), record()
    incoming['id'] = 'different-id'
    incoming[field] = value
    incoming['metadata'][SOURCE_KEY] = [source()]
    assert dedupe_against_existing([incoming], [prior]) == ([], 1)
    assert SOURCE_KEY not in prior['metadata']


def captured_person(monkeypatch, html, *, requested=URL, final=URL, observed=None, render=False, mark=True):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(f'<body>{html}</body>', 'html.parser') if html is not None else None
    if soup is not None and mark:
        ucb_common._mark_fetched_soup_observation(soup, requested_url=requested, final_url=final,
                                                 observed_at=observed or stamp(1))
    if render:
        monkeypatch.setattr(fg, '_render_soup', lambda *_a, **_k: soup)
    else:
        monkeypatch.setattr(ucb_common, 'fetch_soup', lambda *_a, **_k: soup)
    person = fg.faculty('Jane Scientist', title='Professor', url=requested)
    fg._apply_profile_enrich([person], {'always':True, 'render':render})
    return person


@pytest.mark.parametrize('render', [False, True])
@pytest.mark.parametrize('state,html,expected', [
    ('captured', '<h1>Jane Scientist</h1><h2>Undergraduate applicants</h2><p>Please email us with a resume.</p>', None),
    ('empty', '<h1>Jane Scientist</h1><h2>Research</h2><p>We study parsers.</p>', None),
    ('failed', None, 'fetch_failed'),
    ('failed', '<h1>Other Scientist</h1><p>Please email us.</p>', 'identity_mismatch'),
    ('failed', '<h1>Login required</h1><p>Sign in to view Jane Scientist</p>', 'access_page'),
])
def test_actual_enrichment_and_normalization_preserve_capture_state(monkeypatch, render, state, html, expected):
    observed = stamp(1)
    person = captured_person(monkeypatch, html, observed=observed, render=render)
    value = fg._normalize(SCHOOL, DEPT, person)
    capture = value['metadata'][CAPTURE_KEY]
    assert capture['status'] == state and capture['reason'] == expected
    if state == 'captured':
        assert capture['attempted_at'] == observed
        assert value['metadata'][SOURCE_KEY][0]['checked_at'] == observed
    elif state == 'empty':
        assert capture['attempted_at'] == observed and value['metadata'][SOURCE_KEY] == []
    else:
        assert SOURCE_KEY not in value['metadata']


@pytest.mark.parametrize('requested,final', [(URL, URL+'/'), (URL.replace('https:', 'http:'), URL)])
def test_profile_normal_redirect_keeps_actual_final_url_and_record_binding(monkeypatch, requested, final):
    person = captured_person(monkeypatch, '<h1>Jane Scientist</h1><h2>Undergraduate applicants</h2><p>Please email us with a resume.</p>', requested=requested, final=final)
    out = fg._normalize(SCHOOL, DEPT, person)
    assert out['metadata'][CAPTURE_KEY]['status'] == 'captured'
    snapshot = out['metadata'][SOURCE_KEY][0]
    assert snapshot['source_url'] == final and snapshot['record_source_url'] == requested
    assert project_public_detail(_canonicalize_corpus([out])[0])['contact_instructions']['email_policy'] == 'allowed'


@pytest.mark.parametrize('final', ['https://example.edu/other', 'https://other.example.edu/people/jane-scientist', URL+'?project=other'])
def test_profile_different_page_redirect_revokes_old_source_after_merge(monkeypatch, final):
    prior = record()
    prior['metadata'][SOURCE_KEY] = [source()]
    person = captured_person(monkeypatch, '<h1>Jane Scientist</h1><h2>Undergraduate applicants</h2><p>Please email us with a resume.</p>', final=final)
    incoming = fg._normalize(SCHOOL, DEPT, person)
    _carry_forward_enrichment(prior, incoming)
    assert incoming['metadata'][CAPTURE_KEY]['reason'] == 'redirect_mismatch'
    assert incoming['metadata'][SOURCE_KEY] == []


def test_unstamped_fetch_does_not_fabricate_source_observation(monkeypatch):
    person = captured_person(monkeypatch, '<h1>Jane Scientist</h1><h2>Undergraduate applicants</h2><p>Please email us with a resume.</p>', mark=False)
    out = fg._normalize(SCHOOL, DEPT, person)
    assert out['metadata'][CAPTURE_KEY]['reason'] == 'fetch_metadata_missing'
    assert SOURCE_KEY not in out['metadata']


def test_complete_profile_remains_unattempted_without_expanding_fetch_budget(monkeypatch):
    person = fg.faculty('Jane Scientist', title='Professor', url=URL, email='jane@example.edu', keywords=['parsers'])
    monkeypatch.setattr(fg, '_enrich_profile', lambda *_a, **_k: pytest.fail('Existing skip rule must not expand requests'))
    fg._apply_profile_enrich([person], {'always':True})
    assert '_contact_instruction_capture' not in person
    assert SOURCE_KEY not in fg._normalize(SCHOOL, DEPT, person)['metadata']


@pytest.mark.parametrize('collector', ['faculty_graph', 'uiuc_faculty', 'ucb_common'])
def test_each_actual_faculty_upsert_preserves_source_in_temporary_storage(tmp_path, monkeypatch, collector):
    from src.collectors import uiuc_faculty
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    path = tmp_path/'opportunities.json'
    path.write_text(json.dumps([prior]))
    monkeypatch.setattr(ucb_common, 'PROCESSED_FILE', path)
    if collector == 'uiuc_faculty':
        uiuc_faculty.merge_into_processed([incoming], filepath=str(path))
    else:
        (fg if collector == 'faculty_graph' else ucb_common).merge_into_processed([incoming])
    saved = json.loads(path.read_text())
    assert len(saved) == 1
    loaded = _canonicalize_corpus(saved)[0]
    assert loaded['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]
    assert project_public_detail(loaded)['contact_instructions']['email_policy'] == 'allowed'


@pytest.mark.parametrize('invalid', [None, [], 'bad', 42])
def test_invalid_incoming_metadata_does_not_crash_full_enrichment_carry(invalid):
    prior, incoming = record(), record()
    prior['metadata'][SOURCE_KEY] = [source()]
    incoming['metadata'] = invalid
    _carry_forward_enrichment(prior, incoming)
    assert isinstance(incoming['metadata'], dict)
    assert incoming['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]


def test_render_captures_final_url_and_time_before_browser_closes(monkeypatch):
    import sys
    from contextlib import nullcontext
    from types import SimpleNamespace

    state = {'closed':False, 'content_read':False}

    class Page:
        def goto(self, *_a, **_k):
            pass

        def wait_for_timeout(self, _value):
            pass

        def content(self):
            state['content_read'] = True
            return '<body><h1>Jane Scientist</h1><p>Research profile.</p></body>'

        @property
        def url(self):
            assert state['content_read'] and not state['closed']
            return URL+'/'

    class Browser:
        def new_context(self, **_k):
            return SimpleNamespace(new_page=lambda: Page())

        def close(self):
            state['closed'] = True

    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **_k: Browser()))
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(sync_playwright=lambda: nullcontext(playwright)))
    soup = fg._render_soup(URL)
    observed = soup._ofe_fetch_metadata
    assert state['closed']
    assert observed['requested_url'] == URL and observed['final_url'] == URL+'/'
    assert datetime.fromisoformat(observed['checked_at']).tzinfo is not None
    assert soup._ofe_final_url == observed['final_url']


def test_campus_different_feed_update_survives_dedup_storage_and_public_projection(tmp_path, monkeypatch):
    from src.collectors import campus_graph
    prior = normalize({'id':'program-canonical', 'source':'sample_program', 'source_type':'campus_program',
                       'title':'Parser Fellowship', 'organization':'Sample University', 'description_raw':'Undergraduate research fellowship.',
                       'url':URL, 'source_url':URL, 'extra_fields':{SOURCE_KEY:[source()]}})
    # Program evidence has no professor identity claim.
    prior['metadata'][SOURCE_KEY][0].pop('identity_name')
    incoming = deepcopy(prior)
    incoming['id'] = 'program-other-feed'
    incoming['source'] = 'second_feed'
    observed = stamp(1)
    incoming['metadata'].update({CAPTURE_KEY:receipt('captured', observed),
                                 SOURCE_KEY:[source('Do not email us. Submit the application form.', observed)]})
    incoming['metadata'][CAPTURE_KEY].pop('identity_name')
    incoming['metadata'][SOURCE_KEY][0].pop('identity_name')
    path = tmp_path/'opportunities.json'
    path.write_text(json.dumps([prior]))
    monkeypatch.setattr(campus_graph, 'PROCESSED_FILE', path)
    assert campus_graph.merge_into_processed([incoming]) == (0, 1)
    saved = json.loads(path.read_text())
    assert [item['id'] for item in saved] == ['program-canonical']
    public = project_public_detail(_canonicalize_corpus(saved)[0])
    assert public['contact_instructions']['email_policy'] == 'form_only'
    assert saved[0]['metadata'][SOURCE_KEY] == incoming['metadata'][SOURCE_KEY]
