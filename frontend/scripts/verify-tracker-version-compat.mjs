import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'node:http';
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';

const [statusPath, out] = process.argv.slice(2);
const fixture = resolve(statusPath, '..');
const target = 'uiuc-siebel-ugresearch';
const { API_URL: url, ANON_KEY: anon } = JSON.parse(await readFile(statusPath, 'utf8'));
assert.equal(url, 'http://127.0.0.1:54321');
const ports = { previous: 3101, candidate: 3100 };
const temp = await mkdtemp(join(tmpdir(), 'mixed-attachment-versions-'));
const rel = target + '/original.pdf';
const publicTarget=JSON.parse(await readFile('audit-harness/frontend/scripts/compat-tracker-public-target.json','utf8'));
assert.equal(publicTarget.id,target);
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
  const tracking=await api.from('interactions').insert({device_id:uid, opportunity_id:target, interaction_type:'applied'});
  assert.ok(!tracking.error,'Synthetic owner recorded own ordinary Tracker row');
  const uploaded = await api.storage.from('tracker-attachments').upload(path, new Blob([bytes],{type:mime}),
    {upsert:false,contentType:mime});
  assert.ok(!uploaded.error && uploaded.data.id, 'Synthetic own attachment seeded');
  return {api, path, session:signed.data.session};
}
async function publish(owner, bytes = newBytes) {
  const loaded = await owner.api.rpc('resolve_tracker_attachment_versions',{p_paths:[owner.path]});
  assert.ok(!loaded.error);
  const staged = await owner.api.rpc('stage_tracker_attachment',{p_path:owner.path,
    p_revision:loaded.data[owner.path].revision,p_mime:mime,p_size:bytes.length});
  assert.ok(!staged.error && staged.data);
  const key=owner.session.user.id+'/'+staged.data;
  const post = await owner.api.storage.from('tracker-attachment-versions').upload(key, new Blob([bytes],{type:mime}),
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
  const port=ports.candidate, site='http://127.0.0.1:'+port;
  const cwd=resolve('frontend');
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
  const services=[], events=[];
  ctx.on('response',async res=>{
    const u=new URL(res.url()), req=res.request();
    if (u.pathname === '/rest/v1/interactions') events.push(['interaction',res.status(),
      u.searchParams.get('opportunity_id') === 'eq.'+target]);
    else if (u.pathname.startsWith('/rest/v1/rpc/') && u.pathname.includes('tracker_attachment')
      && req.method()==='POST') {
      const d=await res.json().catch(()=>({}));events.push([u.pathname.split('/').pop(),res.status(),
        d.code||null,d.code==='PGRST202'?d.message:null]);
    } else if (u.pathname.startsWith('/storage/v1/object/list/') && req.method()==='POST'){
      const d=await res.json().catch(()=>null);events.push(['own Storage list',res.status(),Array.isArray(d)?d.length:null]);
    }
  });
  await ctx.route('**/*',async route=>{
    const req=route.request(),u=new URL(req.url());
    if(!['127.0.0.1','localhost'].includes(u.hostname))return route.abort();
    const actual= u.pathname === '/rest/v1/interactions' || u.pathname.startsWith('/auth/v1/') || u.pathname.startsWith('/storage/v1/') ||
      u.pathname.startsWith('/rest/v1/rpc/') && u.pathname.includes('tracker_attachment');
    if(actual){
      if(req.method()!=='OPTIONS' && !u.pathname.startsWith('/auth/v1/') && !(req.method()==='GET' && u.pathname.includes('/object/sign/'))){
        assert.equal(req.headers().authorization,'Bearer '+account.session.access_token);
        services.push(u.pathname.startsWith('/storage/v1/')?'storage':u.pathname === '/rest/v1/interactions'?'own Tracker record':'attachment catalog');
      }
      return route.continue();
    }
    // Unrelated dashboard tables and the public recommendations API are not part of this read.
    if(u.pathname.startsWith('/rest/v1/'))return route.fulfill({json:[]});
    if(u.pathname === '/api/opportunities/'+target)return route.fulfill({json:publicTarget});
    if(u.pathname.startsWith('/api/'))return route.fulfill({json:{}});
    return route.continue();
  });
  const page=await ctx.newPage();
  const errors=[];
  page.on('pageerror',error=>errors.push(error.name));
  page.setDefaultTimeout(35000);
  await page.goto(site+'/account');
  try {
    await page.getByRole('button',{name:'Download attachments as ZIP',exact:true}).waitFor();
  } catch(error) {
    console.log('Account gate',new URL(page.url()).pathname, 'errors',errors,'retry visible',
      await page.getByRole('button',{name:/retry/i}).count(),'auth seeded',
      await page.evaluate(()=>Boolean(JSON.parse(localStorage.getItem('ofe_auth')||'null')?.access_token)));
    throw error;
  }
  return {page,which,services,ctx,site,events};
}
async function exportZip(client, label, expected, useResolver) {
  const {page,services}=client;
  const start=services.length;
  const wasRetry=await page.getByRole('button',{name:'Retry export',exact:true}).count()>0;
  const downloadEvent=page.waitForEvent('download',{timeout:90000});
  const done=wasRetry?downloadEvent:Promise.race([downloadEvent,page.getByText(
    'The export could not be verified. Try again for a complete copy.').waitFor({timeout:90000}).then(()=>{
      console.log('Archive diagnostic',label,JSON.stringify(client.events.slice(-18)));
      throw Error('Archive was refused');})]);
  await page.getByRole('button',{name:/^(Download attachments as ZIP|Retry export)$/}).click();
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

const backend=createServer((req,res)=>{
  const path=new URL(req.url,'http://127.0.0.1:8100').pathname;
  res.writeHead(200,{'content-type':'application/json'});
  res.end(JSON.stringify(path.endsWith('/opportunities/'+target) ? publicTarget :
    path.endsWith('/similar') ? [] : {status:'ok',last_updated_at:new Date().toISOString()}));
});
await new Promise(done=>backend.listen(8100,'127.0.0.1',done));
const phase=[];
async function tracker(client) {
  const page=await client.ctx.newPage();
  const document=await page.goto(client.site+'/opportunities/'+target);
  assert.match(document.headers()['content-type'],/text\/html/);
  await page.getByRole('heading',{level:1,name:publicTarget.title}).waitFor();
  const toggle=page.getByRole('button',{name:/Records, notes & reminders|Record, note, remind|Track this opportunity/i});
  if(await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();
  const panel=page.getByTestId('tracker-attachments');
  try{await panel.getByRole('button',{name:'Open original.pdf',exact:true}).waitFor();}
  catch(error){
    console.log('Tracker state',await panel.count(),'error',await page.getByTestId('tracker-attachments-error').count(),
      'empty',await page.getByTestId('tracker-attachments-empty').count(),'signed-out',await page.getByTestId('tracker-attachments-signed-out').count(),
      JSON.stringify(client.events.slice(-18)));throw error;
  }
  assert.equal(await panel.getByRole('button',{name:'Replace original.pdf',exact:true}).count(),0);
  return {page,panel};
}
async function openAndRead(t,bytes,bucket,label) {
  const result=t.page.waitForResponse(r=>r.request().method()==='POST' && r.url().includes('/object/sign/'+bucket+'/'));
  await t.panel.getByRole('button',{name:'Open original.pdf',exact:true}).click();
  const signed=await (await result).json();
  const res=await fetch(url+'/storage/v1'+signed.signedURL,{cache:'no-store'});
  assert.equal(res.status,200);
  const hash=digest(Buffer.from(await res.arrayBuffer()));assert.equal(hash,digest(bytes));
  phase.push({step:label,bucket,sha256:hash,replaceVisible:false});console.log('PASS',label);
}
async function migrate(file, rpcName, api) {
  const { copyFile }=await import('node:fs/promises');
  await copyFile(resolve('staged-schema/supabase/migrations',file),join(fixture,'supabase/migrations',file));
  execFileSync('supabase',['migration','up','--local'],{cwd:fixture,stdio:['ignore','ignore','ignore']});
  // Ask PostgREST to refresh the disposable local schema. No production connection is accepted.
  const status=JSON.parse(await readFile(statusPath,'utf8'));
  const db=new URL(status.DB_URL);assert.equal(db.hostname,'127.0.0.1');
  execFileSync('psql',[status.DB_URL,'-v','ON_ERROR_STOP=1','-c',"NOTIFY pgrst, 'reload schema';"],{stdio:'ignore'});
  const args=rpcName==='resolve_tracker_attachment_versions'?{p_paths:[]}:{};
  for(let i=0;i<30;i++){const r=await api.rpc(rpcName,args);if(!r.error)return;await new Promise(ok=>setTimeout(ok,500));}
  throw Error('disposable schema did not publish '+rpcName);
}
try {
  const site=await openSite('candidate');
  const a=await enter('candidate',site,owner);
  const b=await enter('candidate',site,other);
  const pre=await owner.api.rpc('tracker_attachment_export_marker',{});
  assert.equal(pre.status,404);assert.equal(pre.error.code,'PGRST202');
  await exportZip(a,'pre-migration original ZIP',oldBytes,true);
  await exportZip(b,'pre-migration second account ZIP',otherBytes,true);
  const old=await tracker(a);
  await openAndRead(old,oldBytes,'tracker-attachments','pre-migration Tracker opens original');
  await migrate('20261125183000_tracker_attachment_versions.sql','resolve_tracker_attachment_versions',owner.api);
  let downloads=0;const onDownload=()=>downloads++;a.page.on('download',onDownload);
  const fail=a.page.waitForResponse(r=>r.status()===404 && r.url().includes('/rpc/tracker_attachment_export_marker'));
  const resolveCheck=a.page.waitForResponse(r=>r.status()===200 && r.url().includes('/rpc/resolve_tracker_attachment_versions'));
  await a.page.getByRole('button',{name:'Download attachments as ZIP',exact:true}).click();
  await Promise.all([fail,resolveCheck]);
  await a.page.getByRole('button',{name:'Retry export',exact:true}).waitFor();
  await a.page.getByText('The export could not be verified. Try again for a complete copy.').waitFor();
  assert.equal(downloads,0);a.page.off('download',onDownload);
  phase.push({step:'resolver installed, marker not installed: explicit retry, no ZIP',downloads});
  await migrate('20261126060000_tracker_attachment_export_marker.sql','tracker_attachment_export_marker',owner.api);
  const status=JSON.parse(await readFile(statusPath,'utf8'));
  execFileSync('python3',['staged-schema/scripts/configure_tracker_attachment_versions.py'],{
    env:{...process.env,SUPABASE_URL:url,SUPABASE_SERVICE_ROLE_KEY:status.SERVICE_ROLE_KEY},stdio:'ignore'});
  const stale=await tracker(a);
  await publish(owner);
  await stale.panel.getByRole('button',{name:'Delete original.pdf',exact:true}).click();
  await stale.page.getByTestId('tracker-attachments-error').waitFor();
  const v=await owner.api.rpc('resolve_tracker_attachment_versions',{p_paths:[owner.path]});
  assert.ok(v.data[owner.path].revision.startsWith('v:'));
  phase.push({step:'delete of displayed original refused after a replacement, current revision preserved'});
  const fresh=await tracker(a);
  await openAndRead(fresh,newBytes,'tracker-attachment-versions','current Tracker opens published replacement');
  await exportZip(a,'same account page current revision after migration',newBytes,true);
  const reopened=await enter('candidate',site,owner);
  await exportZip(reopened,'fresh compatibility build returns published replacement',newBytes,true);
  const second=await tracker(b);
  await openAndRead(second,otherBytes,'tracker-attachments','second owner retains own original');
  await exportZip(b,'second owner still exports own original',otherBytes,true);
  let callback;
  const held=new Promise(done=>{ callback=done; });let release;
  const go=new Promise(done=>{ release=done; });
  await fresh.page.route('**/rest/v1/rpc/delete_tracker_attachment',async route=>{callback();await go;await route.continue();});
  const clicking=fresh.panel.getByRole('button',{name:'Delete original.pdf',exact:true}).click();
  await held;const third=Buffer.from('%PDF-1.4\nreplaced again!!\n%%EOF');
  await publish(owner,third);release();await clicking;
  await fresh.page.getByTestId('tracker-attachments-error').waitFor();
  const again=await tracker(a);
  await openAndRead(again,third,'tracker-attachment-versions','real compare-and-set refused concurrent delete and preserved next revision');
  await exportZip(a,'ZIP after real competing publish and rejected delete',third,true);
  await again.panel.getByRole('button',{name:'Delete original.pdf',exact:true}).click();
  await again.page.getByTestId('tracker-attachments-empty').waitFor();
  const tomb=await owner.api.rpc('resolve_tracker_attachment_versions',{p_paths:[owner.path]});
  assert.equal(tomb.data[owner.path],null);phase.push({step:'explicit current revision delete received and singly removed'});
  await writeFile(out,JSON.stringify({allChecksPassed:true,candidate:process.env.CANDIDATE_SHA,schema_source:'a3536b084f0b8dae6ef5469d224a7cef3fe0548b',
    environment:'loopback GoTrue/Postgres/PostgREST/Storage, two real synthetic nonanonymous owners and their real Tracker rows in Chromium; unrelated dashboard data stubbed',
    accountZips:report,trackerAndTransitions:phase},null,2)+'\n');
} catch(error) {
  await writeFile(out,JSON.stringify({allChecksPassed:false,candidate:process.env.CANDIDATE_SHA,
    completedArchives:report,completedTrackerChecks:phase},null,2)+'\n');
  throw error;
} finally { await browser.close();for(const server of servers)server.kill('SIGTERM');backend.close(); }
