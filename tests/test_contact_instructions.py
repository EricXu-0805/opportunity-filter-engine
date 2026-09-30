"""Source policy stays scoped to the fetched target and applicant audience."""
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from src.contact_instructions import SOURCE_KEY, contact_instructions_for, source_from_html

URL = 'https://research.example.edu/join'
STAMP = '2026-09-25T10:00:00Z'


def record(html, **kwargs):
    return {'url': URL, 'source_url': URL, 'metadata': {SOURCE_KEY: [source_from_html(
        '<html><body><main>' + html + '</main></body></html>', source_url=URL, checked_at=STAMP,
    )]}, **kwargs}


def policy(text, heading='Undergraduate researchers'):
    return contact_instructions_for(record(f'<h2>{heading}</h2><p>{text}</p>'))


def test_explicit_no_email_and_form_direction():
    result = policy('Please do not email us directly. Complete the contact form instead.')
    assert result['email_policy'] == 'form_only'
    assert {r['kind'] for r in result['rules']} == {'no_email', 'form_only'}
    assert result['rules'][0]['quote'].startswith('Please do not email')
    assert result['rules'][0]['source_url'] == URL
    assert result['rules'][0]['checked_at'] == STAMP


def test_mixed_audience_page_never_imports_grad_or_postdoc_policy():
    result = contact_instructions_for(record('''
      <h1>Join us</h1><h2>Prospective Ph.D. students</h2>
      <p>Please do not email us directly. Use the form.</p>
      <h2>Current undergraduate students</h2><p>Explore our research projects this fall.</p>
      <h2>Potential postdocs</h2><p>Please email us directly.</p>
    '''))
    assert result == {'version': 1, 'status': 'unknown', 'email_policy': 'unknown', 'rules': []}


@pytest.mark.parametrize('heading,text', [
    ('Undergraduate and graduate students', 'Please do not email us.'),
    ('Undergraduate students', 'PhD applicants should not email us.'),
    ('Join us', 'Please do not email us.'),
    ('Undergraduate students', 'If you have already applied, do not email us.'),
    ('Undergraduate students', 'Do not email us about application status.'),
    ('Undergraduate students', 'Submit applications only through the portal.'),
])
def test_unclear_or_limited_scope_never_becomes_global_ban(heading, text):
    assert policy(text, heading)['email_policy'] == 'unknown'


def test_form_and_email_remain_combined_not_form_only():
    result = policy('Complete the application form and email us with your CV and unofficial transcript. '
                    'Use the subject line "Undergraduate research inquiry".')
    assert result['email_policy'] == 'allowed'
    assert {r['kind'] for r in result['rules']} == {'email_allowed', 'materials', 'subject'}
    materials = next(r['materials'] for r in result['rules'] if r['kind'] == 'materials')
    assert materials == ['resume_cv', 'unofficial_transcript', 'application_form']


def test_subject_and_single_pdf_requirement_preserve_source_text():
    result = policy('Email your application with subject "Undergraduate application – [Your Last Name]". '
                    'Include a CV, transcript and statement of interest in one PDF.')
    subject = next(r for r in result['rules'] if r['kind'] == 'subject')
    assert result['email_policy'] == 'allowed'
    assert subject['subject_template'] == 'Undergraduate application – [Your Last Name]'
    assert 'subject' not in subject
    assert next(r['materials'] for r in result['rules'] if r['kind'] == 'materials') == [
        'resume_cv', 'transcript', 'statement_of_interest', 'single_pdf',
    ]


@pytest.mark.parametrize('template', ['Application {last_name}', 'Research &lt;Your Name&gt;'])
def test_other_placeholder_syntax_is_not_a_static_subject(template):
    result = policy(f'Use subject "{template}".')
    rule = result['rules'][0]
    assert rule['kind'] == 'subject' and 'subject_template' in rule and 'subject' not in rule


def test_unquoted_subject_instruction_keeps_quote_without_guessing_exact_text():
    result = policy('Use your full name and research area in the subject line.')
    assert result['rules'] == [{'kind': 'subject', 'quote': 'Use your full name and research area in the subject line.',
                                'source_url': URL, 'checked_at': STAMP}]


def test_negative_materials_are_not_positive_requirements():
    assert not any(r['kind'] == 'materials' for r in policy('Do not attach a CV or transcript.')['rules'])
    assert policy('Email is not required.')['email_policy'] == 'unknown'


def test_explicit_all_applicants_scope_works():
    assert policy('All applicants should email us with a CV.', heading='Join us')['email_policy'] == 'allowed'


def test_conflicting_sources_and_subjects_are_explicit():
    for html in [
        '<p>Please email us.</p><p>Please do not email us.</p>',
        '<p>Use subject "First". Use subject "Second".</p>',
        '<p>Use subject "First".</p><p>Use subject "[Last Name]".</p>',
    ]:
        result = contact_instructions_for(record('<h2>Undergraduate students</h2>' + html))
        assert (result['status'], result['email_policy']) == ('conflicting', 'conflicting')


def test_nested_heading_keeps_undergraduate_scope_and_adjacent_list():
    result = contact_instructions_for(record('''<h1>Join us</h1><h2>Undergraduate students</h2>
        <h3>How to apply</h3><p>Email us and include:</p><ul><li>CV</li><li>Transcript</li></ul>
        <h2>Graduate students</h2><p>Do not email us.</p>'''))
    assert result['email_policy'] == 'allowed'
    assert next(r['materials'] for r in result['rules'] if r['kind'] == 'materials') == ['resume_cv', 'transcript']


@pytest.mark.parametrize('mutation', ['url', 'source', 'time', 'oversize', 'identity'])
def test_stale_malformed_or_wrong_identity_evidence_is_not_reused(mutation):
    item = record('<h2>Undergraduate students</h2><p>Do not email us.</p>')
    source = item['metadata'][SOURCE_KEY][0]
    if mutation == 'url':
        item.update(url=URL + '/different', source_url=URL + '/different')
    elif mutation == 'source':
        source['source_url'] = 'file:///tmp/example'
    elif mutation == 'time':
        source['checked_at'] = '2026-09-25'
    elif mutation == 'oversize':
        source['sections'][0]['text'] += 'x' * 4001
    else:
        item.update(source_type='faculty_research', pi_name='Jane Scientist')
        source['identity_name'] = 'Other Scientist'
    assert contact_instructions_for(item)['status'] == 'unknown'


def test_synthetic_description_application_and_public_field_cannot_manufacture_source_rules():
    item = {'description_raw': 'Undergraduate students: do not email us.',
            'application': {'contact_method': 'email'},
            'contact_instructions': {'email_policy': 'not_accepted'}}
    assert contact_instructions_for(item)['status'] == 'unknown'


def test_nav_and_og_metadata_are_never_source_instructions():
    source = source_from_html('''<html><head><meta property="og:description"
        content="All applicants must not email us."></head><body><nav><h2>Undergraduate students</h2>
        <p>Do not email us.</p></nav><main><p>Research about water.</p></main></body></html>''', source_url=URL)
    item = {'url': URL, 'metadata': {SOURCE_KEY: [source]}}
    assert contact_instructions_for(item)['status'] == 'unknown'


def test_url_parser_and_normalizer_keep_html_evidence_independent_of_model(monkeypatch):
    from src.collectors.url_parser import _merge_llm_into_base, parse_url
    from src.normalizers.normalizer import normalize
    html = '''<html><head><meta property="og:description" content="A short summary"></head>
        <body><h1>Undergraduate students</h1><p>Do not email us directly. Complete the form.</p></body></html>'''
    monkeypatch.setattr('src.collectors.url_parser._safe_fetch', lambda _url: SimpleNamespace(text=html, url=URL, headers={'Content-Type':'text/html'}))
    raw = parse_url(URL)
    assert raw.description_raw == 'Undergraduate students\nDo not email us directly. Complete the form.'
    assert raw.extra_fields['page_meta_summary'] == 'A short summary'
    enriched = _merge_llm_into_base(raw, {'description': 'Please email us.', SOURCE_KEY: [{'forged': True}]})
    result = normalize(asdict(enriched))
    assert contact_instructions_for(result)['email_policy'] == 'form_only'
    before = deepcopy(result)
    enriched.extra_fields[SOURCE_KEY][0]['sections'][0]['text'] = 'Edited later'
    assert result == before


def test_sro_deep_fetch_keeps_source_but_listing_does_not(monkeypatch):
    from src.collectors.base import RawOpportunity
    from src.collectors.uiuc_sro import UIUCSROCollector, raw_to_normalized
    raw = RawOpportunity(source='uiuc_sro', source_url=URL, url=URL, title='Research', description_raw='Short listing')
    assert contact_instructions_for(raw_to_normalized(raw))['status'] == 'unknown'
    response = SimpleNamespace(text='<html><body><h1>Undergraduate researchers</h1><p>Please email us with your CV.</p></body></html>',
                               url=URL, raise_for_status=lambda: None)
    monkeypatch.setattr('src.collectors.uiuc_sro.requests.get', lambda *_a, **_k: response)
    UIUCSROCollector()._fetch_detail_page(raw)
    assert contact_instructions_for(raw_to_normalized(raw))['email_policy'] == 'allowed'


def test_identity_verified_faculty_enrichment_preserves_five_tuple_and_source(monkeypatch):
    from src.collectors import faculty_graph as fg
    school = {'school_slug': 'sample', 'source': 'sample_faculty', 'organization': 'Sample University',
              'location': 'Sample', 'id_prefix': 'sample'}
    dept = {'short': 'CS', 'name': 'Computer Science', 'majors': ['Computer Science']}
    html = '<html><body><h1>Jane Scientist</h1><h2>Undergraduate researchers</h2><p>Please email us with your CV.</p></body></html>'
    from src.collectors.ucb_common import _mark_fetched_soup_observation
    monkeypatch.setattr('src.collectors.ucb_common.fetch_soup', lambda *_a, **_k: _mark_fetched_soup_observation(BeautifulSoup(html, 'html.parser'), requested_url=URL, final_url=URL))
    result = fg._enrich_profile(URL, {}, expected_name='Jane Scientist')
    assert len(result) == 5 and result[-1] is True
    person = fg.faculty('Jane Scientist', title='Professor', url=URL)
    fg._apply_profile_enrich([person], {'always': True})
    normalized = fg._normalize(school, dept, person)
    assert contact_instructions_for(normalized)['email_policy'] == 'allowed'
    normalized['pi_name'] = 'Other Scientist'
    assert contact_instructions_for(normalized)['status'] == 'unknown'
    rejected = fg._enrich_profile(URL, {}, expected_name='Other Scientist')
    assert rejected[-1] is False and not getattr(rejected, 'contact_instruction_sources', [])


@pytest.mark.parametrize('text', [
    'We do not email students automatically.',
    'Do not email us about project logistics.',
    'Do not email your application; apply through the portal.',
    'Email applications are not accepted. Use the portal.',
])
def test_outgoing_and_application_only_restrictions_are_not_inquiry_bans(text):
    assert policy(text)['email_policy'] == 'unknown'


@pytest.mark.parametrize('text', [
    'Never include a transcript.', 'You may attach a CV.',
    'Include a CV only if you have previous experience.',
    'A transcript is optional. Include your research interests.',
])
def test_optional_or_conditional_materials_do_not_become_required(text):
    assert not any(r['kind'] == 'materials' for r in policy(text)['rules'])


def test_example_and_negated_subject_are_not_enforced():
    for text in ['Never use subject "Application".', 'For example, use subject "Research inquiry".']:
        assert not any(r['kind'] == 'subject' for r in policy(text)['rules'])



def test_future_source_timestamp_cannot_be_used_as_checked_evidence():
    item = record('<h2>Undergraduate students</h2><p>Do not email us.</p>')
    item['metadata'][SOURCE_KEY][0]['checked_at'] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert contact_instructions_for(item)['status'] == 'unknown'


def test_rule_output_is_bounded_with_explicit_review_instead_of_invented_conflict():
    html = '<h2>Undergraduate researchers</h2>' + ''.join(
        f'<p>Email us with your CV. Research project {i}.</p>' for i in range(25))
    result = contact_instructions_for(record(html))
    assert len(result['rules']) == 40
    assert result['status'] == 'known' and result['email_policy'] == 'allowed'
    assert result['review_required'] is True and result['reason'] == 'too_many_requirements'


def test_rules_after_output_bound_still_contribute_to_conflict_detection():
    html = '<h2>Undergraduate researchers</h2>' + ''.join(
        f'<p>Email us with your CV. Research project {i}.</p>' for i in range(25)) + '<p>Do not email us.</p>'
    result = contact_instructions_for(record(html))
    assert len(result['rules']) == 40 and result['review_required'] is True
    assert result['status'] == 'conflicting' and result['email_policy'] == 'conflicting'


def test_exact_bound_does_not_request_unnecessary_review():
    html = '<h2>Undergraduate researchers</h2>' + ''.join(
        f'<p>Email us with your CV. Research project {i}.</p>' for i in range(20))
    result = contact_instructions_for(record(html))
    assert len(result['rules']) == 40 and 'review_required' not in result and 'reason' not in result


def test_unfetched_html_helper_cannot_claim_official_snapshot():
    from src.collectors.url_parser import parse_url
    raw = parse_url(URL, html='<html><body><h1>Undergraduate researchers</h1><p>Do not email us.</p></body></html>')
    assert SOURCE_KEY not in raw.extra_fields


def test_url_llm_fetch_retains_source_even_when_enrichment_is_unavailable(monkeypatch):
    from src.collectors.url_parser import parse_url_llm
    from src.normalizers.normalizer import normalize
    html = '<html><body><h1>Undergraduate researchers</h1><p>Do not email us.</p></body></html>'
    from types import SimpleNamespace
    monkeypatch.setattr('src.collectors.url_parser._safe_fetch', lambda _url: SimpleNamespace(text=html, url=URL, headers={'Content-Type':'text/html'}))
    monkeypatch.setattr('src.collectors.url_parser._run_llm_extraction', lambda *_a, **_k: None)
    raw = parse_url_llm(URL)
    assert contact_instructions_for(normalize(asdict(raw)))['email_policy'] == 'not_accepted'


@pytest.mark.parametrize('text', [
    'If you are a returning student, use subject "Returning".',
    'Use subject "Research" unless you have a referral.',
    'If you are a returning student, use your name in the subject line.',
])
def test_conditional_subject_does_not_apply_to_every_student(text):
    result = policy(text)
    assert result['status'] == 'unknown' and result['rules'] == []


@pytest.mark.parametrize('source_name,expected', [('Jane Scientist, Ph.D.', 'not_accepted'), ('Other Scientist', 'unknown')])
def test_faculty_normalization_keeps_same_person_binding_without_adopting_other_snapshot(source_name, expected):
    from src.collectors import faculty_graph as fg
    school = {'school_slug': 'sample', 'source': 'sample_faculty', 'organization': 'Sample University',
              'location': 'Sample', 'id_prefix': 'sample'}
    dept = {'short': 'CS', 'name': 'Computer Science', 'majors': ['Computer Science']}
    source = source_from_html('<body><h2>Undergraduate researchers</h2><p>Do not email us.</p></body>',
                              source_url=URL, identity_name=source_name, checked_at=STAMP)
    person = fg.faculty('Jane Scientist, Ph.D.', title='Professor', url=URL)
    person['_contact_instruction_sources'] = [source]
    result = fg._normalize(school, dept, person)
    assert result['pi_name'] == 'Jane Scientist'
    assert contact_instructions_for(result)['email_policy'] == expected
    assert source['identity_name'] == source_name
