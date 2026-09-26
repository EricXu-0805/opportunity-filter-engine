import { isOwnerTokenValid, isTokenOwnerStillCurrent, OwnerMismatchError, type OwnerToken } from './identity-owner';

export const ATTACHMENT_REQUEST_TIMEOUT_MS = 30_000;
export class AttachmentRequestError extends Error {
  constructor(public readonly code: 'unavailable' | 'unauthenticated' | 'timeout') {
    super('Attachment request could not be completed');
    this.name = 'AttachmentRequestError';
  }
}
export interface AttachmentRequestOptions { signal?: AbortSignal }
export interface AttachmentRequestContext {
  signal: AbortSignal;
  check(): void;
  wait<T>(pending: PromiseLike<T>): Promise<T>;
}

/** A deadline covers auth and storage together. Abandoning a mutation does
 * not prove it failed remotely; callers must offer a list check, never replay. */
export async function runAttachmentRequest<T>(token: OwnerToken, options: AttachmentRequestOptions,
  work: (request: AttachmentRequestContext) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) abort();
  const timer = setTimeout(() => { timedOut = true; abort(); }, ATTACHMENT_REQUEST_TIMEOUT_MS);
  const check = () => {
    if (!isTokenOwnerStillCurrent(token)) throw new OwnerMismatchError();
    if (controller.signal.aborted) {
      if (timedOut) throw new AttachmentRequestError('timeout');
      throw new DOMException('Attachment request cancelled', 'AbortError');
    }
  };
  const wait = async <R>(pending: PromiseLike<R>): Promise<R> => {
    const promise = Promise.resolve(pending);
    let stop: (() => void) | undefined;
    try {
      const result = await Promise.race([promise, new Promise<never>((_, reject) => {
        stop = () => { try { check(); } catch (error) { reject(error); } };
        controller.signal.addEventListener('abort', stop, { once: true });
        if (controller.signal.aborted) stop();
      })]);
      check();
      return result;
    } finally { if (stop) controller.signal.removeEventListener('abort', stop); }
  };
  try {
    check();
    return await work({ signal: controller.signal, check, wait });
  } catch (error) {
    check();
    if (error instanceof AttachmentRequestError || error instanceof OwnerMismatchError) throw error;
    throw new AttachmentRequestError('unavailable');
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}

export function assertAttachmentOwner(token: OwnerToken, uid: string | null): asserts uid is string {
  if (!isTokenOwnerStillCurrent(token)) throw new OwnerMismatchError();
  if (!uid) throw new AttachmentRequestError('unauthenticated');
  if (!isOwnerTokenValid(token, uid)) throw new OwnerMismatchError();
}
