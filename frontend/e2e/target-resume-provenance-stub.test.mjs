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
 'unknown version':p=>p.provenance.version=6,
 'V5 on V4 target':p=>p.provenance.version=5,
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
function generationPair() {
 const p=pair();p.provenance.version=4;
 p.provenance.events[0].generation={version:'target-resume-generation-v1:'+'a'.repeat(64),pipeline_version:'full-target-v6',document_signature:'v1:sha256:'+'b'.repeat(64),request_ids:['request']};
 return p;
}
test('V4 wire record preserves generation metadata and legacy unknown events',()=>{
 const p=generationPair(), before=structuredClone(p);assert.equal(valid(p.doc,p.provenance),true);assert.deepEqual(p,before);
 const legacy=pair().provenance.events[0];legacy.id='older';p.provenance.events.unshift(legacy);
 assert.equal(valid(p.doc,p.provenance),true);assert.equal(Object.hasOwn(legacy,'generation'),false);
 const event=p.provenance.events[1];event.kind='plan';event.generation.pipeline_version='full-target-plan-v6';
 event.changes[0]={...event.changes[0],field:'included',line_id:null,before:true,after:false};
 assert.equal(valid(p.doc,p.provenance),true);
});
test('V4 wire refuses malformed configurations, kind/context mismatch and old-schema smuggling',()=>{
 const good=generationPair().provenance.events[0].generation;
 for (const generation of [null,{}, {...good,extra:true}, {...good,version:good.version+'\n'},
   {...good,pipeline_version:'full-target-plan-v6'}, ...['\n','\r','\u2028','\u2029'].map(s=>({...good,pipeline_version:good.pipeline_version+s})),
   {...good,document_signature:'bad'}, {...good,request_ids:[]}, {...good,request_ids:['same','same']},
   {...good,request_ids:[' ']}, {...good,request_ids:['x'.repeat(81)]}, {...good,request_ids:Array.from({length:1025},(_,i)=>String(i))}]) {
  const p=generationPair();p.provenance.events[0].generation=generation;assert.equal(valid(p.doc,p.provenance),false);
 }
 for(const mutate of [p=>p.provenance.version=3,p=>p.doc.target_snapshot.context_version=3,p=>p.provenance.events[0].kind='manual']) {
  const p=generationPair();mutate(p);assert.equal(valid(p.doc,p.provenance),false);
 }
 const ordered=generationPair(), event=ordered.provenance.events[0];event.kind='target_order';
 event.changes[0]={...event.changes[0],field:'order',line_id:null,before:['a','b'],after:['b','a'],reason:null,target_evidence:[]};
 const plain=structuredClone(ordered);delete plain.provenance.events[0].generation;
 assert.equal(valid(plain.doc,plain.provenance),true);assert.equal(valid(ordered.doc,ordered.provenance),false);
});
test('V4 wire keeps text-review request, pipeline and source signature aligned',()=>{
 const p=generationPair(), event=p.provenance.events[0], g=event.generation;
 event.changes[0].check={version:'target-resume-source-checks-v6',pipeline_version:g.pipeline_version,document_signature:g.document_signature,
  request_id:'request',original:'Original',evidence:{kind:'experience',id:'experience',revision:1}};
 assert.equal(valid(p.doc,p.provenance),true);
 const later=structuredClone(p);later.provenance.events[0].generation.request_ids=['earlier','request'];assert.equal(valid(later.doc,later.provenance),true);
 for(const field of ['request_id','pipeline_version','document_signature']) {
  const changed=structuredClone(p);changed.provenance.events[0].changes[0].check[field]=field==='document_signature'?'v1:sha256:'+'c'.repeat(64):'other';
  assert.equal(valid(changed.doc,changed.provenance),false);
 }
});
function privatePair() {
 const p=pair(1);p.provenance.version=5;p.doc.target_snapshot.context_version=5;
 p.provenance.events[0].generation=generationPair().provenance.events[0].generation;return p;
}
test('V5 wire record keeps generation metadata on a private target and binds no other',()=>{
 const p=privatePair(), before=structuredClone(p);assert.equal(valid(p.doc,p.provenance),true);assert.deepEqual(p,before);
 for(const mutate of [p=>p.doc.target_snapshot.context_version=4,p=>p.provenance.version=4,p=>{p.provenance.version=1;}]) {
  const q=privatePair();mutate(q);assert.equal(valid(q.doc,q.provenance),false);
 }
 const unknown=privatePair();delete unknown.provenance.events[0].generation;assert.equal(valid(unknown.doc,unknown.provenance),true);
});
test('V5 wire cites the description only',()=>{
 for(const quote of [{field:'requirement',requirement_index:0,start:0,end:2,quote:'中😀'},pair(2).provenance.events[0].changes[0].target_evidence[0],
   pair(3).provenance.events[0].changes[0].target_evidence[0]]) {
  const p=privatePair();p.provenance.events[0].changes[0].target_evidence=[quote];assert.equal(valid(p.doc,p.provenance),false);
 }
});
