import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';

const { API_URL: url, ANON_KEY: anon } = JSON.parse(await readFile(process.argv[2], 'utf8'));
assert.equal(url,'http://127.0.0.1:54321');
const site = 'http://127.0.0.1:3100', target='uiuc-siebel-ugresearch', name='original.pdf', mime='application/pdf';
const api=createClient(url,anon,{auth:{persistSession:false,autoRefreshToken:false}});
const signup=await api.auth.signUp({email:randomUUID()+'@example.com',password:randomUUID()+'9Ab!'});
assert.ok(!signup.error && signup.data.session && !signup.data.user.is_anonymous);
const session=signup.data.session, path=session.user.id+'/'+target+'/'+name;
const contents=n=>Buffer.from('%PDF-1.4\nattachment '+n+'\n%%EOF');
const original=api.storage.from('tracker-attachments');
assert.ok(!(await original.upload(path,new Blob([contents(0)],{type:mime}),{contentType:mime})).error);
const signedOriginal=(await original.createSignedUrl(path,300)).data.signedUrl;
const opportunity = {id:target,title:'Synthetic opportunity for Tracker acceptance',source_type:'campus_program',record_kind:'listing',
  source:'synthetic',organization:'Synthetic University',department:'Synthetic Department',lab_or_program:'Fixture',
  opportunity_type:'Research',on_campus:true,description_clean:'Synthetic opportunity for attachment testing.',
  school:'uiuc',audience:'campus',url:'http://127.0.0.1:8100/source',source_url:'http://127.0.0.1:8100/source',
  location:'Synthetic Campus',remote_option:'unknown',paid:'unknown',is_rolling:true,keywords:[],
  eligibility:{preferred_year:[],majors:[],skills_required:[],skills_preferred:[],international_friendly:'unknown'},
  application:{contact_method:'unknown',application_effort:'unknown'},metadata:{is_active:true,confidence_score:0.9},
  target_truth:{listing_state:'open',reference_only:false,actionable:true,accepting_state:'accepting',reason_code:null,verified_at:null,expires_at:null}};
const backendPaths=new Set();
const backend=createServer((req,res)=>{
  const path=new URL(req.url,'http://127.0.0.1:8100').pathname;
  backendPaths.add(path);
  const data=path==='/api/opportunities/'+target ? opportunity : path.endsWith('/similar') ? {opportunities:[]} : {status:'ok',last_updated_at:new Date().toISOString()};
  res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));
});
await new Promise(resolve=>backend.listen(8100,'127.0.0.1',resolve));
const server=spawn(process.execPath,['node_modules/next/dist/bin/next','dev','--webpack','--hostname','127.0.0.1','--port','3100'],
  {cwd:'frontend',env:{...process.env,NEXT_TELEMETRY_DISABLED:'1',NEXT_PUBLIC_SUPABASE_URL:url,NEXT_PUBLIC_SUPABASE_ANON_KEY:anon,BACKEND_URL:'http://127.0.0.1:8100'},stdio:'ignore'});
const browser=await chromium.launch();
let activePage; const pageErrors=[];
try{
 let ready=false;for(let i=0;i<150;i++){try{const r=await fetch(site+'/opportunities/'+target);if(r.ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,1000));}
 assert.ok(ready,'normal opportunity detail entry');const ctx=await browser.newContext();let lost=false, uploads=0, publish=0,drop=false;const external=[];
 await ctx.addInitScript(s=>{localStorage.setItem('ofe_auth',JSON.stringify(s));localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_lang','en');},session);
 await ctx.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url());
   if(!['127.0.0.1','localhost'].includes(u.hostname)){external.push(u.hostname);return route.abort();}
   if(u.pathname.startsWith('/rest/v1/rpc/') && /tracker_attachment/.test(u.pathname)){
     if(req.method()==='POST' && u.pathname.endsWith('/publish_tracker_attachment')){publish++;if(drop){drop=false;const r=await route.fetch();assert.equal(await r.json(),true);lost=true;return route.fulfill({status:503,json:{message:'Synthetic missing receipt'}});}}
     return route.continue();
   }
   if(u.pathname.startsWith('/storage/v1/')){if(req.method()==='POST' && u.pathname.includes('/object/tracker-attachment-versions/'))uploads++;return route.continue();}
   if(u.pathname.startsWith('/rest/v1/interactions')){return route.fulfill({json:[{id:'fixture',device_id:session.user.id,opportunity_id:target,interaction_type:'applied',notes:'',created_at:'2026-09-26T12:00:00Z',updated_at:'2026-09-26T12:00:00Z'}]});}
   if(u.pathname.startsWith('/rest/v1/'))return route.fulfill({json:[]});
   if(u.pathname.startsWith('/api/'))return route.fulfill({json:{}});
   return route.continue();
 });
 const page=await ctx.newPage();activePage=page;page.on('pageerror',e=>pageErrors.push(e.message.replace(/https?:[^ ]+|[a-zA-Z0-9_.-]{60,}/g,'[redacted]').slice(0,140)));page.setDefaultTimeout(45000);await page.goto(site+'/opportunities/'+target);
 await page.getByRole('heading',{name:opportunity.title}).first().waitFor();
 const toggle=page.getByRole('button',{name:/Records, notes & reminders/});
 if(await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();
 const panel=page.getByTestId('tracker-attachments');
 async function replace(n){const chooser=page.waitForEvent('filechooser');await panel.getByRole('button',{name:'Replace '+name}).click();await(await chooser).setFiles({name:'revised.pdf',mimeType:mime,buffer:contents(n)});}
 await replace(1);await page.getByTestId('tracker-attachments-notice').filter({hasText:'Replaced '+name}).waitFor();
 async function signedFromUi(n){
   const next=page.waitForResponse(r=>r.request().method()==='POST' && r.url().includes('/object/sign/tracker-attachment-versions/'));
   await panel.getByRole('button',{name:'Open '+name}).click();
   const signed=(await(await next).json()).signedURL;
   const r=await fetch(url+'/storage/v1'+signed,{cache:'no-store'});assert.equal(r.status,200);assert.deepEqual(Buffer.from(await r.arrayBuffer()),contents(n));
 }
 await signedFromUi(1);drop=true;await replace(2);await page.getByTestId('tracker-attachments-error').waitFor();assert.ok(lost);
 await panel.getByRole('button',{name:'Retry list'}).click();await signedFromUi(2);
 assert.equal(uploads,2);assert.equal(publish,2);
 const old=await fetch(signedOriginal,{cache:'no-store'});assert.deepEqual(Buffer.from(await old.arrayBuffer()),contents(0));
 assert.equal(external.length,0);console.log('PASS formal account Tracker UI replaces selected file, opens current signed bytes, recovers after lost publish receipt without replay, and preserves old signed bytes');
 await ctx.close();
} catch (error) {
 console.log('Synthetic public request paths:',[...backendPaths].slice(0,10),'page errors:',pageErrors.slice(0,3));
 if(activePage) console.log('Page state:',await activePage.evaluate(()=>({path:location.pathname, headings:[...document.querySelectorAll('h1,h2')].map(x=>x.textContent?.slice(0,70)).slice(0,6), buttons:[...document.querySelectorAll('button[aria-expanded]')].map(x=>x.textContent?.trim()?.slice(0,55)).slice(0,6)})));
 throw error;
} finally {await browser.close();server.kill('SIGTERM');backend.close();}
