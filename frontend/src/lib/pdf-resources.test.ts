import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPdfResourceLoaders, PDF_CMAP_URL, PDF_STANDARD_FONT_URL, PDF_RESOURCE_TIMEOUT_MS } from './pdf-resources';

const origin = 'https://ofe.example';
const ok = () => ({ ok: true, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('PDF.js resource reader factories', () => {
  it('reads packed maps and standard fonts only from constrained same-origin paths', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok());
    vi.stubGlobal('fetch', fetchMock);
    const loaders = createPdfResourceLoaders(origin);
    const cmaps = new loaders.CMapReaderFactory({ baseUrl: PDF_CMAP_URL, isCompressed: true });
    const fonts = new loaders.StandardFontDataFactory({ baseUrl: PDF_STANDARD_FONT_URL });
    expect(await cmaps.fetch({ name: 'UniGB-UCS2-H' })).toEqual({
      cMapData: new Uint8Array([1, 2, 3]), compressionType: 1,
    });
    expect(await fonts.fetch({ filename: 'LiberationSans-Regular.ttf' })).toEqual(new Uint8Array([1, 2, 3]));
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${origin}/pdfjs/cmaps/UniGB-UCS2-H.bcmap`,
      `${origin}/pdfjs/standard_fonts/LiberationSans-Regular.ttf`,
    ]);
    expect(fetchMock.mock.calls.every(([, options]) => options.mode === 'same-origin'
      && options.redirect === 'error' && options.credentials === 'omit')).toBe(true);
    expect(loaders.hasFailure()).toBe(false);
  });

  it.each(['../secret', 'https://other.example/map', 'a/b', '%2e%2e', 'name?key=value', 'name#fragment'])(
    'rejects unsafe CMap names before fetch: %s', async (name) => {
      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);
      const loaders = createPdfResourceLoaders(origin);
      const maps = new loaders.CMapReaderFactory({ baseUrl: PDF_CMAP_URL, isCompressed: true });
      await expect(maps.fetch({ name })).rejects.toThrow('PDF reading resources are unavailable.');
      expect(loaders.hasFailure()).toBe(true);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it.each(['../font.ttf', 'https://other.example/font.pfb', 'font.ttf?token=1', 'font.js'])(
    'rejects unsafe standard-font names before fetch: %s', async (filename) => {
      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);
      const loaders = createPdfResourceLoaders(origin);
      const fonts = new loaders.StandardFontDataFactory({ baseUrl: PDF_STANDARD_FONT_URL });
      await expect(fonts.fetch({ filename })).rejects.toThrow('PDF reading resources are unavailable.');
      expect(loaders.hasFailure()).toBe(true);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it('rejects a foreign base URL even when the resource name is valid', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const loaders = createPdfResourceLoaders(origin);
    const maps = new loaders.CMapReaderFactory({ baseUrl: 'https://other.example/', isCompressed: true });
    await expect(maps.fetch({ name: 'UniGB-UCS2-H' })).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(loaders.hasFailure()).toBe(true);
  });

  it.each(['404', 'network', 'empty', 'body-read'] as const)(
    'remembers %s failures for both resources without exposing the internal error', async (failure) => {
      const fetchMock = vi.fn().mockImplementation(async () => {
        if (failure === 'network') throw new Error('private/path?secret=do-not-display');
        return {
          ok: failure !== '404',
          arrayBuffer: async () => {
            if (failure === 'body-read') throw new Error('private/path');
            return new Uint8Array(failure === 'empty' ? [] : [1]).buffer;
          },
        };
      });
      vi.stubGlobal('fetch', fetchMock);
      const loaders = createPdfResourceLoaders(origin);
      await expect(new loaders.CMapReaderFactory({ baseUrl: PDF_CMAP_URL, isCompressed: true })
        .fetch({ name: 'UniGB-UCS2-H' })).rejects.toThrow('PDF reading resources are unavailable.');
      expect(loaders.hasFailure()).toBe(true);
      const fontLoaders = createPdfResourceLoaders(origin);
      await expect(new fontLoaders.StandardFontDataFactory({ baseUrl: PDF_STANDARD_FONT_URL })
        .fetch({ filename: 'FoxitSerif.pfb' })).rejects.toThrow('PDF reading resources are unavailable.');
      expect(fontLoaders.hasFailure()).toBe(true);
      expect(createPdfResourceLoaders(origin).hasFailure()).toBe(false);
    },
  );
});


it.each(['cmap', 'standard-font'] as const)('aborts a nonresponding %s resource within the configured timeout', async (resource) => {
  vi.useFakeTimers();
  let signal: AbortSignal | undefined;
  vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => {
    signal = options.signal;
    signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  })));
  const loaders = createPdfResourceLoaders(origin);
  const pending = resource === 'cmap'
    ? new loaders.CMapReaderFactory({ baseUrl: PDF_CMAP_URL, isCompressed: true }).fetch({ name: 'UniGB-UCS2-H' })
    : new loaders.StandardFontDataFactory({ baseUrl: PDF_STANDARD_FONT_URL }).fetch({ filename: 'FoxitSerif.pfb' });
  const rejected = expect(pending).rejects.toThrow('PDF reading resources are unavailable.');
  await vi.advanceTimersByTimeAsync(PDF_RESOURCE_TIMEOUT_MS - 1);
  expect(signal?.aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  await rejected;
  expect(signal?.aborted).toBe(true);
  expect(loaders.hasFailure()).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});
