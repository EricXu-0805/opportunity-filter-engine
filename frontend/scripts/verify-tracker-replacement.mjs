import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createClient } from '@supabase/supabase-js';

const { API_URL: url, ANON_KEY: anon } = JSON.parse(await readFile(process.argv[2], 'utf8'));
assert.equal(url, 'http://127.0.0.1:54321');
assert.ok(anon);
const mime = 'application/pdf';
let loseNextPut = false;
let droppedReceipts = 0;
function client() {
  return createClient(url, anon, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: { fetch: async (input, init) => {
      const request = new Request(input, init);
      assert.equal(new URL(request.url).origin, url);
      const response = await fetch(request);
      if (loseNextPut && request.method === 'PUT' && new URL(request.url).pathname.startsWith('/storage/v1/object/')) {
        loseNextPut = false;
        assert.ok(response.ok, 'the simulated lost receipt must come after a real successful commit');
        await response.arrayBuffer();
        droppedReceipts++;
        throw new TypeError('simulated lost receipt');
      }
      return response;
    } },
  });
}
async function signedIn() {
  const api = client();
  const { data, error } = await api.auth.signUp({ email: randomUUID() + '@example.com', password: randomUUID() + 'aB8!' });
  assert.ok(!error && data.session && data.user && !data.user.is_anonymous, 'disposable formal account');
  return { api, uid: data.user.id, bucket: api.storage.from('tracker-attachments') };
}
const owner = await signedIn(), other = await signedIn();
const prefix = owner.uid + '/opportunity';
const original = 'attachment.pdf', path = prefix + '/' + original;
const bytes = version => Buffer.from('%PDF-1.4\n%synthetic payload ' + version + '\n%%EOF\n');
const file = version => new File([bytes(version)], 'new-local-name.pdf', { type: mime });
async function download(expected) {
  const { data, error } = await owner.bucket.download(path);
  assert.ok(!error && data, 'download should return bytes');
  assert.deepEqual(Buffer.from(await data.arrayBuffer()), bytes(expected));
}
async function list() {
  const { data, error } = await owner.bucket.list(prefix);
  assert.ok(!error && Array.isArray(data), 'list success');
  return data.find(x => x.name === original);
}
async function observe(account = owner) {
  const item = await list();
  assert.ok(item?.id && (item.metadata?.eTag || item.updated_at));
  const { data, error } = await account.api.rpc('tracker_attachment_replace_version', {
    p_path: path, p_id: item.id, p_etag: item.metadata.eTag || null,
    p_updated_at: item.updated_at || null, p_mime: mime,
  });
  assert.ok(!error, 'preflight RPC failed: ' + (error?.code || ''));
  return { id: item.id, version: data, mime };
}
function write(guard, version, account = owner) {
  return account.bucket.update(path, file(version), { contentType: mime, metadata: { ofe_replace: guard } });
}
async function rejected(attempt) {
  let response;
  try { response = await attempt; } catch { return; }
  assert.ok(response.error && !response.data, 'write unexpectedly accepted');
}
const put = await owner.bucket.upload(path, file(0), { upsert:false, contentType:mime });
assert.ok(!put.error && put.data?.id && put.data.path === path);
await download(0);
const guard0 = await observe();
assert.equal(guard0.id, put.data.id); assert.equal(typeof guard0.version, 'string');
assert.equal((await observe(other)).version, null);
await rejected(write(guard0, 80, other)); await download(0);
console.log('PASS original bytes and owner isolation');

const put1 = await write(guard0, 1);
assert.ok(!put1.error, 'guarded replace failed: ' + (put1.error?.message || ''));
assert.deepEqual([put1.data.id, put1.data.path], [guard0.id, path]);
await download(1);
const guard1 = await observe(); assert.equal(guard1.id, guard0.id); assert.notEqual(guard1.version, guard0.version);
await rejected(write(guard0, 90)); await download(1);
console.log('PASS real guarded replacement, stable ID/path, stale write cannot alter downloaded bytes');

loseNextPut = true;
await rejected(write(guard1, 2)); assert.equal(droppedReceipts, 1);
await download(2);
const guard2 = await observe(); assert.notEqual(guard2.version, guard1.version);
await rejected(write(guard1, 91)); await download(2);
console.log('PASS lost successful receipt, fresh listing and readback distinguish committed bytes from a rejected replay');

assert.ok(!(await owner.bucket.remove([path])).error);
await rejected(write(guard2, 92)); assert.equal(await list(), undefined);
assert.ok((await owner.bucket.download(path)).error);
const newObject = await owner.bucket.upload(path, file(3), { upsert:false, contentType:mime });
assert.ok(!newObject.error && newObject.data?.id !== guard2.id);
await rejected(write(guard2, 93));
await download(3);
assert.equal((await list()).id, newObject.data.id);
console.log('PASS deleted key stays absent; a subsequent new object at the same key retains its ID and bytes');
const together = await observe();
const results = await Promise.allSettled([write(together, 4), write(together, 5)]);
const winners = results.flatMap((r, i) => r.status === 'fulfilled' && !r.value.error ? [i] : []);
assert.equal(winners.length, 1, 'two competing conditional writes must have one winner');
await download(4 + winners[0]);
assert.equal((await list()).id, together.id);
console.log('PASS concurrent writers produce exactly one winner and that winner downloads intact');
