/** Cancellation for profile reads only: never expose a caller-provided reason. */
export function assertProfileReadActive(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Profile read cancelled', 'AbortError');
}

/** Auth and queued locks may not implement AbortSignal themselves. A late
 * resolution is observed (no unhandled rejection), but never resumes its caller. */
export function awaitProfileRead<T>(pending: PromiseLike<T>, signal?: AbortSignal): Promise<T> {
  const promise = Promise.resolve(pending);
  if (!signal) return promise;
  return new Promise<T>((resolve, reject) => {
    const stop = () => {
      signal.removeEventListener('abort', stop);
      reject(new DOMException('Profile read cancelled', 'AbortError'));
    };
    if (signal.aborted) { void promise.catch(() => {}); stop(); return; }
    signal.addEventListener('abort', stop, { once: true });
    promise.then(
      value => { signal.removeEventListener('abort', stop); resolve(value); },
      error => { signal.removeEventListener('abort', stop); reject(error); },
    );
  });
}
