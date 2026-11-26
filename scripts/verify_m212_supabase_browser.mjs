import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { setTimeout as wait } from 'node:timers/promises';
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';

const { API_URL: api, ANON_KEY: key } = JSON.parse(await readFile(process.argv[2], 'utf8'));
assert.equal(api, 'http://127.0.0.1:54321');
const site = 'http://127.0.0.1:3100';
const client = () => createClient(api, key, {auth: {persistSession: false, autoRefreshToken: false}});
const owner = client(), concurrent = client();
const credentials = {email: randomUUID()+'@example.com', password: randomUUID()+'2aA!'};
const {data: registration, error: signupError} = await owner.auth.signUp(credentials);
assert.equal(signupError?.message, undefined);
const {data: second, error: authError} = await concurrent.auth.signInWithPassword(credentials);
assert.equal(authError?.message, undefined);
assert.equal(registration.user.id, second.user.id);
const jwtId = token => JSON.parse(Buffer.from(token.split('.')[1],'base64url')).session_id;
assert.ok(jwtId(registration.session.access_token));
assert.notEqual(jwtId(registration.session.access_token), jwtId(second.session.access_token));
const uid = registration.user.id, old = {name:'PyTorch', source:'github', level:'experienced'};
const git = {name:'Git', level:'expert', confirmed:true};
const evidence = 'repo vision: topic pytorch';
const expected = [{...old, evidence}, git];
const profile = {name:'Synthetic M212', home_school:'uiuc', search_weight:50, additional_majors:[], experience_entries:[], resume_master:null, institution:'UIUC - University of Illinois Urbana-Champaign', college:'Grainger College of Engineering', grade:'Sophomore',major:'Computer Science',
  research_interests:'computing',github_url:'https://github.com/m212-fixture', skills:[old],coursework:[],seeking_types:['research'],is_international:false};
async function commit(c, revision, patch) {
  const {data,error}=await c.rpc('commit_profile_patch_cas',{p_expected_device_id:uid,p_expected_revision:revision,p_patch:patch});
  assert.equal(error?.message,undefined); assert.equal(data.status,'applied'); return data;
}
assert.equal((await commit(owner,0,profile)).revision,1);
const backend=createServer((req,res)=>{
  res.writeHead(200,{'content-type':'application/json'});
  res.end(JSON.stringify(req.url.includes('/resume/github/')?{username:'m212-fixture',repo_count:1,extracted_skills:['PyTorch'],
    skill_evidence:[{skill:'PyTorch',repo:'vision',field:'topic',value:'pytorch'}]}:{}));
});
await new Promise(resolve=>backend.listen(8100,'127.0.0.1',resolve));
const next=spawn(process.execPath,['node_modules/next/dist/bin/next','dev','--webpack','--hostname','127.0.0.1','--port','3100'],
  {cwd:'frontend',env:{...process.env,NEXT_TELEMETRY_DISABLED:'1',NEXT_PUBLIC_SUPABASE_URL:api,NEXT_PUBLIC_SUPABASE_ANON_KEY:key,BACKEND_URL:'http://127.0.0.1:8100'},stdio:'ignore'});
const browser=await chromium.launch();
const report = [];
const rowStatus = [];
async function context(first) {
  const ctx=await browser.newContext({serviceWorkers:'block'});
  await ctx.addInitScript(session=>{
    localStorage.setItem('ofe_auth',JSON.stringify(session)); localStorage.setItem('ofe_lang','en');
    localStorage.setItem('ofe_onboarding_seen','1');
    localStorage.setItem('ofe_school_confirmed',JSON.stringify({slug:'uiuc',ts:new Date().toISOString()}));
  }, registration.session);
  await ctx.route('**/*',async route=>{
    const req=route.request(), u=new URL(req.url());
    if(!['127.0.0.1','localhost'].includes(u.hostname)) return route.abort();
    if(first && u.origin===api && u.pathname==='/rest/v1/rpc/commit_profile_patch_cas' && req.method()==='POST') {
      if (!report.length) {
        assert.equal((await commit(concurrent,1,{skills:[old,git]})).revision,2);
        console.log('Distinct signed-in session wrote Git at database revision 2');
      }
      const response=await route.fetch(), data=await response.json();
      assert.equal(response.status(),200);
      report.push([req.postDataJSON().p_expected_revision,data.status,data.revision]);
      console.log('PostgREST CAS',JSON.stringify(report.at(-1)));
      return route.fulfill({response});
    }
    if(!first && u.origin===api && u.pathname==='/rest/v1/profiles' && req.method()==='GET' && u.searchParams.get('select')?.includes('revision')) {
      const response=await route.fetch(), data=await response.json(), record=Array.isArray(data)?data[0]:data;
      assert.equal(response.status(),200);rowStatus.push(record);return route.fulfill({response});
    }
    return route.continue();
  });
  return ctx;
}
try {
  let ready=false;
  for(let i=0;i<100;i++){try{if((await fetch(site)).ok){ready=true;break;}}catch{}await wait(1000);}
  assert.ok(ready,'local application started');
  const first=await context(true), page=await first.newPage();
  await page.goto(site,{waitUntil:'domcontentloaded'}); page.setDefaultTimeout(45000);
  await page.getByRole('button',{name:'Keep this level for PyTorch (Experienced)'}).waitFor();
  assert.equal(await page.locator('#github_url').inputValue(),profile.github_url);
  await page.locator('#github_url').locator('..').getByRole('button').click();
  for(let i=0;i<300 && report.length<2;i++) await wait(100);
  assert.deepEqual(report,[[1,'conflict',2],[2,'applied',3]]);
  await first.close();
  const fresh=await context(false), reopened=await fresh.newPage();
  await reopened.goto(site,{waitUntil:'domcontentloaded'}); reopened.setDefaultTimeout(45000);
  await reopened.getByRole('button',{name:'Keep this level for PyTorch (Experienced)'}).waitFor();
  await reopened.getByRole('button',{name:'Remove Git',exact:true}).waitFor();
  const source=reopened.locator('summary').filter({hasText:/Inferred from your GitHub \(repo vision, topic pytorch\)/i});
  await source.first().waitFor();
  assert.ok(rowStatus.some(row=>row?.revision===3),'new context read persisted revision');
  assert.deepEqual(rowStatus.find(row=>row.revision===3).profile_data.skills,expected);
  const {data:row,error}=await concurrent.from('profiles').select('profile_data,revision').eq('id',uid).single();
  assert.equal(error?.message,undefined); assert.equal(row.revision,3); assert.deepEqual(row.profile_data.skills,expected);
  console.log('PASS cold Chromium context and independent authenticated database read at revision 3:',JSON.stringify(row.profile_data.skills));
  await fresh.close();
} finally { await browser.close();next.kill('SIGTERM');backend.close(); }
