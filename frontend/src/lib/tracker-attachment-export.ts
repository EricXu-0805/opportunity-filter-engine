import { downloadZip } from 'client-zip';
import { assertAttachmentOwner, AttachmentRequestError, runAttachmentRequest } from './attachment-request';
import type { OwnerToken } from './identity-owner';
import { ATTACHMENTS_BUCKET, getAuthState, supabase } from './supabase';
import { attachmentCatalogMarker, attachmentLocations, type AttachmentLocation } from './tracker-attachment-reader';

interface SourceFile {
  path: string;
  id: string;
  size: number;
  mime: string;
  etag: string | null;
  updated: string | null;
  version?: AttachmentLocation;
}
interface ExportEntry { originalPath: string; archivePath: string; size: number; mime: string; sha256: string }
type Progress = (done: number, total: number) => void;
const pageSize = 100;

function unavailable(): never { throw new AttachmentRequestError('unavailable'); }

async function inventory(uid: string, token: OwnerToken, signal: AbortSignal, versioned: boolean): Promise<SourceFile[]> {
  const bucket = supabase.storage.from(ATTACHMENTS_BUCKET);
  const files: SourceFile[] = [];
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
        files.push({ path, id: row.id, size, etag, updated, mime: row.metadata?.mimetype || 'application/octet-stream' });
      }
      if (rows.length < pageSize) break;
      boundary = rows[rows.length - 1];
    }
  }
  files.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  if (!versioned) return files;
  const current: SourceFile[] = [];
  for (let i = 0; i < files.length; i += pageSize) {
    const batch = files.slice(i, i + pageSize);
    const keys = batch.map(file => uid + '/' + file.path);
    const resolved = await attachmentLocations(keys, token, { signal });
    if (!resolved) unavailable();
    for (const [j, file] of batch.entries()) {
      const version = resolved.get(keys[j]);
      if (version === null) continue;
      if (!version || version.anchorId !== file.id) unavailable();
      current.push({ ...file, size: version.sizeBytes, mime: version.mimeType, version });
    }
  }
  return current;
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

async function catalogDigest(files: SourceFile[]) {
  const encoder = new TextEncoder();
  const hashes: string[] = [];
  for (let i = 0; i < files.length; i += pageSize) {
    const batch = files.slice(i, i + pageSize).map(({ version }) => {
      if (!version) return unavailable();
      const fields = [version.path, version.anchorId, version.revision, String(version.sizeBytes), version.mimeType];
      return sha256(encoder.encode(fields.join('\0')).buffer);
    });
    hashes.push(...await Promise.all(batch));
  }
  return sha256(encoder.encode(hashes.sort().join('')).buffer);
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
  const initial = await attachmentCatalogMarker(uid, token, signal);
  const versioned = initial !== null;
  const files = await inventory(uid, token, signal, versioned);
  if (initial && (initial.count !== files.length || initial.digest !== await catalogDigest(files))) unavailable();
  const confirmCatalog = async () => {
    const final = await attachmentCatalogMarker(uid, token, signal);
    if ((final === null) !== (initial === null) || final?.count !== initial?.count || final?.digest !== initial?.digest) unavailable();
  };
  check();
  if (!files.length) {
    if ((await inventory(uid, token, signal, versioned)).length) unavailable();
    await confirmSession();
    await confirmCatalog();
    check();
    return null;
  }
  progress(0, files.length);
  async function* members() {
    const entries: ExportEntry[] = [];
    for (const [i, file] of files.entries()) {
      check();
      // The SDK interpolates the supplied key into a URL. Encode individual segments for legacy names.
      const location = file.version?.storagePath ?? uid + '/' + file.path;
      const bucket = supabase.storage.from(file.version?.storageBucket ?? ATTACHMENTS_BUCKET);
      const encoded = location.split('/').map(encodeURIComponent).join('/');
      const bytes = await runAttachmentRequest(token, { signal }, async request => {
        const { data, error } = await request.wait(bucket.download(encoded, {
          cacheNonce: file.version?.revision ?? [file.id, file.etag, file.updated].join('/'),
        }, { signal: request.signal, cache: 'no-store' }));
        if (error || !data || data.size !== file.size) return unavailable();
        return request.wait(data.arrayBuffer());
      });
      check();
      const archivePath = memberName(file.path, i);
      const digest = await sha256(bytes);
      check();
      entries.push({ originalPath: file.path, archivePath, size: file.size, mime: file.mime, sha256: digest });
      yield { name: archivePath, input: new Uint8Array(bytes) };
      progress(i + 1, files.length);
    }
    // No download can be handed to the browser until this second inventory and the entire ZIP finish.
    const verified = await inventory(uid, token, signal, versioned);
    if (JSON.stringify(verified) !== JSON.stringify(files)) unavailable();
    await confirmSession();
    await confirmCatalog();
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
