import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createClient } from '@supabase/supabase-js';

const { API_URL: url, ANON_KEY: anon, SERVICE_ROLE_KEY: serviceKey, DB_URL: dbUrl } =
  JSON.parse(await readFile(process.argv[2], 'utf8'));
assert.equal(url, 'http://127.0.0.1:54321');
assert.equal(new URL(dbUrl).hostname, '127.0.0.1');
const options = { auth: { persistSession: false, autoRefreshToken: false } };
const admin = createClient(url, serviceKey, options);
const versionBucket = 'tracker-attachment-versions', anchorBucket = 'tracker-attachments', mime = 'application/pdf';
const bytes = n => Buffer.from('%PDF-1.4\n synthetic ' + n + '\n%%EOF');
const file = n => new Blob([bytes(n)], { type: mime });
let dropPublish = false, lost = 0;
async function account() {
  const api = createClient(url, anon, { ...options, global: { fetch: async (input, init) => {
    const request = new Request(input, init);
    assert.equal(new URL(request.url).origin, url);
    const response = await fetch(request);
    if (dropPublish && request.url.endsWith('/rpc/publish_tracker_attachment')) {
      dropPublish = false;
      assert.equal(await response.json(), true);
      lost++;
      throw new TypeError('synthetic missing receipt');
    }
    return response;
  } } });
  const { data, error } = await api.auth.signUp({ email: randomUUID() + '@example.com', password: randomUUID() + 'aB8!' });
  assert.ok(!error && data.session && !data.user.is_anonymous);
  return { api, uid: data.user.id };
}
function data(response) {
  assert.ok(!response.error, 'fixture request failed: ' + (response.error?.message ?? ''));
  return response.data;
}
const { api, uid } = await account(), other = await account();
const path = uid + '/synthetic/first.pdf';
const original = api.storage.from(anchorBucket), versions = api.storage.from(versionBucket);
const view = async () => data(await api.rpc('resolve_tracker_attachment_versions', { p_paths: [path] }))[path];
const stage = async (rev, n) => data(await api.rpc('stage_tracker_attachment', { p_path: path, p_revision: rev,
  p_mime: mime, p_size: bytes(n).length }));
const upload = async (op, n) => data(await versions.upload(uid + '/' + op, file(n), { upsert: false, contentType: mime }));
const publish = op => api.rpc('publish_tracker_attachment', { p_id: op });
async function verifyBytes(bucket, key, n, user = api) {
  const b = data(await user.storage.from(bucket).download(key, {}, { cache: 'no-store' }));
  assert.deepEqual(Buffer.from(await b.arrayBuffer()), bytes(n));
}
async function signed(bucket, name) {return data(await api.storage.from(bucket).createSignedUrl(name, 300)).signedUrl;}
async function verifySigned(link, n) {
  assert.equal(new URL(link).origin, url);
  const r = await fetch(link, { cache: 'no-store' }); assert.equal(r.status, 200);
  assert.deepEqual(Buffer.from(await r.arrayBuffer()), bytes(n));
}
const createAnchor = n => original.upload(path, file(n), { upsert: false, contentType: mime });
const first = data(await createAnchor(0)); const old = await view(); const originalUrl = await signed(anchorBucket, path);
assert.equal(old.anchorId, first.id); assert.equal(old.storagePath, path);
assert.ok((await other.api.rpc('resolve_tracker_attachment_versions', { p_paths: [path] })).error);
const a = await stage(old.revision, 1), b = await stage(old.revision, 2);
await Promise.all([upload(a, 1), upload(b, 2)]);
assert.ok((await other.api.storage.from(versionBucket).download(uid + '/' + a)).error);
assert.ok((await versions.download(uid + '/' + a)).error);
assert.equal((await view()).revision, old.revision);
const winners = await Promise.all([a,b].map(async op => data(await publish(op))));
assert.equal(winners.filter(Boolean).length, 1);
const index = winners.indexOf(true), winner = [a,b][index], winnerN = index + 1;
const won = await view();
assert.equal(won.anchorId, first.id); assert.equal(won.path, path); assert.equal(won.storagePath, uid + '/' + winner);
await verifyBytes(versionBucket, won.storagePath, winnerN);
await verifySigned(originalUrl, 0); await verifyBytes(anchorBucket, path, 0);
assert.equal(await stage(old.revision, 3), null);
const winningUrl = await signed(versionBucket, won.storagePath);
const attempt = await stage(won.revision, 3); await upload(attempt,3);
dropPublish = true; const unknown = await publish(attempt); assert.ok(unknown.error); assert.equal(lost,1);
const current = await view(); assert.equal(current.storagePath,uid+'/'+attempt); await verifyBytes(versionBucket,current.storagePath,3);
assert.equal(data(await publish(attempt)),true); await verifySigned(winningUrl,winnerN);
console.log('PASS legacy signed link, logical identity, staged privacy, single concurrent winner, lost receipt and current/original bytes');
const deleting = await stage(current.revision,4); await upload(deleting,4);
assert.equal(data(await api.rpc('delete_tracker_attachment',{p_path:path,p_revision:won.revision})),false);
assert.equal(data(await api.rpc('delete_tracker_attachment',{p_path:path,p_revision:current.revision})),true);
assert.equal(data(await publish(deleting)),false); assert.equal(await view(),null);
assert.deepEqual(data(await api.rpc('pending_tracker_attachment_deletions',{p_paths:[path]})),[path]);
assert.equal(data(await original.remove([path])).length,1);
const fresh = data(await createAnchor(5)); assert.notEqual(fresh.id,first.id);
assert.equal(data(await original.remove([path])).length,0);
assert.equal((await view()).anchorId, fresh.id); await verifyBytes(anchorBucket,path,5);
assert.equal(data(await publish(deleting)),false);
console.log('PASS tombstoned delete, no resurrection, same-name recreation survives a delayed deletion');
const db = sql => execFileSync('psql',[dbUrl,'-X','-q','-v','ON_ERROR_STOP=1','-c',sql],{stdio:'pipe'});
const garbageOps = [a,b,attempt,deleting];
for (const id of garbageOps) assert.match(id,/^[a-f0-9-]{36}$/);
db("UPDATE private.tracker_attachment_edits SET cleanup_after = now() - interval '2 days'");
const jobs = data(await admin.rpc('claim_tracker_attachment_cleanup',{p_limit:20})).jobs;
assert.deepEqual(jobs.map(job=>job.id).sort(),garbageOps.sort());
const retained = execFileSync('psql',[dbUrl,'-XAtc',"SELECT count(*) FROM private.tracker_attachment_edits WHERE state='garbage' AND (path IS NOT NULL OR mime IS NOT NULL OR expected_revision IS NOT NULL)"],{encoding:'utf8'});
assert.equal(retained.trim(),'0');
for(const job of jobs) {
  const k=job.owner_id+'/'+job.id;
  data(await admin.storage.from(versionBucket).remove([k]));
  assert.ok((await admin.storage.from(versionBucket).download(k)).error);
}
assert.equal(data(await admin.rpc('claim_tracker_attachment_cleanup',{p_limit:20})).jobs.length,0);
await verifyBytes(anchorBucket,path,5);
console.log('PASS service cleanup selects only retired/stale private version keys; original and recreated bytes remain');
