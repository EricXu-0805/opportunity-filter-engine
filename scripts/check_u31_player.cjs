const path=require('node:path');
const [frontend,site]=process.argv.slice(2);
const {chromium,expect}=require(path.join(frontend,'node_modules/@playwright/test'));
(async()=>{
 const browser=await chromium.launch({channel:'chrome',args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 try{
  for(const [lang,width,height] of [['en',1280,800],['zh',1280,800],['en',390,844],['zh',390,844]]){
   const ctx=await browser.newContext({viewport:{width,height},serviceWorkers:'block'});
   if(site==='https://joinalab.com'){
    await ctx.route('**/*',route=>{
     const req=route.request();
     if(new URL(req.url()).origin===site && ['GET','HEAD','OPTIONS'].includes(req.method()))return route.continue();
     return route.abort();
    });
   }
   await ctx.addCookies([{name:'ofe_lang',value:lang,url:site}]);
   await ctx.addInitScript(l=>{localStorage.setItem('ofe_lang',l);localStorage.setItem('ofe_onboarding_seen','1')},lang);
   const p=await ctx.newPage();
   const paths=[];
   p.on('response',r=>{if(new URL(r.url()).pathname.startsWith('/demo/'))paths.push([new URL(r.url()).pathname,r.status()])});
   await p.goto(site+'/about',{waitUntil:'domcontentloaded'});
   const video=p.locator('video');
   await expect(video).toHaveCount(1);await expect(video).toBeHidden();
   const btn=p.getByText(lang==='en'?'Watch how to find and save a match':'观看如何查找并收藏匹配机会',{exact:true});await btn.click();
   await expect(video).toBeVisible();await video.evaluate(v=>v.play());
   await p.waitForFunction(()=>document.querySelector('video').currentTime>0.4);
   const page=await video.evaluate(v=>{v.pause();return {duration:v.duration,paused:v.paused,width:v.videoWidth,height:v.videoHeight,captions:[...v.textTracks].map(t=>[t.language,t.mode,t.cues?.length??0]),overflow:document.documentElement.scrollWidth>innerWidth+1}});
   if(page.duration<22||page.duration>23||!page.paused||page.width!==980||page.height!==630||page.overflow||!page.captions.some(([l,m,n])=>l===lang&&m==='showing'&&n===5))throw new Error(JSON.stringify(page));
   const link=p.getByRole('link',{name:lang==='en'?'Start my match':'开始我的匹配'});await expect(link).toHaveAttribute('href','/');
   await link.click();await p.waitForURL(site+'/');
   console.log('Playback and start route',JSON.stringify({lang,width,height,media:paths,page}));
   await ctx.close();
  }
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
