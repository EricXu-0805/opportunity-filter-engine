const fs = require('node:fs');
const path = require('node:path');
const [frontend, dest] = process.argv.slice(2);
const { chromium, expect } = require(path.join(frontend, 'node_modules/@playwright/test'));
const base = 'http://127.0.0.1:3100';
const db = 'http://127.0.0.1:54321';
const target = 'demo-stream-sensor';
const title = 'Stream Sensor Research Assistant';
const reason = 'Your interest in water sensors aligns with the project’s field measurements.';
const profile = {name:'Alex Rivera', institution:'UIUC', home_school:'uiuc',college:'Grainger College of Engineering',major:'Computer Engineering',grade:'Sophomore',research_interests:'',skills:[{name:'Python',level:'beginner',source:'manual'}],is_international:false,seeking_types:['research'],search_weight:50,coursework:[]};
const opp={id: target,title,organization:'Example Water Lab',opportunity_type:'research',source_type:'campus_program',record_kind:'listing',source:'manual',school:'uiuc',audience:'campus',paid:'unknown',location:'Campus',on_campus:true,source_url:'https://example.invalid/stream-sensors',description_clean:'Help a student team check stream sensor readings and plot changes in water quality.',keywords:['water sensors','Python'],is_rolling:true,target_truth:{listing_state:'open',reference_only:false,actionable:true,accepting_state:'accepting',reason_code:null,verified_at:null,expires_at:null},eligibility:{international_friendly:'unknown',preferred_year:[],majors:[],skills_required:[],citizenship_required:false},application:{application_effort:'medium',requires_resume:'unknown',contact_method:'website'},metadata:{is_active:true,confidence_score:1}};
const item={opportunity_id:target,eligibility_score:87,readiness_score:80,upside_score:85,final_score:84,bucket:'high_priority',reasons_fit:[reason],reasons_gap:[],next_steps:[],opportunity:opp};
const response={total:1,high_priority:1,good_match:0,reach:0,low_fit:0,results:[item],returned_count:1,has_more:false,next_cursor:null,result_set_id:'example-stream-sensors',view_id:'example-view',contract_version:'match-view-v3-faculty-trust',target_truth_contract:'target-truth-v2',view_start:0,filtered_total:1,view_counts:{all:1,high_priority:1,good_match:0,reach:0,starred:0},source_facets:[{source:'manual',count:1}],scope_available:false,ai_refined:false,matcher_version:'fictional-demo'};
(async()=>{
  const signup=await fetch(db+'/auth/v1/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const sess=await signup.json();
  const seeded=await fetch(db+'/rest/v1/rpc/commit_profile_patch_cas',{method:'POST',headers:{'Content-Type':'application/json',authorization:'Bearer '+sess.access_token},body:JSON.stringify({p_expected_device_id:sess.user.id,p_expected_revision:0,p_patch:profile})});
  if ((await seeded.json()).status!=='applied') throw new Error('Demo profile did not seed');
  const browser=await chromium.launch({channel:'chrome',args:['--no-sandbox','--disable-dev-shm-usage']});
  const context=await browser.newContext({viewport:{width:1120,height:720},deviceScaleFactor:1,locale:'en-US',serviceWorkers:'block'});
  await context.addInitScript(({sess})=>{if(!localStorage.getItem('demo_bootstrap')){localStorage.setItem('ofe_auth',JSON.stringify(sess));localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_school_confirmed',JSON.stringify({slug:'uiuc',ts:new Date().toISOString()}));localStorage.setItem('ofe_lang','en');localStorage.setItem('demo_bootstrap','1');}}, {sess});
  let matched=0;
  await context.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.hostname!=='127.0.0.1')return route.abort();
    if(u.pathname==='/api/matches/view'){
      if(route.request().postDataJSON()?.profile?.research_interests_text?.includes('water sensors'))matched++;
      return route.fulfill({json:response});
    }
    return route.continue();
  });
  const p=await context.newPage();p.setDefaultTimeout(30000);
  const links=[], fname='frame-';let seq=0;
  async function frame(seconds){
    const name=fname+String(++seq).padStart(3,'0')+'.png';
    await p.screenshot({path:path.join(dest,name),animations:'disabled'});
    links.push({file:name,seconds});
  }
  const center=async (el,block='center')=>el.evaluate((node,where)=>node.scrollIntoView({block:where,behavior:'instant'}),block);
  try{
    await p.goto(base,{waitUntil:'domcontentloaded'});
    await expect(p.locator('#student_name')).toHaveValue(profile.name);
    await p.evaluate(()=>document.fonts.ready);
    const interest=p.locator('#research_interests');
    await center(interest);await interest.focus();await frame(1.1);
    for(const [value,delay] of [['I want to study ',.28],['I want to study water sensors',.42],['I want to study water sensors and analyze stream data.',3.4]]){
      await interest.fill(value);await frame(delay);
    }
    const submit=p.getByTestId('generate-matches');await center(submit);await expect(submit).toBeEnabled();await submit.hover();await frame(2.5);
    await submit.click();
    await expect(p.getByText(title,{exact:true}).first()).toBeVisible({timeout:40000});
    if(!matched)throw new Error('No normal match request using the student interests');
    await center(p.getByText(title,{exact:true}).first());await frame(3.3);
    const show=p.getByRole('button',{name:'Show details',exact:true}).first();
    await center(show);await show.hover();await frame(2.2);await show.click();
    await expect(p.getByText(reason,{exact:true})).toBeVisible();await center(p.getByText(reason,{exact:true}));await frame(4.1);
    const fav=p.getByRole('button',{name:'Add to favorites',exact:true}).first();
    await center(fav);await fav.hover();await frame(2);await fav.click();
    const done=p.getByRole('button',{name:'Remove from favorites',exact:true}).first();
    await expect(done).toBeVisible();await frame(3.4);
    fs.writeFileSync(path.join(dest,'frames.json'),JSON.stringify(links,null,2));
    console.log('Actual form, match reason and saved favorite verified; '+links.length+' frames.');
  }catch(error){console.log('Capture page:',p.url(),(await p.locator('body').innerText()).slice(-1700));await p.screenshot({path:path.join(dest,'debug.png')});throw error;}
  finally{await browser.close()}
})().catch(err=>{console.error(err);process.exit(1)});
