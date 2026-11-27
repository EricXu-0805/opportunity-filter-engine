import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';

const [statusPath, oldFrontendDir, out] = process.argv.slice(2);
const { API_URL: url, ANON_KEY: anon } = JSON.parse(await readFile(statusPath, 'utf8'));
assert.equal(url, 'http://127.0.0.1:54321');
const ports = { previous: 3101, candidate: 3100 };
const temp = await mkdtemp(join(tmpdir(), 'mixed-attachment-versions-'));
const rel = 'synthetic-opportunity/original.pdf';
const mime = 'application/pdf';
const digest = (value) => createHash('sha256').update(value).digest('hex');
const oldBytes = Buffer.from('%PDF-1.4\nprevious content\n%%EOF');
const newBytes = Buffer.from('%PDF-1.4\nreplaced content\n%%EOF');
const otherBytes = Buffer.from('%PDF-1.4\nsecond synthetic account\n%%EOF');
assert.equal(oldBytes.length, newBytes.length);

async function account(bytes) {
  const api = createClient(url, anon, { auth: { persistSession: false, autoRefreshToken: false } });
  const signed = await api.auth.signUp({email: randomUUID()+'@example.invalid', password: randomUUID()+'9Ab!'});
  assert.ok(!signed.error && signed.data.session && !signed.data.user.is_anonymous, 'Loopback signup');
  const uid = signed.data.user.id;
  const path = uid+'/'+rel;
  const uploaded = await api.storage.from('tracker-attachments').upload(path, new Blob([bytes],{type:mime}),
    {upsert:false,contentType:mime});
  assert.ok(!uploaded.error && uploaded.data.id, 'Synthetic own attachment seeded');
  return {api, path, session:signed.data.session};
}
async function publish(owner) {
  const loaded = await owner.api.rpc('resolve_tracker_attachment_versions',{p_paths:[owner.path]});
  assert.ok(!loaded.error);
  const staged = await owner.api.rpc('stage_tracker_attachment',{p_path:owner.path,
    p_revision:loaded.data[owner.path].revision,p_mime:mime,p_size:newBytes.length});
  assert.ok(!staged.error && staged.data);
  const key=owner.session.user.id+'/'+staged.data;
  const post = await owner.api.storage.from('tracker-attachment-versions').upload(key, new Blob([newBytes],{type:mime}),
    {upsert:false,contentType:mime});
  assert.ok(!post.error);
  const published = await owner.api.rpc('publish_tracker_attachment',{p_id:staged.data});
  assert.ok(!published.error && published.data===true);
}
const owner=await account(oldBytes);
const other=await account(otherBytes);
const browser=await chromium.launch();
const servers=[];
const report=[];
async function openSite(which) {
  const port=ports[which], site='http://127.0.0.1:'+port;
  const cwd=which==='candidate'?resolve('frontend'):resolve(oldFrontendDir);
  const server=spawn(process.execPath,['node_modules/next/dist/bin/next','dev','--webpack','--hostname','127.0.0.1','--port',String(port)],{
    cwd,env:{...process.env,NEXT_TELEMETRY_DISABLED:'1',NEXT_PUBLIC_SUPABASE_URL:url,
      NEXT_PUBLIC_SUPABASE_ANON_KEY:anon,BACKEND_URL:'http://127.0.0.1:8100'},stdio:'ignore'});
  servers.push(server);
  for(let i=0;i<150;i++){
    try{if((await fetch(site+'/account')).ok)return site;}catch{}
    await new Promise(ok=>setTimeout(ok,1000));
  }
  throw Error('The '+which+' account frontend did not start');
}
async function enter(which,site,account) {
  const ctx=await browser.newContext({locale:'en-US',acceptDownloads:true});
  await ctx.addInitScript(s=>{localStorage.setItem('ofe_auth',JSON.stringify(s));
    localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_lang','en');},account.session);
  const services=[];
  await ctx.route('**/*',async route=>{
    const req=route.request(),u=new URL(req.url());
    if(!['127.0.0.1','localhost'].includes(u.hostname))return route.abort();
    const actual= u.pathname.startsWith('/auth/v1/') || u.pathname.startsWith('/storage/v1/') ||
      u.pathname.startsWith('/rest/v1/rpc/') && u.pathname.includes('tracker_attachment');
    if(actual){
      if(req.method()!=='OPTIONS' && !u.pathname.startsWith('/auth/v1/')){
        assert.equal(req.headers().authorization,'Bearer '+account.session.access_token);
        services.push(u.pathname.startsWith('/storage/v1/')?'storage':'attachment catalog');
      }
      return route.continue();
    }
    // Unrelated dashboard tables and the public recommendations API are not part of this read.
    if(u.pathname.startsWith('/rest/v1/'))return route.fulfill({json:[]});
    if(u.pathname.startsWith('/api/'))return route.fulfill({json:{}});
    return route.continue();
  });
  const page=await ctx.newPage();
  page.setDefaultTimeout(50000);
  await page.goto(site+'/account');
  await page.getByRole('button',{name:'Download attachments as ZIP',exact:true}).waitFor();
  return {page,which,services};
}
async function exportZip(client, label, expected, useResolver) {
  const {page,services}=client;
  const start=services.length;
  const done=page.waitForEvent('download',{timeout:90000});
  await page.getByRole('button',{name:'Download attachments as ZIP',exact:true}).click();
  const download=await done;
  assert.ok(!await download.failure());
  const archive=join(temp,String(report.length)+'.zip');await download.saveAs(archive);
  const checksum=execFileSync('python3',['-c',
    'import hashlib,json,sys,zipfile\nwith zipfile.ZipFile(sys.argv[1]) as z:\n assert z.testzip() is None\n r=json.loads(z.read("manifest.json"))["files"]\n assert len(r)==1 and r[0]["originalPath"]==sys.argv[2]\n data=z.read(r[0]["archivePath"])\n sha=hashlib.sha256(data).hexdigest()\n assert sha==r[0]["sha256"] and len(data)==r[0]["size"]\n print(sha)',
    archive,rel],{encoding:'utf8'}).trim();
  assert.equal(checksum,digest(expected),label);
  assert.ok(services.slice(start).includes('storage'),label);
  assert.equal(services.slice(start).includes('attachment catalog'),useResolver,label);
  report.push({step:label,which:client.which,member_sha256:checksum,real_storage:true,used_version_catalog:useResolver});
  console.log('PASS',label);
}
try {
  const previous=await openSite('previous');
  const oldOpen=await enter('previous',previous,owner);
  await exportZip(oldOpen,'pre-publication original',oldBytes,false);
  await publish(owner);
  const next=await openSite('candidate');
  const newOpen=await enter('candidate',next,owner);
  await exportZip(newOpen,'paired frontend current revision',newBytes,true);
  await exportZip(oldOpen,'already-open previous account page after version publication',oldBytes,false);
  const freshOld=await enter('previous',previous,owner);
  await exportZip(freshOld,'fresh old frontend after rolling back the app',oldBytes,false);
  const freshNew=await enter('candidate',next,owner);
  await exportZip(freshNew,'fresh paired frontend recovers the published revision',newBytes,true);
  const separate=await enter('candidate',next,other);
  await exportZip(separate,'second account original only',otherBytes,true);
  await writeFile(out,JSON.stringify({old_application:'e4edf82957625f9573a7af276d3951caa1d54fb5',
    new_application:'a3536b084f0b8dae6ef5469d224a7cef3fe0548b',mode:'loopback GoTrue Storage PostgreSQL and Chromium',
    synthetic_registered_owners:2,steps:report},null,2)+'\n');
} finally {
  await browser.close();
  for(const child of servers)child.kill('SIGTERM');
}
