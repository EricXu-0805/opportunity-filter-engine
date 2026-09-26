import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/target-resume-context-v4-golden.json';
import old3 from '../../../tests/fixtures/target-resume-context-v3-golden.json';
import old2 from '../../../tests/fixtures/target-resume-context-v2-golden.json';
import old1 from '../../../tests/fixtures/target-resume-ai-golden.json';
import { targetResumeContextFromOpportunity, targetResumeContextSignature, validateTargetResume,
  verifyTargetResumeSignatures, type TargetResumeContextV4, type TargetResumeV1 } from './target-resume';
import { prepareTargetResumeAI } from './target-resume-ai';
import { prepareTargetResumeExport } from './target-resume-export';
import { isTargetResumeEvidence, targetResumeEvidenceLabel } from './target-resume-evidence';
import { appendTargetResumeProvenance, validateTargetResumeProvenance } from './target-resume-provenance';
import type { Opportunity } from './types';
const clone = <T,>(value:T):T => JSON.parse(JSON.stringify(value));
const doc = () => clone(golden.draft) as TargetResumeV1;
const target = () => clone(golden.draft.target_snapshot) as TargetResumeContextV4;
const quote = {field:'lab_heading' as const,page_index:0,section_index:0,start:0,end:6,quote:'实验室😀研究'};
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));
afterEach(()=>vi.unstubAllGlobals());
describe('V4 official website context',()=>{
 it('shares canonical complete target/document with Python without mutating input',async()=>{
  const source=clone(golden.public_opportunity) as unknown as Opportunity;const before=clone(source);
  expect(targetResumeContextFromOpportunity(source)).toEqual(golden.draft.target_snapshot);expect(source).toEqual(before);
  expect(validateTargetResume(doc())).toEqual({ok:true,value:golden.draft});
  expect(await targetResumeContextSignature(target())).toBe(golden.draft.base.target_signature);
  expect(await verifyTargetResumeSignatures(doc())).toBe(true);
  const prepared=await prepareTargetResumeAI(doc());expect(prepared.ok).toBe(true);
  if(prepared.ok){expect(prepared.value.document_signature).toBe(golden.document_signature);expect(prepared.value.units).toEqual(golden.units);}
 });
 it.each([old1,old2,old3])('keeps an old context byte-compatible for editing/export; new AI requires V4',async old=>{
  const d=clone(old.draft) as TargetResumeV1;const original=clone(d.target_snapshot);
  expect(validateTargetResume(d).ok).toBe(true);expect(await verifyTargetResumeSignatures(d)).toBe(true);
  d.document.sections[0].blocks[0].lines[0].text='Historical manual edit';
  expect((await prepareTargetResumeExport(d,{locale:'en',page_size:'letter'})).ok).toBe(true);
  expect(await prepareTargetResumeAI(d)).toEqual({ok:false,code:'legacy_target_context'});
  expect(d.target_snapshot).toEqual(original);
 });
 it.each(['text','heading','checked_at','status','identity','page_url','section_order'] as const)('binds %s to the target signature',async field=>{
  const t=target(),snapshot=t.lab.snapshot!;
  if(field==='text'||field==='heading')snapshot.pages[0].sections[0][field]+=' Changed';
  else if(field==='checked_at')snapshot.checked_at='2026-09-25T12:00:00Z';
  else if(field==='status')t.lab.status='stale';
  else if(field==='identity'){snapshot.identity_name='Other Person';snapshot.pages[0].identity_text='Other Person';}
  else if(field==='page_url'){snapshot.record_source_url='https://statistics.berkeley.edu/people/other-person';snapshot.pages[0].source_url=snapshot.record_source_url;snapshot.pages[0].requested_url=snapshot.record_source_url;}
  else {snapshot.pages[0].sections.reverse();snapshot.pages[0].sections.forEach((s,i)=>s.section_id=`s${i+1}`);}
  expect(await targetResumeContextSignature(t)).not.toBe(golden.draft.base.target_signature);
 });
 it('uses exact Unicode offsets, explicit labels and independent page/section location',()=>{
  expect(isTargetResumeEvidence(target(),quote)).toBe(true);
  expect(isTargetResumeEvidence(target(),{...quote,field:'lab_text',start:25,end:31,quote:'实验室方法😀'})).toBe(true);
  expect(targetResumeEvidenceLabel(quote,'en')).toBe('Official page 1, section 1 heading');
  expect(targetResumeEvidenceLabel(quote,'zh')).toBe('官网第 1 页，第 1 节标题');
 });
 it.each([{...quote,page_index:1},{...quote,section_index:1},{...quote,section_index:-1},{...quote,page_index:0.5},
  {...quote,start:1},{...quote,end:7},{...quote,quote:'wrong'},{...quote,paper_index:0},{...quote,requirement_index:null},
  {...quote,field:'lab_url'},{...quote,start:true}])('refuses malformed/misbound website quotes %j',q=>expect(isTargetResumeEvidence(target(),q)).toBe(false));
 it.each(['stale','unavailable'] as const)('cannot cite %s website material',status=>{
  const t=target();t.lab.status=status;if(status==='unavailable')t.lab.snapshot=null;
  expect(isTargetResumeEvidence(t,quote)).toBe(false);
 });
 it('counts all website sections toward the unchanged target limit',async()=>{
  const d=doc(),t=d.target_snapshot as TargetResumeContextV4;
  t.lab.snapshot!.pages[0].sections=Array.from({length:6},(_,i)=>({section_id:`s${i+1}`,heading:'',text:'字'.repeat(4000)}));
  d.base.target_signature=await targetResumeContextSignature(t);
  const prepared=await prepareTargetResumeAI(d);expect(prepared.ok).toBe(true);
  if(prepared.ok){expect(prepared.value.batches).toEqual([]);expect(prepared.value.skipped.every(s=>s.reason_code==='target_too_large')).toBe(true);}
  expect(t.lab.snapshot!.pages[0].sections).toHaveLength(6);
 });
 it('records accepted website citations only in V3 provenance and preserves historical check versions',()=>{
  const before=doc(),after=clone(before);const section=after.document.sections.find(s=>s.kind==='activities')!;
  const block=section.blocks[0],line=block.lines.find(l=>l.evidence.kind==='experience')!;line.text='I did not lead the team.';
  const p=appendTargetResumeProvenance(null,before,after,{kind:'ai_rewrite',id:'website-edit',annotations:[{section_id:section.id,block_id:block.id,line_id:line.id,field:'text',reason:'Website relevance',target_evidence:[quote],source_evidence:[],check:{version:'target-resume-source-checks-v1',pipeline_version:'historic-pipeline',request_id:'historic-request',document_signature:golden.document_signature,original:line.original,evidence:line.evidence}}]})!;
  expect(p.version).toBe(3);expect(validateTargetResumeProvenance(p,after).ok).toBe(true);
  expect(p.events[0].changes[0].check?.version).toBe('target-resume-source-checks-v1');
  expect(validateTargetResumeProvenance({...p,version:1},after).ok).toBe(false);
  expect(validateTargetResumeProvenance({...p,version:2},after).ok).toBe(false);
  const mixed=clone(after);mixed.target_snapshot=clone(old3.draft.target_snapshot) as TargetResumeV1['target_snapshot'];
  expect(validateTargetResumeProvenance(p,mixed).ok).toBe(false);
 });
 it('exports selected student text without website, source metadata or provenance',async()=>{
  const result=await prepareTargetResumeExport(doc(),{locale:'zh',page_size:'letter'});expect(result.ok).toBe(true);
  if(result.ok){const text=JSON.stringify(result.value.projection);expect(text).not.toMatch(/lab_context|snapshot_version|official_website|We study Python sensors|实验室方法/);expect(text).toContain('My manual draft edit is not evidence.');}
 });
});
