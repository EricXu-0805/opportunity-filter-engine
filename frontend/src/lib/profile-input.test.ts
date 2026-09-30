import { describe, it, expect, vi, afterEach } from 'vitest';
import { writeFileSync, mkdirSync } from 'node:fs';
import { toProfileRequest, getMatches, generateColdEmailStream, ApiError } from './api';
import { assertProfileInput, profileInputMessage, ProfileInputError } from './profile-input';
import { canFallbackColdEmailStream } from './cold-email-stream';
import { translate } from '../i18n/translate';
import type { ProfileData } from './types';
vi.mock('./supabase', () => ({getRevealAccessToken: async () => null,refreshRevealAccessToken:async()=>null}));
const profile = (overrides: Partial<ProfileData> = {}): ProfileData => ({institution:'UIUC',college:'Engineering',major:'Computer Science',grade:'Junior',name:'Alex 王',is_international:false,seeking_types:['research'],research_interests:'topic '.repeat(500)+'🧪 LATE_INTEREST',skills:Array.from({length:60},(_,i)=>({name:`Skill ${i+1}`,level:'experienced',source:'github',confirmed:true})),coursework:Array.from({length:60},(_,i)=>`Course ${i+1}`),additional_majors:Array.from({length:12},(_,i)=>`Major ${i+1}`),...overrides});
afterEach(()=>vi.unstubAllGlobals());
describe('complete shared profile input',()=>{
 it('keeps late fields, names, and original direction on every mapped request',()=>{
  const original=profile({research_interests:Array.from({length:30},(_,i)=>`research field ${i+1}`).join(', ')+'; '+ '🧪'.repeat(1100)});
  const wire=toProfileRequest(original);
  expect(wire.hard_skills).toEqual(original.skills);expect(wire.coursework).toEqual(original.coursework);expect(wire.secondary_interests).toEqual(original.additional_majors);
  expect(wire.research_interests_text).toBe(original.research_interests);expect(wire.desired_fields.at(-1)).toBe('🧪'.repeat(1100));expect(wire.desired_fields).toHaveLength(31);
 });
 it('keeps the 60000th Unicode character and rejects the 60001st before any request',async()=>{
  const valid=profile({research_interests:'🧪'.repeat(60000)});expect(toProfileRequest(valid).research_interests_text).toBe(valid.research_interests);
  const invalid=profile({research_interests:valid.research_interests+'尾'});const snapshot=JSON.stringify(invalid);const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
  await expect(getMatches(invalid)).rejects.toMatchObject({code:'PROFILE_INPUT_LIMIT_EXCEEDED',detail:{field:'profile.research_interests_text',actual:60001,limit:60000,unit:'characters'}});
  expect(fetch).not.toHaveBeenCalled();expect(JSON.stringify(invalid)).toBe(snapshot);
 });
 it.each(['hard_skills','coursework','secondary_interests','desired_fields'])('rejects an oversized %s list as a whole',field=>{
  expect(()=>assertProfileInput({[field]:Array(513).fill(field==='hard_skills'?{name:'Python',level:'expert'}:'term')})).toThrow(ProfileInputError);
 });
 it('rejects unpaired Unicode without attempting to replace it',()=>expect(()=>toProfileRequest(profile({research_interests:'prefix\ud800tail'}))).toThrow(ProfileInputError));
 it('leaves normalized aggregate counting to the server rather than trimming',()=>{
  const large=profile({research_interests:'R'.repeat(40000),skills:Array.from({length:512},(_,i)=>({name:'s'.repeat(100)+i,level:'experienced'}))});
  expect(toProfileRequest(large).hard_skills).toHaveLength(512);
 });
 it.each(['en','zh'] as const)('formats allowlisted labels and counts in %s without exposing server input',locale=>{
  const t=(key:string,vars?:Record<string,string|number>)=>translate(locale,key,vars);
  const error=new ApiError(422,'PROFILE_INPUT_LIMIT_EXCEEDED','PRIVATE',false,undefined,{field:'profile.hard_skills.50.name',actual:1001,limit:1000,unit:'characters',input:'PRIVATE'});
  const message=profileInputMessage(error,t)!;expect(message).toContain('51');expect(message).toContain('1001');expect(message).not.toContain('hard_skills');expect(message).not.toContain('PRIVATE');
  expect(profileInputMessage({code:'PROFILE_INPUT_INVALID',detail:{field:'private.secret'}},t)).not.toContain('secret');
 });
 it('parses structured errors past the old 4096 boundary and preserves stream failures without compatibility retry',async()=>{
  const detail={code:'PROFILE_INPUT_LIMIT_EXCEEDED',field:'profile',actual:160001,limit:160000,unit:'characters',message:'PRIVATE'};
  const fetch=vi.fn(async()=>new Response(JSON.stringify({padding:'x'.repeat(5000),detail}),{status:422,headers:{'content-type':'application/json'}}));vi.stubGlobal('fetch',fetch);
  await expect(getMatches(profile())).rejects.toMatchObject({code:detail.code,detail});expect(fetch).toHaveBeenCalledTimes(1);
  try {await generateColdEmailStream(profile(),'op-1');throw Error('should reject');}catch(error){expect(error).toMatchObject({code:detail.code,detail});expect(canFallbackColdEmailStream(error)).toBe(false);}
  expect(fetch).toHaveBeenCalledTimes(2);
 });
 it.each(['github',''])('keeps legacy source %j and does not treat string false as confirmation',source=>{
  const wire=toProfileRequest(profile({skills:[{name:'Python',level:'expert',source,confirmed:'false'} as unknown as ProfileData['skills'][number]]}));
  expect(wire.hard_skills).toEqual([{name:'Python',level:'expert',source}]);
 });
 it('writes review fixtures only when explicitly requested',()=>{
  const out=process.env.B53_PROFILE_FIXTURE_DIR;if(!out)return;mkdirSync(out,{recursive:true});
  const normal=profile();const edge=profile({research_interests:'🧪'.repeat(60000)});const invalid=profile({research_interests:'🧪'.repeat(60001)});
  let failure:unknown;try{toProfileRequest(invalid);}catch(error){failure=error;}
  const aggregate=profile({research_interests:'R'.repeat(40000),skills:Array.from({length:512},(_,i)=>({name:'s'.repeat(100)+i,level:'experienced'}))});
  writeFileSync(out+'/profile-adapter-fixtures.json',JSON.stringify({normal:{profile:normal,request:toProfileRequest(normal)},unicodeBoundary:{profile:edge,request:toProfileRequest(edge)},aggregateBoundary:{profile:aggregate,request:toProfileRequest(aggregate)},rejectedBeforeFetch:{profile:invalid,error:failure}},null,2));
 });
});
