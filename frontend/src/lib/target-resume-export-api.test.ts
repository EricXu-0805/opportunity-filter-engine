import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { Blob as NodeBlob } from 'node:buffer';
import golden from '../../../tests/fixtures/target-resume-export-golden.json';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { TARGET_RESUME_EXPORT_HEADERS as HEADERS, TARGET_RESUME_EXPORT_MAX_BODY_BYTES as MAX_BODY,
  TARGET_RESUME_EXPORT_MAX_FILE_BYTES as MAX_FILE, TARGET_RESUME_EXPORT_MIME as MIME,
  TARGET_RESUME_EXPORT_TEMPLATE, type TargetResumeExportRequest } from './target-resume-export-protocol';
const auth = vi.hoisted(() => ({ token: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: vi.fn() }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import { fetchTargetResumeExport, downloadTargetResumeExport } from './target-resume-export-api';
const fetchMock = vi.fn();
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; };
const request = (format: TargetResumeExportRequest['format'] = 'pdf'): TargetResumeExportRequest => ({
  version: 1, request_id: 'export-request', format,
  document_signature: golden.document_signature, export_signature: golden.export_signature,
  projection: structuredClone(golden.projection) as TargetResumeExportRequest['projection'],
});
const headers = (p: TargetResumeExportRequest) => ({ 'content-type': MIME[p.format],
  [HEADERS.request]: p.request_id, [HEADERS.document]: p.document_signature,
  [HEADERS.projection]: p.export_signature, [HEADERS.template]: TARGET_RESUME_EXPORT_TEMPLATE });
const bytes = (format: TargetResumeExportRequest['format'] = 'pdf') => format === 'pdf'
  ? new TextEncoder().encode('%PDF-1.7\nsynthetic file') : new Uint8Array([0x50, 0x4b, 3, 4, 1, 2, 3]);
const ok = (p: TargetResumeExportRequest, overrides: Record<string, string> = {}) => new Response(bytes(p.format), { status: 200, headers: { ...headers(p), ...overrides } });
const owner = () => captureOwnerToken();
const call = (p = request(), signal?: AbortSignal) => fetchTargetResumeExport(p, { owner: owner(), signal });
const flush = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };

beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); vi.stubGlobal('Blob', NodeBlob);
  localStorage.clear(); advanceOwnerEpoch('export-owner'); await syncLocalIdentityOwner('export-owner');
  auth.token.mockReset().mockResolvedValue('synthetic-token'); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('binary export transport contract', () => {
  it.each(['pdf', 'docx'] as const)('sends one private %s projection request and returns only a validated complete file', async format => {
    const p = request(format); fetchMock.mockResolvedValueOnce(ok(p, { 'content-disposition': 'attachment; filename="PRIVATE-untrusted.exe"' }));
    const result = await call(p);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/resume/full-target/export');
    expect(init).toMatchObject({ method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer synthetic-token' } });
    expect(JSON.parse(init.body)).toEqual(p);
    expect(result.filename).toBe(`resume-zh.${format}`); expect(result.blob.type).toBe(MIME[format]);
    expect(Array.from(new Uint8Array(await result.blob.arrayBuffer()))).toEqual(Array.from(bytes(format)));
    expect(JSON.stringify(JSON.parse(init.body))).not.toContain('base_snapshot');
  });
  it('allows an anonymous token result without adding an invalid bearer header', async () => {
    auth.token.mockResolvedValueOnce(null); const p = request(); fetchMock.mockResolvedValueOnce(ok(p));
    await call(p); expect(fetchMock.mock.calls[0][1].headers).not.toHaveProperty('Authorization');
  });
  it('captures all reply bindings and filename options before an asynchronous auth lookup', async () => {
    const p = request(); const before = structuredClone(p); const pending = deferred<string>(); auth.token.mockReturnValueOnce(pending.promise);
    fetchMock.mockResolvedValueOnce(ok(before)); const promise = call(p);
    p.request_id = 'new-id'; p.document_signature = 'changed'; p.export_signature = 'changed'; p.format = 'docx'; p.projection.locale = 'en';
    pending.resolve('synthetic-token'); const result = await promise;
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(before); expect(result.filename).toBe('resume-zh.pdf');
  });
  it.each(Object.values(HEADERS))('rejects a missing or mismatched exact binding header %s', async header => {
    const p = request();
    for (const value of [null, 'mismatch']) {
      const h = new Headers(headers(p)); if (value === null) h.delete(header); else h.set(header, value);
      fetchMock.mockResolvedValueOnce(new Response(bytes(), { headers: h }));
      await expect(call(p)).rejects.toMatchObject({ code: 'export_invalid_file', retryable: false });
    }
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it.each(['text/html', 'application/json', MIME.docx, ''])('rejects a mismatched PDF MIME type %j', async type => {
    const p = request(); fetchMock.mockResolvedValueOnce(ok(p, { 'content-type': type }));
    await expect(call(p)).rejects.toMatchObject({ code: 'export_invalid_file' });
  });
  it('accepts a valid MIME with parameters and normalizes MIME casing', async () => {
    const p = request(); fetchMock.mockResolvedValueOnce(ok(p, { 'content-type': 'Application/PDF; charset=binary' }));
    expect((await call(p)).blob.type).toBe(MIME.pdf);
  });
  it.each(['pdf', 'docx'] as const)('rejects missing %s file magic and empty success bodies', async format => {
    const p = request(format);
    for (const body of ['', 'PRIVATE SERVER HTML']) {
      fetchMock.mockResolvedValueOnce(new Response(body, { headers: headers(p) }));
      await expect(call(p)).rejects.toMatchObject({ code: 'export_invalid_file' });
    }
  });
  it('rejects a success without any readable body', async () => {
    const p = request(); fetchMock.mockResolvedValueOnce(new Response(null, { headers: headers(p) }));
    await expect(call(p)).rejects.toMatchObject({ code: 'export_invalid_file' });
  });
});

describe('body/file limits and safe single-attempt errors', () => {
  it('refuses oversized UTF-8 request bodies before auth or fetch without modifying the caller', async () => {
    const p = request(); p.projection.sections[0].blocks[0].lines[0].text = '界'.repeat(Math.ceil(MAX_BODY / 3));
    const original = p.projection.sections[0].blocks[0].lines[0].text;
    await expect(call(p)).rejects.toMatchObject({ status: 413, code: 'export_too_large' });
    expect(auth.token).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled(); expect(p.projection.sections[0].blocks[0].lines[0].text).toBe(original);
  });
  it('permits a request exactly at the byte cap', async () => {
    const p = request(); const line = p.projection.sections[0].blocks[0].lines[0]; line.text = '';
    line.text = 'x'.repeat(MAX_BODY - new TextEncoder().encode(JSON.stringify(p)).byteLength);
    expect(new TextEncoder().encode(JSON.stringify(p)).byteLength).toBe(MAX_BODY);
    fetchMock.mockResolvedValueOnce(ok(p)); await call(p); expect(fetchMock).toHaveBeenCalledOnce();
  });
  it('refuses an advertised oversized file before reading chunks and cancels its stream', async () => {
    const p = request(); const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    fetchMock.mockResolvedValueOnce(new Response(body, { headers: { ...headers(p), 'content-length': String(MAX_FILE + 1) } }));
    await expect(call(p)).rejects.toMatchObject({ code: 'export_too_large' }); expect(cancel).toHaveBeenCalledOnce();
  });
  it('enforces the actual streaming cap when content-length is absent', async () => {
    const p = request(); const cancel = vi.fn();
    let index = 0; const chunk = new Uint8Array(1024 * 1024); chunk.set(bytes());
    const body = new ReadableStream<Uint8Array>({ pull(controller) {
      index += 1; controller.enqueue(index <= 64 ? chunk : new Uint8Array([1]));
    }, cancel });
    fetchMock.mockResolvedValueOnce(new Response(body, { headers: headers(p) }));
    await expect(call(p)).rejects.toMatchObject({ code: 'export_too_large' }); expect(cancel).toHaveBeenCalledOnce();
  });
  it('copies reused stream buffers so later chunks cannot mutate earlier file bytes', async () => {
    const p = request(); const chunk = bytes(); const original = new Uint8Array(chunk); let n = 0;
    // A custom reader makes the producer reuse precisely the same underlying buffer.
    const reader = { read: vi.fn(async () => {
      n += 1;
      if (n === 1) return { done: false, value: chunk };
      if (n === 2) { chunk.fill(65); return { done: false, value: chunk }; }
      return { done: true, value: undefined };
    }), cancel: vi.fn().mockResolvedValue(undefined) };
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, headers: new Headers(headers(p)), body: { getReader: () => reader } });
    const file = await call(p); const actual = new Uint8Array(await file.blob.arrayBuffer());
    expect(actual.slice(0, original.length)).toEqual(original); expect(actual.slice(original.length)).toEqual(new Uint8Array(original.length).fill(65));
  });
  it.each([
    [422, 'invalid_export_text', 'invalid_export_text'],
    [503, 'export_overloaded', 'export_overloaded'],
    [504, 'PRIVATE_EXCEPTION', 'export_timeout'],
    [413, 'PRIVATE_EXCEPTION', 'export_too_large'],
    [500, 'PRIVATE_EXCEPTION', 'export_failed'],
  ] as const)('returns only an allowlisted safe error for HTTP %i (%s), without implicit retry', async (status, code, expectedCode) => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code, message: 'PRIVATE RESUME TEXT', input: 'PRIVATE SOURCE' } }), { status, headers: { 'retry-after': '0' } }));
    const error = await call().catch(e => e);
    expect(error).toMatchObject({ status, code: expectedCode, retryable: false });
    expect(`${error.message}${JSON.stringify(error.detail)}`).not.toContain('PRIVATE'); expect(fetchMock).toHaveBeenCalledOnce();
  });
  it('bounds error-body reads rather than buffering an unlimited raw response', async () => {
    let n = 0; const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({ pull(c) { n += 1; c.enqueue(new Uint8Array(4096)); }, cancel });
    fetchMock.mockResolvedValueOnce(new Response(stream, { status: 503 }));
    await expect(call()).rejects.toMatchObject({ code: 'export_failed' });
    expect(n).toBeLessThanOrEqual(4); expect(cancel).toHaveBeenCalledOnce();
  });
  it.each(['auth', 'fetch', 'reader'] as const)('never exposes raw exceptions from %s', async stage => {
    const p = request(); const failure = new Error('PRIVATE SOURCE PROVIDER EXCEPTION');
    if (stage === 'auth') auth.token.mockRejectedValueOnce(failure);
    if (stage === 'fetch') fetchMock.mockRejectedValueOnce(failure);
    if (stage === 'reader') fetchMock.mockResolvedValueOnce(new Response(new ReadableStream({ start(c) { c.error(failure); } }), { headers: headers(p) }));
    const error = await call(p).catch(e => e);
    expect(error).toMatchObject({ code: 'export_failed' }); expect(error.message).not.toContain('PRIVATE');
  });
});

describe('ownership, caller cancellation and timeout lifecycle', () => {
  it('does not start authentication/network for an already invalid owner or cancelled caller', async () => {
    const token = owner(); advanceOwnerEpoch('other-owner');
    await expect(fetchTargetResumeExport(request(), { owner: token })).rejects.toMatchObject({ code: 'export_abandoned' });
    const controller = new AbortController(); controller.abort();
    await expect(call(request(), controller.signal)).rejects.toMatchObject({ code: 'export_abandoned' });
    expect(auth.token).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
  });
  it.each(['timeout', 'caller abort', 'owner change'] as const)('settles promptly on %s while auth itself never settles', async action => {
    vi.useFakeTimers(); const authPending = deferred<string>(); auth.token.mockReturnValueOnce(authPending.promise);
    const controller = new AbortController(); let outcome: unknown = 'pending';
    const observed = call(request(), controller.signal).then(result => { outcome = result; }, error => { outcome = error; });
    try {
      if (action === 'timeout') await vi.advanceTimersByTimeAsync(60001);
      else if (action === 'caller abort') { controller.abort(); await flush(); }
      else { advanceOwnerEpoch('different-owner'); await flush(); }
      expect(outcome).toMatchObject({ code: action === 'timeout' ? 'export_timeout' : 'export_abandoned' });
      expect(fetchMock).not.toHaveBeenCalled();
    } finally { authPending.resolve('late-token'); await observed; }
    await flush(); expect(fetchMock).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(['caller abort', 'owner change', 'timeout'] as const)('cancels a pending fetch on %s and returns a safe error', async action => {
    vi.useFakeTimers(); const controller = new AbortController();
    fetchMock.mockImplementation((_url, init) => new Promise((_yes, no) => init.signal.addEventListener('abort', () => no(new DOMException('PRIVATE', 'AbortError')), { once: true })));
    const promise = call(request(), controller.signal); const result = promise.catch(error => error); await flush();
    expect(fetchMock).toHaveBeenCalledOnce();
    if (action === 'timeout') await vi.advanceTimersByTimeAsync(60001);
    else if (action === 'caller abort') controller.abort(); else advanceOwnerEpoch('next-owner');
    expect(await result).toMatchObject({ code: action === 'timeout' ? 'export_timeout' : 'export_abandoned' });
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true); expect(vi.getTimerCount()).toBe(0);
  });
  it.each(['timeout', 'caller abort', 'owner change'] as const)('interrupts an uncooperative stream reader on %s and ignores its late result', async action => {
    vi.useFakeTimers(); const p = request(); const caller = new AbortController();
    const pending = deferred<ReadableStreamReadResult<Uint8Array>>(); let outcome: unknown = 'pending';
    const reader = { read: vi.fn().mockReturnValue(pending.promise), cancel: vi.fn().mockResolvedValue(undefined) };
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, headers: new Headers(headers(p)), body: { getReader: () => reader } });
    const observed = call(p, caller.signal).then(value => { outcome = value; }, error => { outcome = error; });
    await flush(); expect(reader.read).toHaveBeenCalledOnce();
    try {
      if (action === 'timeout') await vi.advanceTimersByTimeAsync(60001);
      else if (action === 'caller abort') { caller.abort(); await flush(); }
      else { advanceOwnerEpoch('reader-next-owner'); await flush(); }
      expect(outcome).toMatchObject({ code: action === 'timeout' ? 'export_timeout' : 'export_abandoned' });
      expect(reader.cancel).toHaveBeenCalledOnce();
    } finally { pending.resolve({ done: false, value: bytes() }); await observed; }
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(['caller abort', 'owner change', 'timeout'] as const)('cancels an incomplete body on %s without returning a partial download', async action => {
    vi.useFakeTimers(); const caller = new AbortController(); const p = request();
    fetchMock.mockImplementation(async (_url, init) => new Response(new ReadableStream<Uint8Array>({ start(c) {
      c.enqueue(bytes()); init.signal.addEventListener('abort', () => c.error(new DOMException('PRIVATE', 'AbortError')), { once: true });
    } }), { headers: headers(p) }));
    const result = call(p, caller.signal).catch(error => error); await flush();
    if (action === 'timeout') await vi.advanceTimersByTimeAsync(60001);
    else if (action === 'caller abort') caller.abort(); else advanceOwnerEpoch('next-owner');
    expect(await result).toMatchObject({ code: action === 'timeout' ? 'export_timeout' : 'export_abandoned' });
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('explicit local download lifecycle', () => {
  it('removes the temporary link and revokes its Blob URL after download starts', async () => {
    vi.useFakeTimers(); const create = vi.fn().mockReturnValue('blob:synthetic'); const revoke = vi.fn();
    vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: revoke }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    downloadTargetResumeExport({ blob: new Blob([bytes()]), filename: 'resume-en.pdf' });
    expect(click).toHaveBeenCalledOnce(); expect(document.querySelector('a[download]')).toBeNull(); expect(revoke).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000); expect(revoke).toHaveBeenCalledWith('blob:synthetic');
  });
});
