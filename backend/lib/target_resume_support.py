"""Resolve only explicitly reviewed, same-activity source lines from a valid doc.

Document signatures bind the submitted snapshot, not current cloud ownership.
The caller must still retire stale profile/document/group selections before apply.
"""
from copy import deepcopy

from backend.lib.target_resume_ai_validation import fail


def support_groups_wire(request):
    groups = getattr(request, 'support_groups', None)
    return None if groups is None else [group.model_dump() if hasattr(group, 'model_dump') else deepcopy(group) for group in groups]


def support_echo(request):
    groups = support_groups_wire(request)
    return {} if groups is None else {'support_groups': groups}


def resolve_support_groups(doc, request, selected_ids=None):
    groups = support_groups_wire(request)
    lookup = {}
    for section in doc['document']['sections']:
        for block in section['blocks']:
            for line in block['lines']:
                lookup[line['id']] = (section, block, line)
    associations = {}
    master = doc['base_snapshot']['resume_master']
    for kind in ('activities', 'education', 'publications'):
        for record in master[kind]:
            for ref in record['details']:
                associations[ref['id']] = associations.get(ref['id'], 0) + 1
    result = {}
    for group in groups or []:
        ident, refs = group['unit_id'], group['support_unit_ids']
        if group['confirmed'] is not True or ident in result or ident not in lookup or (selected_ids is not None and ident not in selected_ids):
            fail('invalid_support_group')
        section, block, line = lookup[ident]
        if (section['kind'] != 'activities' or line['evidence']['kind'] != 'experience'
            or associations.get(line['evidence']['id']) != 1 or ident in refs or len(set(refs)) != len(refs)):
            fail('invalid_support_group')
        sources = []
        for ref in refs:
            if ref not in lookup:
                fail('invalid_support_group')
            source_section, source_block, source = lookup[ref]
            if source_section['id'] != section['id'] or source_block['id'] != block['id'] or source['evidence']['kind'] != 'experience' or associations.get(source['evidence']['id']) != 1:
                fail('invalid_support_group')
            sources.append({'unit_id': source['id'], 'evidence': deepcopy(source['evidence']), 'original': source['original']})
        result[ident] = sources
    return result


def complete_source_quotes(unit):
    return [{'unit_id': item['unit_id'], 'start': 0, 'end': len(item['original']), 'quote': item['original']}
            for item in [unit, *unit.get('support_sources', [])]]


def source_originals(unit):
    return [unit['original'], *[source['original'] for source in unit.get('support_sources', [])]]
