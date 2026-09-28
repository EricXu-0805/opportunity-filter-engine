import { describe, expect, it } from 'vitest';
import golden from '../../../tests/fixtures/lab-context-v2-golden.json';
import old from '../../../tests/fixtures/lab-context-v1-golden.json';
import { labChainFixture } from '../../e2e/lab-fixture';
import { parseLabContext, type LabContext, type LabSnapshotV2 } from './lab-context';
const source=()=>structuredClone(golden) as LabContext & {snapshot:LabSnapshotV2};
const obj=(v:object)=>v as unknown as Record<string,unknown>;
describe('V2 complete website chain',()=>{
 it('accepts the shared Python golden unchanged with all ten research sections',()=>{
  const input=source(),parsed=parseLabContext(input);expect(parsed).toEqual(input);expect(parsed).not.toBe(input);
  expect(parsed?.snapshot?.pages[1].sections).toHaveLength(10);
  expect(parsed?.snapshot?.pages[1].sections[9].text).toContain('TENTH_SECTION_MARKER');
  input.snapshot.source_chain.documents[1].page_title='mutated';expect(parsed?.snapshot).not.toEqual(input.snapshot);
 });
 it('preserves V1 bytes and saved age without upgrading or adding a chain',()=>{
  expect(parseLabContext(old)).toEqual(old);expect(parseLabContext(old)?.snapshot).not.toHaveProperty('source_chain');
  const v=source();v.status='stale';expect(parseLabContext(v)).toEqual(v);
 });
 it('validates historical shape without hardcoding the current Nielsen policy or verifying SHA authenticity',()=>{
  const v=labChainFixture();expect(parseLabContext(v)).toEqual(v);
  v.snapshot.snapshot_version='ls2:'+'f'.repeat(64);expect(parseLabContext(v)).toEqual(v);
 });
 it.each([0,1,2])('accepts canonical absolute observed href for edge %i',i=>{
  const v=source();v.snapshot.source_chain.links[i].raw_href=v.snapshot.source_chain.links[i].to_url;expect(parseLabContext(v)).not.toBeNull();
 });
 const changes:Record<string,(s:LabSnapshotV2)=>void>={
  'unknown snapshot version':s=>obj(s).version=3,
  'wrong policy version':s=>obj(s).policy_version=1,
  'old hash namespace':s=>s.snapshot_version='ls1:'+'a'.repeat(64),
  'unknown source metadata':s=>obj(s).is_read=true,
  'missing chain':s=>delete obj(s).source_chain,
  'unknown chain field':s=>obj(s.source_chain).verified=true,
  'missing document':s=>s.source_chain.documents.pop(),
  'extra document':s=>s.source_chain.documents.push(structuredClone(s.source_chain.documents[0])),
  'wrong document order':s=>s.source_chain.documents.reverse(),
  'redirected document':s=>s.source_chain.documents[1].requested_url+='other/',
  'wrong document title':s=>s.source_chain.documents[3].page_title+='other',
  'mixed observation time':s=>s.source_chain.documents[1].checked_at='2026-09-25T12:00:00Z',
  'malformed body hash':s=>s.source_chain.documents[1].body_sha256='a'.repeat(63),
  'unknown document field':s=>obj(s.source_chain.documents[0]).trusted=true,
  'extra link':s=>s.source_chain.links.push(structuredClone(s.source_chain.links[0])),
  'unknown link field':s=>obj(s.source_chain.links[0]).redirected=false,
  'wrong link order':s=>s.source_chain.links.reverse(),
  'pretend direct profile research link':s=>s.source_chain.links[2].from_url=s.record_source_url,
  'different link destination':s=>s.source_chain.links[2].to_url+='other/',
  'blank anchor':s=>s.source_chain.links[0].anchor_text=' ',
  'oversized anchor':s=>s.source_chain.links[0].anchor_text='字'.repeat(501),
  'wrong identity source':s=>s.source_chain.identity.source_url=s.source_chain.documents[1].source_url,
  'surname-only identity':s=>s.source_chain.identity.full_name='Nielsen',
  'identity casing drift':s=>s.source_chain.identity.full_name='rasmus nielsen',
  'profile identity differs':s=>s.pages[0].identity_text='Other Person',
  'blank role':s=>s.source_chain.identity.role_text=' ',
  'oversized role':s=>s.source_chain.identity.role_text='字'.repeat(2001),
  'unknown identity field':s=>obj(s.source_chain.identity).is_current=true,
  'only profile content':s=>s.pages.pop(),
  'fabricated research identity':s=>obj(s.pages[1]).identity_text=s.identity_name,
  'fabricated research direct link':s=>obj(s.pages[1]).linked_from=null,
  'wrong research page kind':s=>obj(s.pages[1]).kind='lab_website',
  'cross origin team':s=>{const d=s.source_chain.documents[2],link=s.source_chain.links[1];d.requested_url=d.source_url='https://other.example/team/';link.raw_href=link.to_url=d.source_url;s.source_chain.identity.source_url=d.source_url;},
 };
 it.each(Object.entries(changes))('rejects %s',(_name,change)=>{const v=source();change(v.snapshot);expect(parseLabContext(v)).toBeNull();});
 it.each(['team/','//nielsen-lab.github.io/team/','/../team/','/%2e%2e/team/','/team/?x=1','/team/#bio','/team/\\x',
  'https://user@nielsen-lab.github.io/team/','https://nielsen-lab.github.io:443/team/','https://nielsen-lab.github.io/team/../team/',
  'https://nielsen-lab.github.io/team/?','https://nielsen-lab.github.io/team/#',' https://nielsen-lab.github.io/team/'])('rejects normalized or ambiguous raw link %s',raw=>{
  const v=source();v.snapshot.source_chain.links[1].raw_href=raw;expect(parseLabContext(v)).toBeNull();
 });
 it.each(['^','"','<','>','`','{','}','\\','?','#'])('rejects forbidden literal URL/raw-href character %s',character=>{
  const v=source(),d=v.snapshot.source_chain.documents[2],link=v.snapshot.source_chain.links[1];
  d.requested_url=d.source_url='https://nielsen-lab.github.io/team/'+character;
  link.raw_href=link.to_url=d.source_url;v.snapshot.source_chain.identity.source_url=d.source_url;
  expect(parseLabContext(v)).toBeNull();
 });
 it('preserves every Unicode codepoint at exact section, role and total boundaries',()=>{
  const v=source();v.snapshot.pages[0].sections=[{section_id:'s1',heading:'',text:'x'}];
  v.snapshot.pages[1].sections=Array.from({length:6},(_,i)=>({section_id:`s${i+1}`,heading:'',text:'😀'.repeat(i===0?3999:4000)}));
  v.snapshot.source_chain.identity.role_text='😀'.repeat(2000);expect(parseLabContext(v)).not.toBeNull();
  v.snapshot.pages[1].sections[0].text+='😀';expect(parseLabContext(v)).toBeNull();
 });
});
