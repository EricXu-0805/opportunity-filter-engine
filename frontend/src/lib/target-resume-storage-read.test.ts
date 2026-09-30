import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/target-resume-ai-golden.json';
const mocked = vi.hoisted(() => ({ device:vi.fn(), from:vi.fn(), rpc:vi.fn() }));
vi.mock('./supabase', () => ({ getDeviceId:mocked.device, supabase:{from:mocked.from,rpc:mocked.rpc} }));
import {advanceOwnerEpoch,captureOwnerToken,syncLocalIdentityOwner} from './identity-owner';
import {loadTargetResume,loadTargetResumeHistory,loadTargetResumeVersion,TARGET_RESUME_READ_TIMEOUT_MS,type TargetResumeReadOptions} from './target-resume-storage';
const uid='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
function deferred<T>() { let resolve!:(value:T)=>void;let reject!:(error:unknown)=>void;const promise=new Promise<T>((done,fail)=>{resolve=done;reject=fail});return {promise,resolve,reject}; }
function call(kind:string,options:TargetResumeReadOptions={}) { const owner=captureOwnerToken();return kind==='current'?loadTargetResume('golden-target',owner,options):kind==='history'?loadTargetResumeHistory('golden-target',owner,undefined,options):loadTargetResumeVersion('golden-target',1,owner,options); }
let respond = vi.fn<() => Promise<unknown>>(); let abortSignal:ReturnType<typeof vi.fn>;
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.useRealTimers();advanceOwnerEpoch(uid);await syncLocalIdentityOwner(uid);
 mocked.device.mockReset().mockResolvedValue(uid);mocked.from.mockReset();mocked.rpc.mockReset();
 respond=vi.fn<() => Promise<unknown>>().mockResolvedValue({data:null,error:null});abortSignal=vi.fn();
 const chain={select:vi.fn(),eq:vi.fn(),order:vi.fn(),limit:vi.fn(),maybeSingle:vi.fn(),abortSignal,then:(resolve:(value:unknown)=>void,reject:(error:unknown)=>void)=>respond().then(resolve,reject)};
 for(const field of ['select','eq','order','limit','maybeSingle'] as const)chain[field].mockReturnValue(chain);
 abortSignal.mockReturnValue(chain);mocked.from.mockReturnValue(chain);
});
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals();});
describe('bounded target resume reads',()=>{
 it.each(['current','history','version'])('%s: auth deadline retires before a late auth result can start storage',async kind=>{
  vi.useFakeTimers();const auth=deferred<string>();mocked.device.mockReturnValue(auth.promise);
  const result=call(kind).catch(error=>error);await vi.advanceTimersByTimeAsync(TARGET_RESUME_READ_TIMEOUT_MS);
  expect(await result).toMatchObject({code:'timeout'});expect(mocked.from).not.toHaveBeenCalled();
  auth.resolve(uid);await vi.advanceTimersByTimeAsync(1);expect(mocked.from).not.toHaveBeenCalled();expect(mocked.rpc).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
 });
 it.each(['current','history','version'])('%s: transport timeout passes abort signal and permits an explicit fresh read',async kind=>{
  vi.useFakeTimers();const storage=deferred<unknown>();respond.mockReturnValueOnce(storage.promise);
  const result=call(kind).catch(error=>error);await vi.advanceTimersByTimeAsync(TARGET_RESUME_READ_TIMEOUT_MS);
  expect(await result).toMatchObject({code:'timeout'});expect(abortSignal).toHaveBeenCalledOnce();expect(abortSignal.mock.calls[0][0].aborted).toBe(true);
  respond.mockResolvedValue({data:kind==='history'?[]:null,error:null});expect(await call(kind)).toEqual(kind==='history'?[]:null);
  storage.resolve({data:{PRIVATE:'late response'},error:null});await vi.advanceTimersByTimeAsync(1);expect(mocked.from).toHaveBeenCalledTimes(2);expect(mocked.rpc).not.toHaveBeenCalled();
 });
 it.each(['current','history','version'])('%s: caller cancellation settles held auth and suppresses its late query',async kind=>{
  vi.useFakeTimers();const auth=deferred<string>();mocked.device.mockReturnValue(auth.promise);const controller=new AbortController();
  const result=call(kind,{signal:controller.signal}).catch(error=>error);controller.abort();expect(await result).toMatchObject({code:'abandoned'});
  auth.resolve(uid);await vi.advanceTimersByTimeAsync(1);expect(mocked.from).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
 });
 it('observes an already-created identity promise when cancellation occurs before wait subscribes',async()=>{
  const auth=deferred<string>();const controller=new AbortController();const unhandled:unknown[]=[];
  const observe=(reason:unknown)=>{unhandled.push(reason)};process.on('unhandledRejection',observe);
  try {
   mocked.device.mockImplementation(()=>{controller.abort();return auth.promise});
   await expect(call('current',{signal:controller.signal})).rejects.toMatchObject({code:'abandoned'});
   auth.reject(new Error('Late identity rejection'));
   await new Promise(resolve=>setTimeout(resolve,0));
   expect(unhandled).toEqual([]);expect(mocked.from).not.toHaveBeenCalled();
  } finally {process.off('unhandledRejection',observe)}
 });
 it('cancels an in-flight body read with the same transport signal',async()=>{
  const storage=deferred<unknown>();respond.mockReturnValue(storage.promise);const controller=new AbortController();
  const result=call('current',{signal:controller.signal}).catch(error=>error);await vi.waitFor(()=>expect(abortSignal).toHaveBeenCalled());controller.abort();
  expect(await result).toMatchObject({code:'abandoned'});expect(abortSignal.mock.calls[0][0].aborted).toBe(true);storage.resolve({data:null,error:null});
 });
 it('does not begin a read for an already-cancelled caller',async()=>{
  const controller=new AbortController();controller.abort();await expect(call('current',{signal:controller.signal})).rejects.toMatchObject({code:'abandoned'});
  expect(mocked.device).not.toHaveBeenCalled();expect(mocked.from).not.toHaveBeenCalled();
 });
 it.each([-1,Infinity,NaN])('rejects an invalid read deadline %s without a request',async timeoutMs=>{
  await expect(call('current',{timeoutMs})).rejects.toMatchObject({code:'invalid'});expect(mocked.device).not.toHaveBeenCalled();
 });
 it('includes signature validation in the same read deadline',async()=>{
  // The complete valid legacy fixture reaches its asynchronous signature check.
  const id=golden.draft.opportunity_id;
  respond.mockResolvedValue({data:{revision:1,updated_at:'2026-09-24T12:00:00Z',doc:golden.draft,provenance:null},error:null});
  const digest=deferred<ArrayBuffer>();const spy=vi.spyOn(webcrypto.subtle,'digest').mockReturnValue(digest.promise);
  vi.useFakeTimers();const result=loadTargetResume(id,captureOwnerToken()).catch(error=>error);
  await vi.advanceTimersByTimeAsync(TARGET_RESUME_READ_TIMEOUT_MS);expect(spy).toHaveBeenCalled();expect(await result).toMatchObject({code:'timeout'});
  digest.resolve(new ArrayBuffer(32));await vi.advanceTimersByTimeAsync(1);expect(mocked.rpc).not.toHaveBeenCalled();
 });
});
