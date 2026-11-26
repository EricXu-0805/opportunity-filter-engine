import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFileSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';

const script = readFileSync('public/sw.js');
const server = createServer((req, res) => {
  if (req.url.startsWith('/sw.js')) res.writeHead(200, {'Content-Type':'application/javascript'}).end(script);
  else res.writeHead(200, {'Content-Type':'text/html'}).end('<title>Worker diagnostic</title>');
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
const origin = 'http://127.0.0.1:'+server.address().port;
const mode=process.env.FIXTURE_MODE;
console.log('Fixture mode', mode);
const dir=mkdtempSync(join(tmpdir(),'ofe-push-'));
mkdirSync(join(dir,'Default'));
writeFileSync(join(dir,'Default','Preferences'),JSON.stringify({profile:{default_content_setting_values:{notifications:1}}}));
const ctx = await chromium.launchPersistentContext(dir,{...(mode==='shell-persistent'?{}:{channel:'chromium'}),headless:mode!=='chrome-headed'});
try {
  const page=await ctx.newPage();
  const cdp=await ctx.newCDPSession(page);
  let id;
  cdp.on('ServiceWorker.workerRegistrationUpdated', ({registrations}) => {
    for(const r of registrations) if(r.scopeURL===origin+'/' && !r.isDeleted) id=r.registrationId;
  });
  await cdp.send('ServiceWorker.enable');
  await page.goto(origin+'/');
  const [worker]=await Promise.all([ctx.waitForEvent('serviceworker'),page.evaluate(async()=>{
    await navigator.serviceWorker.register('/sw.js?account=1');
    await navigator.serviceWorker.ready;
    const cache=await caches.open('ofe-push-binding-v1');
    await cache.put('/.ofe/push-owner',new Response(JSON.stringify({uid:'B',enabled:true})));
  })]);
  console.log('Before delivery',await worker.evaluate(async()=>{
    self.probe=[];
    const original=ExtendableEvent.prototype.waitUntil;
    ExtendableEvent.prototype.waitUntil=function(work) {
      const r=this.data?.json()?.tag||this.type;
      self.probe.push(['waitUntil', r]); work.then(()=>self.probe.push(['handled',r]),e=>self.probe.push(['failure',r,String(e)]));
      return original.call(this,work);
    };
    const show=self.registration.showNotification.bind(self.registration);
    self.registration.showNotification=async(t,opts)=>{
      self.probe.push(['display',opts.tag]); try { await show(t,opts); self.probe.push(['native-completed',opts.tag]); } catch(e) { self.probe.push(['native-rejected',opts.tag,String(e)]); throw e; }
    };
    self.addEventListener('push',e=>self.probe.push(['arrived',e.data?.json()?.tag]));
    const cache=await caches.open('ofe-push-binding-v1');
    return {url:self.location.href,locks:!!navigator.locks,owner:await (await cache.match('/.ofe/push-owner')).json(),permission:(await navigator.permissions.query({name:'notifications'})).state,active:self.registration.active?.state,subscription:!!await self.registration.pushManager.getSubscription()};
  }));
  console.log('CDP registration',id);
  for(const recipient of ['A','B']) await cdp.send('ServiceWorker.deliverPushMessage',{origin,registrationId:id,data:JSON.stringify({recipient,title:'local fixture',tag:'cdp-'+recipient})});
  await pause(1200);
  console.log('After CDP',await worker.evaluate(async()=>({events:self.probe.slice(),notifications:(await self.registration.getNotifications()).map(n=>n.tag)})));
  console.log('After local browser events',await worker.evaluate(async()=>{
    for(const recipient of ['A','B']){
      const event=new PushEvent('push',{data:JSON.stringify({recipient,title:'isolated',tag:'dispatch-'+recipient})});
      let work;
      Object.defineProperty(event,'waitUntil',{value:p=>{work=p;}});
      self.dispatchEvent(event);
      if(!work) throw new Error('Worker missed event');
      try {await work;} catch(e){self.probe.push(['event-error',String(e)]);}
    }
    return {events:self.probe.slice(),notifications:(await self.registration.getNotifications()).map(n=>n.tag)};
  }));
  console.log('Native control',await page.evaluate(async()=>{
    const registration=await navigator.serviceWorker.ready;
    try {await registration.showNotification('Local diagnostic',{tag:'control'}); return {notifications:(await registration.getNotifications()).map(n=>n.tag)};} catch(e){return String(e);}
  }));
} finally {await ctx.close(); server.close();}
