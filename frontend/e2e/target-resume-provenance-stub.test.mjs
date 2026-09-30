import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validStubTargetResumeProvenance as valid } from './target-resume-provenance-stub.mjs';
function pair(version=3) {
  const doc={id:'doc',opportunity_id:'opp',target_snapshot:{context_version:version+1},base:{master_id:'m',master_revision:1,profile_signature:'p',source_signature:'s',target_signature:'t'}};
  const quote=version===3 ? {field:'lab_text',page_index:0,section_index:0,start:0,end:2,quote:'中😀'}
    : version===2 ? {field:'paper_title',paper_index:0,start:0,end:2,quote:'中😀'}
    : {field:'description',requirement_index:null,start:0,end:2,quote:'中😀'};
  const provenance={version,document_id:'doc',opportunity_id:'opp',base:structuredClone(doc.base),events:[{id:'event',kind:'ai_rewrite',changes:[{
    section_id:'s',block_id:'b',line_id:'l',field:'text',before:'Original',after:'Shorter',reason:'Target relevance',target_evidence:[quote],source_evidence:[],check:null,
  }]}]};
  return {doc,provenance};
}
for (const version of [1,2,3]) test(`accept exact historical/current provenance V${version}`,()=>{const p=pair(version);assert.equal(valid(p.doc,p.provenance),true);});
test('null metadata remains accepted; V3 permits old and paper quote variants',()=>{
 const {doc,provenance}=pair();assert.equal(valid(doc,null),true);
 provenance.events[0].changes[0].target_evidence.push(pair(1).provenance.events[0].changes[0].target_evidence[0],pair(2).provenance.events[0].changes[0].target_evidence[0]);
 assert.equal(valid(doc,provenance),true);
});
const mutations={
 'unknown version':p=>p.provenance.version=4,
 'string version':p=>p.provenance.version='3',
 'V3 on V3 target':p=>p.doc.target_snapshot.context_version=3,
 'V2 on V4 target':p=>p.provenance.version=2,
 'foreign document':p=>p.provenance.document_id='other',
 'foreign target':p=>p.provenance.opportunity_id='other',
 'changed base':p=>p.provenance.base.master_revision=2,
 'unknown envelope field':p=>p.provenance.extra=true,
 'empty events':p=>p.provenance.events=[],
 'duplicate event IDs':p=>p.provenance.events.push(structuredClone(p.provenance.events[0])),
 'empty changes':p=>p.provenance.events[0].changes=[],
 'missing section':p=>p.provenance.events[0].changes[0].section_id=null,
 'text boolean':p=>p.provenance.events[0].changes[0].after=true,
 'manual borrows target quotes':p=>p.provenance.events[0].kind='manual',
 'negative page':p=>p.provenance.events[0].changes[0].target_evidence[0].page_index=-1,
 'string section':p=>p.provenance.events[0].changes[0].target_evidence[0].section_index='0',
 'unsafe page':p=>p.provenance.events[0].changes[0].target_evidence[0].page_index=Number.MAX_SAFE_INTEGER+1,
 'mixed lab-paper keys':p=>p.provenance.events[0].changes[0].target_evidence[0].paper_index=0,
 'missing section index':p=>delete p.provenance.events[0].changes[0].target_evidence[0].section_index,
 'blank quote':p=>p.provenance.events[0].changes[0].target_evidence[0].quote=' ',
 'empty span':p=>p.provenance.events[0].changes[0].target_evidence[0].end=0,
 'V1 cannot hold website quote':p=>{p.provenance.version=1;p.doc.target_snapshot.context_version=2;},
 'invalid check':p=>p.provenance.events[0].changes[0].check={version:'checks-v2'},
 'over total capacity':p=>p.provenance.events[0].changes[0].reason='中'.repeat(90000),
};
for(const [name,mutate] of Object.entries(mutations)) test(`reject ${name} without mutating input`,()=>{
 const p=pair();mutate(p);const before=structuredClone(p);assert.equal(valid(p.doc,p.provenance),false);assert.deepEqual(p,before);
});
