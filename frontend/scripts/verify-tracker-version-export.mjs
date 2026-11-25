import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFile, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';

const { API_URL: url, ANON_KEY: anon } = JSON.parse(await readFile(process.argv[2], 'utf8'));
const site = 'http://127.0.0.1:3100';
assert.equal(url, 'http://127.0.0.1:54321');
assert.ok(anon);
const tmp = await mkdtemp(join(tmpdir(), 'tracker-export-'));
async function account() {
  const api = createClient(url, anon, {auth:{persistSession:false,autoRefreshToken:false,detectSessionInUrl:false}});
  const { data, error } = await api.auth.signUp({email:randomUUID()+'@example.com',password:randomUUID()+'8Ab!'});
  assert.ok(!error && data.session && data.user && !data.user.is_anonymous);
  return {api,session:data.session, bucket:api.storage.from('tracker-attachments'), uid:data.user.id};
}
const owner = await account(), other = await account();
const files = new Map(), otherFiles = new Map([['other-account/only.pdf','separate owner bytes']]);
for (let i = 0; i < 101; i++) files.set('old-opportunity/'+String(i).padStart(3,'0')+'.pdf', 'unique synthetic bytes '+i);
files.set('old-opportunity/CV.pdf','first original'); files.set('retired/CV.pdf','second original');
files.set('retired/deep/space name.pdf','nested legacy original');
async function upload(account, entries) {
  for (const [path,bytes] of entries) {
    const {data,error} = await account.bucket.upload(account.uid+'/'+path,new Blob([bytes],{type:'application/pdf'}),{contentType:'application/pdf',upsert:false});
    assert.ok(!error && data?.id,'synthetic upload failed '+(error?.statusCode || ''));
  }
}
await upload(owner,files); await upload(other,otherFiles);
const resolved = async rel => {
  const path = owner.uid + '/' + rel;
  const r=await owner.api.rpc('resolve_tracker_attachment_versions',{p_paths:[path]});
  assert.ok(!r.error);return r.data[path];
};
const revisionKey='retired/CV.pdf', deletedKey='old-opportunity/099.pdf';
const mime='application/pdf', versions=owner.api.storage.from('tracker-attachment-versions');
async function stage(rel,bytes) {
  const orig=await resolved(rel); const path=owner.uid+'/'+rel;
  const op=await owner.api.rpc('stage_tracker_attachment',{
    p_path:path,p_revision:orig.revision,p_mime:mime,p_size:Buffer.byteLength(bytes)});
  assert.ok(!op.error && op.data);
  const upload=await versions.upload(owner.uid+'/'+op.data,new Blob([bytes],{type:mime}),{upsert:false,contentType:mime});
  assert.ok(!upload.error);return op.data;
}
const committedBytes='newer synthetic';
assert.equal(committedBytes.length,files.get(revisionKey).length);
const current=await stage(revisionKey,committedBytes);
const publish=await owner.api.rpc('publish_tracker_attachment',{p_id:current});
assert.ok(!publish.error && publish.data === true);
files.set(revisionKey,committedBytes);
const stagedOnly=await stage(revisionKey,'unpublished data');
assert.notEqual(stagedOnly,current);
const tomb=await resolved(deletedKey);
const del=await owner.api.rpc('delete_tracker_attachment',{p_path:owner.uid+'/'+deletedKey,p_revision:tomb.revision});
assert.ok(!del.error && del.data===true);files.delete(deletedKey);
assert.equal(await resolved(deletedKey),null);
const legacy=await owner.bucket.download(owner.uid+'/'+deletedKey);
assert.ok(!legacy.error,'tombstoned anchor remains physically present');
console.log('PASS same-length replacement, staged unpublished bytes and a tombstoned physical legacy object seeded');
const next = spawn(process.execPath, ['node_modules/next/dist/bin/next','dev','--webpack','--hostname','127.0.0.1','--port','3100'],{
  cwd:'frontend', env:{...process.env,NEXT_TELEMETRY_DISABLED:'1',NEXT_PUBLIC_SUPABASE_URL:url,NEXT_PUBLIC_SUPABASE_ANON_KEY:anon,BACKEND_URL:'http://127.0.0.1:8100'},stdio:'ignore',
});
const browser=await chromium.launch();
try {
  let ready=false;
  for(let i=0;i<120;i++){try{if((await fetch(site+'/account')).ok){ready=true;break}}catch{} await new Promise(r=>setTimeout(r,1000));}
  assert.ok(ready,'Account page failed to start');
  for (const [account,expected,inject] of [[owner,files,true],[other,otherFiles,false]]) {
    const ctx=await browser.newContext({locale:'en-US',acceptDownloads:true});
    let failOnce=inject, dl=0, pageReads=0, lastPageReads=0, fileReads=0, versionReads=0, resolveReads=0;
    const external=[];
    await ctx.addInitScript(session=>{
      localStorage.setItem('ofe_auth',JSON.stringify(session));
      localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_lang','en');
    },account.session);
    await ctx.route('**/*',async route=>{
      const req=route.request(), u=new URL(req.url());
      if(!['127.0.0.1','localhost'].includes(u.hostname)){external.push(u.hostname);return route.abort();}
      // The isolated database contains only Storage policies. Empty unrelated account dashboard tables.
      if(u.pathname.endsWith('/rpc/resolve_tracker_attachment_versions') && req.method() !== 'OPTIONS') {
        const keys=req.postDataJSON().p_paths;assert.ok(keys.length>0 && keys.length<=100 && keys.every(k=>k.startsWith(account.uid+'/')));
        assert.equal(req.headers().authorization,'Bearer '+account.session.access_token);resolveReads++; return route.continue();
      }
      if(u.pathname.startsWith('/rest/v1/') && !u.pathname.endsWith('/rpc/resolve_tracker_attachment_versions'))return route.fulfill({json:[]});
      if(u.pathname.startsWith('/api/'))return route.fulfill({json:{}});
      if(u.pathname.startsWith('/storage/v1/') && req.method() !== 'OPTIONS'){
        assert.ok(req.headers().authorization === 'Bearer '+account.session.access_token, 'unexpected Storage caller');
        if(u.pathname.endsWith('/object/list/tracker-attachments')){
          assert.equal(req.method(),'POST');const {prefix,offset}=req.postDataJSON();
          assert.ok(prefix===account.uid || prefix.startsWith(account.uid+'/'));
          pageReads++; if(offset===99)lastPageReads++;
        } else {
          assert.equal(req.method(),'GET');
          if (u.pathname.includes('/tracker-attachment-versions/')){
            assert.ok(inject && u.pathname.endsWith('/tracker-attachment-versions/'+owner.uid+'/'+current));versionReads++;
          } else {
            assert.ok(u.pathname.includes('/tracker-attachments/'+account.uid+'/'));
            assert.ok(!u.pathname.endsWith('/'+revisionKey) && !u.pathname.endsWith('/'+deletedKey));
          }
          fileReads++;
          if(failOnce && u.pathname.endsWith('/003.pdf')){failOnce=false;return route.fulfill({status:503,json:{error:'controlled temporary read failure'}});}
        }
      }
      return route.continue();
    });
    const page=await ctx.newPage();page.setDefaultTimeout(30000);page.on('download',()=>dl++);
    await page.goto(site+'/account');
    const exportButton=page.getByRole('button',{name:'Download attachments as ZIP'});
    await exportButton.waitFor();
    if(inject){
      await exportButton.click();
      await page.getByRole('button',{name:'Retry export'}).waitFor();
      assert.equal(dl,0); assert.equal(failOnce,false);
    }
    const done=page.waitForEvent('download',{timeout:90000});
    await page.getByRole('button',{name:inject?'Retry export':'Download attachments as ZIP'}).click();
    const artifact=await done;
    assert.equal(artifact.suggestedFilename(),'tracker-attachments.zip');
    const target=join(tmp,randomUUID()+'.zip'); await artifact.saveAs(target);
    execFileSync('python3',['-c',`
import hashlib, json, sys, zipfile
expected=json.load(sys.stdin)
with zipfile.ZipFile(sys.argv[1]) as z:
 assert z.testzip() is None
 entries=json.loads(z.read("manifest.json"))["files"]
 assert {r["originalPath"] for r in entries}==set(expected)
 names=[r["archivePath"] for r in entries]
 assert len(entries)==len(set(n.casefold() for n in names))==len(expected)
 assert set(z.namelist())==set(names)|{"manifest.json","SHA256SUMS"}
 for r in entries:
  b=z.read(r["archivePath"]); assert b==expected[r["originalPath"]].encode() and len(b)==r["size"] and hashlib.sha256(b).hexdigest()==r["sha256"]
 sums=dict(line.split("  ",1)[::-1] for line in z.read("SHA256SUMS").decode().splitlines())
 assert set(sums)==set(names)|{"manifest.json"}
 assert all(hashlib.sha256(z.read(n)).hexdigest()==s for n,s in sums.items())`,target],{input:JSON.stringify(Object.fromEntries(expected))});
    assert.equal(dl,1); assert.deepEqual(external,[]); assert.ok(pageReads>=2);
    assert.ok(fileReads>=expected.size); if(inject)assert.ok(lastPageReads>=2);assert.ok(resolveReads >= (inject ? 4 : 2));assert.equal(versionReads, inject ? 1 : 0);
    console.log('PASS browser ZIP uses current bytes, logical paths, SHA-256, and owner RLS, omits tombstones and unpublished objects:',expected.size,'files;',pageReads,'real list requests;',fileReads,'file requests');
    await ctx.close();
  }
} finally {await browser.close();next.kill('SIGTERM');}
