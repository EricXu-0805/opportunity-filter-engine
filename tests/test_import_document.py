"""Offline, source-preserving HTML reader contract."""
import signal
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.collectors.import_document import ImportDocumentError, extract_import_document


def page(body, head=''):
    return f'<html><head>{head}</head><body>{body}</body></html>'


def test_complete_body_survives_metadata_multiple_regions_and_late_conditions():
    middle = 'Full source paragraph. ' * 400
    result = extract_import_document(page(
        '<header>Source header</header><main><p>' + middle + '</p></main>'
        '<article><p>Second article: experience in SQL.</p></article>'
        '<aside><p>Minimum GPA 3.0.</p></aside>'
        '<footer><p>TAIL_DEADLINE: March 30. Submit a transcript.</p></footer>',
        '<title>Original title</title><meta name="description" content="Short meta summary">',
    ))
    assert middle.strip() in result['text']
    assert all(value in result['text'] for value in [
        'Source header', 'Second article: experience in SQL.', 'Minimum GPA 3.0.', 'TAIL_DEADLINE',
    ])
    assert result['title'] == 'Original title'
    assert result['meta_summary'] == 'Short meta summary'
    assert result['source_kind'] == 'fetched_html'
    assert 'Short meta summary' not in result['text']


def test_preserves_paragraph_list_and_table_boundaries():
    result = extract_import_document(page(
        '<h1>Application</h1><p>Read <strong>all</strong> conditions.<br>Second line.</p>'
        '<ol start="2"><li>Transcript</li><li>CV</li></ol><ul><li>Portfolio</li></ul>'
        '<table><caption>Dates</caption><thead><tr><th>Round</th><th>Deadline</th></tr></thead>'
        '<tbody><tr><td>First</td><td>June 1</td></tr><tr><td>Second</td><td>July 1</td></tr></tbody></table>'
    ))
    text = result['text']
    assert 'Read all conditions.\nSecond line.' in text
    assert '2. Transcript\n3. CV' in text
    assert '- Portfolio' in text
    assert 'Round\tDeadline\nFirst\tJune 1\nSecond\tJuly 1' in text


def test_removes_code_comments_and_explicit_hidden_but_keeps_static_details():
    text = extract_import_document(page(
        '<script>PRIVATE_SCRIPT</script><style>PRIVATE_STYLE</style><!--PRIVATE_COMMENT-->'
        '<p hidden>PRIVATE_HIDDEN</p><span aria-hidden="true">PRIVATE_ARIA</span>'
        '<div style="display: none !important">PRIVATE_DISPLAY</div>'
        '<div style="visibility: hidden">PRIVATE_VISIBILITY</div>'
        '<template>PRIVATE_TEMPLATE</template><svg><text>PRIVATE_SVG</text></svg>'
        '<p>Readable content.</p><details><summary>Requirements</summary><p>TAIL_FULL_REQUIREMENTS</p></details>'
    ))['text']
    assert 'PRIVATE_' not in text
    assert 'Requirements\nTAIL_FULL_REQUIREMENTS' in text


def test_entities_unicode_and_inline_nodes_keep_visible_text():
    text = extract_import_document('<p>研究 &amp; Python <b>skills</b>🙂. GPA &gt; 3.0.</p>')['text']
    assert text == '研究 & Python skills🙂. GPA > 3.0.'


def test_long_body_has_no_internal_excerpt_limit():
    source = 'Full Unicode source🙂. ' * 5000 + 'LAST_SOURCE_MARKER'
    assert extract_import_document(page('<p>' + source + '</p>'))['text'] == source


@pytest.mark.parametrize('mime', ['text/html', 'text/html; charset=UTF-8', 'application/xhtml+xml'])
def test_supported_content_types(mime):
    assert extract_import_document(page('<p>Source content.</p>'), content_type=mime)['text'] == 'Source content.'


@pytest.mark.parametrize('mime', ['application/pdf', 'application/octet-stream', 'image/png', 'application/json', 'text/plain'])
def test_non_html_content_types_are_explicitly_refused(mime):
    with pytest.raises(ImportDocumentError, match=r'^Unsupported source content type\.$') as raised:
        extract_import_document(page('<p>PRIVATE_INPUT</p>'), content_type=mime)
    assert raised.value.reason == 'unsupported_content_type'


@pytest.mark.parametrize('value', [None, b'<p>source</p>', 5, '\ud800'])
def test_invalid_input_does_not_echo_source(value):
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(value)
    assert raised.value.reason == 'invalid_html'
    assert str(raised.value) == 'Invalid HTML source.'


@pytest.mark.parametrize('html', ['%PDF-1.7\nPRIVATE_SOURCE', '\x89PNG\r\nPRIVATE_SOURCE', '<p>hello\x00world</p>'])
def test_binary_signatures_or_null_are_refused_without_mime(html):
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(html)
    assert raised.value.reason == 'unsupported_content_type'
    assert 'PRIVATE' not in str(raised.value)


@pytest.mark.parametrize(('html', 'reason'), [
    ('', 'empty_page'), ('  \n ', 'empty_page'), (page(''), 'empty_page'),
    (page('', '<meta name="description" content="Not the source">'), 'metadata_only'),
    (page('', '<title>Source title</title>'), 'metadata_only'),
    (page('<script>window.source="PRIVATE"</script><div id="root"></div>'), 'javascript_required'),
    # A bundler's shell: the script sits in the head and the body is one empty mount point.
    (page('<div id="app"></div>', '<title>Jobs</title><script type="module" crossorigin src="/assets/index-4f2a.js">'
                                  '</script>'), 'javascript_required'),
    (page('<noscript>Please enable JavaScript to view this page.</noscript>'), 'javascript_required'),
    (page('<h1>Access denied</h1><p>Verify you are human.</p>', '<title>Access denied</title>'), 'access_page'),
    (page('<form><label>Email</label><input><input type="password"><button>Log in</button></form>'), 'access_page'),
    (page('<h1>Just a moment...</h1><div id="challenge-running">Checking your browser</div>'), 'access_page'),
])
def test_empty_access_and_dynamic_shells_are_not_imported(html, reason):
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(html)
    assert raised.value.reason == reason


@pytest.mark.parametrize('login', [
    '<p>Log in to apply. An account is required to submit your application.</p>',
    '<form><label>Email</label><input><input type="password"><button>Sign in</button></form>',
    '<div class="g-recaptcha">CAPTCHA application form</div>',
])
def test_application_login_or_captcha_does_not_hide_readable_posting(login):
    source = '<main><h1>Research opportunity</h1><p>Undergraduates may apply. Deadline June 1.</p></main>'
    text = extract_import_document(page(source + login))['text']
    assert 'Undergraduates may apply. Deadline June 1.' in text


def test_static_noscript_content_is_readable_when_not_a_js_wall():
    text = extract_import_document(page('<noscript><p>Applications close June 1. Submit a CV.</p></noscript>'))['text']
    assert text == 'Applications close June 1. Submit a CV.'


def test_fragment_and_bare_text_are_read_without_chasing_link_or_iframe():
    text = extract_import_document('<p>Read the <a href="https://example.edu/details">linked details</a>.</p>'
                                   '<iframe src="https://example.edu/more">FALLBACK_FRAME</iframe>')['text']
    assert text == 'Read the linked details.'
    assert extract_import_document('Current fetched text.')['text'] == 'Current fetched text.'


def test_head_only_fragment_and_empty_doctype_are_not_body_content():
    for html, reason in [
        ('<title>Page title</title><meta name="description" content="Summary">', 'metadata_only'),
        ('<!doctype html><html><head></head></html>', 'empty_page'),
    ]:
        with pytest.raises(ImportDocumentError) as raised:
            extract_import_document(html)
        assert raised.value.reason == reason


def test_indented_table_remains_one_row_per_line():
    text = extract_import_document(page('<table>\n <tr>\n <th>Item</th>\n <th>Required</th>\n </tr>\n'
                                        '<tr>\n <td>CV</td>\n <td>Yes</td>\n </tr>\n</table>'))['text']
    assert text == 'Item\tRequired\nCV\tYes'


def test_explicit_list_numbers_and_reversed_lists_are_not_reinvented():
    text = extract_import_document('<ol><li value="4">Four</li><li>Five</li></ol>'
                                   '<ol reversed><li>Two</li><li>One</li></ol>')['text']
    assert text == '4. Four\n5. Five\n2. Two\n1. One'


def test_account_heading_does_not_make_a_password_wall_readable():
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(page('<h1>University Account Portal</h1><form>'
                                     '<label>Password</label><input type="password"></form>'))
    assert raised.value.reason == 'access_page'


def test_login_title_can_coexist_with_real_readable_source():
    text = extract_import_document(page('<h1>Sign in</h1><p>Undergraduates may apply. Deadline June 1.</p>'
                                        '<form><input type="password"></form>', '<title>Sign in</title>'))['text']
    assert 'Undergraduates may apply. Deadline June 1.' in text


def test_hidden_denial_heading_does_not_override_visible_source():
    source = '<p>Applications close June 1.</p><div hidden><h1>Access denied</h1></div>'
    assert extract_import_document(page(source))['text'] == 'Applications close June 1.'


def test_password_input_type_is_case_insensitive_and_hidden_forms_are_not_walls():
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(page('<form><input type="PASSWORD"></form>'))
    assert raised.value.reason == 'access_page'
    assert extract_import_document(page('<p>Research.</p><form hidden><input type="PASSWORD"></form>'))['text'] == 'Research.'


@pytest.mark.parametrize(('body', 'reason'), [
    ('<div>Please verify you are human.</div>', 'access_page'),
    ('<div>Please log in to continue.</div>', 'access_page'),
    ('<div>Access denied.</div>', 'access_page'),
    ('<div>Loading...</div><script src="app.js"></script>', 'javascript_required'),
])
def test_bare_gate_and_dynamic_loading_shells_are_not_source(body, reason):
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(page(body))
    assert raised.value.reason == reason


def test_login_instruction_in_same_paragraph_keeps_real_conditions():
    html = page('<h1>Research internship</h1><p>Applications close June 1. Log in to apply.</p>'
                '<form><input type="password"></form>')
    assert 'Applications close June 1. Log in to apply.' in extract_import_document(html)['text']


def test_javascript_skill_requirement_is_not_a_dynamic_page_wall():
    html = page('<h1>Frontend internship</h1><p>Applicants require JavaScript experience. Applications close June 1.</p>')
    assert 'Applicants require JavaScript experience.' in extract_import_document(html)['text']


def test_footer_navigation_does_not_make_a_login_wall_readable():
    html = page('<h1>University Account Portal</h1><form><input type="password"><button>Sign in</button></form>'
                '<footer><a href="/accessibility">Accessibility statement</a></footer>', '<title>Sign in</title>')
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(html)
    assert raised.value.reason == 'access_page'


def test_table_keeps_blank_leading_and_trailing_cells():
    html = page('<table><tr><th>Round</th><th>Deadline</th><th>Notes</th></tr>'
                '<tr><td></td><td>June 1</td><td></td></tr></table>')
    assert extract_import_document(html)['text'] == 'Round\tDeadline\tNotes\n\tJune 1\t'


@pytest.mark.parametrize('requirement', [
    'JavaScript experience is required.',
    'Applicants must have JavaScript experience.',
    'The role requires JavaScript and SQL.',
])
def test_javascript_requirement_wording_remains_source(requirement):
    assert extract_import_document(page('<p>' + requirement + '</p>'))['text'] == requirement


def test_footer_links_remain_in_successful_output():
    source = '<p>Applications close June 1.</p><footer><a href="/accessibility">Accessibility statement</a></footer>'
    assert extract_import_document(page(source))['text'] == 'Applications close June 1.\nAccessibility statement'


def test_table_with_only_blank_cells_is_not_readable_source():
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(page('<table><tr><td></td><td></td></tr></table>'))
    assert raised.value.reason == 'empty_page'


@pytest.mark.parametrize(('source', 'expected'), [
    ('<ol start="7"><li>A</li><li value="10">B</li><li>C</li></ol>', '7. A\n10. B\n11. C'),
    ('<ol reversed start="10"><li>A</li><li value="7">B</li><li>C</li></ol>', '10. A\n7. B\n6. C'),
    ('<ol start="-2"><li>A</li><li>B</li></ol>', '-2. A\n-1. B'),
    ('<ol start="invalid"><li>A</li><li value="5">B</li></ol>', '- A\n- B'),
    ('<ol><li>A</li><li value="invalid">B</li><li>C</li></ol>', '1. A\n- B\n- C'),
    ('<ol reversed><li>A<ol start="4"><li>Nested</li></ol></li><li>B</li></ol>', '2. A\n4. Nested\n1. B'),
    ('<ol><li>A</li><li hidden>B</li><li>C</li></ol>', '1. A\n3. C'),
])
def test_ordered_list_numbering_and_invalid_value_fallback_stay_stable(source, expected):
    assert extract_import_document(source)['text'] == expected


def test_large_ordered_list_keeps_every_item_and_number():
    source = '<ol>' + ''.join(f'<li>Complete item {i}</li>' for i in range(3000)) + '</ol>'
    lines = extract_import_document(source)['text'].splitlines()
    assert lines == [f'{i + 1}. Complete item {i}' for i in range(3000)]


# Bot-verification interstitials a site served to our fetcher instead of the
# posting. On 2026-09-30 researchops.web.illinois.edu answered the production
# server with an Imunify360 check, imported as an "AI-assisted" opportunity
# titled "One moment, please..." whose text was only "Please wait while your
# request is being verified...". The walk kept that title and text, not the
# page, so the first case is a reconstruction of Imunify360's WebShield
# template with the same title and text.
IMUNIFY_WEBSHIELD = (
    '<!DOCTYPE html><html><head><meta charset="utf-8"><title>One moment, please...</title>'
    '<style>body{background:#F6F7F8}</style></head><body>'
    '<h1>Please wait while your request is being verified...</h1>'
    '<form id="wsidchk-form" style="display:none;" action="/z0f76a1d14fd21a8fb5f" method="GET">'
    '<input type="hidden" id="wsidchk" name="wsidchk"/></form>'
    '<script>(function(){var wsidchk=1;})();</script></body></html>'
)


@pytest.mark.parametrize('html', [
    pytest.param(IMUNIFY_WEBSHIELD, id='imunify360-webshield'),
    # The same interstitial without the vendor form, title or script: its
    # sentences alone are not opportunity text.
    pytest.param(page('<h1>Please wait while your request is being verified...</h1>'
                      '<script>setTimeout(function(){},1)</script>', '<title>One moment, please...</title>'),
                 id='imunify360-h1-script'),
    pytest.param(page('<p>Please wait while your request is being verified...</p>',
                      '<title>One moment, please...</title>'), id='imunify360-paragraph'),
    pytest.param(page('<div><h1>Please wait while your request is being verified...</h1><form method="post">'
                      '<input type="hidden" name="x" value="1"></form></div><noscript>Enable JS</noscript>'),
                 id='imunify360-untitled-form'),
    pytest.param(page('<p>Please wait while your request is being verified...</p>'), id='verification-sentence-only'),
    # Anubis: a blocked title with explanatory prose under it.
    pytest.param(page('<main><h1 id="title">Making sure you&#39;re not a bot!</h1><p id="status">Loading...</p>'
                      '<details><summary>Why am I seeing this?</summary><p>You are seeing this because the '
                      'administrator of this website has set up Anubis to protect the server against the scourge '
                      'of AI companies aggressively scraping websites.</p></details>'
                      '<footer><p>Protected by Anubis From Techaro.</p></footer></main>',
                      '<title>Making sure you&#39;re not a bot!</title>'
                      '<script id="anubis_challenge" type="application/json">{"challenge":"abc"}</script>'),
                 id='anubis'),
    pytest.param(page('<h1>Pardon Our Interruption...</h1><p>As you were browsing something about your browser made '
                      'us think you were a bot. There are a few reasons this might happen:</p>'
                      '<ul><li>You have disabled cookies in your web browser.</li></ul>',
                      '<title>Pardon Our Interruption</title>'), id='imperva-distil'),
    # Incapsula: the whole page is a challenge frame, or a script and its noscript notice.
    pytest.param('<html style="height:100%"><head><META NAME="ROBOTS" CONTENT="NOINDEX, NOFOLLOW"></head>'
                 '<body style="margin:0px;height:100%"><iframe id="main-iframe" '
                 'src="/_Incapsula_Resource?CWUDNSAI=9&xinfo=1" frameborder=0 width="100%" height="100%">'
                 'Request unsuccessful. Incapsula incident ID: 123-456</iframe></body></html>', id='incapsula-frame'),
    pytest.param('<html><head><script src="/_Incapsula_Resource?SWJIYLWA=719d34d31c8e3a6e6fffd425f7e032f3"></script>'
                 '</head><body><noscript>Request unsuccessful. Incapsula incident ID: 470000100123456-123456789'
                 '</noscript></body></html>', id='incapsula-noscript'),
    pytest.param(page('<div id="px-captcha"></div><p>Press &amp; Hold to confirm you are a human (and not a bot).</p>'
                      '<p>Reference ID 5b0f8a10-1234-11ef-9c1a-7a6f1f1c0000</p>',
                      '<title>Access to this page has been denied</title>'), id='perimeterx'),
    # PerimeterX's template breaks its sentence over two lines; its title refuses it.
    pytest.param(page('<h1>Before we continue...</h1><p>Press &amp; Hold to confirm you are<br>a human (and not a bot).</p>'
                      '<div id="px-captcha"></div><p>Reference ID 5b0f8a10-1234-11ef-9c1a-7a6f1f1c0000</p>',
                      '<title>Access to this page has been denied</title>'), id='perimeterx-template'),
    # DataDome: the site's own name as title, a captcha frame as the body.
    pytest.param('<html lang="en"><head><title>example.edu</title>'
                 "<script>var dd={'rt':'c','cid':'AHrlqAAAAAMA','host':'geo.captcha-delivery.com'}</script>"
                 '<script src="https://ct.captcha-delivery.com/c.js"></script></head>'
                 '<body><iframe src="https://geo.captcha-delivery.com/captcha/?initialCid=AHrlq" '
                 'title="DataDome CAPTCHA"></iframe></body></html>', id='datadome'),
    # DataDome's block page as public reports quote it (ahivert/tgtg-python#205):
    # the site's name as title, one notice, and the captcha loader.
    pytest.param('<html><head><title>example.edu</title><style>#cmsg{animation: A 1.5s;}</style></head>'
                 '<body style="margin:0"><p id="cmsg">Please enable JS and disable any ad blocker</p>'
                 "<script data-cfasync=\"false\">var dd={'cid':'AHrlqAAAAAMA','t':'bv','r':'b',"
                 "'host':'geo.captcha-delivery.com'}</script>"
                 '<script data-cfasync="false" src="https://ct.captcha-delivery.com/c.js"></script></body></html>',
                 id='datadome-block-page'),
    # Cloudflare's current challenge, with its "Just a moment..." title removed.
    pytest.param(page('<main><h1>example.edu</h1><p>Verify you are human by completing the action below.</p>'
                      '<p>example.edu needs to review the security of your connection before proceeding.</p>'
                      '<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script></main>'),
                 id='cloudflare-untitled'),
    pytest.param(page('<h1>Checking your browser before accessing example.edu</h1>', '<title>DDoS-Guard</title>'),
                 id='ddos-guard'),
    pytest.param(page('<p>Verifying you are human. This may take a few seconds.</p>',
                      '<title>Human Verification</title>'), id='human-verification'),
    # Under the site's own title, a loading line beside the check is not source.
    pytest.param(page('<p id="status">Loading...</p><p>Verifying you are human. This may take a few seconds.</p>'
                      '<script src="/challenge.js"></script>', '<title>example.edu</title>'), id='verifying-with-loading-line'),
    # "Please wait" opens the sentence, but it is a bot check, not a loading page.
    pytest.param(page('<h1>Please wait while your request is being verified...</h1><script>(function(){})();</script>'),
                 id='verification-sentence-script'),
    pytest.param(page('<h1>Vercel Security Checkpoint</h1><p>We are verifying your browser.</p>',
                      '<title>Vercel Security Checkpoint</title>'), id='vercel-checkpoint'),
    pytest.param(page('<p>Robot Challenge Screen</p>', '<title>Robot Challenge Screen</title>'
                      '<meta http-equiv="refresh" content="0;/.well-known/sgcaptcha/?r=%2Fprogram">'),
                 id='siteground'),
])
def test_bot_verification_interstitial_is_an_access_page_not_a_posting(html):
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(html, content_type='text/html')
    assert raised.value.reason == 'access_page'


# BotStopper titles the check with the site's own name and explains it in four
# paragraphs, so neither a title nor a missing-text rule can tell it apart.
ANUBIS_BOTSTOPPER = (Path(__file__).parent / 'fixtures' / 'anubis_botstopper_challenge.html').read_text(encoding='utf-8')


def test_anubis_check_under_the_site_title_with_its_explanation_is_an_access_page():
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(ANUBIS_BOTSTOPPER, content_type='text/html')
    assert raised.value.reason == 'access_page'


# One vendor's challenge markup per case. Only a bot-check page carries it, so
# it refuses the page whatever title and explanation surround it. Cloudflare's
# form counts by the __cf_chl_ token it posts back, not by its id.
@pytest.mark.parametrize(('head', 'body'), [
    pytest.param('<script id="anubis_challenge" type="application/json">{"rules":{"algorithm":"fast"}}</script>', '',
                 id='anubis-challenge-data'),
    pytest.param('', '<script async type="module" src="/.within.website/x/cmd/anubis/static/js/main.mjs?cacheBuster=1.22.2">'
                 '</script>', id='anubis-script'),
    pytest.param('', '<form id="wsidchk-form" style="display:none;" action="/z0f76a1d14fd" method="GET">'
                 '<input type="hidden" id="wsidchk" name="wsidchk"></form>', id='imunify360-form'),
    pytest.param('', '<form id="challenge-form" action="/?__cf_chl_f_tk=abc" method="POST">'
                 '<input type="hidden" name="md" value="x"></form>', id='cloudflare-form'),
    pytest.param('', '<div id="cf-challenge-running"></div>', id='cloudflare-legacy-running'),
    pytest.param('<meta http-equiv="refresh" content="0;/.well-known/sgcaptcha/?r=%2Fprogram">', '',
                 id='siteground-refresh'),
])
def test_vendor_challenge_markup_refuses_the_page_however_much_it_explains(head, body):
    title = '<title>Nicholas Institute for Energy, Environment &amp; Sustainability</title>'
    explained = ('<main><h1>Nicholas Institute for Energy, Environment &amp; Sustainability</h1><p id="status">Loading...</p>'
                 '<p>You are seeing this because the administrator of this website has set up a check to protect the '
                 'server against aggressive scraping. This can and does cause downtime for the website.</p>{}</main>')
    assert 'set up a check' in extract_import_document(page(explained.format(''), title))['text']
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(page(explained.format(body), title + head))
    assert raised.value.reason == 'access_page'


@pytest.mark.parametrize('extra', [
    '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>',
    '<div class="cf-turnstile" data-sitekey="0x4AAA"></div><p>Complete the check below to verify you are human, then submit.</p>',
    '<iframe src="https://geo.captcha-delivery.com/captcha/?x=1"></iframe>',
    '<noscript>Please enable JavaScript and cookies to continue.</noscript>',
])
def test_challenge_widget_or_script_does_not_hide_a_readable_posting(extra):
    source = '<main><h1>Research opportunity</h1><p>Undergraduates may apply. Deadline June 1.</p></main>'
    text = extract_import_document(page(source + extra))['text']
    assert 'Undergraduates may apply. Deadline June 1.' in text


# ASP.NET WebForms and SharePoint wrap the whole page, posting included, in one
# form, so text inside forms has to count against a bot-check sentence or script.
@pytest.mark.parametrize('extra', [
    pytest.param('<p>Please verify you are human before submitting.</p>', id='captcha-note'),
    pytest.param('<p>Uploading your CV: this may take a few seconds.</p>', id='upload-note'),
    pytest.param('<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>', id='cloudflare-page-script'),
    pytest.param('<iframe src="https://geo.captcha-delivery.com/captcha/?x=1"></iframe>', id='datadome-frame'),
    pytest.param('<script src="/_Incapsula_Resource?SWJIYLWA=719d34d31c8e3a6e6fffd425f7e032f3&ns=2"></script>',
                 id='incapsula-script'),
])
def test_bot_check_sentence_or_script_does_not_hide_a_posting_inside_one_page_wide_form(extra):
    source = page('<form method="post" action="./Posting.aspx?id=12" id="form1"><div class="aspNetHidden">'
                  '<input type="hidden" name="__VIEWSTATE" value="abc"></div><div id="content">'
                  '<h1>Undergraduate Research Assistant</h1><p>The Soil Microbiology Lab seeks an undergraduate '
                  'research assistant for spring 2027.</p><p>Deadline: January 15, 2027.</p>' + extra + '</div></form>')
    text = extract_import_document(source)['text']
    assert 'The Soil Microbiology Lab seeks an undergraduate research assistant for spring 2027.' in text


# Imperva adds this script to ordinary pages of the sites it protects. Only its
# frame (incapsula-frame above) serves a challenge.
@pytest.mark.parametrize('body', [
    pytest.param('<table><tr><th>Lab</th><th>Pay</th></tr><tr><td>Optics</td><td>$15</td></tr>'
                 '<tr><td>Robotics</td><td>$16</td></tr></table>', id='table-listing'),
    pytest.param('<p>Log in to Handshake and search for job 12345 to apply.</p>'
                 '<p>Sign in with your NetID to see the full description.</p>', id='sign-in-sentences-only'),
])
def test_imperva_page_script_alone_is_not_a_bot_check(body):
    source = '<main><h1>Open positions</h1>' + body + '</main>'
    script = '<script src="/_Incapsula_Resource?SWJIYLWA=719d34d31c8e3a6e6fffd425f7e032f3&ns=2"></script>'
    assert extract_import_document(page(source + script)) == extract_import_document(page(source))


# Markup a site can carry for its own reasons: a "Grand Challenge" sign-up form,
# a competition's status box, PerimeterX's widget inside an apply form, and the
# script Cloudflare adds to pages it serves. Main imports these pages; the
# markup must not refuse them, however little else they say.
CHALLENGE_SCHOLARS = ('<main><h1>Illinois Grand Challenge Scholars</h1><p>Undergraduates may join the Grand Challenge '
                      'program in spring 2027. Scholars complete research, service and entrepreneurship components.</p>'
                      '{}</main>')
SOIL_POSTING = ('<main><h1>Undergraduate Research Assistant</h1><p>The Soil Microbiology Lab seeks an undergraduate '
                'research assistant for spring 2027. Students will analyze soil samples.</p>'
                '<p>Deadline: January 15, 2027.</p>{}</main>')
SHORT_LIST = ('<main><h1>Summer REU 2027</h1><h2>Deadline Feb 1</h2><ul><li>Paid</li><li>10 weeks</li>'
              '<li>Housing</li></ul><p><a href="/apply">Apply</a></p>{}</main>')
LAB_TABLE = ('<main><h1>Open positions</h1><table><tr><th>Lab</th><th>Pay</th></tr><tr><td>Optics</td><td>$15</td></tr>'
             '<tr><td>Robotics</td><td>$16</td></tr></table>{}</main>')
LABELS_ONLY = ('<form action="/apply"><h2>Research assistant application</h2><label>Describe your interest in soil '
               'microbiology research</label><textarea></textarea></form>{}')
CLOUDFLARE_PAGE_SCRIPT = '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'


@pytest.mark.parametrize(('source', 'markup'), [
    pytest.param(CHALLENGE_SCHOLARS, '<form id="challenge-form" action="/register" method="post"><label>Email</label>'
                 '<input name="email"><button>Register</button></form>', id='competition-sign-up-form'),
    pytest.param(CHALLENGE_SCHOLARS, '<div id="challenge-running">The challenge is running now.</div>',
                 id='competition-status'),
    pytest.param(SOIL_POSTING, '<form action="/apply"><div id="px-captcha"></div><button>Apply</button></form>',
                 id='captcha-widget-in-apply-form'),
    pytest.param(SHORT_LIST, CLOUDFLARE_PAGE_SCRIPT, id='short-list-cloudflare-script'),
    pytest.param(LAB_TABLE, CLOUDFLARE_PAGE_SCRIPT, id='table-cloudflare-script'),
    pytest.param(LABELS_ONLY, CLOUDFLARE_PAGE_SCRIPT, id='form-labels-cloudflare-script'),
])
def test_markup_a_site_can_carry_for_itself_does_not_refuse_its_page(source, markup):
    plain = extract_import_document(page(source.format('')))['text']
    marked = extract_import_document(page(source.format(markup)))['text']
    assert all(line in marked.splitlines() for line in plain.splitlines())


def test_an_empty_challenge_box_is_still_a_bot_check():
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(page('<div id="challenge-running"></div>'))
    assert raised.value.reason == 'access_page'


# A title that only begins with a bot check's name, or a courtesy title over a
# readable posting, belongs to the site's own page. The whole stock title still
# refuses (human-verification, vercel-checkpoint and the Imunify360 cases above).
@pytest.mark.parametrize(('body', 'head', 'kept'), [
    pytest.param('<main><h1>Human verification: a psychology study</h1><p>We are recruiting undergraduate research '
                 'assistants for a study of how people judge CAPTCHA tasks.</p></main>',
                 '<title>Human Verification: RA position</title>', 'how people judge CAPTCHA tasks', id='human-verification-study'),
    pytest.param('<main><h1>Security Checkpoint - Airport Screening Research</h1><p>The Human Factors Lab seeks '
                 'undergraduates to study airport screening queues. Paid, 10 hours a week.</p></main>', '',
                 'study airport screening queues', id='security-checkpoint-study'),
    pytest.param('<main><h1>Bot Verification | Undergraduate security research</h1><p>Join our lab to study automated '
                 'traffic detection on university networks.</p></main>', '',
                 'automated traffic detection', id='bot-verification-lab'),
    pytest.param('<main><h1>TSA Research</h1><h1>Security checkpoint</h1><p>Undergraduates will observe checkpoint '
                 'throughput this summer.</p></main>', '', 'observe checkpoint throughput', id='security-checkpoint-heading'),
    pytest.param(SOIL_POSTING.format(''), '<title>One moment, please</title>', 'Soil Microbiology Lab',
                 id='one-moment-title'),
])
def test_bot_check_words_in_a_postings_title_do_not_refuse_it(body, head, kept):
    assert kept in extract_import_document(page(body, head))['text']


# Sentences an ordinary sparse posting can hold. Bot checks print different
# ones (PerimeterX "confirm you are a human", Imunify360 "is being verified",
# Imperva's incident ID), and main imports these pages.
SPARSE = '<main><h1>Summer REU 2027</h1><ul><li>Stipend $6,000</li><li>10 weeks</li></ul>{}</main>'


@pytest.mark.parametrize('note', [
    pytest.param('<p>Press and hold the record key to test.</p>', id='press-and-hold'),
    pytest.param('<p>This may take a few seconds.</p>', id='may-take-seconds'),
    pytest.param('<form action="/apply"><p>Request unsuccessful. Try again.</p><button>Apply</button></form>',
                 id='request-unsuccessful'),
    pytest.param('<p>Your request will be verified by the lab manager.</p>', id='request-will-be-verified'),
])
def test_ordinary_sentences_on_a_sparse_posting_are_not_a_bot_check(note):
    text = extract_import_document(page(SPARSE.format(note)))['text']
    assert '- Stipend $6,000' in text


# A script page whose only text is a loading line is a page its scripts have
# yet to fill, not a bot check, so the student hears that it needs JavaScript.
@pytest.mark.parametrize('html', [
    pytest.param(page('<div id="app"><p>Loading positions, this may take a few seconds...</p></div>'
                      '<script src="/app.js"></script>'), id='loading-sentence'),
    pytest.param(page('<div id="root">Loading, please wait...</div>', '<script type="module" src="/assets/index.js">'
                      '</script>'), id='head-script'),
    pytest.param(page('<div id="app"><p>Loading jobs…</p><p>This may take a few seconds.</p></div>'
                      '<script src="/app.js"></script>'), id='two-lines'),
    pytest.param(page('<div id="app"><p>Loading jobs. This may take a few seconds.</p></div>'
                      '<script src="/app.js"></script>'), id='single-period'),
])
def test_script_page_with_only_a_loading_line_needs_javascript(html):
    with pytest.raises(ImportDocumentError) as raised:
        extract_import_document(html)
    assert raised.value.reason == 'javascript_required'


@pytest.mark.parametrize(('body', 'kept'), [
    pytest.param('<main><h1>Loading dock assistant</h1><p>Loading dock worker needed</p></main>',
                 'Loading dock worker needed', id='loading-dock'),
    pytest.param(SOIL_POSTING.format('<p id="status">Loading...</p>'), 'Soil Microbiology Lab', id='posting-with-status'),
    pytest.param('<main><p>Loading dock worker needed.</p><p>The campus warehouse hires students for spring 2027.</p></main>',
                 'campus warehouse hires students', id='loading-dock-sentence'),
])
def test_loading_words_beside_source_are_not_a_loading_page(body, kept):
    assert kept in extract_import_document(page(body + '<script src="/app.js"></script>'))['text']


@contextmanager
def _deadline(seconds):
    """Fail a runaway scan instead of hanging the suite: re checks signals while it matches."""
    def expire(signum, frame):
        raise TimeoutError(f'still reading after {seconds} s')
    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


# The loading-line rule reads the whole text of a script page and each sentence
# a sign-in or bot-check rule weighs. A run of "loading" words can be split into
# lines many ways, and a failed match used to try every split: 409 characters
# held a guest's /api/import-url request, and the API process with it, for 8 s,
# doubling with each further pair of words.
@pytest.mark.parametrize('html', [
    pytest.param(page('<p>' + 'loading loading, ' * 400 + 'x</p><script src="/app.js"></script>'), id='page-text'),
    pytest.param(page('<p>' + 'loading loading... ' * 400 + 'x</p><script src="/app.js"></script>'), id='page-text-dots'),
    pytest.param(page('<p>' + 'loading loading, ' * 400 + 'x</p>', '<title>Sign in</title>'), id='sentence-behind-sign-in'),
    pytest.param(page('<p>' + 'loading loading, ' * 400 + 'x</p><p>Checking your browser.</p>'),
                 id='sentence-beside-bot-check-text'),
])
def test_loading_line_rule_reads_a_long_run_of_loading_words_in_linear_time(html):
    with _deadline(2):
        text = extract_import_document(html)['text']
    assert text.startswith('loading loading')


# The blocked-title rule matches the <title> and each visible <h1> whole. After
# "checking your browser before proceeding" it let two quantifiers share a run
# of '.', '!' or '…', and a title that failed at a newline after the run was
# retried at every split of it: 32,000 characters took 2.1 s, and each doubling
# took four times longer. Such a title is not a bot check; the posting imports.
@pytest.mark.parametrize('mark', ['.', '!', '…'])
@pytest.mark.parametrize('where', ['title', 'h1'])
def test_blocked_title_rule_reads_a_long_punctuation_run_in_linear_time(where, mark):
    heading = 'Checking your browser before proceeding' + mark * 50_000 + '\nThe lab'
    if where == 'title':
        html = page(SOIL_POSTING.format(''), f'<title>{heading}</title>')
    else:
        html = page(SOIL_POSTING.format(f'<h1>{heading}</h1>'))
    with _deadline(2):
        text = extract_import_document(html)['text']
    assert 'The Soil Microbiology Lab seeks an undergraduate research assistant for spring 2027.' in text
