"""Reserve room for complete suggestion rows, including confirmed supplements.

This is a conservative length estimate, not a provider tokenizer or a guarantee
against truncation. Complete-response and rewrite-review checks still apply.
"""
from __future__ import annotations

import json

OUTPUT_BUDGET_POLICY = {
    'max_tokens': 16000,
    'envelope_tokens': 350,
    'fact_tokens': 120,
    'experience_floor_tokens': 320,
    'experience_metadata_tokens': 200,
    'ascii_weight': 1,
    'non_ascii_weight': 2,
    'expansion_percent': 120,
}


def suggestion_output_tokens(units):
    """Uncapped estimate: callers split an oversized combination before dispatch.

    Inputs are server-validated units. A supporting line shared by two rewrites
    is counted twice: it can appear in both outputs, even though input admission
    deduplicates that source. Protected facts never emit replacement wording.
    """
    policy = OUTPUT_BUDGET_POLICY
    total = policy['envelope_tokens']
    for unit in units:
        if unit['evidence']['kind'] != 'experience':
            total += policy['fact_tokens']
            continue
        weight = sum(
            policy['ascii_weight'] if char.isascii() else policy['non_ascii_weight']
            for source in [unit, *unit.get('support_sources', [])]
            for char in json.dumps(source['original'], ensure_ascii=False)
        )
        wording = (weight * policy['expansion_percent'] + 99) // 100
        total += max(policy['experience_floor_tokens'], policy['experience_metadata_tokens'] + wording)
    return total


def output_budget_fits(units):
    return suggestion_output_tokens(units) <= OUTPUT_BUDGET_POLICY['max_tokens']
