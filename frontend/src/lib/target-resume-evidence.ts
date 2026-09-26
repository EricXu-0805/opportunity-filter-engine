import type { TargetResumeContext } from './target-resume';
import type { TargetResumeAiEvidence } from './target-resume-ai-protocol';

/** Exact source and codepoint range; this does not establish semantic relevance. */
export function isTargetResumeEvidence(target: TargetResumeContext, value: unknown, allowPapers = true): value is TargetResumeAiEvidence {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const e = value as Record<string, unknown>;
  const paper = e.field === 'paper_title' || e.field === 'paper_abstract';
  const keys = ['field', paper ? 'paper_index' : 'requirement_index', 'start', 'end', 'quote'];
  if (Object.keys(e).length !== keys.length || keys.some(k => !Object.hasOwn(e, k))) return false;
  let source: string;
  if (paper) {
    if (!allowPapers || !('context_version' in target) || target.context_version !== 3 || target.research.status !== 'available') return false;
    const works = target.research.snapshot!.works;
    if (!Number.isSafeInteger(e.paper_index) || (e.paper_index as number) < 0 || (e.paper_index as number) >= works.length) return false;
    const work = works[e.paper_index as number];
    if (e.field === 'paper_abstract' && (work.abstract_status !== 'present' || work.abstract === null)) return false;
    source = e.field === 'paper_title' ? work.title : work.abstract!;
  } else if (e.field === 'description' && e.requirement_index === null) source = target.description;
  else if (e.field === 'requirement' && Number.isSafeInteger(e.requirement_index)
    && (e.requirement_index as number) >= 0 && (e.requirement_index as number) < target.requirements.length) source = target.requirements[e.requirement_index as number];
  else return false;
  return typeof e.quote === 'string' && !!e.quote.trim() && Number.isSafeInteger(e.start) && Number.isSafeInteger(e.end)
    && (e.start as number) >= 0 && (e.end as number) > (e.start as number) && (e.end as number) <= Array.from(source).length
    && Array.from(source).slice(e.start as number, e.end as number).join('') === e.quote;
}
export function targetResumeEvidenceLabel(evidence: TargetResumeAiEvidence, locale: string): string {
  const zh = locale === 'zh';
  if (evidence.field === 'paper_title') return zh ? `论文 ${evidence.paper_index + 1} 标题` : `Paper ${evidence.paper_index + 1} title`;
  if (evidence.field === 'paper_abstract') return zh ? `论文 ${evidence.paper_index + 1} 摘要` : `Paper ${evidence.paper_index + 1} abstract`;
  return zh ? '机会引用' : 'Opportunity citation';
}
