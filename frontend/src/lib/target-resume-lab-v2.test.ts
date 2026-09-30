import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest';
import {webcrypto} from 'node:crypto';
import lab from '../../../tests/fixtures/lab-context-v2-golden.json';
import legacy from '../../../tests/fixtures/target-resume-context-v4-golden.json';
import type {LabContext,LabSnapshotV2} from './lab-context';
import {targetResumeContextSignature,validateTargetResume,verifyTargetResumeSignatures,type TargetResumeContextV4,type TargetResumeV1} from './target-resume';
import {prepareTargetResumeAI} from './target-resume-ai';
import {prepareTargetResumeExport} from './target-resume-export';
import {isTargetResumeEvidence} from './target-resume-evidence';
import {appendTargetResumeProvenance,validateTargetResumeProvenance} from './target-resume-provenance';
const copy=<T,>(x:T):T=>structuredClone(x);
async function document(){const d=copy(legacy.draft) as TargetResumeV1;const t=d.target_snapshot as TargetResumeContextV4;t.lab=copy(lab) as LabContext;d.base.target_signature=await targetResumeContextSignature(t);return d;}
const snapshot=(d:TargetResumeV1)=>(d.target_snapshot as TargetResumeContextV4).lab.snapshot as LabSnapshotV2;
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
describe('V2 source chain in existing V4 resume/provenance contracts',()=>{
 it('keeps V1 historical documents unchanged while V2 validates and prepares without a context bump',async()=>{
  const old=copy(legacy.draft) as TargetResumeV1;expect(validateTargetResume(old).ok).toBe(true);expect(await verifyTargetResumeSignatures(old)).toBe(true);
  const d=await document();expect(validateTargetResume(d).ok).toBe(true);expect(await verifyTargetResumeSignatures(d)).toBe(true);
  const prepared=await prepareTargetResumeAI(d);expect(prepared.ok).toBe(true);if(prepared.ok)expect(prepared.value.batches.length).toBeGreaterThan(0);
  expect((old.target_snapshot as TargetResumeContextV4).lab.snapshot!.version).toBe(1);expect(snapshot(d).version).toBe(2);
 });
 it.each(['body_sha256','raw_href','role_text','last_section'] as const)('binds %s changes into the full target signature',async field=>{
  const d=await document(),s=snapshot(d);const previous=d.base.target_signature;
  if(field==='body_sha256')s.source_chain.documents[1].body_sha256='b'.repeat(64);
  else if(field==='raw_href')s.source_chain.links[0].raw_href=s.source_chain.links[0].to_url;
  else if(field==='role_text')s.source_chain.identity.role_text+=' Explicit additional role.';
  else s.pages[1].sections[9].text+=' Source revision.';
  expect(await targetResumeContextSignature(d.target_snapshot)).not.toBe(previous);expect(await verifyTargetResumeSignatures(d)).toBe(false);
 });
 it('accepts an exact second-page last-section quote and refuses stale/wrong page/UTF16 offsets',async()=>{
  const d=await document(),t=d.target_snapshot as TargetResumeContextV4,s=snapshot(d);s.pages[1].sections[9].text='第十节😀原文';
  const q={field:'lab_text',page_index:1,section_index:9,start:0,end:6,quote:'第十节😀原文'};
  expect(isTargetResumeEvidence(t,q)).toBe(true);expect(isTargetResumeEvidence(t,{...q,end:7})).toBe(false);
  expect(isTargetResumeEvidence(t,{...q,page_index:0})).toBe(false);t.lab.status='stale';expect(isTargetResumeEvidence(t,q)).toBe(false);
 });
 it('counts complete chain metadata as well as both content pages toward the unchanged target budget',async()=>{
  const d=await document(),s=snapshot(d);s.pages[0].sections=[{section_id:'s1',heading:'',text:'x'}];
  s.pages[1].sections=Array.from({length:6},(_,i)=>({section_id:`s${i+1}`,heading:'',text:'字'.repeat(i===0?3999:4000)}));
  d.base.target_signature=await targetResumeContextSignature(d.target_snapshot);const p=await prepareTargetResumeAI(d);expect(p.ok).toBe(true);
  if(p.ok){expect(p.value.batches).toEqual([]);expect(p.value.skipped.every(x=>x.reason_code==='target_too_large')).toBe(true);}
  expect(snapshot(d).source_chain).toEqual(s.source_chain);expect(snapshot(d).pages[1].sections).toHaveLength(6);
 });
 it('retains a V3 provenance history with exact page-two quote and does not export sources or chain metadata',async()=>{
  const d=await document(),after=copy(d),section=after.document.sections.find(x=>x.kind==='activities')!,block=section.blocks[0],line=block.lines.find(x=>x.evidence.kind==='experience')!;
  line.text='I did not lead the team.';const text=snapshot(after).pages[1].sections[9].text;
  const q={field:'lab_text' as const,page_index:1,section_index:9,start:0,end:Array.from(text).length,quote:text};
  const p=appendTargetResumeProvenance(null,d,after,{kind:'ai_rewrite',id:'chain-edit',annotations:[{section_id:section.id,block_id:block.id,line_id:line.id,field:'text',reason:'Lab research relevance only',target_evidence:[q],source_evidence:[],check:null}]})!;
  expect(p.version).toBe(3);expect(validateTargetResumeProvenance(copy(p),copy(after))).toEqual({ok:true,value:p});
  expect(snapshot(after)).toEqual(snapshot(d));
  for(const locale of ['en','zh'] as const){const e=await prepareTargetResumeExport(after,{locale,page_size:'letter'});expect(e.ok).toBe(true);if(e.ok){const payload=JSON.stringify(e.value.projection);expect(payload).not.toMatch(/source_chain|nielsen-lab|Rasmus Nielsen|TENTH_SECTION_MARKER/);expect(payload).toContain('I did not lead the team.');}}
 });
});
