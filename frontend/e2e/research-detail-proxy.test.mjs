import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { createResearchDetailProxy } from './research-detail-proxy.mjs';
const canonical = value => Array.isArray(value) ? `[${value.map(canonical).join(',')}]` : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}` : JSON.stringify(value);
const start = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`)));
const stop = server => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); });
test('rejects ambiguous or non-loopback upstream without networking', () => {
  for (const bad of ['https://127.0.0.1:8200','http://example.test:8200','http://user@127.0.0.1:8200','http://127.0.0.1:8200/path','http://127.0.0.1:8200/?x=1']) assert.throws(()=>createResearchDetailProxy(bad));
});
test('SSR and client share exact snapshot; export bytes pass through; clear restores original', async()=>{
  const original = { id:'uiuc-siebel-ugresearch',description_clean:'Local fixture target',writing_target_version:'old',research_context:{version:1,status:'unavailable',snapshot:null} };
  const pdf=Buffer.from('%PDF-real-local-byte-fixture\n');
  const upstream=createServer((req,res)=>{if(req.url.startsWith('/api/resume/full-target/export')){res.writeHead(200,{'Content-Type':'application/pdf'});res.end(pdf);}else if(req.url.startsWith('/api/opportunities/')){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(original));}else{res.writeHead(503);res.end('known upstream error');}});
  const upstreamUrl=await start(upstream);const proxy=createResearchDetailProxy(upstreamUrl);const base=await start(proxy);
  try {
    const stored={version:1,works:[{title:'Synthetic 😀'}]};const context={version:1,status:'available',snapshot:{...stored,snapshot_version:'rs1:'+createHash('sha256').update(canonical(stored)).digest('hex')}};
    const control=base+'/__fixture/research/uiuc-siebel-ugresearch';
    assert.equal((await fetch(control,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({research_context:context})})).status,200);
    const ssr=await(await fetch(base+'/api/opportunities/uiuc-siebel-ugresearch?_release_scope=fixture')).json();
    const browser=await(await fetch(base+'/api/opportunities/uiuc-siebel-ugresearch')).json();
    assert.deepEqual(ssr,browser);assert.deepEqual(ssr.research_context,context);assert.match(ssr.writing_target_version,/^wt1:[a-f0-9]{64}$/);
    assert.deepEqual(Buffer.from(await(await fetch(base+'/api/resume/full-target/export',{method:'POST',body:'fixture'})).arrayBuffer()),pdf);
    assert.equal((await fetch(base+'/api/failure')).status,503);
    assert.equal((await(await fetch(control)).json()).detail_reads.length,2);
    await fetch(control,{method:'DELETE'});assert.deepEqual(await(await fetch(base+'/api/opportunities/uiuc-siebel-ugresearch')).json(),original);
    assert.equal(original.research_context.snapshot,null);
    const bad=structuredClone(context);bad.snapshot.snapshot_version='rs1:'+'a'.repeat(64);
    assert.equal((await fetch(control,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({research_context:bad})})).status,400);
  } finally {await stop(proxy);await stop(upstream);}
});
test('unregistered traffic streams large request bytes and never follows an external redirect', async () => {
  const payload = Buffer.alloc(4 * 1024 * 1024, 0xa7);
  let received = 0;
  const upstream = createServer(async (req, res) => {
    if (req.url === '/redirect') { res.writeHead(307, { Location: 'https://example.invalid/no-fetch' }); res.end(); return; }
    const chunks = [];
    for await (const chunk of req) { received += chunk.length; chunks.push(chunk); }
    res.writeHead(201, { 'Content-Type': 'application/octet-stream' });
    for (const chunk of chunks) res.write(chunk);
    res.end();
  });
  const upstreamUrl = await start(upstream); const proxy = createResearchDetailProxy(upstreamUrl); const base = await start(proxy);
  try {
    const response = await fetch(base + '/api/large-file', { method: 'POST', body: payload });
    assert.equal(response.status, 201);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), payload);
    assert.equal(received, payload.length);
    const redirect = await fetch(base + '/redirect', { redirect: 'manual' });
    assert.equal(redirect.status, 307); assert.equal(redirect.headers.get('location'), 'https://example.invalid/no-fetch');
  } finally { await stop(proxy); await stop(upstream); }
});
