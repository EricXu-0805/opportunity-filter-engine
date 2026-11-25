import { downloadZip } from 'client-zip';
import { assertAttachmentOwner, AttachmentRequestError, runAttachmentRequest } from './attachment-request';
import type { OwnerToken } from './identity-owner';
import { ATTACHMENTS_BUCKET, getAuthState, resolveTrackerAttachmentVersions, supabase, type ResolvedTrackerAttachment } from './supabase';

interface Anchor {
  path: string;
  id: string;
  etag: string | null;
  updated: string | null;
}
interface SourceFile { anchor: Anchor; version: ResolvedTrackerAttachment }
interface ExportEntry { originalPath: string; archivePath: string; size: number; mime: string; sha256: string }
type Progress = (done: number, total: number) => void;
const pageSize = 100;

function unavailable(): never { throw new AttachmentRequestError('unavailable'); }

async function inventory(uid: string, token: OwnerToken, signal: AbortSignal): Promise<SourceFile[]> {
  const bucket = supabase.storage.from(ATTACHMENTS_BUCKET);
  const anchors: Anchor[] = [];
  const folders = [''];
  for (let index = 0; index < folders.length; index++) {
    const relative = folders[index];
    const prefix = relative ? uid + '/' + relative : uid;
    let boundary: { name: string; id: string | null } | undefined;
    const seen = new Set<string>();
    for (let offset = 0; ; offset += pageSize - 1) {
      const rows = await runAttachmentRequest(token, { signal }, async request => {
        assertAttachmentOwner(token, uid);
        const { data, error } = await request.wait(bucket.list(prefix, {
          limit: pageSize, offset, sortBy: { column: 'name', order: 'asc' },
        }, { signal: request.signal }));
        assertAttachmentOwner(token, uid);
        if (error || !Array.isArray(data)) return unavailable();
        return data;
      });
      if (rows.length > pageSize || (boundary && (boundary.name !== rows[0]?.name || boundary.id !== rows[0]?.id))) unavailable();
      for (const row of rows.slice(boundary ? 1 : 0)) {
        const name = row?.name;
        if (typeof name !== 'string' || !name || name === '.' || name === '..' || name.includes('/')) unavailable();
        const folder = row.id === null && row.metadata === null;
        const key = (folder ? 'folder/' : 'file/') + name;
        if (seen.has(key)) unavailable();
        seen.add(key);
        const path = relative ? relative + '/' + name : name;
        if (folder) { folders.push(path); continue; }
        if (name === '.emptyFolderPlaceholder' && row.metadata?.size === 0) continue;
        const size: unknown = row.metadata?.size;
        const etag = typeof row.metadata?.eTag === 'string' ? row.metadata.eTag : null;
        const updated = typeof row.updated_at === 'string' ? row.updated_at : null;
        if (!row.id || typeof size !== 'number' || !Number.isSafeInteger(size) || size < 0 || !(etag || updated)) unavailable();
        anchors.push({ path, id: row.id, etag, updated });
      }
      if (rows.length < pageSize) break;
      boundary = rows[rows.length - 1];
    }
  }
  anchors.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  const files: SourceFile[] = [];
  for (let i = 0; i < anchors.length; i += pageSize) {
    const batch = anchors.slice(i, i + pageSize);
    const paths = batch.map(anchor => uid + '/' + anchor.path);
    const resolved = await resolveTrackerAttachmentVersions(paths, token, { signal });
    assertAttachmentOwner(token, uid);
    for (const [j, anchor] of batch.entries()) {
      const version = resolved.get(paths[j]);
      if (version === null) continue; // Deleted files can still have a legacy Storage anchor.
      if (!version || version.path !== paths[j] || version.anchorId !== anchor.id) unavailable();
      if (version.storageBucket === ATTACHMENTS_BUCKET
        ? version.storagePath !== version.path
        : version.storageBucket !== 'tracker-attachment-versions' || !version.storagePath.startsWith(uid + '/')) unavailable();
      files.push({ anchor, version });
    }
  }
  return files;
}

function memberName(path: string, index: number) {
  // Numeric prefixes survive case-insensitive extraction, reserved basenames and sanitization collisions.
  const basename = path.slice(path.lastIndexOf('/') + 1).normalize('NFC');
  const safe = Array.from(basename, ch => {
    const cp = ch.codePointAt(0)!;
    return cp < 32 || (cp >= 127 && cp <= 159) || /[\\:*?"<>|\u202a-\u202e\u2066-\u2069]/u.test(ch) ? '_' : ch;
  }).slice(-56).join('').replace(/[. ]+$/u, '') || 'file';
  return 'files/' + String(index + 1).padStart(6, '0') + '-' + safe;
}

async function sha256(bytes: ArrayBuffer) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('');
}

/** Account-wide, including keys whose opportunity no longer exists in the catalog. */
export async function exportTrackerAttachments(uid: string, token: OwnerToken, signal: AbortSignal, progress: Progress) {
  const check = () => { signal.throwIfAborted(); assertAttachmentOwner(token, uid); };
  const confirmSession = () => runAttachmentRequest(token, { signal }, async request => {
    const auth = await request.wait(getAuthState({ throwOnError: true }));
    assertAttachmentOwner(token, auth.user?.id ?? null);
  });
  check();
  await confirmSession();
  const files = await inventory(uid, token, signal);
  check();
  if (!files.length) {
    if ((await inventory(uid, token, signal)).length) unavailable();
    await confirmSession();
    check();
    return null;
  }
  progress(0, files.length);
  async function* members() {
    const entries: ExportEntry[] = [];
    for (const [i, { anchor, version }] of files.entries()) {
      const bucket = supabase.storage.from(version.storageBucket);
      check();
      // The SDK interpolates the supplied key into a URL. Encode individual segments for legacy names.
      const encoded = version.storagePath.split('/').map(encodeURIComponent).join('/');
      const bytes = await runAttachmentRequest(token, { signal }, async request => {
        const { data, error } = await request.wait(bucket.download(encoded, {
          cacheNonce: [version.anchorId, version.revision, version.etag, version.updatedAt].join('/'),
        }, { signal: request.signal, cache: 'no-store' }));
        if (error || !data || data.size !== version.sizeBytes) return unavailable();
        return request.wait(data.arrayBuffer());
      });
      check();
      const archivePath = memberName(anchor.path, i);
      const digest = await sha256(bytes);
      check();
      entries.push({ originalPath: anchor.path, archivePath, size: version.sizeBytes, mime: version.mimeType, sha256: digest });
      yield { name: archivePath, input: new Uint8Array(bytes) };
      progress(i + 1, files.length);
    }
    // No download can be handed to the browser until this second inventory and the entire ZIP finish.
    const verified = await inventory(uid, token, signal);
    if (JSON.stringify(verified) !== JSON.stringify(files)) unavailable();
    await confirmSession();
    check();
    const manifest = JSON.stringify({ formatVersion: 1, files: entries }, null, 2) + '\n';
    const manifestHash = await sha256(new TextEncoder().encode(manifest).buffer);
    yield { name: 'manifest.json', input: manifest };
    const checksums = entries.map(entry => entry.sha256 + '  ' + entry.archivePath);
    checksums.push(manifestHash + '  manifest.json');
    yield { name: 'SHA256SUMS', input: checksums.join('\n') + '\n' };
  }
  const blob = await downloadZip(members()).blob();
  check();
  return { filename: 'tracker-attachments.zip', blob, count: files.length };
}
