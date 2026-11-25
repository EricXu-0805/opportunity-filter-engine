import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile, writeFile, mkdtemp } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { createClient } from '@supabase/supabase-js';

const config=JSON.parse(await readFile(process.argv[2],'utf8'));
const url=config.API_URL, anon=config.ANON_KEY;
assert.equal(url,'http://127.0.0.1:54321');
const api=createClient(url,anon,{auth:{persistSession:false,autoRefreshToken:false,detectSessionInUrl:false}});
const {data,error}=await api.auth.signUp({email:randomUUID()+'@example.com',password:randomUUID()+'xA8!'});
assert.ok(!error && data.session && !data.user.is_anonymous);
const bucket=api.storage.from('tracker-attachments'), uid=data.user.id, auth=data.session.access_token;
const key=uid+'/synthetic/compatibility.pdf';
const contents=version=>Buffer.from('%PDF-1.4\nsynthetic '+version+'\n%%EOF');
async function upload(version) {
  const r=await bucket.upload(key,new Blob([contents(version)],{type:'application/pdf'}),{contentType:'application/pdf',upsert:false});
  assert.ok(!r.error && r.data?.id);
}
async function value() {
  const rows=await bucket.list(uid+'/synthetic');
  assert.ok(!rows.error && Array.isArray(rows.data));
  const meta=rows.data.find(row=>row.name==='compatibility.pdf');
  if(!meta) return null;
  const r=await bucket.download(key,{}, {cache:'no-store'});assert.ok(!r.error && r.data);
  return {id:meta.id,etag:meta.metadata.eTag,bytes:Buffer.from(await r.data.arrayBuffer())};
}
async function remove() {const r=await bucket.remove([key]);assert.ok(!r.error);assert.equal(await value(),null);}
const route=url+'/storage/v1/object/tracker-attachments/'+key;
async function put(etag,version) {
  const response=await fetch(route,{method:'PUT',headers:{authorization:'Bearer '+auth,apikey:anon,'Content-Type':'application/pdf','If-Match':etag},body:contents(version)});
  await response.arrayBuffer();return response.status;
}
await upload('original'); const first=await value(); assert.deepEqual(first.bytes,contents('original'));
const wrong='"00000000000000000000000000000000"';assert.notEqual(first.etag,wrong);
const bad=await put(wrong,'updated');const now=await value();
assert.ok((bad>=400&&now.bytes.equals(first.bytes)) || (bad<300&&now.bytes.equals(contents('updated'))));
console.log('REST mismatched destination If-Match: HTTP',bad,'original bytes preserved:',now.bytes.equals(first.bytes));
await remove();const missing=await put(first.etag,'absent');const added=await value();
assert.ok((missing>=400&&added===null)||(missing<300&&added && added.id!==first.id && added.bytes.equals(contents('absent'))));
console.log('REST valid prior If-Match after deletion: HTTP',missing,'key remained absent:',added===null);
if(added)await remove();
await upload('s3original');const s3first=await value();
const temp=await mkdtemp(join(tmpdir(),'ofe-storage-probe-'));const body=join(temp,'synthetic.pdf');
await writeFile(body,contents('s3update'));
const access=config.S3_PROTOCOL_ACCESS_KEY_ID??config.S3_ACCESS_KEY,secret=config.S3_PROTOCOL_ACCESS_KEY_SECRET??config.S3_SECRET_KEY;
assert.ok(access && secret,'local S3 credentials missing; status names only '+Object.keys(config).join(','));
const env={...process.env,AWS_ACCESS_KEY_ID:access,AWS_SECRET_ACCESS_KEY:secret,AWS_DEFAULT_REGION:config.S3_PROTOCOL_REGION??config.S3_REGION??'local',AWS_MAX_ATTEMPTS:'1',AWS_EC2_METADATA_DISABLED:'true',AWS_REQUEST_CHECKSUM_CALCULATION:'when_required',AWS_RESPONSE_CHECKSUM_VALIDATION:'when_required',AWS_PAGER:''};
const s3=op=>spawnSync('aws',['--endpoint-url',url+'/storage/v1/s3','s3api',...op,'--bucket','tracker-attachments','--key',key],{env,encoding:'utf8'});
const baseline=s3(['head-object']);assert.equal(baseline.status,0,'S3 plain HeadObject control did not succeed');
const staleHead=s3(['head-object','--if-match',wrong]);
console.log('S3 mismatched If-Match on HEAD rejected:',staleHead.status!==0);
const normal=s3(['put-object','--body',body,'--content-type','application/pdf']);
assert.equal(normal.status,0,'S3 plain PutObject control did not succeed');assert.deepEqual((await value()).bytes,contents('s3update'));
await writeFile(body,contents('conditional'));
const conditional=s3(['put-object','--body',body,'--content-type','application/pdf','--if-match',wrong]);
assert.ok(!conditional.stderr.includes('Unknown options'),'installed AWS CLI cannot send PutObject If-Match');
const after=await value();
assert.ok(conditional.status===0?after.bytes.equals(contents('conditional')):after.bytes.equals(contents('s3update')));
console.log('S3 mismatched destination If-Match on PUT accepted:',conditional.status===0,'original bytes preserved:',after.bytes.equals(contents('s3update')));
await remove();
const absent=s3(['put-object','--body',body,'--content-type','application/pdf','--if-match',s3first.etag]);
const afterDelete=await value();
assert.ok(absent.status===0?afterDelete?.bytes.equals(contents('conditional')):afterDelete===null);
console.log('S3 prior destination If-Match on a deleted key accepted:',absent.status===0,'key remained absent:',afterDelete===null);
