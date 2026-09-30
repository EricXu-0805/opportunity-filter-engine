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


def render_reason(value, recommendation, source_quotes, target_quotes, locale='en'):
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
    return '\n'.join(rows)
