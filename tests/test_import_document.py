"""Offline, source-preserving HTML reader contract."""
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
