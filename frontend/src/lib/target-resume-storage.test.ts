import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import legacyGolden from '../../../tests/fixtures/target-resume-ai-golden.json';
import { appendTargetResumeProvenance, type TargetResumeProvenance } from './target-resume-provenance';
import { createEmptyResumeMaster } from './resume-master';
import { createTargetResume, type TargetResumeV1 } from './target-resume';
const { rpc, from, device } = vi.hoisted(() => ({ rpc: vi.fn(), from: vi.fn(), device: vi.fn() }));
vi.mock('./supabase', () => ({ supabase: { rpc, from }, getDeviceId: device }));
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { loadTargetResume, loadTargetResumeHistory, loadTargetResumeVersion, saveTargetResume } from './target-resume-storage';
const UID='77000000-0000-4000-8000-000000000001';
const stamp='2026-09-24T18:00:00.000Z';
let doc:TargetResumeV1;let filters:Array<[string,unknown]>;let select:ReturnType<typeof vi.fn>;let single:ReturnType<typeof vi.fn>;let limit:ReturnType<typeof vi.fn>;
function deferred<T>() { let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve}; }
const row=(revision=1,d=doc)=>({revision,doc:d,updated_at:stamp,provenance:null as TargetResumeProvenance|null});
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);localStorage.clear();advanceOwnerEpoch(null);advanceOwnerEpoch(UID);await syncLocalIdentityOwner(UID);
 rpc.mockReset();from.mockReset();device.mockReset().mockResolvedValue(UID);filters=[];
 single=vi.fn().mockResolvedValue({data:row(),error:null});limit=vi.fn().mockResolvedValue({data:[],error:null});
 const chain={select:vi.fn(),eq:vi.fn((k,v)=>{filters.push([k,v]);return chain;}),lt:vi.fn((k,v)=>{filters.push(['lt:'+k,v]);return chain;}),order:vi.fn(()=>chain),maybeSingle:single,limit};
 select=chain.select.mockReturnValue(chain);from.mockReturnValue(chain);
 const master=createEmptyResumeMaster('master');master.basics.name={id:'name',revision:1,status:'confirmed',value:'Alex 王',source:{kind:'manual'}};
 doc=await createTargetResume({institution:'UIUC',college:'Grainger',major:'CS',grade:'Junior',is_international:false,research_interests:'robotics',skills:[],resume_master:master,resume_text:'Source',experience_entries:[]},{opportunity_id:'opp',title:'Lab',organization:'UIUC',description:'robotics',requirements:[],source_url:'https://example.edu/lab',context_version:3,research:{version:1,status:'unavailable',snapshot:null},criteria:{eligibility:{},timing:{},application:{},setting:{},availability:{},attribution:{}}},'target');
 single.mockResolvedValue({data:row(),error:null});
});
describe('target resume persistence',()=>{
 it('reads, edits, saves and restores legacy six-key documents without upgrading their source',async()=>{
  const legacy=JSON.parse(JSON.stringify(legacyGolden.draft)) as TargetResumeV1;
  const id=legacy.opportunity_id, targetBefore=JSON.stringify(legacy.target_snapshot), signature=legacy.base.target_signature;
  single.mockResolvedValue({data:row(1,legacy),error:null});
  const read=await loadTargetResume(id,captureOwnerToken());expect(read?.doc).toEqual(legacy);
  const historical=await loadTargetResumeVersion(id,1,captureOwnerToken());expect(historical?.doc).toEqual(legacy);
  const edited=JSON.parse(JSON.stringify(read!.doc)) as TargetResumeV1;
  edited.document.sections[0].blocks[0].lines[0].text='Manual old source edit 王';
  rpc.mockImplementation(async(_fn,args)=>({data:{status:'saved',...row(2,args.p_doc)},error:null}));
  expect((await saveTargetResume(edited,1,captureOwnerToken())).status).toBe('saved');
  expect(JSON.stringify(rpc.mock.calls[0][1].p_doc.target_snapshot)).toBe(targetBefore);
  expect(rpc.mock.calls[0][1].p_doc.base.target_signature).toBe(signature);
  expect(rpc.mock.calls[0][1].p_doc.target_snapshot).not.toHaveProperty('context_version');
 });
 it('saves only with the captured owner and accepts semantically reordered JSON response',async()=>{
  rpc.mockImplementation(async(_fn,args)=>({data:{status:'saved',...row(1,{...args.p_doc,base:{...args.p_doc.base}})},error:null}));
  expect((await saveTargetResume(doc,0,captureOwnerToken())).status).toBe('saved');
  expect(rpc).toHaveBeenCalledWith('commit_target_resume_with_provenance_cas',{p_expected_owner:UID,p_opportunity_id:'opp',p_expected_revision:0,p_doc:doc,p_provenance:null});
  expect(from).not.toHaveBeenCalled();
 });
 it.each(['saved','unchanged'] as const)('validates %s response content and revision before acknowledging',async(status)=>{
  const wrong=structuredClone(doc);wrong.document.sections[0].blocks[0].lines[0].text='other';
  rpc.mockResolvedValue({data:{status,...row(1,wrong)},error:null});
  expect((await saveTargetResume(doc,0,captureOwnerToken())).status).toBe('failed');
  rpc.mockResolvedValue({data:{status,...row(5)},error:null});
  expect((await saveTargetResume(doc,0,captureOwnerToken())).status).toBe('failed');
 });
 it('exposes conflict current and missing without pretending either saved',async()=>{
  rpc.mockResolvedValue({data:{status:'conflict',...row(4)},error:null});
  expect(await saveTargetResume(doc,1,captureOwnerToken())).toEqual({status:'conflict',current:row(4)});
  rpc.mockResolvedValue({data:{status:'missing'},error:null});expect(await saveTargetResume(doc,4,captureOwnerToken())).toEqual({status:'missing'});
 });
 it('keeps an ambiguous failed request retryable with the same expected revision',async()=>{
  rpc.mockResolvedValueOnce({data:null,error:{message:'lost response'}}).mockResolvedValueOnce({data:{status:'unchanged',...row(2)},error:null});
  const token=captureOwnerToken();expect((await saveTargetResume(doc,1,token)).status).toBe('failed');expect((await saveTargetResume(doc,1,token)).status).toBe('unchanged');
  expect(rpc.mock.calls.map(c=>c[1].p_expected_revision)).toEqual([1,1]);
 });
 it('captures a deep snapshot before the first digest/session await',async()=>{
  const gate=deferred<string>();device.mockReturnValue(gate.promise);
  rpc.mockImplementation(async(_fn,args)=>({data:{status:'saved',...row(1,args.p_doc)},error:null}));
  const before=JSON.stringify(doc);const result=saveTargetResume(doc,0,captureOwnerToken());
  doc.document.sections[0].blocks[0].lines[0].text='late edit';gate.resolve(UID);
  expect((await result).status).toBe('saved');expect(JSON.stringify(rpc.mock.calls[0][1].p_doc)).toBe(before);
 });
 it('rejects changed raw/signature, malformed evidence and a >2MiB draft before RPC',async()=>{
  expect((await saveTargetResume({...doc,unknown:undefined} as TargetResumeV1,0,captureOwnerToken())).status).toBe('failed');
  const bad=JSON.parse(JSON.stringify(doc));bad.base_snapshot.resume_text='different';
  expect((await saveTargetResume(bad,0,captureOwnerToken())).status).toBe('failed');
  const invalid=JSON.parse(JSON.stringify(doc));invalid.document.sections[0].blocks[0].lines[0].original='unproven';
  expect((await saveTargetResume(invalid,0,captureOwnerToken())).status).toBe('failed');
  const huge=JSON.parse(JSON.stringify(doc));huge.document.sections[0].blocks[0].lines[0].text='🧪'.repeat(530000);
  expect((await saveTargetResume(huge,0,captureOwnerToken())).status).toBe('failed');expect(rpc).not.toHaveBeenCalled();
 });
 it('does not send after session resolution switches owners',async()=>{
  const gate=deferred<string>();device.mockReturnValue(gate.promise);const token=captureOwnerToken();const result=saveTargetResume(doc,0,token);
  await vi.waitFor(()=>expect(device).toHaveBeenCalled());
  advanceOwnerEpoch('other');await syncLocalIdentityOwner('other');gate.resolve('other');
  expect(await result).toEqual({status:'abandoned'});expect(rpc).not.toHaveBeenCalled();
 });
 it('drops a late successful response after an A→B→A generation change',async()=>{
  const gate=deferred<unknown>();rpc.mockReturnValue(gate.promise);const result=saveTargetResume(doc,0,captureOwnerToken());
  await vi.waitFor(()=>expect(rpc).toHaveBeenCalled());advanceOwnerEpoch('other');await syncLocalIdentityOwner('other');advanceOwnerEpoch(UID);await syncLocalIdentityOwner(UID);gate.resolve({data:{status:'saved',...row()},error:null});
  expect(await result).toEqual({status:'abandoned'});
 });
 it('strictly distinguishes successful absence from failures and invalid rows',async()=>{
  single.mockResolvedValue({data:null,error:null});expect(await loadTargetResume('opp',captureOwnerToken())).toBeNull();
  single.mockResolvedValue({data:null,error:{message:'not readable'}});await expect(loadTargetResume('opp',captureOwnerToken())).rejects.toMatchObject({code:'failed'});
  single.mockResolvedValue({data:row(0),error:null});await expect(loadTargetResume('opp',captureOwnerToken())).rejects.toMatchObject({code:'invalid'});
  const bad=JSON.parse(JSON.stringify(doc));bad.target_snapshot.title='forged';single.mockResolvedValue({data:row(1,bad),error:null});await expect(loadTargetResume('opp',captureOwnerToken())).rejects.toMatchObject({code:'invalid'});
 });
 it('loads a single verified version and rejects a different target/revision',async()=>{
  single.mockResolvedValue({data:row(4),error:null});expect(await loadTargetResumeVersion('opp',4,captureOwnerToken())).toEqual(row(4));
  expect(filters).toContainEqual(['owner_id',UID]);expect(filters).toContainEqual(['revision',4]);
  await expect(loadTargetResumeVersion('opp',3,captureOwnerToken())).rejects.toMatchObject({code:'invalid'});
  await expect(loadTargetResume('different',captureOwnerToken())).rejects.toMatchObject({code:'invalid'});
 });
 it('paginates metadata only and refuses duplicated/out-of-order/out-of-cursor rows',async()=>{
  limit.mockResolvedValue({data:[{revision:9,updated_at:stamp},{revision:7,updated_at:stamp}],error:null});
  expect(await loadTargetResumeHistory('opp',captureOwnerToken(),10)).toHaveLength(2);
  expect(select).toHaveBeenCalledWith('revision,updated_at');expect(limit).toHaveBeenCalledWith(20);expect(filters).toContainEqual(['lt:revision',10]);
  for(const revisions of [[9,9],[7,9],[10,8]]) {limit.mockResolvedValue({data:revisions.map(revision=>({revision,updated_at:stamp})),error:null});await expect(loadTargetResumeHistory('opp',captureOwnerToken(),10)).rejects.toMatchObject({code:'invalid'});}
  await expect(loadTargetResumeHistory('opp',captureOwnerToken(),0)).rejects.toMatchObject({code:'invalid'});
 });
 it('never turns history failure/null into an empty history',async()=>{
  for(const result of [{data:null,error:null},{data:[],error:{message:'denied'}}]){limit.mockResolvedValue(result);await expect(loadTargetResumeHistory('opp',captureOwnerToken())).rejects.toThrow();}
 });
 it('drops late current/history/version reads on owner change',async()=>{
  for(const kind of ['current','history','version']){
   advanceOwnerEpoch(UID);await syncLocalIdentityOwner(UID);const token=captureOwnerToken();const gate=deferred<unknown>();single.mockReturnValue(gate.promise);limit.mockReturnValue(gate.promise);
   const queried=kind==='history'?limit:single;const started=queried.mock.calls.length;
   const request=kind==='current'?loadTargetResume('opp',token):kind==='history'?loadTargetResumeHistory('opp',token):loadTargetResumeVersion('opp',1,token);
   const asserted=expect(request).rejects.toMatchObject({code:'abandoned'});await vi.waitFor(()=>expect(queried).toHaveBeenCalledTimes(started+1));
   advanceOwnerEpoch('other');await syncLocalIdentityOwner('other');gate.resolve({data:kind==='history'?[]:row(),error:null});await asserted;
  }
 });
});

function recorded() {
 const before=structuredClone(doc);const after=structuredClone(doc);
 after.document.sections[0].blocks[0].lines[0].text='Manual name 王';
 const provenance=appendTargetResumeProvenance(null,before,after,{kind:'manual',id:'edit'})!;
 return {after,provenance};
}
describe('atomic document and provenance storage',()=>{
 it('normalizes missing legacy fields to unknown on both reads',async()=>{
  const legacy={revision:3,doc,updated_at:stamp};single.mockResolvedValue({data:legacy,error:null});
  expect(await loadTargetResume('opp',captureOwnerToken())).toEqual({...legacy,provenance:null});
  expect(await loadTargetResumeVersion('opp',3,captureOwnerToken())).toEqual({...legacy,provenance:null});
  expect(select).toHaveBeenCalledWith('revision,doc,updated_at,provenance');
 });
 it('reads and restores the complete historical record without changing old check metadata',async()=>{
  const {after,provenance}=recorded();const historical={...row(2,after),provenance};
  single.mockResolvedValue({data:historical,error:null});const read=await loadTargetResumeVersion('opp',2,captureOwnerToken());
  expect(read).toEqual(historical);
  rpc.mockImplementation(async(_name,args)=>({data:{status:'saved',...row(4,args.p_doc),provenance:args.p_provenance},error:null}));
  expect(await saveTargetResume(read!.doc,3,captureOwnerToken(),read!.provenance)).toEqual({status:'saved',value:{...historical,revision:4}});
  expect(rpc.mock.calls[0][1]).toMatchObject({p_doc:after,p_provenance:provenance});
 });
 it('freezes both values before identity/hash waits so late caller mutation cannot split the saved pair',async()=>{
  const {after,provenance}=recorded();const expected=structuredClone({after,provenance});const gate=deferred<string>();device.mockReturnValue(gate.promise);
  rpc.mockImplementation(async(_name,args)=>({data:{status:'saved',...row(1,args.p_doc),provenance:args.p_provenance},error:null}));
  const pending=saveTargetResume(after,0,captureOwnerToken(),provenance);
  after.document.sections[0].blocks[0].lines[0].text='Late typing';provenance.events[0].changes[0].after='Late typing';gate.resolve(UID);
  expect((await pending).status).toBe('saved');expect(rpc.mock.calls[0][1]).toMatchObject({p_doc:expected.after,p_provenance:expected.provenance});
 });
 it.each(['saved','unchanged'])('does not acknowledge %s if a receipt drops or replaces the provenance',async(status)=>{
  const {after,provenance}=recorded();
  for(const returned of [null,undefined,{...provenance,events:[{...provenance.events[0],id:'different'}]}]){
   rpc.mockResolvedValue({data:{status,...row(1,after),provenance:returned},error:null});
   expect(await saveTargetResume(after,0,captureOwnerToken(),provenance)).toEqual({status:'failed'});
  }
 });
 it('returns a valid conflict pair and rejects a corrupt one instead of replacing local state',async()=>{
  const {after,provenance}=recorded();rpc.mockResolvedValue({data:{status:'conflict',...row(5,after),provenance},error:null});
  expect(await saveTargetResume(doc,1,captureOwnerToken())).toEqual({status:'conflict',current:{...row(5,after),provenance}});
  rpc.mockResolvedValue({data:{status:'conflict',...row(5,doc),provenance},error:null});
  expect(await saveTargetResume(doc,1,captureOwnerToken())).toEqual({status:'failed'});
 });
 it('retries an uncertain outcome with the identical pair and expected revision without a legacy fallback',async()=>{
  const {after,provenance}=recorded();rpc.mockResolvedValueOnce({data:null,error:{message:'transport'}})
   .mockResolvedValueOnce({data:{status:'unchanged',...row(3,after),provenance},error:null});
  const token=captureOwnerToken();expect((await saveTargetResume(after,2,token,provenance)).status).toBe('failed');
  expect((await saveTargetResume(after,2,token,provenance)).status).toBe('unchanged');
  expect(rpc.mock.calls[0]).toEqual(rpc.mock.calls[1]);expect(rpc).toHaveBeenCalledTimes(2);
 });
 it('refuses damaged or over-limit nonempty records before sending any write',async()=>{
  const {after,provenance}=recorded();const invalid={...provenance,version:9};
  expect((await saveTargetResume(after,0,captureOwnerToken(),invalid as unknown as TargetResumeProvenance)).status).toBe('failed');
  const huge=structuredClone(provenance);huge.events[0].changes[0].before='王'.repeat(90000);
  expect((await saveTargetResume(after,0,captureOwnerToken(),huge)).status).toBe('failed');expect(rpc).not.toHaveBeenCalled();
 });
 it('rejects malformed current and historical records rather than treating them as legacy unknown',async()=>{
  for(const provenance of [{},[],{version:7},false]){
   single.mockResolvedValue({data:{...row(1),provenance},error:null});
   await expect(loadTargetResume('opp',captureOwnerToken())).rejects.toMatchObject({code:'invalid'});
   await expect(loadTargetResumeVersion('opp',1,captureOwnerToken())).rejects.toMatchObject({code:'invalid'});
  }
 });
 it('drops a late complete pair after owner changes',async()=>{
  const {after,provenance}=recorded();const gate=deferred<unknown>();rpc.mockReturnValue(gate.promise);
  const pending=saveTargetResume(after,0,captureOwnerToken(),provenance);await vi.waitFor(()=>expect(rpc).toHaveBeenCalled());
  advanceOwnerEpoch('other');await syncLocalIdentityOwner('other');gate.resolve({data:{status:'saved',...row(1,after),provenance},error:null});
  expect(await pending).toEqual({status:'abandoned'});
 });
});
