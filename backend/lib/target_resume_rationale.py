"""Advice categories plus exact evidence, never free-form accomplishment claims.

The model chooses a recommendation and sources; relevance remains an opinion.
We render the explanation ourselves, rather than try to certify arbitrary prose
with a keyword filter. Unknown legacy prose falls back to a source comparison.
"""
import json

REASON_TYPES = ('method_relevance', 'topic_relevance', 'transferable_experience', 'supporting_context',
                'space_tradeoff', 'limited_relevance', 'review_sources')
REASON_PROMPT = '''For reason return ONLY one category: method_relevance (review methods against target),
topic_relevance (review research direction), transferable_experience (review transfer to target),
supporting_context (retain useful background), space_tradeoff (reduce length toward page goal),
limited_relevance (consider lower emphasis), or review_sources (manual comparison needed).
Do not write free-form claims about student achievements in reason. The server will explain the
recommendation using this category and exact student/target quotations. This is advice, not proven fit.
'''


# Why-lines for an evidence-mapped suggestion. A link reads as a match only when
# the faithfulness review confirmed it; otherwise the target quote above it is
# shown as the opportunity's own words, with no claim about the student's line.
_WHY = {
    'en': {
        'match': 'Matches the opportunity\'s {term} (your words: {source}).',
        'lead_with': 'Leads with the matching part.', 'relabel': 'Uses the opportunity\'s term.',
        'verb_first': 'Starts with your own verb.', 'personal_first': 'Puts your own part first.',
        'tighten': 'Drops a repeated word.',
        'no_link': 'No change recommended: nothing in this line matches what the opportunity lists.',
        'already_aligned': 'No change recommended: this line already uses the opportunity\'s wording.',
        'no_safe_change': 'No change recommended: related wording found, but no change the checks could verify.',
        'cosmetic_only': 'No change recommended: the only possible edits were cosmetic.',
        'beyond_allowed_edit': 'Kept your wording: the suggested edit went beyond the allowed changes.',
        'rewrite_rejected': 'Kept your wording: the suggestion did not pass the fact check.',
        'review_rejected': 'Kept your wording: the suggestion did not pass the fact check.',
        'no_change': 'No change suggested.',
    },
    'zh': {
        'match': '与机会中的{term}对应（你的原文：{source}）。',
        'lead_with': '把相关内容放在最前。', 'relabel': '改用机会中的术语。',
        'verb_first': '以你原有的动词开头。', 'personal_first': '先写你本人负责的部分。',
        'tighten': '删去重复的词。',
        'no_link': '建议保留原文：这一条与机会列出的内容没有对应。',
        'already_aligned': '建议保留原文：这一条已使用机会中的表述。',
        'no_safe_change': '建议保留原文：找到了相关表述，但没有能通过核对的改法。',
        'cosmetic_only': '建议保留原文：可做的修改只是措辞上的。',
        'beyond_allowed_edit': '保留你的表述：建议的修改超出了允许的范围。',
        'rewrite_rejected': '保留你的表述：建议未通过事实核对。',
        'review_rejected': '保留你的表述：建议未通过事实核对。',
        'no_change': '建议保留原文。',
    },
}


def why_lines(links=(), ops=(), keep_code=None, locale='en'):
    """Server-rendered why-lines: confirmed matches, the operations used, the keep reason."""
    table = _WHY['zh' if locale == 'zh' else 'en']
    rows = [table['match'].format(term=json.dumps(link['target_evidence']['quote'], ensure_ascii=False),
                                  source=json.dumps(link['source_evidence']['quote'], ensure_ascii=False))
            for link in links if link.get('entailed') is True]
    rows += [table[op] for op in ops if op in table]
    if keep_code in table:
        rows.append(table[keep_code])
    return rows


def render_reason(value, recommendation, source_quotes, target_quotes, locale='en', *, links=(), ops=(),
                  keep_code=None):
    code = value if value in REASON_TYPES else 'review_sources'
    if locale == 'zh':
        action = {'keep': '建议保留', 'compress': '建议压缩', 'omit': '建议省略',
                  'high': '建议优先考虑', 'normal': '建议正常考虑', 'low': '建议降低优先级'}[recommendation]
        motive = {
            'method_relevance': '比较所述方法与目标需要的关联。',
            'topic_relevance': '比较所述研究主题与目标方向。',
            'transferable_experience': '判断这段经历是否能支持目标工作。',
            'supporting_context': '保留理解这段经历所需的背景。',
            'space_tradeoff': '为目标页数减少篇幅，同时保留有依据的内容。',
            'limited_relevance': '依据下列原文核对是否需要降低这部分篇幅。',
            'review_sources': '请对照学生材料与目标原文，再决定是否采用。',
        }[code]
        labels = ('学生原文', '目标原文')
    else:
        action = {'keep': 'Keep suggestion', 'compress': 'Compress suggestion', 'omit': 'Omit suggestion',
                  'high': 'Higher-priority suggestion', 'normal': 'Normal-priority suggestion', 'low': 'Lower-priority suggestion'}[recommendation]
        motive = {
            'method_relevance': 'Compare the stated methods with the target requirements.',
            'topic_relevance': 'Compare the research topic with the target direction.',
            'transferable_experience': 'Review whether this experience can support the target work.',
            'supporting_context': 'Retain background needed to understand this experience.',
            'space_tradeoff': 'Reduce length toward the page goal while retaining supported content.',
            'limited_relevance': 'Review the cited material before giving this block less space.',
            'review_sources': 'Compare the student and target originals before accepting this advice.',
        }[code]
        labels = ('Student original', 'Target original')
    rows = [f'{action}: {motive}']
    for label, quotes in zip(labels, (source_quotes, target_quotes), strict=True):
        rows.extend(f'{label}: {json.dumps(quote["quote"], ensure_ascii=False)}' for quote in quotes)
    rows += why_lines(links, ops, keep_code, locale)
    return '\n'.join(rows)
