"""Self-reported student status is not citizenship, a visa or eligibility."""
import json

import pytest

from backend.routes import cold_email as ce
from src.recommender.cold_email import _common_parts
from tests import test_cold_email_writing_quality as quality
from tests.test_email_contact_context import result

OPP, PROFILE, client = quality.OPP, quality.PROFILE, quality.client

CURRENT = 'Dear Pat Lee,\n\nCould we talk?\n\nBest regards,\nAudit Student'
BRIEF_LINE = '- International student (self-reported): '
BRIEF_RULE = ('International student: true is a self-report; null means not supplied, not domestic. '
              'Mention it only when relevant to the request. '
              'It establishes no citizenship, visa, work authorization or eligibility.\n')


def profile(flag):
    out = dict(PROFILE)
    if flag != 'absent':
        out['international_student'] = flag
    return out


@pytest.mark.parametrize('flag', [True, 1, 'true', False, None, 'absent'])
def test_only_a_checked_box_reaches_the_student_parts(flag):
    assert _common_parts(profile(flag), OPP)['international_student'] is (True if flag is True else None)


@pytest.mark.parametrize('flag', [True, False, 'absent'])
@pytest.mark.parametrize('path', ['', 'stream', 'body', 'selection'])
def test_every_ai_prompt_carries_the_box_as_true_or_null(client, monkeypatch, path, flag):
    calls = []

    def provider(messages, **kwargs):
        calls.append(messages)
        if path == 'selection':
            return json.dumps({'replacement': 'Could we meet?'})
        return CURRENT if path == 'body' else 'Subject: Research inquiry\n\n' + CURRENT

    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', provider)
    monkeypatch.setenv('OFE_COLD_EMAIL_NDRAFT', '1')
    monkeypatch.setenv('OFE_COLD_EMAIL_CRITIQUE', '0')
    payload = {'profile': profile(flag), 'opportunity_id': OPP['id']}
    if path in ('', 'stream'):
        result(client.post('/api/cold-email' + (f'/{path}' if path else ''), json={**payload, 'engine': 'ai'}), path)
    else:
        payload.update(subject='Research inquiry', current_body=CURRENT,
                       instruction='Make it more formal and professional')
        if path == 'selection':
            start = CURRENT.index('Could we talk?')
            payload['selection'] = {'start_utf16': start, 'end_utf16': start + len('Could we talk?'),
                                    'text': 'Could we talk?'}
        response = client.post('/api/cold-email/refine', json=payload)
        assert response.status_code == 200, response.text
    assert calls
    for messages in calls:
        brief = messages[1]['content']
        assert BRIEF_LINE + ('true' if flag is True else 'null') + '\n' in brief
        assert BRIEF_RULE in brief
