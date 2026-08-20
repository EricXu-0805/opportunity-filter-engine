import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ResultsHeader } from './ResultsHeader';
import type { MatchResult, MatchesResponse } from '@/lib/types';

const { sendMatchesEmailMock } = vi.hoisted(() => ({
  sendMatchesEmailMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  sendMatchesEmail: sendMatchesEmailMock,
}));

// The badge logic is what these tests are about, not the release gate that
// currently hides it: match_ai_refine is closed on main, so an unmocked scope
// would make every badge assertion pass for the wrong reason. Same framing
// CompareTable.test.tsx uses.
const releaseScopeRef = vi.hoisted(() => ({ matchAiRefine: false }));
vi.mock('@/lib/release-scope', () => ({
  RELEASE_SCOPE: releaseScopeRef,
}));

// The header's own onSend, captured off the button. Driving it directly is
// what lets a test AWAIT the outcome: the click path fires and forgets, so a
// rejection there is neither observable nor consumed, and swallowing it in
// the stub would hide the same failure it is supposed to prove.
const captured = vi.hoisted(() => ({
  onSend: null as null | ((email: string) => Promise<unknown>),
}));
vi.mock('@/components/EmailMeButton', () => ({
  default: ({ onSend }: { onSend: (email: string) => Promise<unknown> }) => {
    captured.onSend = onSend;
    return <button type="button" onClick={() => void onSend('student@example.com')}>
      mock-email
    </button>;
  },
}));

const t = (k: string, vars?: Record<string, string | number>) =>
  vars ? `${k}{${Object.entries(vars).map(([a, b]) => `${a}=${b}`).join(',')}}` : k;

beforeEach(() => {
  sendMatchesEmailMock.mockReset();
  sendMatchesEmailMock.mockResolvedValue({ ok: true, count: 6 });
  // Cleared, so a test that never rendered the button cannot drive the
  // previous test's onSend and assert against the wrong header.
  captured.onSend = null;
});

function renderHeader(
  fieldRelevantCount: number,
  overrides: Partial<React.ComponentProps<typeof ResultsHeader>> = {},
) {
  const data = {
    total: 5,
    high_priority: 1,
    good_match: 2,
    reach: 1,
    low_fit: 1,
    results: [],
    field_relevant_count: fieldRelevantCount,
  } as MatchesResponse;
  return render(
    <ResultsHeader
      loading={false}
      showSlowHint={false}
      refining={false}
      refined={false}
      refineFailed={false}
      data={data}
      filteredTotal={0}
      counts={{ all: 5 }}
      favs={new Set<string>()}
      activeTab="all"
      semanticRerank={false}
      onSemanticChange={() => {}}
      onOpenHelp={() => {}}
      onExport={() => {}}
      loadEmailMatches={async () => []}
      t={t}
      {...overrides}
    />,
  );
}

describe('ResultsHeader strong-match header', () => {
  it('hides AI refine until the server can attest a real refined result', () => {
    renderHeader(0);
    expect(screen.queryByTestId('semantic-toggle')).not.toBeInTheDocument();
  });

  it('uses the singular variant for exactly one strong match', () => {
    renderHeader(1);
    expect(screen.getByText(/results\.fieldMatchesOne/)).toBeInTheDocument();
    expect(screen.queryByText(/results\.fieldMatches\{/)).not.toBeInTheDocument();
  });

  it('uses the plural variant with the count otherwise', () => {
    renderHeader(3);
    expect(screen.getByText(/results\.fieldMatches\{count=3\}/)).toBeInTheDocument();
  });

  it('hides the line entirely at zero', () => {
    renderHeader(0);
    expect(screen.queryByText(/results\.fieldMatches/)).not.toBeInTheDocument();
  });
});

describe('ResultsHeader email payload', () => {
  it('sends nothing at all when the loader refuses the page', async () => {
    // The whole chain, not the formatter: onSend awaits loadEmailMatches
    // before it builds a single item, and the loader throws
    // MATCH_CONTRACT_MISMATCH for a page it cannot vouch for — an
    // unnegotiated wire version, a row with no truth, a closed target. If
    // that rejection did not stop the send, a digest goes out under our name
    // built from rows the results page itself refused to render.
    const loadEmailMatches = vi.fn().mockRejectedValue(
      new Error('Match results need to be refreshed. Please retry.'),
    );
    renderHeader(0, { filteredTotal: 3, counts: { all: 3 }, loadEmailMatches });

    // THIS render's handler, not a leftover. beforeEach nulls it; asserting
    // it came back says the button was rendered and the prop assigned, so
    // deleting either fails here instead of silently re-running the previous
    // test's onSend against the previous test's loader.
    expect(captured.onSend).not.toBeNull();

    // Awaited, not clicked. The rejection has to be observed to be asserted
    // on — and it must still be a rejection when it leaves onSend: a header
    // that caught it internally would report a send that never happened.
    await expect(captured.onSend!('student@example.com')).rejects.toThrow(
      'Match results need to be refreshed. Please retry.',
    );

    expect(loadEmailMatches).toHaveBeenCalledTimes(1);
    expect(sendMatchesEmailMock).toHaveBeenCalledTimes(0);
  });

  it('sends once when the loader hands back a page it vouched for', async () => {
    // The positive control for the assertion above, through the same seam:
    // without it, a header that never sends anything at all — or one whose
    // onSend always rejects — would pass the refusal test.
    const loadEmailMatches = vi.fn().mockResolvedValue([{
      final_score: 91,
      opportunity: {
        id: 'opp-live-1',
        title: 'A real listing',
        source_type: 'campus_program',
        deadline: '2026-09-02',
      },
    }] as unknown as MatchResult[]);
    renderHeader(0, { filteredTotal: 1, counts: { all: 1 }, loadEmailMatches });

    expect(captured.onSend).not.toBeNull();
    await expect(captured.onSend!('student@example.com')).resolves.toEqual({
      ok: true, count: 6,
    });

    expect(sendMatchesEmailMock).toHaveBeenCalledTimes(1);
    const [item] = sendMatchesEmailMock.mock.calls[0][1] as Array<Record<string, unknown>>;
    expect(item.opportunity_id).toBe('opp-live-1');
  });

  it('fails closed when the producer cannot prove a listing record', async () => {
    const data = {
      total: 6,
      high_priority: 6,
      good_match: 0,
      reach: 0,
      low_fit: 0,
      results: [],
    } as MatchesResponse;
    const matches = [
      {
        final_score: 98,
        opportunity: {
          title: 'Faculty contact',
          source_type: 'faculty_research',
          deadline: '2026-09-01',
        },
      },
      {
        final_score: 95,
        opportunity: {
          title: 'Verified listing',
          source_type: 'campus_program',
          deadline: '2026-09-02',
        },
      },
      {
        final_score: 90,
        opportunity: {
          title: 'Missing type',
          deadline: '2026-09-03',
        },
      },
      {
        final_score: 85,
        opportunity: {
          title: 'Empty type',
          source_type: '   ',
          deadline: '2026-09-04',
        },
      },
      {
        final_score: 80,
        opportunity: {
          title: 'Unknown type',
          source_type: 'unknown',
          deadline: '2026-09-05',
        },
      },
      {
        final_score: 75,
        opportunity: {
          title: 'Unrecognized type',
          source_type: 'unreviewed_feed',
          deadline: '2026-09-06',
        },
      },
    ] as unknown as MatchResult[];

    render(
      <ResultsHeader
        loading={false}
        showSlowHint={false}
        refining={false}
        refined={false}
        refineFailed={false}
        data={data}
        filteredTotal={matches.length}
        counts={{ all: matches.length }}
        favs={new Set<string>()}
        activeTab="all"
        semanticRerank={false}
        onSemanticChange={() => {}}
        onOpenHelp={() => {}}
        onExport={() => {}}
        loadEmailMatches={async () => matches}
        t={t}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'mock-email' }));

    await waitFor(() => expect(sendMatchesEmailMock).toHaveBeenCalledOnce());
    const items = sendMatchesEmailMock.mock.calls[0][1] as Array<{
      record_kind: string;
      deadline: string | null;
    }>;
    expect(items.map(({ record_kind, deadline }) => [record_kind, deadline])).toEqual([
      ['faculty_contact', null],
      ['listing', '2026-09-02'],
      ['unknown', null],
      ['unknown', null],
      ['unknown', null],
      ['unknown', null],
    ]);
  });

  it('sends BOTH the id and the legacy fields during the split deploy', async () => {
    // Kills the "changed the type but not the payload" mutant in both
    // directions. Without opportunity_id a NEW backend 422s; without title a
    // still-running OLD backend 422s, and Vercel usually deploys first.
    const data = { total: 1, high_priority: 1, good_match: 0, reach: 0, low_fit: 0 } as never;
    const matches = [{
      final_score: 91,
      opportunity: {
        id: 'opp-bridge-1',
        title: 'A real listing',
        source_type: 'campus_program',
        url: 'https://example.edu/listing',
        source: 'uiuc_program',
        organization: 'UIUC',
        deadline: '2026-09-02',
      },
    }] as unknown as MatchResult[];

    render(
      <ResultsHeader
        loading={false}
        showSlowHint={false}
        refining={false}
        refined={false}
        refineFailed={false}
        data={data}
        filteredTotal={1}
        counts={{ all: 1 }}
        favs={new Set<string>()}
        activeTab="all"
        semanticRerank={false}
        onSemanticChange={() => {}}
        onOpenHelp={() => {}}
        onExport={() => {}}
        loadEmailMatches={async () => matches}
        t={t}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'mock-email' }));

    await waitFor(() => expect(sendMatchesEmailMock).toHaveBeenCalledOnce());
    const [item] = sendMatchesEmailMock.mock.calls[0][1] as Array<Record<string, unknown>>;
    expect(item.opportunity_id).toBe('opp-bridge-1');
    expect(item.title).toBe('A real listing');
    expect(item.url).toBe('https://example.edu/listing');
    expect(item.source).toBe('uiuc_program');
    expect(item.record_kind).toBe('listing');
    // The old backend also reads the subject hint.
    expect(sendMatchesEmailMock.mock.calls[0][2]).toBeTruthy();
  });
});

describe('ResultsHeader refine state', () => {
  // Opened only here. The badge logic has to be right for the release that
  // reopens the flag, and main's own test asserts the control stays hidden
  // while it is closed — a file-wide override would make that pass vacuously.
  beforeEach(() => { releaseScopeRef.matchAiRefine = true; });
  afterEach(() => { releaseScopeRef.matchAiRefine = false; });

  it('does not call a list AI-refined while the refine is still running', () => {
    renderHeader(0, { semanticRerank: true, refining: true });
    expect(screen.getByText('results.aiRefining')).toBeInTheDocument();
    expect(screen.queryByText('results.aiBadge')).not.toBeInTheDocument();
  });

  it('claims the AI badge once the refined list is the one on screen', () => {
    renderHeader(0, { semanticRerank: true, refining: false, refined: true });
    expect(screen.getByText('results.aiBadge')).toBeInTheDocument();
    expect(screen.queryByText('results.aiRefining')).not.toBeInTheDocument();
  });

  it('says so plainly when the refine failed, instead of a silent downgrade', () => {
    renderHeader(0, { semanticRerank: true, refining: false, refined: false, refineFailed: true });
    expect(screen.getByText('results.refineFailed')).toBeInTheDocument();
    expect(screen.queryByText('results.aiBadge')).not.toBeInTheDocument();
  });

  it('wears no badge at all when the refine was asked for and never arrived', () => {
    // The rule list is a real answer and stays on screen. What it is not is an
    // AI-refined one, and the toggle being on is not evidence that it is.
    renderHeader(0, { semanticRerank: true, refining: false, refined: false });
    expect(screen.queryByText('results.aiBadge')).not.toBeInTheDocument();
    expect(screen.queryByText('results.aiRefining')).not.toBeInTheDocument();
  });

  it('locks the toggle mid-refine so a click cannot land between two answers', () => {
    renderHeader(0, { semanticRerank: true, refining: true });
    expect(screen.getByTestId('semantic-toggle')).toBeDisabled();
  });
});
