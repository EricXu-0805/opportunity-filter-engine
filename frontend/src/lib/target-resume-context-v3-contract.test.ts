import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/target-resume-context-v3-golden.json';
import v2 from '../../../tests/fixtures/target-resume-context-v2-golden.json';
import { parseResearchContext } from './research-context';
import { hasTargetResumeCriteria, targetResumeContextFromOpportunity, targetResumeContextSignature, validateTargetResume, verifyTargetResumeSignatures, type TargetResumeContextV3, type TargetResumeV1 } from './target-resume';
import { prepareTargetResumeAI } from './target-resume-ai';
import { prepareTargetResumeExport } from './target-resume-export';
import { isTargetResumeEvidence } from './target-resume-evidence';
import { appendTargetResumeProvenance, validateTargetResumeProvenance } from './target-resume-provenance';
import type { Opportunity } from './types';
const clone = <T,>(v:T):T => JSON.parse(JSON.stringify(v));
const doc = () => clone(golden.draft) as TargetResumeV1;
const target = () => clone(golden.draft.target_snapshot) as TargetResumeContextV3;
const paper = {field:'paper_title',paper_index:0,start:0,end:6,quote:'机器人😀研究'};
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));
afterEach(()=>vi.unstubAllGlobals());
describe('V3 shared research context contract',()=>{
 it('matches cross-language signed complete snapshot and whole document without mutating public data',async()=>{
  expect(parseResearchContext(golden.draft.target_snapshot.research)).not.toBeNull();
  const input=clone(golden.public_opportunity) as unknown as Opportunity;const before=clone(input);
  const { lab: _lab, ...projected } = targetResumeContextFromOpportunity(input); void _lab;
  expect({ ...projected, context_version: 3 }).toEqual(golden.draft.target_snapshot);expect(input).toEqual(before);
  expect(validateTargetResume(doc())).toEqual({ok:true,value:golden.draft});
  expect(await targetResumeContextSignature(target())).toBe(golden.draft.base.target_signature);
  expect(await verifyTargetResumeSignatures(doc())).toBe(true);
  expect(await prepareTargetResumeAI(doc())).toEqual({ok:false,code:'legacy_target_context'});
 });
 it('keeps V2 signatures, criteria display and export valid while requiring V4 for new AI',async()=>{
  const legacy=clone(v2.draft) as TargetResumeV1;expect(hasTargetResumeCriteria(legacy.target_snapshot)).toBe(true);
  expect(validateTargetResume(legacy).ok).toBe(true);expect(await verifyTargetResumeSignatures(legacy)).toBe(true);
  expect(await prepareTargetResumeAI(legacy)).toEqual({ok:false,code:'legacy_target_context'});
  expect((await prepareTargetResumeExport(legacy,{locale:'en',page_size:'letter'})).ok).toBe(true);
  expect(legacy).toEqual(v2.draft);
 });
 it.each(['title','abstract','checked_at','status','author_id','order'] as const)('binds research %s to the target signature',async field=>{
  const t=target();const snap=t.research.snapshot!;
  if(field==='title'||field==='abstract')snap.works[0][field]+=' Changed';
  else if(field==='checked_at')snap.checked_at='2026-09-25T12:00:00Z';
  else if(field==='status')t.research.status='stale';
  else if(field==='author_id')snap.author_id='https://openalex.org/A124';
  else snap.works.reverse();
  expect(await targetResumeContextSignature(t)).not.toBe(golden.draft.base.target_signature);
 });
 it('quotes exact Unicode codepoints in available title and abstract',()=>{
  expect(isTargetResumeEvidence(target(),paper)).toBe(true);
  expect(isTargetResumeEvidence(target(),{field:'paper_abstract',paper_index:0,start:25,end:28,quote:'研究😀'})).toBe(true);
 });
 it.each([
  {...paper,paper_index:1}, {...paper,paper_index:-1}, {...paper,paper_index:0.5}, {...paper,end:7}, {...paper,start:1},
  {...paper,requirement_index:null}, {...paper,field:'paper_abstract',paper_index:1}, {...paper,quote:'invented'},
 ])('rejects malformed/misbound citation %j',e=>expect(isTargetResumeEvidence(target(),e)).toBe(false));
 it.each(['stale','unavailable'] as const)('cannot quote %s research or silently use legacy fields',status=>{
  const t=target();t.research.status=status;if(status==='unavailable')t.research.snapshot=null;
  expect(isTargetResumeEvidence(t,paper)).toBe(false);
  expect(isTargetResumeEvidence(t,{field:'requirement',requirement_index:0,start:0,end:6,quote:'Python'})).toBe(true);
 });
 it('atomically records paper provenance as v2; v1 cannot claim it and old v1 stays append-compatible',()=>{
  const before=doc(), after=clone(before);const section=after.document.sections.find(s=>s.blocks.some(b=>b.lines.some(l=>l.evidence.kind==='experience')))!;
  const block=section.blocks.find(b=>b.lines.some(l=>l.evidence.kind==='experience'))!;const line=block.lines.find(l=>l.evidence.kind==='experience')!;
  line.text='I did not lead the team.';
  const p=appendTargetResumeProvenance(null,before,after,{kind:'ai_rewrite',id:'paper-edit',annotations:[{section_id:section.id,block_id:block.id,line_id:line.id,field:'text',reason:'Related research',target_evidence:[paper as never],source_evidence:[],check:null}]})!;
  expect(p.version).toBe(2);expect(validateTargetResumeProvenance(p,after).ok).toBe(true);
  expect(validateTargetResumeProvenance({...p,version:1},after).ok).toBe(false);
  const manual=appendTargetResumeProvenance(null,before,after,{kind:'manual',id:'manual'})!;
  const old={...manual,version:1 as const};expect(validateTargetResumeProvenance(old,after).ok).toBe(true);
  const edited=clone(after);edited.document.sections.find(s=>s.id===section.id)!.blocks.find(b=>b.id===block.id)!.lines.find(l=>l.id===line.id)!.text='Manual draft';
  expect(appendTargetResumeProvenance(old,after,edited,{kind:'manual'})?.version).toBe(2);
  expect(old.version).toBe(1);
 });
});
