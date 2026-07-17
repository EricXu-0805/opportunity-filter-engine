/**
 * Exercises the REAL SSE parse loop in generateColdEmailStream (the modal
 * tests mock the whole function away). Frames are deliberately delivered in
 * tiny chunks that split mid-frame and mid-delimiter — the buffer/frame-split
 * logic must reassemble them; a regression here would otherwise only manifest
 * as silently-missing stage labels or spurious double-LLM fallbacks in prod.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('./analytics', () => ({ track: vi.fn(), trackOnce: vi.fn() }));

import { generateColdEmailStream } from './api';
import type { ProfileData } from './types';

const profile = {
  institution: 'UIUC',
  college: 'Grainger',
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: [],
  coursework: [],
} as unknown as ProfileData;

function sseResponse(frames: string[], chunkSize = 3): Response {
  const text = frames.map((f) => `data: ${f}\n\n`).join('');
  const encoder = new TextEncoder();
  const bytes = encoder.encode(text);
  let offset = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (offset < bytes.length) {
        controller.enqueue(bytes.slice(offset, offset + chunkSize));
        offset += chunkSize;
      } else {
        controller.close();
      }
    },
  });
  return {
    ok: true,
    headers: new Headers({ 'content-type': 'text/event-stream' }),
    body,
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('generateColdEmailStream SSE parsing', () => {
  it('reassembles frames split across tiny chunks and relays stages before done', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        '{"stage": "drafting"}',
        '{"stage": "critiquing"}',
        '{"stage": "revising"}',
        '{"stage": "done", "subject": "中文主题 Fit", "body": "Dear Professor,\\nBody.", "recipient_email": "p@x.edu", "mailto_link": "mailto:p@x.edu", "method": "ai"}',
      ]),
    );
    vi.stubGlobal('fetch', fetchMock);

    const stages: string[] = [];
    const resp = await generateColdEmailStream(
      profile, 'opp-1', { engine: 'ai' }, (s) => stages.push(s),
    );

    expect(stages).toEqual(['drafting', 'critiquing', 'revising']);
    expect(resp.subject).toBe('中文主题 Fit'); // multi-byte chars survive chunk splits
    expect(resp.body).toContain('Dear Professor');
    expect(resp.method).toBe('ai');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/cold-email/stream');
  });

  it('throws when the stream closes before a done event (caller falls back)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      sseResponse(['{"stage": "drafting"}']),
    ));
    await expect(
      generateColdEmailStream(profile, 'opp-1', { engine: 'ai' }),
    ).rejects.toThrow(/done event/);
  });

  it('throws on a done payload missing core fields (version-skew guard)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      sseResponse(['{"stage": "done", "method": "ai"}']),
    ));
    await expect(
      generateColdEmailStream(profile, 'opp-1', { engine: 'ai' }),
    ).rejects.toThrow(/malformed done payload/);
  });

  it('throws on a non-SSE response (old backend → caller falls back)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      body: null,
    } as unknown as Response));
    await expect(
      generateColdEmailStream(profile, 'opp-1', { engine: 'ai' }),
    ).rejects.toThrow(/not an event stream/);
  });
});
