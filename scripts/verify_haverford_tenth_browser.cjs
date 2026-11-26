const {chromium} = require("playwright");
const sha="85f20cfad2dbb0f0600cdecdc14c976cf100f913";
(async()=>{
 const evidence=await (await fetch("https://raw.githubusercontent.com/EricXu-0805/opportunity-filter-engine/2703b59c7714a2e9902f0ec8ceec74f837032aa6/data/audits/m64-haverford-two-missing-departments-2026-11-26.json")).json();
 const browser=await chromium.launch({executablePath:"/usr/bin/google-chrome",headless:true,args:["--no-sandbox","--disable-dev-shm-usage"]});
 const context=await browser.newContext({locale:"en-US",serviceWorkers:"block"});
 await context.route("**/*",route=>{
   const r=route.request(),u=new URL(r.url());
   if(u.hostname==="joinalab.com" && ["GET","HEAD","OPTIONS"].includes(r.method()))return route.continue();
   return route.abort();
 });
 const page=await context.newPage(), rows=[];
 for (const [dept,records] of Object.entries(evidence.site_role_and_person_link_by_card)) {
   for(const rec of records.filter(x=>x.selected_id)){
     const url="https://joinalab.com/opportunities/"+rec.selected_id;
     await page.goto(url,{waitUntil:"domcontentloaded"});
     const heading=page.getByRole("heading",{name:rec.name,exact:true}).first();
     await heading.waitFor({state:"visible",timeout:25000});
     const rank=page.getByText(rec.rank,{exact:true}).first();
     await rank.waitFor({state:"visible",timeout:16000});
     const mark=await page.locator("html").getAttribute("data-release-sha");
     const links=await page.locator("a").evaluateAll(a=>a.map(x=>x.href));
     if(mark!==sha || !links.includes(rec.profile))throw Error("Source or release mismatch "+rec.selected_id);
     rows.push({department:dept,original_id:rec.selected_id,visible_person:true,visible_official_rank:true,personal_url_matches_source:true,product_page:url,release:mark});
   }
 }
 console.log("HAVERFORD RELEASE RECEIPT",JSON.stringify({release:sha,observed_utc:new Date().toISOString(),rows}));
 console.log("Rendered and verified",rows.length);await browser.close();
})().catch(e=>{console.error(e.message);process.exit(1)});
