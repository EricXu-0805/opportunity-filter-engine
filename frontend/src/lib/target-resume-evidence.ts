import type { TargetResumeContext } from './target-resume';
import type { TargetResumeAiEvidence } from './target-resume-ai-protocol';

/** Exact source and codepoint range; this does not establish semantic relevance. */
export function isTargetResumeEvidence(target: TargetResumeContext, value: unknown, allowPapers = true, allowLab = true): value is TargetResumeAiEvidence {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const e = value as Record<string, unknown>;
  const paper = e.field === 'paper_title' || e.field === 'paper_abstract';
  const lab = e.field === 'lab_heading' || e.field === 'lab_text';
  const keys = ['field', ...(lab ? ['page_index', 'section_index'] : [paper ? 'paper_index' : 'requirement_index']), 'start', 'end', 'quote'];
  if (Object.keys(e).length !== keys.length || keys.some(k => !Object.hasOwn(e, k))) return false;
  let source: string;
  if (paper) {
    if (!allowPapers || !('context_version' in target) || (target.context_version !== 3 && target.context_version !== 4) || target.research.status !== 'available') return false;
    const works = target.research.snapshot!.works;
    if (!Number.isSafeInteger(e.paper_index) || (e.paper_index as number) < 0 || (e.paper_index as number) >= works.length) return false;
    const work = works[e.paper_index as number];
    if (e.field === 'paper_abstract' && (work.abstract_status !== 'present' || work.abstract === null)) return false;
    source = e.field === 'paper_title' ? work.title : work.abstract!;
  } else if (lab) {
    if (!allowLab || !('context_version' in target) || target.context_version !== 4 || target.lab.status !== 'available') return false;
    const pages = target.lab.snapshot!.pages;
    if (!Number.isSafeInteger(e.page_index) || (e.page_index as number) < 0 || (e.page_index as number) >= pages.length) return false;
    const sections = pages[e.page_index as number].sections;
    if (!Number.isSafeInteger(e.section_index) || (e.section_index as number) < 0 || (e.section_index as number) >= sections.length) return false;
    const section = sections[e.section_index as number];
    source = e.field === 'lab_heading' ? section.heading : section.text;
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
  if (evidence.field === 'lab_heading' || evidence.field === 'lab_text') return zh
    ? `官网第 ${evidence.page_index + 1} 页，第 ${evidence.section_index + 1} 节${evidence.field === 'lab_heading' ? '标题' : '正文'}`
    : `Official page ${evidence.page_index + 1}, section ${evidence.section_index + 1} ${evidence.field === 'lab_heading' ? 'heading' : 'text'}`;
  return zh ? '机会引用' : 'Opportunity citation';
}
