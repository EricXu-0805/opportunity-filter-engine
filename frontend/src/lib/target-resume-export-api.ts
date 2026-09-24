import { ApiError } from './api';
import { getRevealAccessToken } from './supabase';
import { isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from './identity-owner';
import { TARGET_RESUME_EXPORT_HEADERS as HEADERS, TARGET_RESUME_EXPORT_MAX_BODY_BYTES,
  TARGET_RESUME_EXPORT_MAX_FILE_BYTES, TARGET_RESUME_EXPORT_MIME, TARGET_RESUME_EXPORT_TEMPLATE,
  type TargetResumeExportRequest } from './target-resume-export-protocol';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';
export interface TargetResumeExportFile { blob: Blob; filename: string }
const safeCodes = new Set(['invalid_export_request', 'invalid_export_signature', 'invalid_export_text',
  'empty_document', 'unsupported_glyph', 'fonts_unavailable', 'export_overloaded', 'export_timeout',
  'export_failed', 'export_too_large', 'feature_disabled']);
const failure = (code: string, status = 0) => new ApiError(status, code, 'The export could not be completed. Your draft is kept.', false);

/** One private render request. No automatic replay and no upload of source
 * snapshots. A complete binary body is validated before a download can begin. */
export async function fetchTargetResumeExport(payload: TargetResumeExportRequest,
  options: { owner: OwnerToken; signal?: AbortSignal }): Promise<TargetResumeExportFile> {
  const body = JSON.stringify(payload);
  const request = JSON.parse(body) as TargetResumeExportRequest;
  if (new TextEncoder().encode(body).byteLength > TARGET_RESUME_EXPORT_MAX_BODY_BYTES) throw failure('export_too_large', 413);
  const controller = new AbortController();
  const aborted = () => controller.abort();
  let timeout = false;
  const ensureActive = () => {
    if (timeout) throw failure('export_timeout', 408);
    if (controller.signal.aborted || !isOwnerTokenValid(options.owner, options.owner.uid)) throw failure('export_abandoned', 409);
  };
  if (options.signal?.aborted) controller.abort();
  else options.signal?.addEventListener('abort', aborted, { once: true });
  const unsubscribe = onLocalOwnerStateChange(() => {
    if (!isOwnerTokenValid(options.owner, options.owner.uid)) controller.abort();
  });
  const timer = setTimeout(() => { timeout = true; controller.abort(); }, 60_000);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  // Auth refresh and a stalled stream must retire promptly even when their
  // underlying promise does not implement AbortSignal.
  const interruptible = <T,>(pending: Promise<T>): Promise<T> => new Promise((resolve, reject) => {
    const stop = () => reject(failure(timeout ? 'export_timeout' : 'export_abandoned', timeout ? 408 : 409));
    if (controller.signal.aborted) { pending.catch(() => {}); stop(); return; }
    controller.signal.addEventListener('abort', stop, { once: true });
    pending.then(resolve, reject).finally(() => controller.signal.removeEventListener('abort', stop));
  });
  try {
    ensureActive();
    const token = await interruptible(getRevealAccessToken());
    ensureActive();
    const response = await interruptible(fetch(`${API_BASE}/resume/full-target/export`, { method: 'POST', body,
      signal: controller.signal, cache: 'no-store', headers: { 'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}) } }));
    ensureActive();
    reader = response.body?.getReader();
    if (!reader) throw failure('export_invalid_file', response.status);
    const type = (response.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase();
    if (response.ok && (type !== TARGET_RESUME_EXPORT_MIME[request.format]
      || response.headers.get(HEADERS.request) !== request.request_id
      || response.headers.get(HEADERS.document) !== request.document_signature
      || response.headers.get(HEADERS.projection) !== request.export_signature
      || response.headers.get(HEADERS.template) !== TARGET_RESUME_EXPORT_TEMPLATE)) throw failure('export_invalid_file', response.status);
    const limit = response.ok ? TARGET_RESUME_EXPORT_MAX_FILE_BYTES : 8192;
    const advertised = response.headers.get('content-length');
    if (advertised && /^\d+$/.test(advertised) && Number(advertised) > limit) throw failure(response.ok ? 'export_too_large' : 'export_failed', response.status);
    const chunks: Uint8Array<ArrayBuffer>[] = []; let size = 0;
    for (;;) {
      const part = await interruptible(reader.read()); ensureActive();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > limit) throw failure(response.ok ? 'export_too_large' : 'export_failed', response.status);
      // An owned buffer also prevents a reused stream buffer changing content.
      chunks.push(new Uint8Array(part.value));
    }
    if (!response.ok) {
      let code = response.status === 504 ? 'export_timeout' : response.status === 413 ? 'export_too_large' : 'export_failed';
      try {
        const parsed = JSON.parse(await new Blob(chunks).text());
        if (typeof parsed?.detail?.code === 'string' && safeCodes.has(parsed.detail.code)) code = parsed.detail.code;
      } catch { /* Never display a server body or parser exception. */ }
      throw failure(code, response.status);
    }
    const blob = new Blob(chunks, { type });
    const first = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
    const magic = request.format === 'pdf'
      ? new TextDecoder().decode(first) === '%PDF-'
      : first[0] === 0x50 && first[1] === 0x4b && first[2] === 3 && first[3] === 4;
    ensureActive();
    if (!magic) throw failure('export_invalid_file', response.status);
    return { blob, filename: `resume-${request.projection.locale}.${request.format}` };
  } catch (error) {
    if (timeout) throw failure('export_timeout', 408);
    if (controller.signal.aborted || !isOwnerTokenValid(options.owner, options.owner.uid)) throw failure('export_abandoned', 409);
    throw error instanceof ApiError ? error : failure('export_failed');
  } finally {
    clearTimeout(timer); unsubscribe(); options.signal?.removeEventListener('abort', aborted);
    void reader?.cancel().catch(() => {});
  }
}

export function downloadTargetResumeExport(file: TargetResumeExportFile): void {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement('a'); link.href = url; link.download = file.filename;
  document.body.appendChild(link);
  try { link.click(); }
  finally {
    link.remove();
    // Let the browser begin reading the Blob before releasing its URL.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
