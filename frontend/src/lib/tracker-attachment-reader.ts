import { assertAttachmentOwner, AttachmentRequestError, runAttachmentRequest, type AttachmentRequestContext, type AttachmentRequestOptions } from './attachment-request';
import { captureOwnerToken, type OwnerToken } from './identity-owner';
import {
  ATTACHMENTS_BUCKET, getAttachmentSignedUrl as legacySignedUrl, deleteAttachment as legacyDelete, getAuthState,
  listAttachments as legacyList, supabase, type Attachment,
} from './supabase';

const versionBucket = 'tracker-attachment-versions';
const resolver = 'resolve_tracker_attachment_versions';
const marker = 'tracker_attachment_export_marker';
// A later schema-cache miss cannot turn a known versioned database into a legacy reader.
let observedCatalog = false;
const uuid = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;
export interface AttachmentLocation {
  path: string;
  anchorId: string;
  revision: string;
  storageBucket: string;
  storagePath: string;
  sizeBytes: number;
  mimeType: string;
}
export interface AttachmentCatalogMarker {
  count: number;
  digest: string;
  observedAt: string;
}
export interface ReadableAttachment extends Attachment { catalogRevision?: string }

async function attachmentOwner(token: OwnerToken, request: AttachmentRequestContext) {
  const auth = await request.wait(getAuthState({ throwOnError: true }));
  const uid = auth.user?.id ?? null;
  assertAttachmentOwner(token, uid);
  return uid;
}

function unavailable(): never { throw new AttachmentRequestError('unavailable'); }

// Rollout compatibility applies only to PostgREST's explicit missing-function response
// for the exact function we called. Timeouts, denied access and malformed data stay errors.
function missingFunction(status: number, error: {code?: string; message?: string} | null, name: string) {
  return status === 404 && error?.code === 'PGRST202' &&
    (error.message?.startsWith('Could not find the function public.' + name + '(') ||
     error.message?.startsWith('Could not find the function public.' + name + ' '));
}
function location(data: unknown, path: string, uid: string): AttachmentLocation | null {
  if (data === null) return null;
  if (!data || typeof data !== 'object') return unavailable();
  const row = data as Partial<AttachmentLocation>;
  if (row.path !== path || typeof row.anchorId !== 'string' || !uuid.test(row.anchorId) ||
      typeof row.revision !== 'string' || typeof row.mimeType !== 'string' || !row.mimeType ||
      typeof row.sizeBytes !== 'number' || !Number.isSafeInteger(row.sizeBytes) || row.sizeBytes < 0) return unavailable();
  const op = row.revision.slice(2);
  const anchor = row.revision.startsWith('o:' + row.anchorId + ':') && row.storageBucket === ATTACHMENTS_BUCKET && row.storagePath === path;
  const version = row.revision.startsWith('v:') && uuid.test(op) && row.storageBucket === versionBucket && row.storagePath === uid + '/' + op;
  if (!anchor && !version) return unavailable();
  return row as AttachmentLocation;
}

/** null distinguishes a verified pre-migration schema from deleted or unknown files in a live catalog. */
export async function attachmentLocations(paths: string[], token: OwnerToken, options: AttachmentRequestOptions = {}) {
  return runAttachmentRequest(token, options, async request => {
    const uid = await attachmentOwner(token, request);
    if (paths.length > 100 || paths.some(path => !path.startsWith(uid + '/'))) return unavailable();
    const answer = await request.wait(supabase.rpc(resolver, { p_paths: paths }));
    if (answer.error) {
      if (answer.status === 401) throw new AttachmentRequestError('unauthenticated');
      if (observedCatalog || !missingFunction(answer.status, answer.error, resolver)) return unavailable();
      const other = await request.wait(supabase.rpc(marker, {}));
      if (!other.error) observedCatalog = true;
      if (!observedCatalog && missingFunction(other.status, other.error, marker)) return null;
      return unavailable();
    }
    observedCatalog = true;
    if (!answer.data || typeof answer.data !== 'object' || Array.isArray(answer.data)) return unavailable();
    return new Map(paths.map(path => [path, location(answer.data[path], path, uid)]));
  });
}

export async function attachmentCatalogMarker(uid: string, token: OwnerToken, signal: AbortSignal): Promise<AttachmentCatalogMarker | null> {
  return runAttachmentRequest(token, { signal }, async request => {
    assertAttachmentOwner(token, uid);
    const answer = await request.wait(supabase.rpc(marker, {}));
    if (answer.error) {
      if (answer.status === 401) throw new AttachmentRequestError('unauthenticated');
      if (observedCatalog || !missingFunction(answer.status, answer.error, marker)) return unavailable();
      const other = await request.wait(supabase.rpc(resolver, { p_paths: [] }));
      if (!other.error) observedCatalog = true;
      if (!observedCatalog && missingFunction(other.status, other.error, resolver)) return null;
      return unavailable();
    }
    observedCatalog = true;
    const data = answer.data;
    if (!data || !Number.isSafeInteger(data.count) || data.count < 0 || typeof data.digest !== 'string' ||
        !/^[0-9a-f]{64}$/.test(data.digest) || typeof data.observedAt !== 'string' || !Number.isFinite(Date.parse(data.observedAt))) return unavailable();
    return { count: data.count, digest: data.digest, observedAt: data.observedAt };
  });
}

export async function listReadableAttachments(opportunityId: string, token = captureOwnerToken(), options: AttachmentRequestOptions = {}): Promise<ReadableAttachment[]> {
  const files = await legacyList(opportunityId, token, options);
  if (!files.length) return files;
  const uid = await runAttachmentRequest(token, options, request => attachmentOwner(token, request));
  const result: ReadableAttachment[] = [];
  let legacyMode: boolean | undefined;
  for (let offset = 0; offset < files.length; offset += 100) {
    const batch = files.slice(offset, offset + 100);
    const paths = batch.map(file => uid + '/' + opportunityId + '/' + file.name);
    const resolved = await attachmentLocations(paths, token, options);
    if (legacyMode !== undefined && legacyMode !== (resolved === null)) return unavailable();
    legacyMode = resolved === null;
    if (!resolved) {
      result.push(...batch.map(file => ({ ...file, canReplace: false })));
      continue;
    }
    for (const [i, file] of batch.entries()) {
      const current = resolved.get(paths[i]);
      if (current === null) continue;
      if (!current || current.anchorId !== file.revision?.id) return unavailable();
      result.push({
        ...file, canReplace: false, catalogRevision: current.revision,
        sizeBytes: current.sizeBytes, mimeType: current.mimeType,
      });
    }
  }
  assertAttachmentOwner(token, uid);
  return result;
}

export async function getReadableAttachmentUrl(opportunityId: string, name: string, seconds = 300,
  token = captureOwnerToken(), options: AttachmentRequestOptions = {}) {
  const uid = await runAttachmentRequest(token, options, request => attachmentOwner(token, request));
  const path = uid + '/' + opportunityId + '/' + name;
  const resolved = await attachmentLocations([path], token, options);
  if (!resolved) return legacySignedUrl(opportunityId, name, seconds, token, options);
  const file = resolved.get(path);
  if (!file) return null;
  return runAttachmentRequest(token, options, async request => {
    const ttl = file.storageBucket === versionBucket ? Math.min(seconds, 300) : seconds;
    const { data, error } = await request.wait(supabase.storage.from(file.storageBucket).createSignedUrl(file.storagePath, ttl));
    if (error || typeof data?.signedUrl !== 'string') return unavailable();
    const url = new URL(data.signedUrl);
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
      return unavailable();
    }
    return url.href;
  });
}

/** Use the revision the user saw even if another tab publishes before deletion. */
export async function deleteReadableAttachment(opportunityId: string, file: ReadableAttachment,
  token: OwnerToken, options: AttachmentRequestOptions = {}): Promise<boolean> {
  const uid = await runAttachmentRequest(token, options, request => attachmentOwner(token, request));
  const path = uid + '/' + opportunityId + '/' + file.name;
  const resolved = await attachmentLocations([path], token, options);
  if (!resolved) {
    if (file.catalogRevision) return unavailable();
    return legacyDelete(opportunityId, file.name, token, options);
  }
  // A file listed before migration needs a fresh read before it can be deleted.
  if (!file.catalogRevision || resolved.get(path)?.revision !== file.catalogRevision) return false;
  const deleted = await runAttachmentRequest(token, options, async request => {
    const reply = await request.wait(supabase.rpc('delete_tracker_attachment', {
      p_path: path, p_revision: file.catalogRevision,
    }));
    if (reply.error || typeof reply.data !== 'boolean') return unavailable();
    return reply.data;
  });
  if (!deleted) return false;
  return legacyDelete(opportunityId, file.name, token, options);
}
