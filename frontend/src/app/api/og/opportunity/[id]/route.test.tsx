/**
 * The share card is an image, and an image cannot be qualified.
 *
 * og-facts.test.ts already pins WHAT the card says for each posture. This file
 * pins the other half: that asking for the same URL twice, either side of a
 * record closing, produces a second card built from the second record — and
 * that neither response invites anyone to store the first one.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  captured: [] as Array<{ element: unknown; options: Record<string, unknown> }>,
}));

// The real ImageResponse rasterises through satori, which needs fonts and is
// not the thing under test. This records exactly what the route handed it.
vi.mock('next/og', () => ({
  ImageResponse: class {
    constructor(element: unknown, options: Record<string, unknown>) {
      mocks.captured.push({ element, options });
    }
  },
}));

// `@/lib/api-server` is deliberately NOT mocked. The whole point of this file
// is which outcome the route derives from a real transport result, so the
// stub goes at the boundary the resolver itself talks to — global fetch — and
// the route runs through the real `fetchOpportunityDetail`, including its
// status classification, its id echo check and its abort timer.
vi.stubGlobal('fetch', mocks.fetch);

import { GET } from './route';

/** 200 with a JSON body. */
function okJson(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

/** A status with no usable body — 400/404/429/5xx all arrive this way. */
function statusOnly(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({}),
  } as unknown as Response;
}

/** 200 whose body will not parse. */
function badJson(): Response {
  return {
    ok: true,
    status: 200,
    json: async () => { throw new SyntaxError('Unexpected token < in JSON'); },
  } as unknown as Response;
}

/**
 * A fetch that never settles on its own and rejects only when the resolver's
 * own AbortController fires. Paired with fake timers this exercises the real
 * 8s timeout without spending 8s.
 */
function hangsUntilAborted() {
  return (_url: string, init: { signal: AbortSignal }) =>
    new Promise<Response>((_resolve, reject) => {
      init.signal.addEventListener('abort', () => {
        reject(new DOMException('The operation was aborted.', 'AbortError'));
      });
    });
}

/** Every string the card would render, flattened out of the element tree. */
function textOf(node: unknown): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(' ');
  const element = node as { props?: { children?: unknown } };
  if (element.props) return textOf(element.props.children);
  return '';
}

function inDays(n: number): string {
  return new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);
}

const OPEN_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
};

const CLOSED_TRUTH = {
  listing_state: 'closed',
  reference_only: false,
  actionable: false,
  accepting_state: 'not_accepting',
  reason_code: 'listing_closed',
  verified_at: null,
  expires_at: null,
};

const REFERENCE_TRUTH = {
  listing_state: 'unknown',
  reference_only: true,
  actionable: false,
  accepting_state: 'unknown',
  reason_code: 'reference_only',
  verified_at: null,
  expires_at: null,
};

function listing(truth: unknown) {
  return {
    id: 'opp-1',
    title: 'Vision Lab Research Assistant',
    organization: 'UIUC ECE',
    source_type: 'campus_program',
    record_kind: 'listing',
    target_truth: truth,
    opportunity_type: 'research',
    paid: 'yes',
    on_campus: true,
    location: 'Urbana, IL',
    deadline: inDays(5),
    // Explicitly source-stated, which is what unlocks the countdown; an
    // unjudged date renders as a plain listed date with no urgency.
    deadline_is_estimate: false,
    eligibility: { international_friendly: 'yes' },
  };
}

async function get(id = 'opp-1') {
  return GET(
    new Request(`https://joinalab.com/api/og/opportunity/${id}`),
    { params: Promise.resolve({ id }) },
  );
}

function cacheControlOf(index: number): string {
  const headers = mocks.captured[index].options.headers as Record<string, string>;
  return headers['Cache-Control'];
}

beforeEach(() => {
  mocks.fetch.mockReset();
  // Not `= []`: the mock closure captured this exact array reference.
  mocks.captured.length = 0;
});

describe('the opportunity share card', () => {
  it('rebuilds from the record it was just given — an open card, then a closed one for the same id', async () => {
    mocks.fetch
      .mockResolvedValueOnce(okJson(listing(OPEN_TRUTH)))
      .mockResolvedValueOnce(okJson(listing(CLOSED_TRUTH)));

    await get();
    await get();

    expect(mocks.fetch).toHaveBeenCalledTimes(2);
    expect(String(mocks.fetch.mock.calls[0][0])).toContain('opp-1');
    expect(String(mocks.fetch.mock.calls[1][0])).toContain('opp-1');
    // Two distinct responses, not one element reused. Both are asserted, so a
    // route that somehow returned the first twice fails on the second.
    expect(mocks.captured).toHaveLength(2);
    expect(mocks.captured[0].element).not.toBe(mocks.captured[1].element);

    const open = textOf(mocks.captured[0].element);
    expect(open).toContain('Paid');
    expect(open).toMatch(/Due in \d+d/);
    expect(open).toContain('On campus');
    expect(open).toContain('International OK');
    expect(open).toContain('Find research & internships that fit you');
    expect(open).toContain('Vision Lab Research Assistant');

    const closed = textOf(mocks.captured[1].element);
    expect(closed).not.toContain('Paid');
    expect(closed).not.toMatch(/Due in/);
    expect(closed).not.toContain('On campus');
    expect(closed).not.toContain('International OK');
    expect(closed).not.toContain('Find research & internships that fit you');
    expect(closed.toLowerCase()).toContain('closed listing');
    expect(closed).toContain('This listing has closed');
    // The identity survives; it is the terms that do not.
    expect(closed).toContain('Vision Lab Research Assistant');
  });

  it.each([
    ['reference-only', REFERENCE_TRUTH, 'Kept for reference'],
    // A truth this build cannot parse. "We could not confirm" is not "closed".
    ['unreadable', { listing_state: 'open' }, 'Check the original source'],
  ])('drops the offer terms for a %s record too', async (_label, truth, footer) => {
    mocks.fetch
      .mockResolvedValueOnce(okJson(listing(OPEN_TRUTH)))
      .mockResolvedValueOnce(okJson(listing(truth)));

    await get();
    await get();

    const second = textOf(mocks.captured[1].element);
    expect(second).not.toContain('Paid');
    expect(second).not.toMatch(/Due in/);
    expect(second).toContain(footer);
  });

  it('tells no cache to keep the found card', async () => {
    mocks.fetch.mockResolvedValue(okJson(listing(OPEN_TRUTH)));

    await get();

    expect(cacheControlOf(0)).toBe('no-store, max-age=0');
    expect(cacheControlOf(0)).not.toContain('s-maxage');
    expect(cacheControlOf(0)).not.toContain('public');
  });

  it('tells no cache to keep the not-found card either', async () => {
    // The miss used to carry no Cache-Control at all — the same bug pointing
    // the other way. A record that appears (a slow backend recovering, a newly
    // published row) would stay "not found" in every cache that stored it.
    mocks.fetch.mockResolvedValue(statusOnly(404));

    await get('never-existed');

    expect(mocks.captured).toHaveLength(1);
    expect(textOf(mocks.captured[0].element)).toContain('Opportunity not found');
    expect(cacheControlOf(0)).toBe('no-store, max-age=0');
    expect(cacheControlOf(0)).not.toContain('s-maxage');
    expect(cacheControlOf(0)).not.toContain('public');
  });

  it('a card that was found, then is not, says so on the second ask', async () => {
    mocks.fetch
      .mockResolvedValueOnce(okJson(listing(OPEN_TRUTH)))
      .mockResolvedValueOnce(statusOnly(404));

    await get();
    await get();

    expect(textOf(mocks.captured[0].element)).toContain('Vision Lab Research Assistant');
    expect(textOf(mocks.captured[1].element)).toContain('Opportunity not found');
    expect(cacheControlOf(0)).toBe('no-store, max-age=0');
    expect(cacheControlOf(1)).toBe('no-store, max-age=0');
  });

  it('keeps the card at the size every scraper expects', async () => {
    mocks.fetch.mockResolvedValue(okJson(listing(OPEN_TRUTH)));

    await get();

    expect(mocks.captured[0].options.width).toBe(1200);
    expect(mocks.captured[0].options.height).toBe(630);
  });
});

describe('location reaches the card as a job site or as an affiliation', () => {
  // og-facts.test.ts pins the DECISION; this pins the SINK. The route has its
  // own JSX block that renders `facts.location` and `facts.locationPrefix`,
  // and deleting or unlabelling it would leave og-facts perfectly green while
  // the published image still showed a bare location.

  it('shows an actionable listing its location', async () => {
    mocks.fetch.mockResolvedValue(okJson(listing(OPEN_TRUTH)));

    await get();

    const text = textOf(mocks.captured[0].element);
    expect(text).toContain('Urbana, IL');
    expect(text).not.toContain('Faculty affiliation');
  });

  it.each([
    ['closed', CLOSED_TRUTH],
    ['reference-only', REFERENCE_TRUTH],
    ['unreadable', { listing_state: 'open' }],
  ])('never puts a %s listing\'s location on the card', async (_label, truth) => {
    // The location on the fixture is poison: if it appears at all, the card is
    // still advertising where a job that is not open used to be.
    mocks.fetch.mockResolvedValue(okJson(listing(truth)));

    await get();

    const text = textOf(mocks.captured[0].element);
    expect(text).not.toContain('Urbana, IL');
    // The identity still renders — it is the offer terms that do not.
    expect(text).toContain('Vision Lab Research Assistant');
  });

  it('keeps a non-actionable faculty affiliation, and keeps it labelled', async () => {
    mocks.fetch.mockResolvedValue(okJson({
      id: 'opp-1',
      title: 'Ada Lovelace',
      organization: 'Test University',
      source_type: 'faculty_research',
      location: 'Test City',
      paid: 'yes',
      on_campus: true,
      deadline: inDays(5),
      deadline_is_estimate: false,
      eligibility: { international_friendly: 'yes' },
      target_truth: {
        listing_state: 'unknown', reference_only: false, actionable: false,
        accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
        verified_at: null, expires_at: null,
      },
    }));

    await get();

    const text = textOf(mocks.captured[0].element);
    expect(text).toContain('Test City');
    expect(text).toContain('Faculty affiliation');
    // A person is not an offer: none of the terms may ride along.
    expect(text).not.toContain('Paid');
    expect(text).not.toMatch(/Due in/);
    expect(text).not.toContain('On campus');
    expect(text).not.toContain('International OK');
  });
});

describe('infrastructure failure is not a missing record', () => {
  // The card used to be built from a resolver that returned record-or-null, so
  // a 429, a 5xx, a dropped connection, a timeout and a malformed body all
  // produced the same image as a genuinely absent id: "Opportunity not found".
  // That image is then cached by whatever chat app rendered it — a durable
  // false claim about a record that exists, published under our name.

  it('renders the real card when the backend answers with the right record', async () => {
    mocks.fetch.mockResolvedValue(okJson(listing(OPEN_TRUTH)));

    await get();

    const text = textOf(mocks.captured[0].element);
    expect(text).toContain('Vision Lab Research Assistant');
    expect(text).not.toContain('not found');
    expect(text).not.toContain('temporarily unavailable');
  });

  it.each([
    ['400', statusOnly(400)],
    ['404', statusOnly(404)],
  ])('says not found only when the backend says so (%s)', async (_label, response) => {
    mocks.fetch.mockResolvedValue(response);

    await get('gone-1');

    const text = textOf(mocks.captured[0].element);
    expect(text).toContain('Opportunity not found');
    expect(text).not.toContain('temporarily unavailable');
    expect(cacheControlOf(0)).toBe('no-store, max-age=0');
  });

  const UNAVAILABLE: [string, () => void][] = [
    ['429 rate limited', () => mocks.fetch.mockResolvedValue(statusOnly(429))],
    ['500', () => mocks.fetch.mockResolvedValue(statusOnly(500))],
    ['503', () => mocks.fetch.mockResolvedValue(statusOnly(503))],
    ['a network-level rejection', () => mocks.fetch.mockRejectedValue(new TypeError('fetch failed'))],
    ['a body that will not parse', () => mocks.fetch.mockResolvedValue(badJson())],
    ['a body with no id', () => mocks.fetch.mockResolvedValue(okJson({ title: 'No id here' }))],
    ['an empty body', () => mocks.fetch.mockResolvedValue(okJson({}))],
    ['a null body', () => mocks.fetch.mockResolvedValue(okJson(null))],
    // The one that used to render ANOTHER RECORD'S CARD under this URL.
    ['a record whose id does not match the request', () => mocks.fetch.mockResolvedValue(
      okJson({ ...listing(OPEN_TRUTH), id: 'some-other-record', title: 'Someone Else Lab' }),
    )],
  ];

  it.each(UNAVAILABLE)('reports %s as temporarily unavailable, never as not found', async (_label, arrange) => {
    arrange();

    await get();

    const text = textOf(mocks.captured[0].element);
    expect(text).toContain('Opportunity temporarily unavailable');
    expect(text).toContain('Please try again later');
    // The exact words that must not appear: this is our failure, not a
    // statement about whether the record exists.
    expect(text.toLowerCase()).not.toContain('not found');
    // And never the wrong record's identity.
    expect(text).not.toContain('Someone Else Lab');
    expect(cacheControlOf(0)).toBe('no-store, max-age=0');
  });

  it('reports a timeout as temporarily unavailable, without waiting eight seconds', async () => {
    vi.useFakeTimers();
    try {
      mocks.fetch.mockImplementation(hangsUntilAborted());

      const pending = get();
      await vi.advanceTimersByTimeAsync(8000);
      await pending;

      const text = textOf(mocks.captured[0].element);
      expect(text).toContain('Opportunity temporarily unavailable');
      expect(text.toLowerCase()).not.toContain('not found');
      expect(cacheControlOf(0)).toBe('no-store, max-age=0');
    } finally {
      vi.useRealTimers();
    }
  });
});
