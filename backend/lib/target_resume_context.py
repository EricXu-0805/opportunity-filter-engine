"""Versioned public target snapshot; no private/raw fields or implicit upgrades.

V2 captures the published values, not a claim that each value is source-stated.
Missing, null, unknown, estimates and inference markers remain distinguishable.
The caller must first apply the anonymous public opportunity projection.
"""
from __future__ import annotations

import json
from copy import deepcopy

import rfc8785

from src.research_context import validate_public_research_context

LEGACY_FIELDS = ('opportunity_id', 'title', 'organization', 'source_url', 'description', 'requirements')
CRITERIA_FIELDS = {
    'eligibility': {
        'preferred_year': list, 'min_gpa_decimal': str, 'majors': list, 'skills_required': list,
        'skills_preferred': list, 'citizenship_required': bool, 'international_friendly': str,
        'work_auth_notes': str, 'first_time_researchers': bool,
    },
    'timing': {
        'deadline': str, 'deadline_is_estimate': bool, 'is_rolling': bool, 'deadline_note': str,
        'start_date': str, 'posted_date': str, 'duration': str,
    },
    'application': {
        'contact_method': str, 'application_effort': str, 'requires_resume': str,
        'requires_cover_letter': str, 'requires_transcript': str, 'requires_recommendation': str,
        'application_url': str,
    },
    'setting': {
        'location': str, 'remote_option': str, 'on_campus': bool, 'opportunity_type': str,
        'paid': str, 'compensation_details': str, 'department': str, 'lab_or_program': str, 'pi_name': str,
    },
    'availability': {
        'record_kind': str, 'source_type': str, 'faculty_availability_status': str, 'target_truth': dict,
    },
    'attribution': {
        'skills_attribution': str, 'majors_attribution': str, 'preferred_year_attribution': str,
        'international_attribution': str, 'citizenship_attribution': str, 'paid_attribution': str,
    },
}
TRUTH_FIELDS = {
    'listing_state': str, 'reference_only': bool, 'actionable': bool,
    'accepting_state': str, 'reason_code': str,
}


class InvalidTargetContext(ValueError):
    """A safe public code; do not embed source values."""


def invalid():
    raise InvalidTargetContext('invalid_target')


def _text(value):
    if type(value) is not str or '\x00' in value:
        invalid()
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        invalid()


def _fields(value, schema):
    if type(value) is not dict or value.keys() - schema.keys():
        invalid()
    for key, item in value.items():
        if item is None:
            continue
        expected = schema[key]
        if type(item) is not expected:
            invalid()
        if expected is str:
            _text(item)
        elif expected is list:
            for entry in item:
                _text(entry)
        elif expected is dict:
            _fields(item, TRUTH_FIELDS)


def validate_target_context(value):
    """Accept exact legacy, v2 or v3 shape without defaulting/mutating."""
    if type(value) is not dict:
        invalid()
    extra = {'context_version', 'criteria'} if 'context_version' in value else set()
    if value.get('context_version') == 3:
        extra.add('research')
    if set(value) != set(LEGACY_FIELDS) | extra:
        invalid()
    for key in LEGACY_FIELDS[:-1]:
        _text(value[key])
    if not value['opportunity_id'].strip() or len(value['opportunity_id']) > 200:
        invalid()
    if type(value['requirements']) is not list or len(value['requirements']) > 100000:
        invalid()
    for item in value['requirements']:
        _text(item)
    if extra:
        if type(value['context_version']) is not int or value['context_version'] not in (2, 3):
            invalid()
        if value['context_version'] == 3 and not validate_public_research_context(value['research']):
            invalid()
        criteria = value['criteria']
        if type(criteria) is not dict or set(criteria) != set(CRITERIA_FIELDS):
            invalid()
        for group, schema in CRITERIA_FIELDS.items():
            _fields(criteria[group], schema)
        if any(flag not in (None, 'inferred') for flag in criteria['attribution'].values()):
            invalid()
    return value


def _copy_fields(value, keys):
    if type(value) is not dict:
        invalid()
    return {key: deepcopy(value[key]) for key in keys if key in value}


def public_target_context(public):
    """Project a *redacted* full detail. No object/key outside the allowlist is copied."""
    if type(public) is not dict:
        invalid()
    eligibility = public.get('eligibility', {})
    application = public.get('application', {})
    metadata = public.get('metadata', {})
    if any(type(value) is not dict for value in (eligibility, application, metadata)):
        invalid()
    criteria = {
        'eligibility': _copy_fields(eligibility, CRITERIA_FIELDS['eligibility'].keys() - {'min_gpa_decimal'}),
        'timing': _copy_fields(public, CRITERIA_FIELDS['timing'].keys() - {'deadline_note'}),
        'application': _copy_fields(application, CRITERIA_FIELDS['application']),
        'setting': _copy_fields(public, CRITERIA_FIELDS['setting']),
        'availability': _copy_fields(public, CRITERIA_FIELDS['availability'].keys() - {'target_truth'}),
        'attribution': {},
    }
    if 'min_gpa' in eligibility:
        gpa = eligibility['min_gpa']
        if type(gpa) in (int, float):
            try:
                # The browser parses JSON numbers as binary64. JCS serializes
                # this scalar with ECMAScript's shortest representation only;
                # the established document/signature canonicalizer is unchanged.
                gpa = rfc8785.dumps(float(gpa)).decode('utf-8')
            except (ValueError, OverflowError, rfc8785.CanonicalizationError):
                invalid()
        criteria['eligibility']['min_gpa_decimal'] = gpa
    if 'deadline_note' in metadata:
        criteria['timing']['deadline_note'] = deepcopy(metadata['deadline_note'])
    if 'target_truth' in public:
        truth = public['target_truth']
        criteria['availability']['target_truth'] = None if truth is None else _copy_fields(truth, TRUTH_FIELDS)
    for field in CRITERIA_FIELDS['attribution']:
        if field in public:
            criteria['attribution'][field] = deepcopy(public[field])
        elif field in metadata:
            criteria['attribution'][field] = deepcopy(metadata[field])
    inferred = criteria['attribution'].get('skills_attribution') == 'inferred'
    target = {
        'opportunity_id': public.get('id'), 'title': public.get('title', ''),
        'organization': public.get('organization', ''),
        'source_url': public.get('source_url') if public.get('source_url') is not None else (public.get('url') or ''),
        'description': public.get('description_clean', ''),
        'requirements': [] if inferred else deepcopy(eligibility.get('skills_required') or []),
        'context_version': 3, 'criteria': criteria,
        'research': deepcopy(public.get('research_context', {'version': 1, 'status': 'unavailable', 'snapshot': None})),
    }
    validate_target_context(target)
    return target


def target_context_character_count(target):
    """Legacy value budget plus complete canonical criteria/research, Unicode codepoints."""
    count = sum(len(target[key]) for key in LEGACY_FIELDS[:-1]) + sum(map(len, target['requirements']))
    if target.get('context_version') in (2, 3):
        count += len(json.dumps(target['criteria'], ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    if target.get('context_version') == 3:
        count += len(json.dumps(target['research'], ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return count


def target_context_for_prompt(target):
    """Keep the signed snapshot intact; stale research is display-only."""
    result = deepcopy(target)
    if result.get('context_version') == 3 and result['research']['status'] != 'available':
        result['research']['snapshot'] = None
    return result
