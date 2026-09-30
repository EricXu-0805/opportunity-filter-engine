"""Reviewed Nielsen four-document chain; all transport is injected/offline."""
from copy import deepcopy
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup

from src.collectors.lab_website import collect_lab_snapshot
from src.lab_context import NIELSEN_HOME, NIELSEN_PROFILE, NIELSEN_RESEARCH, NIELSEN_TEAM, lab_context_for
from tests.lab_nielsen_fixtures import nielsen_fetch, nielsen_pages, nielsen_record
from tests.test_lab_context import NOW


def collected(pages=None, *, record=None, now=NOW, errors=None):
    pages=nielsen_pages() if pages is None else pages; item=nielsen_record() if record is None else record
    calls=[];read=nielsen_fetch(pages)
    def fetch(url):
        calls.append(url)
        if errors and url in errors: return None,errors[url]
        return read(url)
    return collect_lab_snapshot(item,now=now,fetch=fetch),calls


@pytest.mark.parametrize('where,qualifier',[
    ('profile','<span>Former lab; no longer affiliated.</span>'),
    ('profile',' Former lab; no longer affiliated.'),
    ('home','<span>Archived; no longer current.</span>'),
    ('home',' Archived; no longer current.'),
])
def test_link_qualifiers_cannot_be_silently_ignored(where,qualifier):
    pages=nielsen_pages();url=NIELSEN_PROFILE if where=='profile' else NIELSEN_HOME
    html=pages[url].decode()
    needle='https://nielsen-lab.github.io</a>' if where=='profile' else 'href="/research/">Research</a>'
    pages[url]=html.replace(needle,needle+qualifier).encode()
    patch,_=collected(pages)
    assert patch['lab_refresh']['reason']=='unsupported_template'
    assert 'lab_snapshot' not in patch


def test_complete_chain_preserves_all_ten_sections_and_actual_link_evidence():
    item=nielsen_record();before=deepcopy(item);patch,calls=collected(record=item)
    assert item==before and calls==[NIELSEN_PROFILE,NIELSEN_HOME,NIELSEN_TEAM,NIELSEN_RESEARCH]
    assert patch['lab_refresh']['status']=='success'
    source=patch['lab_snapshot'];assert source['version']==2
    assert len(source['pages'][1]['sections'])==10
    assert 'TENTH_SECTION_MARKER' in source['pages'][1]['sections'][-1]['text']
    assert 'Example paper title 10' in source['pages'][1]['sections'][-1]['text']
    assert 'do not claim clinical validation; 12 samples' in source['pages'][1]['sections'][0]['text']
    assert 'identity_text' not in source['pages'][1] and 'linked_from' not in source['pages'][1]
    chain=source['source_chain']
    assert [d['role'] for d in chain['documents']]==['profile','home','team','research']
    assert [link['raw_href'] for link in chain['links']]==['https://nielsen-lab.github.io','/team/','/research/']
    item['metadata'].update(patch)
    assert lab_context_for(item,now=NOW)['status']=='available'


@pytest.mark.parametrize('url,expected_calls',[(NIELSEN_PROFILE,1),(NIELSEN_HOME,2),(NIELSEN_TEAM,3),(NIELSEN_RESEARCH,4)])
def test_temporary_failure_stops_chain_and_keeps_prior_source_date(url,expected_calls):
    item=nielsen_record();old,_=collected(now=NOW-timedelta(days=31));item['metadata'].update(old);before=deepcopy(item)
    patch,calls=collected(record=item,errors={url:'request_failed'})
    assert len(calls)==expected_calls and patch['lab_refresh']['reason']=='request_failed'
    assert 'lab_snapshot' not in patch and item==before
    item['metadata'].update(patch)
    assert item['metadata']['lab_snapshot']==before['metadata']['lab_snapshot']
    assert lab_context_for(item,now=NOW)['status']=='stale'


@pytest.mark.parametrize('url,remove',[
    (NIELSEN_PROFILE,'profile'),(NIELSEN_HOME,'team'),(NIELSEN_HOME,'research')
])
def test_trusted_link_removal_durably_revokes_until_complete_new_success(url,remove):
    item=nielsen_record();old,_=collected(now=NOW-timedelta(days=1));item['metadata'].update(old)
    pages=nielsen_pages();soup=BeautifulSoup(pages[url],'html.parser')
    if remove=='profile': soup.select_one('.field--name-field-website').decompose()
    else: soup.select_one('a[href="/'+remove+'/"]').parent.decompose()
    pages[url]=str(soup).encode();patch,calls=collected(pages,record=item)
    assert patch['lab_refresh']['reason']=='source_link_removed'
    assert patch['lab_refresh']['identity_revoked_at']==patch['lab_refresh']['checked_at']
    assert len(calls)==(1 if remove=='profile' else 2)
    item['metadata'].update(patch);assert lab_context_for(item,now=NOW)['status']=='unavailable'
    patch,_=collected(record=item,now=NOW+timedelta(hours=1),errors={NIELSEN_HOME:'http_error'})
    item['metadata'].update(patch);assert lab_context_for(item,now=NOW+timedelta(hours=1))['status']=='unavailable'
    assert patch['lab_refresh']['identity_revoked_at']==NOW.isoformat().replace('+00:00','Z')
    patch,_=collected(record=item,now=NOW+timedelta(hours=2));item['metadata'].update(patch)
    assert lab_context_for(item,now=NOW+timedelta(hours=2))['status']=='available'


@pytest.mark.parametrize('change',[
    lambda s:s.replace('>Rasmus Nielsen<','>Another Nielsen<'),
    lambda s:s.replace('Professor of Computational Biology','Former Professor of Computational Biology'),
])
def test_team_person_or_role_mismatch_is_revocation_not_a_success(change):
    pages=nielsen_pages();pages[NIELSEN_TEAM]=change(pages[NIELSEN_TEAM].decode()).encode()
    patch,calls=collected(pages)
    assert len(calls)==3 and patch['lab_refresh']['reason']=='identity_mismatch'
    assert 'identity_revoked_at' in patch['lab_refresh'] and 'lab_snapshot' not in patch


@pytest.mark.parametrize('change',[
    lambda s:s.replace('class="media-body"','class="changed-member-layout"'),
    lambda s:s.replace('class="col-lg-4 memberbox"','class="col-lg-4"><div class="memberbox"').replace('</div></div></div></div>','</div></div></div></div></div>',1),
    lambda s:s.replace('<p class="note">','<p>New limitation.</p><p class="note">'),
])
def test_team_template_changes_are_not_misreported_as_proven_identity_removal(change):
    pages=nielsen_pages();pages[NIELSEN_TEAM]=change(pages[NIELSEN_TEAM].decode()).encode()
    patch,_=collected(pages)
    assert patch['lab_refresh']['reason']=='unsupported_template'
    assert 'identity_revoked_at' not in patch['lab_refresh']


def test_duplicate_identity_card_is_ambiguous_and_does_not_fetch_research():
    pages=nielsen_pages();soup=BeautifulSoup(pages[NIELSEN_TEAM],'html.parser');card=soup.select_one('.memberbox');card.insert_after(deepcopy(card))
    pages[NIELSEN_TEAM]=str(soup).encode();patch,calls=collected(pages)
    assert patch['lab_refresh']['reason']=='unsupported_template' and len(calls)==3


@pytest.mark.parametrize('href',['//nielsen-lab.github.io/team/','team/','/other/../team/','/team/?next=1','https://nielsen-lab.github.io/team/'])
def test_unreviewed_nav_link_normalization_is_not_a_verified_removal(href):
    pages=nielsen_pages();pages[NIELSEN_HOME]=pages[NIELSEN_HOME].replace(b'href="/team/"',('href="'+href+'"').encode())
    patch,_=collected(pages)
    assert patch['lab_refresh']['reason']=='unsupported_template'
    assert 'identity_revoked_at' not in patch['lab_refresh']


@pytest.mark.parametrize('mode',['missing','extra','nested','overlong','base'])
def test_research_partial_or_changed_layout_never_silently_truncates(mode):
    pages=nielsen_pages();soup=BeautifulSoup(pages[NIELSEN_RESEARCH],'html.parser')
    if mode=='missing': soup.find_all('h1')[-1].decompose()
    elif mode=='extra': soup.select_one('body > div.container.mt-4').append(BeautifulSoup('<h1>New eleventh theme</h1>Extra new text','html.parser'))
    elif mode=='nested': soup.find('h1').wrap(soup.new_tag('section'))
    elif mode=='overlong': soup.find('h1').insert_after('研'*4001)
    else: soup.head.append(BeautifulSoup('<base href="https://other.example/">','html.parser'))
    pages[NIELSEN_RESEARCH]=str(soup).encode();patch,calls=collected(pages)
    assert len(calls)==4 and patch['lab_refresh']['status']=='failed' and 'lab_snapshot' not in patch


def test_wrong_record_id_does_not_follow_lab_links():
    item=nielsen_record();item['id']='other-same-named-professor'
    patch,calls=collected(record=item)
    assert len(calls)==1 and patch['lab_snapshot']['version']==1


@pytest.mark.parametrize('selector', ['.memberbox', '.media', '.media-body', '.head'])
@pytest.mark.parametrize('markup', ['Former member.', '<span>Former member.</span>'])
def test_team_identity_qualifiers_are_not_silently_discarded(selector,markup):
    pages=nielsen_pages();soup=BeautifulSoup(pages[NIELSEN_TEAM],'html.parser')
    soup.select_one(selector).append(BeautifulSoup(markup,'html.parser'))
    pages[NIELSEN_TEAM]=str(soup).encode();patch,calls=collected(pages)
    assert patch['lab_refresh']['reason']=='unsupported_template'
    assert 'identity_revoked_at' not in patch['lab_refresh'] and len(calls)==3


@pytest.mark.parametrize('where', ['profile_caption', 'profile_field', 'home_menu'])
def test_source_link_qualifiers_inside_caption_or_around_link_groups_are_rejected(where):
    pages=nielsen_pages();url=NIELSEN_PROFILE if where.startswith('profile') else NIELSEN_HOME
    soup=BeautifulSoup(pages[url],'html.parser')
    selector={'profile_caption':'.field--name-field-website a','profile_field':'.field--name-field-website','home_menu':'ul.navbar-nav'}[where]
    soup.select_one(selector).append('Former lab / archived sources.')
    pages[url]=str(soup).encode();patch,_=collected(pages)
    assert patch['lab_refresh']['reason']=='unsupported_template' and 'lab_snapshot' not in patch
