import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { readFile, mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { setTimeout as pause } from 'node:timers/promises';
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';

const { API_URL: url, ANON_KEY: anon }=JSON.parse(await readFile(process.argv[2],'utf8'));
assert.equal(url,'http://127.0.0.1:54321');
const site='http://127.0.0.1:3100';
async function account() {
  const api=createClient(url,anon,{auth:{persistSession:false,autoRefreshToken:false,detectSessionInUrl:false}});
  const signup=await api.auth.signUp({email:randomUUID()+'@example.com',password:randomUUID()+'!9Ab'});
  assert.ok(!signup.error && signup.data.session && !signup.data.user.is_anonymous);
  return {api,uid:signup.data.user.id,session:signup.data.session};
}
async function rows(account) {
  const {data,error}=await account.api.from('push_subscriptions').select('device_id,endpoint');
  assert.ok(!error,'push row read: '+(error?.code||''));
  assert.ok(data.every(r=>r.device_id===account.uid),'unexpected owner visibility');
  return data.map(r=>r.endpoint);
}
const a=await account(), b=await account();
assert.notEqual(a.uid,b.uid);
assert.deepEqual(await rows(a),[]);assert.deepEqual(await rows(b),[]);
console.log('PASS two isolated non-anonymous GoTrue accounts authenticated and read their own empty table');
const next=spawn(process.execPath,['node_modules/next/dist/bin/next','dev','--webpack','--hostname','127.0.0.1','--port','3100'],{cwd:'frontend',stdio:'ignore',env:{...process.env,NEXT_TELEMETRY_DISABLED:'1',NEXT_PUBLIC_SUPABASE_URL:url,NEXT_PUBLIC_SUPABASE_ANON_KEY:anon,BACKEND_URL:'http://127.0.0.1:8100'}});
const profile=await mkdtemp(join(tmpdir(),'m48-chromium-'));
await mkdir(join(profile,'Default'));await writeFile(join(profile,'Default','Preferences'),JSON.stringify({profile:{default_content_setting_values:{notifications:1}}}));
const ctx=await chromium.launchPersistentContext(profile,{channel:'chromium',locale:'en-US'});
let page;
try {
  let ready=false;
  for(let i=0;i<90;i++){try{if((await fetch(site+'/dashboard')).ok){ready=true;break;}}catch{}await pause(1000);}
  assert.ok(ready,'dashboard did not start');
  const allowed=new Set(['localhost','127.0.0.1']);
  let failWrites=false,failedPosts=0,posts=0;
  await ctx.route('**/*',async route=>{
    const req=route.request(),u=new URL(req.url());
    if(!allowed.has(u.hostname))return route.abort();
    if(u.pathname==='/rest/v1/push_subscriptions'){
      if(req.method()==='POST'){posts++;if(failWrites){failedPosts++;return route.fulfill({status:503,json:{code:'fixture',message:'Controlled availability failure'}});}}
      return route.continue();
    }
    if(u.pathname.startsWith('/auth/v1/'))return route.continue();
    if(u.pathname.startsWith('/rest/v1/'))return route.fulfill({json:[]});
    if(u.pathname.endsWith('/push/vapid-public-key'))return route.fulfill({json:{key:'AQID'}});
    if(u.pathname.startsWith('/api/'))return route.fulfill({json:{}});
    return route.continue();
  });
  // Only the external Web Push transport is synthetic. Its state persists across
  // pages like a browser subscription, and unsubscribe can remove only its captured id.
  await ctx.addInitScript(()=>{
    if(!location.origin.startsWith('http://127.0.0.1:3100'))return;
    localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_lang','en');
    function subscription(id) {
      const endpoint='https://fixture.invalid/subscription/'+id;
      return {endpoint,toJSON:()=>({endpoint,keys:{p256dh:'synthetic-public-'+id,auth:'synthetic-auth-'+id}}),unsubscribe:async()=>{
        if(localStorage.getItem('m48-transport')!==id)return false;
        localStorage.removeItem('m48-transport');localStorage.setItem('m48-retired-'+id,'1');return true;
      }};
    }
    Object.defineProperty(PushManager.prototype,'getSubscription',{value:async()=>{const id=localStorage.getItem('m48-transport');return id?subscription(id):null;}});
    Object.defineProperty(PushManager.prototype,'subscribe',{value:async()=>{let id=localStorage.getItem('m48-transport');if(!id){id=crypto.randomUUID();localStorage.setItem('m48-transport',id);}return subscription(id);}});
  });
  page=await ctx.newPage();page.setDefaultTimeout(25000);
  // Establish the actual, locally issued sessions the same way the SDK restores them on load.
  await page.route('**/m48-session-fixture',r=>r.fulfill({contentType:'text/html',body:'<title>Session fixture</title>'}));
  await page.goto(site+'/m48-session-fixture');
  await page.evaluate(s=>localStorage.setItem('ofe_auth',JSON.stringify(s)),a.session);
  await page.goto(site+'/dashboard');
  const turnOn=()=>page.getByRole('button',{name:'Enable notifications',exact:true});
  const on=()=>page.getByRole('button',{name:'Notifications on',exact:true});
  await turnOn().click(); await on().waitFor();
  const aRows=await rows(a);
  assert.equal(aRows.length,1);assert.deepEqual(await rows(b),[]);
  console.log('PASS account A enrolled through Dashboard; A read its row, B could not read it');
  await page.evaluate(s=>localStorage.setItem('ofe_auth',JSON.stringify(s)),b.session);
  await page.reload();
  await turnOn().waitFor();
  const aId=aRows[0].split('/').at(-1);
  await page.waitForFunction(id=>localStorage.getItem('m48-retired-'+id)==='1',aId);
  assert.deepEqual(await rows(b),[]);assert.deepEqual(await rows(a),aRows);
  console.log('PASS direct A-to-B account restoration retired A transport; the stale A row stayed private');
  failWrites=true;
  await turnOn().click();await page.getByText("Couldn't turn on notifications. Try again.",{exact:true}).waitFor();
  assert.ok(failedPosts>0);assert.deepEqual(await rows(b),[]);
  failWrites=false;
  await turnOn().click();await on().waitFor();
  const bRows=await rows(b);assert.equal(bRows.length,1);assert.notEqual(aRows[0],bRows[0]);
  assert.deepEqual(await rows(a),aRows);assert.ok(posts>failedPosts);
  console.log('PASS B received a write failure, retained zero database rows, retried through Dashboard and committed a distinct endpoint');
  await page.close();page=await ctx.newPage();await page.goto(site+'/dashboard');
  await on().waitFor();assert.deepEqual(await rows(b),bRows);assert.deepEqual(await rows(a),aRows);
  console.log('PASS reopened Dashboard restored B’s subscribed state; independent authenticated readbacks showed exactly one distinct row per owner');
} catch(e) {
  if(page && !page.isClosed())console.log('Dashboard diagnostic',await page.locator('button').allTextContents().then(v=>v.filter(s=>/notifica|retry/i.test(s)).slice(0,12)));
  throw e;
}finally{await ctx.close();next.kill();}
