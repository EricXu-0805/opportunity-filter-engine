/* @vitest-environment jsdom */
// Page metadata is the one output that keeps making its claim after the page
// stops. A link preview is cached by whatever chat app rendered it; a search
// snippet by the index. Neither can be qualified, corrected, or clicked
// through to a banner. So every opening-shaped field here — the scraped
// description, the posted date, the "research opportunity at X" framing —
// gates on the record being one we still call a live listing.
import { describe, expect, it, vi, beforeEach } from 'vitest';

// vi.hoisted, not a plain const: vi.mock factories are hoisted above every
// top-level binding, so a factory closing over one only works while the
// factory happens to run late. That is a property of the loader, not of this
// file, and it turns into a temporal-dead-zone crash the moment it changes.
const { fetchOpportunityDetail } = vi.hoisted(() => ({
  fetchOpportunityDetail: vi.fn(),
}));
vi.mock('@/lib/api-server', () => ({
  fetchOpportunityDetail,
  fetchSimilarServer: vi.fn().mockResolvedValue([]),
}));

import { generateMetadata } from './page';

const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

const POISON_DESCRIPTION = 'POISON apply now, we are recruiting two students for fall';
const POISON_POSTED = '2026-08-01';

function record(overrides: Record<string, unknown> = {}) {
  return {
    id: 'opp-1',
    title: 'Vision Lab RA',
    organization: 'Test University',
    opportunity_type: 'research',
    source_type: 'campus_program',
    description_clean: POISON_DESCRIPTION,
    description_raw: POISON_DESCRIPTION,
    posted_date: POISON_POSTED,
    deadline: '2099-12-31',
    keywords: ['machine learning'],
    target_truth: { ...ACTIONABLE_TRUTH },
    ...overrides,
  };
}

async function metadataFor(overrides: Record<string, unknown> = {}) {
  fetchOpportunityDetail.mockResolvedValue({
    status: 'ok', opportunity: record(overrides),
  });
  return generateMetadata({ params: Promise.resolve({ id: 'opp-1' }) });
}

type Meta = Awaited<ReturnType<typeof generateMetadata>>;

/** Every place a description reaches a reader. */
function descriptions(meta: Meta): string[] {
  return [
    String(meta.description ?? ''),
    String(meta.openGraph?.description ?? ''),
    String(meta.twitter?.description ?? ''),
  ];
}

/** `publishedTime` lives on the article variant of Next's OpenGraph union. */
function publishedTime(meta: Meta): string | undefined {
  return (meta.openGraph as { publishedTime?: string } | undefined)?.publishedTime;
}

beforeEach(() => fetchOpportunityDetail.mockReset());

describe('a live listing may describe itself', () => {
  it('uses the source description and publication date', async () => {
    const meta = await metadataFor();

    for (const text of descriptions(meta)) {
      expect(text).toContain('POISON apply now');
    }
    expect(publishedTime(meta)).toBe(POISON_POSTED);
  });
});

describe('nothing else propagates an opening claim', () => {
  const REASONS: [string, unknown, string][] = [
    ['listing_closed', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'closed',
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      reference_only: true,
    }, 'This listing is closed and is kept for reference.'],
    ['reference_only', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'unknown', reason_code: 'reference_only', reference_only: true,
    }, 'Published as reference material, not as an open listing.'],
    ['faculty_not_accepting', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
    }, 'This faculty profile states they are not currently accepting undergraduate students.'],
    ['inactive', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'unknown', reason_code: 'inactive',
    }, 'This record is no longer active.'],
    ['malformed', { listing_state: 'open' },
      'Current status could not be confirmed — check the source.'],
    ['null', null, 'Current status could not be confirmed — check the source.'],
    ['self-contradicting', { ...ACTIONABLE_TRUTH, listing_state: 'closed' },
      'Current status could not be confirmed — check the source.'],
  ];

  it.each(REASONS)('%s says why, and nothing the source claimed', async (
    _label, truth, expected,
  ) => {
    const meta = await metadataFor({
      target_truth: truth,
      // Canonical kind per reason. `faculty_not_accepting` is a named
      // person's own refusal and the backend emits it only for a
      // `faculty_research` row; on the default listing it reads as
      // unverified, so this case would assert the generic sentence while
      // claiming to test the person's words.
      ...((truth as { reason_code?: string } | null)?.reason_code === 'faculty_not_accepting'
        ? { source_type: 'faculty_research' }
        : {}),
    });

    for (const text of descriptions(meta)) {
      expect(text).toContain(expected);
      expect(text).not.toContain('POISON');
    }
    // A dead posting is not freshly published news.
    expect(publishedTime(meta)).toBeUndefined();
    // And no deadline leaks into any preview text.
    for (const text of descriptions(meta)) {
      expect(text).not.toContain('2099-12-31');
    }
  });

  it('omits the truth field entirely, same as a malformed one', async () => {
    const opp = record();
    delete (opp as Record<string, unknown>).target_truth;
    fetchOpportunityDetail.mockResolvedValue({ status: 'ok', opportunity: opp });

    const meta = await generateMetadata({ params: Promise.resolve({ id: 'opp-1' }) });

    for (const text of descriptions(meta)) {
      expect(text).toContain('Current status could not be confirmed');
      expect(text).not.toContain('POISON');
    }
    expect(publishedTime(meta)).toBeUndefined();
  });

  it('withholds the description from an unreviewed record kind, truth or no truth', async () => {
    // Two shapes, both unreviewed. The first is the one the backend now
    // stamps; the second is a payload still claiming `actionable`, which the
    // parser refuses outright because an unreviewed kind can never be live.
    const stamped = await metadataFor({
      source_type: undefined,
      target_truth: {
        ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
        accepting_state: 'unknown', reference_only: false,
        reason_code: 'record_kind_unverified',
      },
    });
    for (const text of descriptions(stamped)) {
      expect(text).not.toContain('POISON');
      expect(text).toContain('Record type is unverified');
    }
    expect(publishedTime(stamped)).toBeUndefined();

    const claiming = await metadataFor({ source_type: undefined });
    for (const text of descriptions(claiming)) {
      expect(text).not.toContain('POISON');
      expect(text).toContain('Current status could not be confirmed');
    }
    expect(publishedTime(claiming)).toBeUndefined();
  });

  it('gives a live faculty profile neutral framing, not the scraped prose', async () => {
    const meta = await metadataFor({ source_type: 'faculty_research' });

    for (const text of descriptions(meta)) {
      expect(text).not.toContain('POISON');
      expect(text).toContain('Current openings are not confirmed');
    }
    expect(publishedTime(meta)).toBeUndefined();
  });
});
