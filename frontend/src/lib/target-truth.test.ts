import { describe, expect, it } from 'vitest';
import type { Opportunity, PublicTargetTruth } from './types';
import {
  opportunityApplicationUrl,
  opportunitySourceUrl,
  targetPosture,
  targetStatusReason,
} from './target-truth';

function opp(
  truth: Partial<PublicTargetTruth> | undefined,
  overrides: Partial<Opportunity> = {},
): Opportunity {
  return {
    id: 'opp-1',
    title: 'A project',
    source_type: 'campus_program',
    url: 'https://example.edu/projects/1',
    source_url: 'https://example.edu/projects/1',
    application: { application_url: 'https://example.edu/apply' },
    ...(truth ? { target_truth: truth as PublicTargetTruth } : {}),
    ...overrides,
  } as unknown as Opportunity;
}

const OPEN: PublicTargetTruth = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: '2026-07-21T08:18:35',
  expires_at: null,
};

// Exactly what src/evidence.target_truth emits for each refusal — derived by
// enumerating the backend, not written from memory. These are the only shapes
// the parser accepts, and the poison matrix below is built by breaking one
// field of each.
const CANONICAL = {
  listing_closed: {
    ...OPEN,
    actionable: false, reason_code: 'listing_closed' as const,
    listing_state: 'closed' as const, accepting_state: 'not_accepting' as const,
    reference_only: false,
  },
  reference_only: {
    ...OPEN,
    actionable: false, reason_code: 'reference_only' as const,
    listing_state: 'unknown' as const, accepting_state: 'unknown' as const,
    reference_only: true,
  },
  faculty_not_accepting: {
    ...OPEN,
    actionable: false, reason_code: 'faculty_not_accepting' as const,
    listing_state: 'unknown' as const, accepting_state: 'not_accepting' as const,
    reference_only: false,
  },
  inactive: {
    ...OPEN,
    actionable: false, reason_code: 'inactive' as const,
    listing_state: 'unknown' as const, accepting_state: 'unknown' as const,
    reference_only: false,
  },
};

// The kind each refusal is emitted on. `faculty_not_accepting` is a person's
// own written words, so the backend only ever reaches it through
// faculty_availability_status — which answers `unknown` for anything that is
// not a `faculty_research` row. Putting that reason on the default listing
// fixture would be testing a payload the contract cannot produce.
const SOURCE_TYPE_FOR_REASON: Record<string, string> = {
  listing_closed: 'campus_program',
  reference_only: 'campus_program',
  faculty_not_accepting: 'faculty_research',
  inactive: 'campus_program',
};

/** A record whose kind is the one the backend emits this truth's reason on. */
function canonicalOpp(truth: Record<string, unknown>): Opportunity {
  return opp(truth as never, {
    source_type: SOURCE_TYPE_FOR_REASON[String(truth.reason_code)] ?? 'campus_program',
  } as unknown as Partial<Opportunity>);
}

describe('targetPosture', () => {
  it('is actionable for a complete, consistent, actionable truth', () => {
    expect(targetPosture(opp(OPEN))).toBe('actionable');
  });

  it('keeps a legacy record with unknown listing_state actionable', () => {
    // The unstamped majority of the corpus reports unknown/actionable. Reading
    // "unknown" as "suspend" would retire almost every record in the product.
    expect(targetPosture(opp({
      ...OPEN,
      listing_state: 'unknown',
      accepting_state: 'unknown',
    }))).toBe('actionable');
  });

  // Every reason the backend contract can emit. A code this parser does not
  // know fails the whole payload and degrades the record to `unknown`, so
  // omitting one here means the frontend silently suspends actions on records
  // the server merely explained differently.
  it.each([
    'listing_closed', 'reference_only', 'faculty_not_accepting', 'inactive',
  ] as const)(
    'is historical when the server refused for %s',
    (reason) => {
      expect(targetPosture(canonicalOpp(CANONICAL[reason]))).toBe('historical');
    },
  );

  it('does not fall back to unknown for the faculty stop reason', () => {
    // The distinction that matters: `unknown` means "we could not read this",
    // `historical` means "the source told us". Rendering a stated refusal as
    // unreadable would show the vague banner instead of the person's own words.
    const truth = {
      ...OPEN,
      actionable: false,
      listing_state: 'unknown' as const,
      accepting_state: 'not_accepting' as const,
      reason_code: 'faculty_not_accepting' as const,
    };
    const faculty = opp(truth, {
      source_type: 'faculty_research',
    } as unknown as Partial<Opportunity>);
    expect(targetPosture(faculty)).toBe('historical');
    expect(targetPosture(opp(
      { ...truth, reason_code: 'not_a_real_reason' as never },
      { source_type: 'faculty_research' } as unknown as Partial<Opportunity>,
    ))).toBe('unknown');
  });

  it('is unknown when the field is missing entirely', () => {
    expect(targetPosture(opp(undefined))).toBe('unknown');
  });

  it.each([
    ['not an object', 'nope'],
    ['null', null],
    ['an array', []],
    ['missing actionable', { listing_state: 'open' }],
    ['non-boolean actionable', { ...OPEN, actionable: 'yes' }],
    ['unrecognised listing_state', { ...OPEN, listing_state: 'maybe' }],
    ['non-string verified_at', { ...OPEN, verified_at: 1721000000 }],
    ['non-string expires_at', { ...OPEN, expires_at: {} }],
  ])('is unknown for malformed truth: %s', (_label, truth) => {
    expect(targetPosture(opp(truth as never))).toBe('unknown');
  });

  it.each([
    ['actionable but closed', { ...OPEN, listing_state: 'closed' as const }],
    ['actionable but reference_only', { ...OPEN, reference_only: true }],
    ['actionable but carrying a refusal reason', {
      ...OPEN, reason_code: 'inactive' as const,
    }],
  ])('is unknown for a self-contradicting truth: %s', (_label, truth) => {
    // Two halves of the payload disagree. Trusting the optimistic half is how
    // a closed listing gets an Apply button; suspending is the honest read.
    expect(targetPosture(opp(truth))).toBe('unknown');
  });
});

describe('destination splitting', () => {
  it('offers the application url only for an actionable target', () => {
    expect(opportunityApplicationUrl(opp(OPEN))).toBe('https://example.edu/apply');
  });

  it.each(['historical', 'unknown'])(
    'never offers an application url for a %s target',
    (posture) => {
      const target = posture === 'unknown'
        ? opp(undefined)
        : opp({ ...OPEN, actionable: false, reason_code: 'listing_closed', listing_state: 'closed' });
      expect(opportunityApplicationUrl(target)).toBeUndefined();
    },
  );

  it('never promotes a source url into an application url', () => {
    // The bug this splits apart: falling back through url/source_url meant a
    // reference page could be rendered under an Apply label.
    const noApplyUrl = opp(OPEN, {
      application: { application_url: null },
    } as unknown as Partial<Opportunity>);
    expect(opportunityApplicationUrl(noApplyUrl)).toBeUndefined();
    expect(opportunitySourceUrl(noApplyUrl)).toBe('https://example.edu/projects/1');
  });

  it('never offers a faculty profile url as an application url', () => {
    // A faculty record's application_url is a directory page. Truth alone says
    // "live", so record-kind is the fact that stops it becoming an Apply CTA.
    const faculty = opp(OPEN, {
      source_type: 'faculty_research',
    } as unknown as Partial<Opportunity>);
    expect(targetPosture(faculty)).toBe('actionable');
    expect(opportunityApplicationUrl(faculty)).toBeUndefined();
    expect(opportunitySourceUrl(faculty)).toBe('https://example.edu/projects/1');
  });

  it.each([
    ['missing', undefined],
    ['unrecognised', 'some_new_collector'],
    ['empty', ''],
  ])('never offers an application url for a %s source_type', (_label, sourceType) => {
    const target = opp(OPEN, {
      source_type: sourceType,
    } as unknown as Partial<Opportunity>);
    expect(opportunityApplicationUrl(target)).toBeUndefined();
  });

  it('prefers source_url over url when they differ', () => {
    // url is a display link some collectors rewrite; source_url is the page
    // actually read. The citable one is the source.
    const split = opp(OPEN, {
      url: 'https://example.edu/display/1',
      source_url: 'https://example.edu/scraped/1',
    } as unknown as Partial<Opportunity>);
    expect(opportunitySourceUrl(split)).toBe('https://example.edu/scraped/1');
  });

  it('falls back to url when source_url is absent', () => {
    const displayOnly = opp(OPEN, {
      url: 'https://example.edu/display/1',
      source_url: undefined,
    } as unknown as Partial<Opportunity>);
    expect(opportunitySourceUrl(displayOnly)).toBe('https://example.edu/display/1');
  });

  it('keeps the source url readable for every posture', () => {
    for (const target of [
      opp(OPEN),
      opp({ ...OPEN, actionable: false, reason_code: 'listing_closed', listing_state: 'closed' }),
      opp(undefined),
    ]) {
      expect(opportunitySourceUrl(target)).toBe('https://example.edu/projects/1');
    }
  });

  it('never returns the application url as a source url', () => {
    const applyOnly = opp(OPEN, {
      url: undefined, source_url: undefined,
    } as unknown as Partial<Opportunity>);
    expect(opportunitySourceUrl(applyOnly)).toBeUndefined();
  });
});

describe('a refusal must agree with its own fields', () => {
  // Until this check existed, `actionable: false` was taken at face value and
  // the reason was trusted whatever the rest of the payload said. Every
  // surface then rendered copy asserting the one specific thing the payload
  // contradicted: "this listing closed" on a record reporting listing_state
  // `open`, "reference material" with the reference flag clear.
  //
  // Each poison below breaks exactly one field of a canonical shape, so a
  // failure here names the field that stopped being checked.
  const POISON: [string, Record<string, unknown>][] = [
    ['listing_closed without a closed listing_state',
      { ...CANONICAL.listing_closed, listing_state: 'open' }],
    ['listing_closed still reporting it accepts',
      { ...CANONICAL.listing_closed, accepting_state: 'accepting' }],
    ['listing_closed with an unknown accepting_state',
      { ...CANONICAL.listing_closed, accepting_state: 'unknown' }],
    ['reference_only with the flag clear',
      { ...CANONICAL.reference_only, reference_only: false }],
    ['reference_only that also says closed',
      { ...CANONICAL.reference_only, listing_state: 'closed' }],
    ['reference_only claiming a decided accepting_state',
      { ...CANONICAL.reference_only, accepting_state: 'not_accepting' }],
    ['faculty_not_accepting asserting a listing state',
      { ...CANONICAL.faculty_not_accepting, listing_state: 'closed' }],
    ['faculty_not_accepting flagged as reference material',
      { ...CANONICAL.faculty_not_accepting, reference_only: true }],
    ['faculty_not_accepting that does not say not_accepting',
      { ...CANONICAL.faculty_not_accepting, accepting_state: 'unknown' }],
    ['inactive that also says closed',
      { ...CANONICAL.inactive, listing_state: 'closed' }],
    ['inactive flagged as reference material',
      { ...CANONICAL.inactive, reference_only: true }],
    ['inactive claiming a decided accepting_state',
      { ...CANONICAL.inactive, accepting_state: 'not_accepting' }],
  ];

  it.each(POISON)('%s is unreadable, not historical', (_label, truth) => {
    // On the kind the reason belongs to, so the ONLY thing that can reject it
    // is the field agreement being tested. Leaving the three faculty poisons
    // on the default listing record would let the kind gate reject them and
    // the assertion would hold with reasonAgreesWithFields deleted.
    const target = canonicalOpp(truth);
    expect(targetPosture(target)).toBe('unknown');
    // And the reason a surface would print is the honest one: we could not
    // confirm the status, NOT the specific claim the payload made.
    expect(targetStatusReason(target)).toBe('status_unverified');
  });

  it.each(Object.entries(CANONICAL))('accepts the canonical %s shape', (reason, truth) => {
    const target = canonicalOpp(truth);
    expect(targetPosture(target)).toBe('historical');
    expect(targetStatusReason(target)).toBe(reason);
  });
});

describe('the record kind and the truth must corroborate each other', () => {
  // Parsing the envelope alone leaves two holes: a payload can claim
  // `actionable` on a row nobody has classified — and every CTA unlocks off
  // that — or claim `record_kind_unverified` on a confirmed listing, hiding a
  // real opening behind copy about our own review queue.
  const KIND_UNVERIFIED = {
    ...OPEN,
    actionable: false,
    listing_state: 'unknown' as const,
    accepting_state: 'unknown' as const,
    reference_only: false,
    reason_code: 'record_kind_unverified' as const,
  };

  function withKind(truth: unknown, sourceType?: string, wireKind?: unknown) {
    const target = opp(truth as never, {
      ...(sourceType === undefined ? {} : { source_type: sourceType }),
      ...(wireKind === undefined ? {} : { record_kind: wireKind }),
    } as never);
    if (sourceType === undefined) {
      delete (target as unknown as Record<string, unknown>).source_type;
    }
    return target;
  }

  it('reports an unreviewed kind as historical, in its own words', () => {
    const target = withKind(KIND_UNVERIFIED, undefined);
    expect(targetPosture(target)).toBe('historical');
    expect(targetStatusReason(target)).toBe('record_kind_unverified');
  });

  it.each(['campus_program', 'faculty_research'])(
    'refuses that reason on a confirmed %s record',
    (sourceType) => {
      const target = withKind(KIND_UNVERIFIED, sourceType);
      expect(targetPosture(target)).toBe('unknown');
      expect(targetStatusReason(target)).toBe('status_unverified');
    },
  );

  it.each([
    ['a brand-new source type nobody has classified', 'future_new_collector_v9'],
    ['no source type at all', undefined],
  ])('never lets %s be actionable', (_label, sourceType) => {
    const target = withKind(OPEN, sourceType);
    expect(targetPosture(target)).toBe('unknown');
    expect(targetStatusReason(target)).toBe('status_unverified');
    // The consequence: no Apply URL is handed out for it.
    expect(opportunityApplicationUrl(target)).toBeUndefined();
  });

  it.each([
    ['listing_closed', CANONICAL.listing_closed],
    ['reference_only', CANONICAL.reference_only],
    ['inactive', CANONICAL.inactive],
  ])('keeps the more specific %s reason on an unreviewed row', (reason, truth) => {
    // One-way, not an equivalence: an unreviewed row that ALSO states it
    // closed should tell the student what the source said, not a vaguer truth
    // about our review queue.
    const target = withKind(truth, undefined);
    expect(targetPosture(target)).toBe('historical');
    expect(targetStatusReason(target)).toBe(reason);
  });

  const WIRE_KIND_POISON: [string, unknown][] = [
    ['a kind that disagrees with the source type', 'listing'],
    ['a kind nobody defines', 'some_future_kind'],
    ['a non-string kind', 7],
    ['a null kind', null],
    ['an object kind', {}],
  ];

  it.each(WIRE_KIND_POISON)('fails closed on %s', (_label, wireKind) => {
    // The wire may carry the server's own normalization; where it does, it
    // must agree with what this build derives from the same field. Silently
    // ignoring a value we cannot read is how a renamed source type becomes a
    // listing on one side of the deploy and not the other.
    const target = withKind(OPEN, 'faculty_research', wireKind);
    expect(targetPosture(target)).toBe('unknown');
    expect(targetStatusReason(target)).toBe('status_unverified');
  });

  it.each([
    ['faculty_research', 'faculty_contact'],
    ['campus_program', 'listing'],
  ])('accepts %s when the wire agrees', (sourceType, wireKind) => {
    const target = withKind(OPEN, sourceType, wireKind);
    expect(targetPosture(target)).toBe('actionable');
    expect(targetStatusReason(target)).toBeNull();
  });

  it('accepts a record that carries no wire kind at all', () => {
    // Absence is not disagreement: an older backend simply does not send it.
    expect(targetPosture(withKind(OPEN, 'campus_program'))).toBe('actionable');
  });
});

describe('faculty_not_accepting is a quotation only a faculty record can carry', () => {
  function stopRecord(sourceType: string | undefined, wireKind?: string) {
    const target = opp(CANONICAL.faculty_not_accepting as never, {
      ...(sourceType === undefined ? {} : { source_type: sourceType }),
      ...(wireKind === undefined ? {} : { record_kind: wireKind }),
    } as never);
    if (sourceType === undefined) {
      delete (target as unknown as Record<string, unknown>).source_type;
    }
    return target;
  }

  it('a real faculty profile keeps the person\'s own words', () => {
    const target = stopRecord('faculty_research', 'faculty_contact');
    expect(targetPosture(target)).toBe('historical');
    expect(targetStatusReason(target)).toBe('faculty_not_accepting');
  });

  it.each([
    ['a confirmed listing', 'campus_program', 'listing'],
    ['a source type nobody has reviewed', 'future_new_collector_v9', 'unknown'],
    ['a row with no source type at all', undefined, 'unknown'],
  ])('refuses it on %s', (_label, sourceType, wireKind) => {
    // Every surface renders this reason as a named person's written refusal.
    // On a listing nobody wrote it; on an unreviewed row we do not know that
    // anybody did. So the payload is not read at all, rather than quoted at
    // someone who never spoke — and the honest sentence is printed instead.
    const target = stopRecord(sourceType, wireKind);
    expect(targetPosture(target)).toBe('unknown');
    expect(targetStatusReason(target)).toBe('status_unverified');
    expect(opportunityApplicationUrl(target)).toBeUndefined();
  });

  it.each([
    ['listing_closed', CANONICAL.listing_closed],
    ['reference_only', CANONICAL.reference_only],
    ['inactive', CANONICAL.inactive],
  ])('leaves %s on an unreviewed row exactly as precise as it was', (reason, truth) => {
    // One reason, not the whole table. Widening the gate to every reason
    // would take three statements the source itself made and replace all of
    // them with "we could not confirm this".
    //
    // The row carries `record_kind: 'unknown'` — what a CURRENT backend sends
    // for an unreviewed source type, as opposed to the wire-kind-less shape
    // an older one sends, which the block above covers.
    const target = opp(truth as never, { record_kind: 'unknown' } as never);
    delete (target as unknown as Record<string, unknown>).source_type;
    expect(targetPosture(target)).toBe('historical');
    expect(targetStatusReason(target)).toBe(reason);
  });
});

describe('a live truth must agree with its own fields too', () => {
  // `actionable` is what unlocks every CTA in the product, so it gets the same
  // exact table the refusals do. The backend emits precisely two live shapes:
  // a stated-open listing that is accepting, and an unstamped record that
  // states nothing either way. Anything between them was written by something
  // other than the contract.
  const LIVE_OK: [string, Record<string, unknown>][] = [
    ['a stated-open, accepting listing',
      { ...OPEN, listing_state: 'open', accepting_state: 'accepting' }],
    ['the unstamped corpus majority',
      { ...OPEN, listing_state: 'unknown', accepting_state: 'unknown' }],
  ];

  it.each(LIVE_OK)('%s stays actionable', (_label, truth) => {
    expect(targetPosture(opp(truth as never))).toBe('actionable');
    expect(targetStatusReason(opp(truth as never))).toBeNull();
  });

  const LIVE_POISON: [string, Record<string, unknown>][] = [
    ['open but not saying it accepts',
      { ...OPEN, listing_state: 'open', accepting_state: 'unknown' }],
    ['unstamped yet claiming to accept',
      { ...OPEN, listing_state: 'unknown', accepting_state: 'accepting' }],
  ];

  it.each(LIVE_POISON)('%s is unreadable, not actionable', (_label, truth) => {
    const target = opp(truth as never);
    expect(targetPosture(target)).toBe('unknown');
    expect(targetStatusReason(target)).toBe('status_unverified');
    // The consequence that matters: no Apply URL is handed out for it.
    expect(opportunityApplicationUrl(target)).toBeUndefined();
  });
});
