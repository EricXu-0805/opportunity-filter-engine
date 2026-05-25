import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { downloadCSV } from './csv-export';

let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;
let clickSpy: ReturnType<typeof vi.fn>;
let appendedNodes: Node[];

beforeEach(() => {
  createObjectURL = vi.fn(() => 'blob:mock-url');
  revokeObjectURL = vi.fn();
  // @ts-expect-error jsdom doesn't ship URL.createObjectURL by default
  URL.createObjectURL = createObjectURL;
  URL.revokeObjectURL = revokeObjectURL as unknown as (url: string) => void;

  appendedNodes = [];
  clickSpy = vi.fn();
  const realCreate = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    const el = realCreate(tag);
    if (tag === 'a') {
      Object.defineProperty(el, 'click', { value: clickSpy });
    }
    appendedNodes.push(el);
    return el;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('downloadCSV', () => {
  it('creates a Blob with text/csv MIME and a blob: URL', () => {
    downloadCSV('out.csv', 'a,b\n1,2\n');
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blobArg = createObjectURL.mock.calls[0][0] as Blob;
    expect(blobArg).toBeInstanceOf(Blob);
    expect(blobArg.type).toMatch(/^text\/csv/);
  });

  it('sets href + download attribute on the anchor and clicks it', () => {
    downloadCSV('export-2026-05-24.csv', 'id,title\n');
    const anchor = appendedNodes.find((n) => (n as HTMLElement).tagName === 'A') as HTMLAnchorElement | undefined;
    expect(anchor).toBeDefined();
    expect(anchor!.href).toBe('blob:mock-url');
    expect(anchor!.download).toBe('export-2026-05-24.csv');
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it('revokes the object URL after click to avoid memory leaks', () => {
    downloadCSV('x.csv', '');
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url');
  });

  it('handles empty content without throwing', () => {
    expect(() => downloadCSV('empty.csv', '')).not.toThrow();
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });
});
