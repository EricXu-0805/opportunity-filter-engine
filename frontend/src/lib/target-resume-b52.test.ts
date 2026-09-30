import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createEmptyResumeMaster } from './resume-master';
import { sourceDigest } from './experience-evidence';
import { prepareExperienceAssignment, unassignedConfirmedExperiences } from './resume-experience-assignment';
import { createTargetResume, validateTargetResume, type TargetResumeV1 } from './target-resume';
import { parseTargetResumeSupportGroups, targetResumeSupportActivities, targetResumeSupportEvidence, type TargetResumeSupportGroup } from './target-resume-support';
import { prepareTargetResumeAI, validateTargetResumeAIResponse, applyTargetResumeAI } from './target-resume-ai';
import { prepareTargetResumePlan, validateTargetResumePlanResponse, applyTargetResumePlan } from './target-resume-plan';
import { appendTargetResumeProvenance, validateTargetResumeProvenance } from './target-resume-provenance';
import { prepareTargetResumeExport } from './target-resume-export';
import type { PreparedTargetResumeAi, TargetResumeAiResponse } from './target-resume-ai-protocol';
import type { TargetResumePlanResponse } from './target-resume-plan-protocol';
import type { ExperienceEntry, ProfileData, ResumeFact } from './types';
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
const fact=(id:string,value:string):ResumeFact=>({id,value,revision:1,status:'confirmed',source:{kind:'manual'}});
const entry=(id:string,text:string):ExperienceEntry=>({id,text,revision:1,status:'confirmed',source:{kind:'manual'}});
function profile():ProfileData {
 const master=createEmptyResumeMaster('b52-master');master.basics.name=fact('name','Alex 王');
 master.activities=[{id:'robot',kind:'research',title:fact('title','Robot trials'),organization:fact('org','Example Lab'),start:fact('start','Fall 2025'),end:fact('end','Spring 2026'),details:[{id:'original',revision:1},{id:'support',revision:1}]},
 {id:'other',kind:'project',title:fact('other-title','Other project'),details:[{id:'other-entry',revision:1}]}];
 return {institution:'Example University',college:'Engineering',major:'CS',grade:'Junior',is_international:false,skills:[],research_interests:'I want to explore reliable robot perception. 我希望研究鲁棒感知。',resume_text:'',resume_master:master,
 experience_entries:[entry('original','Measured robot trials; I did not lead the team.'),entry('support','I wrote Python scripts to compare the recorded trials. I did not design the experiment.'),entry('other-entry','Built a website for a club.'),entry('unbound','I checked the robot trial logs in Spring 2026.')]};
}
const target={opportunity_id:'b52-fixture-opportunity',title:'Robotics research',organization:'Example Lab',source_url:'',description:'Research on reliable robot perception with Python.',requirements:['Python'],context_version:4 as const,
 lab:{version:1 as const,status:'unavailable' as const,snapshot:null},research:{version:1 as const,status:'unavailable' as const,snapshot:null},criteria:{eligibility:{},timing:{},application:{},setting:{},availability:{},attribution:{}}};
const make=(p=profile())=>createTargetResume(p,target,'b52-fixture-draft');
const lines=(d:TargetResumeV1)=>d.document.sections.flatMap(s=>s.blocks.flatMap(b=>b.lines));
function groups(d:TargetResumeV1):TargetResumeSupportGroup[]{return [{unit_id:lines(d).find(l=>l.evidence.id==='original')!.id,support_unit_ids:[lines(d).find(l=>l.evidence.id==='support')!.id],confirmed:true}];}
function response(p:PreparedTargetResumeAi):TargetResumeAiResponse{
 const g=p.support_groups!;
 return {version:1,pipeline_version:'full-target-v6',check_version:'target-resume-source-checks-v4',request_id:'b52-request',document_id:p.draft.id,opportunity_id:p.draft.opportunity_id,document_signature:p.document_signature,base:clone(p.draft.base),
 support_groups:clone(g),manifest:{unit_ids:p.units.map(u=>u.unit_id),protected_unit_count:p.protected_unit_count},method:'ai',logical_calls:2,provider_attempts_upper_bound:4,
 receipts:p.units.map(u=>{const group=g.find(x=>x.unit_id===u.unit_id),experience=u.evidence.kind==='experience';return {unit_id:u.unit_id,section_id:u.section_id,block_id:u.block_id,evidence:clone(u.evidence),before_text:u.before_text,status:group||!experience?'suggested':'unchanged',reason_code:group||!experience?null:'no_link',
 suggestion:{priority:'normal',reason:'Review the original trial work and confirmed Python contribution.',target_evidence:[],links:[],ops:group?['personal_first']:[],alternative_text:null,proposed_text:group?'Measured robot trials; wrote Python scripts to compare the recorded trials. I did not lead the team. I did not design the experiment.':null,...(group?{source_evidence:targetResumeSupportEvidence(p.draft,group)}:{})}};})};
}
const current=(d:TargetResumeV1)=>({profile_signature:d.base.profile_signature,source_signature:d.base.source_signature,target_signature:d.base.target_signature});
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
describe('B52 explicit existing-entry assignment',()=>{
 it('links the current unbound original without changing text or existing target drafts',async()=>{const p=profile(),before=clone(p),old=await make(p);expect((await unassignedConfirmedExperiences(p)).map(e=>e.id)).toEqual(['unbound']);
 const prepared=await prepareExperienceAssignment(p,{entryId:'unbound',entryRevision:1,activityId:'robot'});expect(prepared.ok).toBe(true);if(!prepared.ok)return;
 expect(prepared.desired.experience_entries).toEqual(before.experience_entries);expect(prepared.desired.resume_master?.revision).toBe(2);expect(p).toEqual(before);expect(lines(old).some(l=>l.evidence.id==='unbound')).toBe(false);
 expect(lines(await make(prepared.desired)).some(l=>l.evidence.id==='unbound')).toBe(true);});
 it.each(['candidate','rejected','withdrawn'] as const)('does not assign %s entries',async status=>{const p=profile();p.experience_entries![3].status=status;expect(await unassignedConfirmedExperiences(p)).toEqual([]);});
 it.each(['revision','activity','already-linked','stale-source'] as const)('rejects %s changes',async kind=>{const p=profile();const request={entryId:'unbound',entryRevision:1,activityId:'robot'};
 if(kind==='revision')p.experience_entries![3].revision=2;if(kind==='activity')request.activityId='missing';if(kind==='already-linked')p.resume_master!.education=[{id:'edu',details:[{id:'unbound',revision:1}]}];
 if(kind==='stale-source')p.experience_entries![3].source={kind:'resume',signature:await sourceDigest('old'),start:0,end:3,quote:'old'};
 expect((await prepareExperienceAssignment(p,request)).ok).toBe(false);});
});
describe('B52 direction and confirmed source combinations',()=>{
 it('preserves full interests including tail and Unicode, separately from facts and exports',async()=>{const p=profile();p.research_interests='😀'.repeat(18000)+'I want to study perception; I have not done this research.';const d=await make(p);expect(d.base_snapshot.research_interests).toBe(p.research_interests);expect(lines(d).some(l=>l.original===p.research_interests)).toBe(false);const ex=await prepareTargetResumeExport(d,{locale:'en',page_size:'letter'});expect(ex.ok).toBe(true);expect(JSON.stringify(ex.ok&&ex.value.projection)).not.toContain('I want to study');
 const n=await make({...p,research_interests:p.research_interests+' New direction.'});expect(n.base.profile_signature).not.toBe(d.base.profile_signature);});
 it('keeps legacy missing direction missing, rejects invalid direction characters',async()=>{const d=clone(await make());delete d.base_snapshot.research_interests;const legacy=validateTargetResume(d);expect(legacy.ok).toBe(true);expect(legacy.ok&&legacy.value.base_snapshot).not.toHaveProperty('research_interests');for(const value of ['\0','\ud800']){d.base_snapshot.research_interests=value;expect(validateTargetResume(d).ok).toBe(false);}});
 it('offers only uniquely related current activity lines; education/publication duplicates exclude both',async()=>{for(const section of ['education','publications'] as const){const p=profile();p.resume_master![section]=[{id:'duplicate',details:[{id:'support',revision:1}]}];expect(targetResumeSupportActivities(await make(p))).toHaveLength(0);}});
 it.each(['unconfirmed','other-project','self','duplicate','missing','empty','extra'] as const)('rejects %s source choices',async kind=>{const d=await make(),g=groups(d);if(kind==='unconfirmed')Object.assign(g[0],{confirmed:false});if(kind==='other-project')g[0].support_unit_ids=[lines(d).find(l=>l.evidence.id==='other-entry')!.id];if(kind==='self')g[0].support_unit_ids=[g[0].unit_id];if(kind==='duplicate')g[0].support_unit_ids.push(g[0].support_unit_ids[0]);if(kind==='missing')g[0].support_unit_ids=['missing'];if(kind==='empty')g[0].support_unit_ids=[];if(kind==='extra')Object.assign(g[0],{other:true});expect(parseTargetResumeSupportGroups(d,g)).toBeNull();});
 it('counts the full supporting sources in each batch without truncation',async()=>{const p=profile();p.experience_entries![0].text='a'.repeat(3500);p.experience_entries![1].text='b'.repeat(3500);const d=await make(p),g=groups(d);const prep=await prepareTargetResumeAI(d,g);expect(prep.ok).toBe(true);if(!prep.ok)return;expect(prep.value.skipped.some(r=>r.unit_id===g[0].unit_id&&r.reason_code==='unit_too_large')).toBe(true);expect(prep.value.units.find(u=>u.unit_id===g[0].unit_id)?.original).toHaveLength(3500);});
 it('binds response, acceptance, stored source record and actual export to the reviewed group',async()=>{
 const assigned=await prepareExperienceAssignment(profile(),{entryId:'unbound',entryRevision:1,activityId:'robot'});if(!assigned.ok)throw Error(assigned.reason);
 const d=await make(assigned.desired),g=groups(d),prepared=await prepareTargetResumeAI(d,g);if(!prepared.ok)throw Error(prepared.code);const p=prepared.value,r:TargetResumeAiResponse=process.env.OFE_B52_BACKEND_RESPONSE ? JSON.parse(readFileSync(process.env.OFE_B52_BACKEND_RESPONSE,'utf8')) : response(p),request={request_id:r.request_id,selected_unit_ids:p.units.map(u=>u.unit_id),support_groups:g};
 const checked=validateTargetResumeAIResponse(p,request,r);expect(checked.ok).toBe(true);if(!checked.ok)throw Error(checked.code);
 const applied=applyTargetResumeAI(p,d,[checked.value],{currentContext:current(d),rewriteUnitIds:[g[0].unit_id],applyStructure:false,supportGroups:g});expect(applied.ok).toBe(true);if(!applied.ok)throw Error(applied.code);
 const receipt=checked.value.receipts.find(r=>r.unit_id===g[0].unit_id)!,unit=p.units.find(u=>u.unit_id===g[0].unit_id)!;
 const provenance=appendTargetResumeProvenance(null,d,applied.value,{kind:'ai_rewrite',id:'b52-reviewed-combination',annotations:[{section_id:unit.section_id,block_id:unit.block_id,line_id:unit.unit_id,field:'text',reason:receipt.suggestion!.reason,target_evidence:receipt.suggestion!.target_evidence,source_evidence:receipt.suggestion!.source_evidence!,check:{version:checked.value.check_version!,pipeline_version:checked.value.pipeline_version,request_id:r.request_id,document_signature:p.document_signature,original:unit.original,evidence:unit.evidence}}]});
 expect(provenance!.events[0].changes[0].source_evidence).toEqual(targetResumeSupportEvidence(d,g[0]));expect(validateTargetResumeProvenance(provenance,applied.value).ok).toBe(true);
 const projection=await prepareTargetResumeExport(applied.value,{locale:'en',page_size:'letter'});if(!projection.ok)throw Error(projection.code);
 expect(JSON.stringify(projection.value.projection)).toContain(receipt.suggestion!.proposed_text);expect(JSON.stringify(projection.value.projection)).not.toContain('I want to explore');
 if(process.env.OFE_B52_FIXTURE_PATH)writeFileSync(process.env.OFE_B52_FIXTURE_PATH,JSON.stringify({profile:assigned.desired,before:d,preparation_request:{version:1,locale:'en',draft:d,document_signature:p.document_signature,...request},request:{version:1,locale:'en',include_check_version:true,draft:d,document_signature:p.document_signature,...request},response:r,doc:applied.value,provenance,export_projection:projection.value.projection},null,2)+'\n');
 expect(applyTargetResumeAI(p,d,[r],{currentContext:current(d),rewriteUnitIds:[g[0].unit_id],applyStructure:false,supportGroups:[]})).toEqual({ok:false,code:'stale_context'});
 });
 it.each(['missing-echo','changed-echo','missing-source','partial-source','wrong-order'] as const)('rejects %s receipts atomically',async kind=>{const d=await make(),g=groups(d),prep=await prepareTargetResumeAI(d,g);if(!prep.ok)throw Error(prep.code);const r=response(prep.value),expected={request_id:r.request_id,selected_unit_ids:prep.value.units.map(u=>u.unit_id),support_groups:g};const s=r.receipts.find(x=>x.unit_id===g[0].unit_id)!.suggestion!;if(kind==='missing-echo')delete r.support_groups;if(kind==='changed-echo')r.support_groups=[];if(kind==='missing-source')delete s.source_evidence;if(kind==='partial-source')s.source_evidence!.pop();if(kind==='wrong-order')s.source_evidence!.reverse();expect(validateTargetResumeAIResponse(prep.value,expected,r).ok).toBe(false);});
 it('permits a group compression longer than the old sentence but shorter than combined sources, and keeps source proof when skipped',async()=>{const d=await make(),g=groups(d),prepared=await prepareTargetResumePlan(d,{target_pages:1},g);if(!prepared.ok)throw Error(prepared.code);const p=prepared.value;const r:TargetResumePlanResponse={version:1,pipeline_version:'full-target-plan-v4',request_id:'plan',document_id:d.id,opportunity_id:d.opportunity_id,document_signature:p.document_signature,base:clone(d.base),support_groups:g,options:p.options,manifest:p.manifest,scope:p.scope,method:'ai',complete:true,reason_code:null,logical_calls:1,provider_attempts_upper_bound:2,items:p.manifest.map(m=>{const l=lines(d).find(l=>l.id===m.line_ids[0])!;return {section_id:m.section_id,block_id:m.block_id,action:'keep',reason:'Review sources.',target_evidence:[{field:'requirement',requirement_index:0,start:0,end:6,quote:'Python'}],source_evidence:[{unit_id:l.id,start:0,end:Array.from(l.original).length,quote:l.original}],rewrites:[]};})};
 const item=r.items.find(i=>i.block_id===lines(d).find(l=>l.id===g[0].unit_id)!.id.split(':').slice(0,-1).join(':')) ?? r.items.find(i=>p.manifest.find(m=>m.block_id===i.block_id)!.line_ids.includes(g[0].unit_id))!;
 item.action='compress';item.rewrites=[{unit_id:g[0].unit_id,status:'suggested',reason_code:null,proposed_text:'Measured robot trials; wrote Python scripts to compare the recorded trials. I did not lead the team. I did not design the experiment.',source_evidence:targetResumeSupportEvidence(d,g[0])}];
 const request={request_id:'plan',options:p.options,support_groups:g};expect(validateTargetResumePlanResponse(p,request,r).ok).toBe(true);expect(applyTargetResumePlan(p,d,r,{current_context:current(d),options:p.options,selection_block_ids:[],rewrite_unit_ids:[g[0].unit_id],support_groups:g}).ok).toBe(true);
 item.rewrites[0]={...item.rewrites[0],status:'skipped',reason_code:'ungrounded_rewrite',proposed_text:null};expect(validateTargetResumePlanResponse(p,request,r).ok).toBe(true);delete item.rewrites[0].source_evidence;expect(validateTargetResumePlanResponse(p,request,r).ok).toBe(false);
 });
});
