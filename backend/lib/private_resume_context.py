"""Owner-bound private résumé source snapshot; never a public opportunity projection.

The snapshot repeats the complete saved import for its owner. It is always
unverified: nothing guessed at import time becomes a requirement.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from backend.lib.private_import_targets_schema import identifier, owner
from backend.lib.private_target_resolution import PrivateResolvedTarget, safe_private_source_link

CONTEXT_VERSION = 5
FIELDS = {'context_version', 'opportunity_id', 'title', 'organization', 'source_url', 'description', 'requirements',
          'private_source'}
SOURCE_FIELDS = {'version', 'purpose', 'target_scope', 'verification', 'owner_id', 'revision', 'source_version',
                 'import_source'}
LABEL_FIELDS = {'version', 'description_source', 'ai_input_scope', 'llm_enriched'}
# The private import storage limits, in Unicode codepoints.
TEXT_LIMITS = (('title', 1000), ('organization', 2000), ('source_url', 8192), ('description', 5 * 1024 * 1024))


def _invalid():
    raise ValueError('invalid_private_resume_context')


def _source_version(opportunity_id, owner_id, revision):
    identity = {'id': opportunity_id, 'owner_id': owner_id, 'revision': revision}
    return 'pit1:' + hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _labels_valid(labels):
    if labels is None:
        return True
    if (type(labels) is not dict or set(labels) != LABEL_FIELDS or type(labels['version']) is not int
            or labels['version'] != 1 or type(labels['llm_enriched']) is not bool
            or labels['description_source'] not in ('page_text', 'page_excerpt', 'pasted_text', 'unknown')
            or labels['ai_input_scope'] not in ('full_source', 'source_excerpt', 'unknown')):
        return False
    # As in src/import_source.py: a recorded scope needs the success flag, full_source a whole text.
    if labels['ai_input_scope'] == 'source_excerpt':
        return labels['llm_enriched'] and labels['description_source'] != 'unknown'
    if labels['ai_input_scope'] == 'full_source':
        return labels['llm_enriched'] and labels['description_source'] in ('page_text', 'pasted_text')
    return True


def validate_private_resume_context(value):
    """Accept only the exact v5 shape; the source version must bind its id, owner and revision."""
    if (type(value) is not dict or set(value) != FIELDS or type(value['context_version']) is not int
            or value['context_version'] != CONTEXT_VERSION):
        _invalid()
    identifier(value['opportunity_id'])
    for key, maximum in TEXT_LIMITS:
        text = value[key]
        if type(text) is not str or '\0' in text or len(text) > maximum:
            _invalid()
        text.encode('utf-8')
    if not value['title'].strip() or not value['description'].strip() or value['requirements'] != []:
        _invalid()
    if value['source_url'] and safe_private_source_link(value['source_url']) != value['source_url']:
        _invalid()
    source = value['private_source']
    if (type(source) is not dict or set(source) != SOURCE_FIELDS or type(source['version']) is not int
            or source['version'] != 1 or source['purpose'] != 'resume' or source['target_scope'] != 'private_import'
            or source['verification'] != 'unverified' or type(source['revision']) is not int
            or not 1 <= source['revision'] <= 9007199254740991):
        _invalid()
    owner(source['owner_id'])
    if source['source_version'] != _source_version(value['opportunity_id'], source['owner_id'], source['revision']):
        _invalid()
    if not _labels_valid(source['import_source']):
        _invalid()
    return value


def private_resume_context(target: PrivateResolvedTarget) -> dict:
    detail = target.detail
    value = {
        'context_version': CONTEXT_VERSION, 'opportunity_id': target.id, 'title': detail['title'],
        'organization': detail['organization'] or '', 'source_url': detail['source_url'] or detail['url'] or '',
        'description': detail['description_raw'], 'requirements': [],
        'private_source': {
            'version': 1, 'purpose': 'resume', 'target_scope': 'private_import', 'verification': 'unverified',
            'owner_id': target.owner_id, 'revision': target.revision, 'source_version': target.target_version,
            'import_source': deepcopy(detail['import_source']),
        },
    }
    return validate_private_resume_context(value)
