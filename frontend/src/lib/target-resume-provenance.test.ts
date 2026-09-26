import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { createEmptyResumeMaster } from './resume-master';
import { createTargetResume, type TargetResumeV1 } from './target-resume';
import type { ExperienceEntry, ResumeFact } from './types';
import { appendTargetResumeProvenance as append, currentLineRecord, validateTargetResumeProvenance as validate,
  type TargetResumeProvenance, type TargetResumeProvenanceAnnotation, type TargetResumeProvenanceChange } from './target-resume-provenance';
const copy = <T,>(v:T):T => JSON.parse(JSON.stringify(v));
const fact = (id:string,value:string):ResumeFact => ({id,value,revision:1,status:'confirmed',source:{kind:'manual'}});
let doc:TargetResumeV1;
const section = (d=doc) => d.document.sections.find(s=>s.kind==='activities')!;
const line = (d=doc,index=0) => section(d).blocks[index].lines.find(l=>l.evidence.kind==='experience')!;
const changeText = (d:TargetResumeV1,text:string,index=0) => {const n=copy(d);line(n,index).text=text;return n;};
const path = (d=doc,index=0) => ({section_id:section(d).id,block_id:section(d).blocks[index].id,line_id:line(d,index).id,field:'text' as const});
function annotation(d=doc,index=0):TargetResumeProvenanceAnnotation {
 return {...path(d,index),reason:'Uses Python',target_evidence:[{field:'requirement',requirement_index:0,start:0,end:6,quote:'Python'}],
 source_evidence:[{unit_id:line(d,index).id,start:0,end:Array.from(line(d,index).original).length,quote:line(d,index).original}],
 check:{version:'old-rule-v1',pipeline_version:'full-target-v2',request_id:'request',document_signature:'v1:sha256:'+'a'.repeat(64),original:line(d,index).original,evidence:copy(line(d,index).evidence)}};
}
function ai(d=doc) {const after=changeText(d,'Built a Python parser.');return {after,provenance:append(null,d,after,{kind:'ai_rewrite',id:'ai',annotations:[annotation(d)]})!};}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);
 const master=createEmptyResumeMaster('master');master.basics={name:fact('name','Alex 王'),links:[]};
 const entries:ExperienceEntry[]=['Built a Python parser with tests.','Analyzed 10000 samples with Python.'].map((text,i)=>({id:'exp-'+i,revision:1,status:'confirmed',text,source:{kind:'manual'}}));
 master.activities=entries.map(e=>({id:'block-'+e.id,kind:'project',title:fact('title-'+e.id,'Project '+e.id),details:[{id:e.id,revision:1}]}));
 doc=await createTargetResume({institution:'UIUC',college:'Engineering',major:'CS',grade:'Junior',is_international:false,research_interests:'',skills:[],resume_text:'',experience_entries:entries,resume_master:master},
 {opportunity_id:'opp',title:'Lab',organization:'UIUC',source_url:'',description:'😀研究 Python',requirements:['Python'],context_version:4,lab:{version:1,status:'unavailable',snapshot:null},research:{version:1,status:'unavailable',snapshot:null},criteria:{eligibility:{},timing:{},application:{},setting:{},availability:{},attribution:{}}},'draft');
});
describe('bounded provenance records',()=>{
 it('keeps legacy unknown null without inventing an operation or check',()=>{
  expect(validate(null,doc)).toEqual({ok:true,value:null});expect(append(null,doc,copy(doc),{kind:'manual'})).toBeNull();expect(currentLineRecord(null,doc,line().id)).toBeNull();
 });
 it('binds accepted experience text to original, target and exact before/after',()=>{
  const {after,provenance}=ai();const record=currentLineRecord(provenance,after,line().id)!;
  expect(record.kind).toBe('ai_rewrite');expect(record.change).toMatchObject({before:line().original,after:'Built a Python parser.',check:{version:'old-rule-v1',original:line().original}});
  expect(provenance.base).toEqual(doc.base);expect(validate(provenance,after).ok).toBe(true);
 });
 it('preserves old/future version names and does not infer absent checks from pipeline',()=>{
  const after=changeText(doc,'Built parser tests.');const a=annotation();a.check=null;
  expect(currentLineRecord(append(null,doc,after,{kind:'ai_rewrite',annotations:[a]}),after,line().id)?.change.check).toBeNull();
  a.check=annotation().check;a.check!.version='future-unknown-version';
  expect(currentLineRecord(append(null,doc,after,{kind:'ai_rewrite',annotations:[a]}),after,line().id)?.change.check?.version).toBe('future-unknown-version');
 });
 it('merges consecutive typing but keeps a manual marker after restoring the identical AI text',()=>{
  const {after,provenance}=ai();const typed=changeText(after,'Personal edit😀');
  const first=append(provenance,after,typed,{kind:'manual',id:'manual'})!;
  const restored=append(first,typed,after,{kind:'manual',id:'unused'})!;
  expect(restored.events).toHaveLength(2);expect(restored.events[1].id).toBe('manual');
  expect(restored.events[1].changes[0].before).toBe(restored.events[1].changes[0].after);
  expect(currentLineRecord(restored,after,line().id)).toMatchObject({kind:'manual',change:{check:null}});
  expect(provenance.events).toHaveLength(1);expect(first.events[1].changes[0].after).toBe('Personal edit😀');
 });
 it('does not coalesce separate paths or cross another operation',()=>{
  const a=changeText(doc,'A');const p=append(null,doc,a,{kind:'manual',id:'one'});
  const b=changeText(a,'B',1);const q=append(p,a,b,{kind:'manual',id:'two'});
  const c=changeText(b,'C');expect(append(q,b,c,{kind:'manual',id:'three'})!.events.map(e=>e.id)).toEqual(['one','two','three']);
 });
 it('records selection and compression separately and omits unchanged/unselected items',()=>{
  const after=changeText(doc,'Built a Python parser.');section(after).blocks[1].included=false;
  const unused={...annotation(doc,1),check:null};
  const p=append(null,doc,after,{kind:'plan',annotations:[annotation(),unused]})!;
  expect(p.events[0].changes).toHaveLength(2);
  expect(p.events[0].changes.find(c=>c.field==='included')).toMatchObject({block_id:section().blocks[1].id,before:true,after:false,check:null});
  expect(currentLineRecord(p,after,line(doc,1).id)).toBeNull();
 });
 it('records top, section, and block order with exact arrays without pretending text was checked',()=>{
  const after=copy(doc);after.document.sections.reverse();section(after).blocks.reverse();section(after).blocks[0].lines.reverse();
  const p=append(null,doc,after,{kind:'target_order'})!;
  expect(p.events[0].changes).toHaveLength(3);expect(p.events[0].changes.every(c=>c.field==='order' && c.check===null)).toBe(true);
  expect(validate(p,after).ok).toBe(true);expect(currentLineRecord(p,after,line().id)).toBeNull();
 });
 it('records parent/child inclusion independently and permits manual facts without an AI check',()=>{
  const after=copy(doc);section(after).included=false;section(after).blocks[0].included=false;line(after).included=false;
  after.document.sections[0].blocks[0].lines[0].text='Name 王';
  const p=append(null,doc,after,{kind:'manual'})!;expect(p.events[0].changes).toHaveLength(4);expect(validate(p,after).ok).toBe(true);
 });
 it('keeps a restored historical record unchanged rather than upgrading versions',()=>{
  const {after,provenance}=ai();const history=copy(provenance);
  const parsed=validate(history,after);expect(parsed).toEqual({ok:true,value:provenance});
  if(parsed.ok && parsed.value)parsed.value.events[0].id='changed';expect(history).toEqual(provenance);
 });
 it('validates Unicode codepoint citations rather than UTF16 positions',()=>{
  const a=annotation();a.target_evidence=[{field:'description',requirement_index:null,start:0,end:3,quote:'😀研究'}];
  const after=changeText(doc,'Built parser tests.');expect(append(null,doc,after,{kind:'ai_rewrite',annotations:[a]})).not.toBeNull();
  a.target_evidence[0].end=4;expect(()=>append(null,doc,after,{kind:'ai_rewrite',annotations:[a]})).toThrow();
 });
 it('accepts redundant exact citations without treating them as stronger proof',()=>{
  const a=annotation();a.source_evidence.push(copy(a.source_evidence[0]));a.target_evidence.push(copy(a.target_evidence[0]));
  const after=changeText(doc,'Built parser tests.');expect(validate(append(null,doc,after,{kind:'plan',annotations:[a]}),after).ok).toBe(true);
 });
});
describe('stale, forged and malformed records',()=>{
 it.each(['document_id','opportunity_id','base'] as const)('rejects mismatched %s',key=>{
  const {after,provenance}=ai();const bad=copy(provenance);if(key==='base')bad.base.target_signature='v1:sha256:'+'f'.repeat(64);else bad[key]='other';
  expect(validate(bad,after)).toEqual({ok:false,code:'invalid'});
 });
 it('rejects stale text even when another line has the same content',()=>{
  const {after,provenance}=ai();const stale=changeText(after,'different');line(stale,1).text=line(after).text;
  expect(validate(provenance,stale).ok).toBe(false);expect(()=>currentLineRecord(provenance,stale,line().id)).toThrow();
 });
 it('replays all earlier events and refuses a disconnected history',()=>{
  const {after,provenance}=ai();const edited=changeText(after,'Manual');const p=append(provenance,after,edited,{kind:'manual'})!;
  p.events[1].changes[0].before='Unrelated';expect(validate(p,edited).ok).toBe(false);
 });
 it.each(['section_id','block_id','line_id'] as const)('rejects wrong %s rather than matching text',key=>{
  const {after,provenance}=ai();provenance.events[0].changes[0][key]='unknown';expect(validate(provenance,after).ok).toBe(false);
 });
 it.each(['root','event','change','check','evidence','quote'] as const)('rejects unknown fields at %s',level=>{
  const {after,provenance}=ai();const c=provenance.events[0].changes[0];
  const target=level==='root'?provenance:level==='event'?provenance.events[0]:level==='change'?c:level==='check'?c.check:level==='evidence'?c.check!.evidence:c.source_evidence[0];
  Object.assign(target!,{extra:undefined});expect(validate(provenance,after).ok).toBe(false);
 });
 it.each(['before','after'] as const)('rejects wrong %s type',key=>{
  const {after,provenance}=ai();provenance.events[0].changes[0][key]=false;expect(validate(provenance,after).ok).toBe(false);
 });
 it('rejects copied checks from another experience and forged original text',()=>{
  const {after,provenance}=ai();const c=provenance.events[0].changes[0];c.check!.evidence=copy(line(doc,1).evidence);
  expect(validate(provenance,after).ok).toBe(false);c.check!.evidence=copy(line().evidence);c.check!.original='Unproven';expect(validate(provenance,after).ok).toBe(false);
 });
 it('refuses cross-project source citations and changed requirement citations',()=>{
  const {after,provenance}=ai();const c=provenance.events[0].changes[0];c.source_evidence=annotation(doc,1).source_evidence;
  expect(validate(provenance,after).ok).toBe(false);c.source_evidence=[];c.target_evidence[0].quote='Other';expect(validate(provenance,after).ok).toBe(false);
 });
 it('refuses an AI check or AI text operation on protected facts',()=>{
  const after=copy(doc);after.document.sections[0].blocks[0].lines[0].text='New Name';
  expect(()=>append(null,doc,after,{kind:'ai_rewrite'})).toThrow();
 });
 it('refuses check metadata on manual/order/selection, duplicate event IDs and duplicate paths',()=>{
  const {after,provenance}=ai();const p=copy(provenance);p.events[0].kind='manual';expect(validate(p,after).ok).toBe(false);
  const duplicate=copy(provenance);duplicate.events.push(copy(duplicate.events[0]));expect(validate(duplicate,after).ok).toBe(false);
  const repeated=copy(provenance);repeated.events[0].changes.push(copy(repeated.events[0].changes[0]));expect(validate(repeated,after).ok).toBe(false);
 });
 it('refuses corrupt order arrays, no-op AI events and invalid JSON/Unicode',()=>{
  const {after,provenance}=ai();const p=copy(provenance);p.events[0].changes[0].before=p.events[0].changes[0].after;expect(validate(p,after).ok).toBe(false);
  const reordered=copy(doc);section(reordered).blocks.reverse();const q=append(null,doc,reordered,{kind:'target_order'})!;q.events[0].changes[0].before=['same','same'];expect(validate(q,reordered).ok).toBe(false);
  for(const value of [undefined,{},[],new Date(),{...provenance,events:[,]}])expect(validate(value,after).ok).toBe(false);
  for(const value of ['\0','\ud800']){const bad=copy(provenance);bad.events[0].id=value;expect(validate(bad,after).ok).toBe(false);}
 });
 it('refuses mutations to original snapshots even if a caller supplies matching sidecar base',()=>{
  const after=copy(doc);after.target_snapshot.title='Different';expect(()=>append(null,doc,after,{kind:'manual'})).toThrow();
 });
 it('snapshots records and does not mutate source documents or annotations',()=>{
  const after=changeText(doc,'Built parser tests.');const a=annotation();const before=JSON.stringify([doc,after,a]);
  const p=append(null,doc,after,{kind:'ai_rewrite',annotations:[a]})!;expect(JSON.stringify([doc,after,a])).toBe(before);
  a.check!.version='edited';line(after).text='edited';expect(p.events[0].changes[0].check!.version).toBe('old-rule-v1');expect(p.events[0].changes[0].after).toBe('Built parser tests.');
 });
});
describe('explicit capacity failures',()=>{
 it('rejects UTF8 overflow without truncating input or old record',()=>{
  const after=changeText(doc,'王'.repeat(90000));const original=JSON.stringify(after);
  expect(()=>append(null,doc,after,{kind:'manual'})).toThrow(expect.objectContaining({code:'too_large'}));expect(JSON.stringify(after)).toBe(original);
 });
 it('allows 512 events, rejects 513 and still permits same-path manual coalescing',()=>{
  const after=changeText(doc,'512');const template=append(null,doc,changeText(doc,'1'),{kind:'manual',id:'event-1'})!;
  template.events=Array.from({length:512},(_,i)=>({id:'event-'+(i+1),kind:'manual',changes:[{...copy(template.events[0].changes[0]),before:i===0?line().text:String(i),after:String(i+1)}]}));
  expect(validate(template,after).ok).toBe(true);
  const next=changeText(after,'513');expect(append(template,after,next,{kind:'manual'})!.events).toHaveLength(512);
  const overflow=copy(template);overflow.events.push({id:'513',kind:'manual',changes:[{...copy(template.events[0].changes[0]),before:'512',after:'513'}]});
  expect(validate(overflow,next)).toEqual({ok:false,code:'too_large'});
 });
 it('rejects 1025 changes before replaying a partial event',()=>{
  const {after,provenance}=ai();const c=copy(provenance.events[0].changes[0]);provenance.events[0].changes=Array.from({length:1025},()=>copy(c));
  expect(validate(provenance,after)).toEqual({ok:false,code:'too_large'});
 });
});
