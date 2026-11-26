import { downloadZip, predictLength } from 'client-zip';
import { assertAttachmentOwner, AttachmentRequestError, runAttachmentRequest } from './attachment-request';
import type { OwnerToken } from './identity-owner';
import { ATTACHMENTS_BUCKET, ATTACHMENTS_MAX_BYTES, getAuthState, resolveTrackerAttachmentVersions, supabase, type ResolvedTrackerAttachment } from './supabase';

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

export interface ExportVolume { filename: string; blob: Blob; number: number; total: number; confirmBeforeDownload: () => Promise<void> }
export type OfferVolume = (file: ExportVolume) => Promise<void>;
export class AttachmentExportLimitError extends Error {
  readonly #path: string;
  get path() { return this.#path; }
  constructor(path: string, readonly metadata = false) {
    super('Attachment exceeds the export limit');
    this.#path = path;
  }
}
const volumeBytes = 16 * 1024 * 1024;
const volumeFiles = 128;
const emptyDigest = '0'.repeat(64);
const encoder = new TextEncoder();
interface ExportMarker { count: number; digest: string; observedAt: string }
interface VerifiedAttachmentDownload { filename: string; blob: Blob; verifiedAt: string }
type ExportResult = VerifiedAttachmentDownload & { count: number } & (
  | { parts?: undefined; downloadFreshReceipt?: undefined }
  | { parts: number; downloadFreshReceipt: () => Promise<VerifiedAttachmentDownload> }
);

async function inventoryDigest(files: SourceFile[]) {
  const hashes: string[] = [];
  // This encoding is shared with tracker_attachment_export_marker(). Every
  // resolved row must belong to the same snapshot, including rows from
  // different pagination or resolver calls and changes that later revert.
  for (let i = 0; i < files.length; i += pageSize) {
    const batch = files.slice(i, i + pageSize).map(({ version }) => {
      const fields = [version.path, version.anchorId, version.revision, String(version.sizeBytes), version.mimeType];
      return sha256(encoder.encode(fields.join('\0')).buffer);
    });
    hashes.push(...await Promise.all(batch));
  }
  return sha256(encoder.encode(hashes.sort().join('')).buffer);
}

function manifestText(entries: ExportEntry[], exportId?: string) {
  const header = exportId ? { formatVersion: 2, scope: 'partial-volume', exportId } : { formatVersion: 1 };
  return JSON.stringify({ ...header, files: entries }, null, 2) + '\n';
}

function checksumText(entries: ExportEntry[], manifestHash: string) {
  return [...entries.map(entry => entry.sha256 + '  ' + entry.archivePath), manifestHash + '  manifest.json'].join('\n') + '\n';
}

function projectedSize(entries: ExportEntry[], exportId?: string) {
  // The real SHA-256 strings have the same UTF-8 length as the placeholders.
  const manifest = manifestText(entries, exportId);
  const checksums = checksumText(entries, emptyDigest);
  return Number(predictLength([
    ...entries.map(entry => ({ name: entry.archivePath, size: entry.size })),
    { name: 'manifest.json', input: manifest }, { name: 'SHA256SUMS', input: checksums },
  ]));
}

function partition(entries: ExportEntry[], exportId: string) {
  if (entries.length <= volumeFiles && projectedSize(entries) <= volumeBytes) return [entries.length];
  const ends: number[] = [];
  let start = 0;
  while (start < entries.length) {
    let lo = start;
    let hi = Math.min(start + volumeFiles, entries.length);
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (projectedSize(entries.slice(start, mid), exportId) <= volumeBytes) lo = mid;
      else hi = mid - 1;
    }
    if (lo === start) throw new AttachmentExportLimitError(entries[start].originalPath, true);
    ends.push(lo);
    start = lo;
  }
  return ends;
}

/** Account-wide, including keys whose opportunity no longer exists in the catalog. */
export async function exportTrackerAttachments(uid: string, token: OwnerToken, signal: AbortSignal, progress: Progress, offerVolume?: OfferVolume): Promise<ExportResult | null> {
  const check = () => { signal.throwIfAborted(); assertAttachmentOwner(token, uid); };
  const confirmSession = () => runAttachmentRequest(token, { signal }, async request => {
    const auth = await request.wait(getAuthState({ throwOnError: true }));
    assertAttachmentOwner(token, auth.user?.id ?? null);
  });
  const marker = () => runAttachmentRequest(token, { signal }, async request => {
    const { data, error } = await request.wait(supabase.rpc('tracker_attachment_export_marker', {}));
    assertAttachmentOwner(token, uid);
    if (error || !data || !Number.isSafeInteger(data.count) || data.count < 0 ||
        typeof data.digest !== 'string' || !/^[0-9a-f]{64}$/u.test(data.digest) ||
        typeof data.observedAt !== 'string' || !Number.isFinite(Date.parse(data.observedAt))) unavailable();
    return data as ExportMarker;
  });
  check();
  await confirmSession();
  const original = await marker();
  const files = await inventory(uid, token, signal);
  if (original.count !== files.length || original.digest !== await inventoryDigest(files)) unavailable();
  const verify = async () => {
    const verified = await inventory(uid, token, signal);
    if (verified.length !== files.length || verified.some((file, i) => JSON.stringify(file) !== JSON.stringify(files[i]))) unavailable();
    await confirmSession();
    const final = await marker();
    check();
    if (final.count !== original.count || final.digest !== original.digest) unavailable();
    return final.observedAt;
  };
  check();
  if (!files.length) { await verify(); return null; }
  const entries = files.map(({ anchor, version }, index) => {
    if (version.sizeBytes > ATTACHMENTS_MAX_BYTES) throw new AttachmentExportLimitError(anchor.path);
    return { originalPath: anchor.path, archivePath: memberName(anchor.path, index), size: version.sizeBytes,
      mime: version.mimeType, sha256: emptyDigest };
  });
  // Separate retries cannot accidentally be combined into one verified set.
  const exportId = crypto.randomUUID();
  const ends = partition(entries, exportId);
  const multipart = ends.length > 1;
  if (multipart && !offerVolume) return unavailable();
  progress(0, files.length);
  async function* members(start: number, end: number) {
    for (let i = start; i < end; i++) {
      const { version } = files[i];
      check();
      const bucket = supabase.storage.from(version.storageBucket);
      const encoded = version.storagePath.split('/').map(encodeURIComponent).join('/');
      const bytes = await runAttachmentRequest(token, { signal }, async request => {
        const { data, error } = await request.wait(bucket.download(encoded, {
          cacheNonce: [version.anchorId, version.revision, version.etag, version.updatedAt].join('/'),
        }, { signal: request.signal, cache: 'no-store' }));
        if (error || !data || data.size !== version.sizeBytes) return unavailable();
        return request.wait(data.arrayBuffer());
      });
      entries[i].sha256 = await sha256(bytes);
      check();
      yield { name: entries[i].archivePath, input: new Uint8Array(bytes) };
      progress(i + 1, files.length);
    }
    const batch = entries.slice(start, end);
    const id = multipart ? exportId : undefined;
    const manifest = manifestText(batch, id);
    const hash = await sha256(new TextEncoder().encode(manifest).buffer);
    const checksums = checksumText(batch, hash);
    yield { name: 'manifest.json', input: manifest };
    yield { name: 'SHA256SUMS', input: checksums };
  }
  const sums: string[] = [];
  let start = 0;
  for (const [index, end] of ends.entries()) {
    const expected = projectedSize(entries.slice(start, end), multipart ? exportId : undefined);
    const blob = await downloadZip(members(start, end)).blob();
    check();
    if (blob.size !== expected || blob.size > volumeBytes) unavailable();
    if (!multipart) {
      const verifiedAt = await verify();
      return { filename: 'tracker-attachments.zip', blob, verifiedAt, count: files.length };
    }
    const name = 'tracker-attachments-' + exportId + '-partial-' + (index + 1) + '-of-' + ends.length + '.zip';
    sums.push(await sha256(await blob.arrayBuffer()) + '  ' + name);
    await confirmSession();
    check();
    await offerVolume!({ filename: name, blob, number: index + 1, total: ends.length, confirmBeforeDownload: confirmSession });
    check();
    start = end;
  }
  // A partial volume only describes its own files. The separate whole-export
  // receipt is withheld until every volume was offered and the snapshot is rechecked.
  function receipt(verifiedAt: string): VerifiedAttachmentDownload {
    const text = '# Verified at ' + verifiedAt + '\n' + sums.join('\n') + '\n';
    return { filename: 'tracker-attachments-' + exportId + '-complete.sha256', verifiedAt,
      blob: new Blob([text], { type: 'text/plain' }) };
  }
  return { ...receipt(await verify()), count: files.length, parts: ends.length,
    downloadFreshReceipt: async () => receipt(await verify()) };
}
