/** Public PDF.js reader-factory hooks, scoped to a single PDF upload.
 * PDF.js can resolve an ErrorFont after a resource failure even with
 * stopAtErrors=true. Keep that failure outside the worker so the caller can
 * reject an incomplete extraction instead of saving the remaining text.
 */
export const PDF_CMAP_URL = '/pdfjs/cmaps/';
export const PDF_STANDARD_FONT_URL = '/pdfjs/standard_fonts/';
export const PDF_RESOURCE_TIMEOUT_MS = 15_000;

export function createPdfResourceLoaders(origin: string) {
  const source = new URL(origin);
  if (!['http:', 'https:'].includes(source.protocol) || source.origin !== origin) {
    throw new Error('PDF resources require the application origin.');
  }
  let failed = false;

  async function readResource(path: string): Promise<Uint8Array> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), PDF_RESOURCE_TIMEOUT_MS);
    try {
      const response = await fetch(new URL(path, origin).href, {
        mode: 'same-origin', credentials: 'omit', redirect: 'error', signal: controller.signal,
      });
      if (!response.ok) throw new Error('PDF reading resources are unavailable.');
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (!bytes.byteLength) throw new Error('PDF reading resources are unavailable.');
      return bytes;
    } finally {
      clearTimeout(timeout);
    }
  }

  // Interfaces follow pdfjs-dist 4.4.168 DocumentInitParameters:
  // CMapReaderFactory.fetch -> { cMapData, compressionType }, where 1 is
  // CMapCompressionType.BINARY for the bundled .bcmap files.
  class CMapReaderFactory {
    private readonly validOptions: boolean;
    constructor(options: { baseUrl?: string; isCompressed?: boolean }) {
      this.validOptions = options.baseUrl === PDF_CMAP_URL && options.isCompressed === true;
    }
    async fetch(request: { name: string }) {
      try {
        if (!this.validOptions || typeof request?.name !== 'string'
          || !/^[A-Za-z0-9_-]{1,100}$/.test(request.name)) {
          throw new Error('Unsupported PDF reading resource.');
        }
        return {
          cMapData: await readResource(`${PDF_CMAP_URL}${request.name}.bcmap`),
          compressionType: 1,
        };
      } catch {
        failed = true;
        // Never surface an internal URL or raw network error to the upload UI.
        throw new Error('PDF reading resources are unavailable.');
      }
    }
  }

  class StandardFontDataFactory {
    private readonly validOptions: boolean;
    constructor(options: { baseUrl?: string }) {
      this.validOptions = options.baseUrl === PDF_STANDARD_FONT_URL;
    }
    async fetch(request: { filename: string }): Promise<Uint8Array> {
      try {
        if (!this.validOptions || typeof request?.filename !== 'string'
          || !/^[A-Za-z0-9_-]{1,100}\.(?:pfb|ttf)$/.test(request.filename)) {
          throw new Error('Unsupported PDF reading resource.');
        }
        return await readResource(`${PDF_STANDARD_FONT_URL}${request.filename}`);
      } catch {
        failed = true;
        throw new Error('PDF reading resources are unavailable.');
      }
    }
  }

  return { CMapReaderFactory, StandardFontDataFactory, hasFailure: () => failed };
}
