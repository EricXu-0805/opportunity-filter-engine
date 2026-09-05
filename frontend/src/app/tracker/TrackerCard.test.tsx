/* @vitest-environment jsdom */
import { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) => {
      if (vars && 'title' in vars) return `${key}:${vars.title}`;
      return key;
    },
  }),
}));

import { TrackerCard } from './TrackerCard';
import type { TFunc } from '@/app/favorites/types';

const t: TFunc = ((key: string) => key) as TFunc;

// Canonical builders, one per shape. Spreading a listing fixture and
// overriding only `source_type` produces a record the backend cannot emit —
// faculty kind wearing a listing's (open, accepting) truth — and a test built
// on an impossible record proves nothing about a real one.
const LIVE_LISTING_TRUTH = {
  listing_state: 'open', reference_only: false, actionable: true,
  accepting_state: 'accepting', reason_code: null,
  verified_at: null, expires_at: null,
} as const;

// A directory page states no listing and no acceptance, so both are unknown.
const LIVE_FACULTY_TRUTH = {
  listing_state: 'unknown', reference_only: false, actionable: true,
  accepting_state: 'unknown', reason_code: null,
  verified_at: null, expires_at: null,
} as const;

const CLOSED_TRUTH = {
  listing_state: 'closed', reference_only: false, actionable: false,
  accepting_state: 'not_accepting', reason_code: 'listing_closed',
  verified_at: null, expires_at: null,
} as const;

const REFERENCE_TRUTH = {
  listing_state: 'unknown', reference_only: true, actionable: false,
  accepting_state: 'unknown', reason_code: 'reference_only',
  verified_at: null, expires_at: null,
} as const;

function liveListing(fields: Record<string, unknown> = {}) {
  return {
    id: 'o1', title: 'Test Lab', url: 'https://example.com',
    source_type: 'campus_program', record_kind: 'listing',
    target_truth: { ...LIVE_LISTING_TRUTH },
    ...fields,
  };
}

function liveFaculty(fields: Record<string, unknown> = {}) {
  return {
    id: 'o1', title: 'Prof. Rivera', url: 'https://faculty.example/profile',
    source_type: 'faculty_research', record_kind: 'faculty_contact',
    target_truth: { ...LIVE_FACULTY_TRUTH },
    ...fields,
  };
}

function deadListing(truth: unknown, fields: Record<string, unknown> = {}) {
  return {
    id: 'o1', title: 'Test Lab', url: 'https://example.com',
    source_type: 'campus_program', record_kind: 'listing',
    target_truth: truth,
    ...fields,
  };
}

// A record nobody has reviewed: an unreviewed source type, the wire kind to
// match, and no truth at all.
function unknownKind(fields: Record<string, unknown> = {}) {
  return {
    id: 'o1', title: 'Test Lab', url: 'https://example.com',
    source_type: 'departmental_newsletter', record_kind: 'unknown',
    ...fields,
  };
}

const opp = liveListing();

describe('TrackerCard faculty trust boundary', () => {
  it('never renders a legacy faculty deadline as an opening deadline', () => {
    render(
      <TrackerCard
        opp={liveFaculty({ deadline: '2099-12-31' })}
        status="applied"
        draft=""
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        t={t}
      />,
    );
    expect(screen.queryByText('2099-12-31')).toBeNull();
  });
});

// TrackerCard's `draft` is a CONTROLLED prop (see TrackerCard.tsx) — the
// real caller (useTrackerData's noteDrafts + page.tsx) owns the state.
// This harness plays that role for tests that need realistic typing+blur
// interaction, mirroring exactly what page.tsx wires in production.
function ControlledCard(
  props: Omit<Parameters<typeof TrackerCard>[0], 'draft' | 'onDraftChange'> & { initialDraft?: string },
) {
  const { initialDraft, ...rest } = props;
  const [draft, setDraft] = useState(initialDraft ?? '');
  return <TrackerCard {...rest} draft={draft} onDraftChange={(_id, v) => setDraft(v)} />;
}

describe('TrackerCard — notes draft is a CONTROLLED prop (owned by the caller, not local state)', () => {
  it('a save invoked on blur (N1) does not block typing the next edit (N2) — the textarea stays editable while notesPending', () => {
    const onSaveNotes = vi.fn();
    render(
      <ControlledCard
        opp={opp}
        status="applied"
        onChangeStatus={() => {}}
        onSaveNotes={onSaveNotes}
        onSetReminder={() => {}}
        notesPending
        t={t}
      />,
    );
    const textarea = screen.getByPlaceholderText('tracker.notesPlaceholder');
    expect(textarea).not.toBeDisabled();
    fireEvent.change(textarea, { target: { value: 'N2 draft, typed while N1 is still saving' } });
    expect(textarea).toHaveValue('N2 draft, typed while N1 is still saving');
  });

  it('blurring commits the current draft via onSaveNotes(id, draft)', () => {
    const onSaveNotes = vi.fn();
    render(
      <ControlledCard
        opp={opp}
        status="applied"
        onChangeStatus={() => {}}
        onSaveNotes={onSaveNotes}
        onSetReminder={() => {}}
        t={t}
      />,
    );
    const textarea = screen.getByPlaceholderText('tracker.notesPlaceholder');
    fireEvent.change(textarea, { target: { value: 'updated notes' } });
    fireEvent.blur(textarea);
    expect(onSaveNotes).toHaveBeenCalledWith('o1', 'updated notes');
  });

  it('blurring ALWAYS hands the current draft to onSaveNotes, even with no visible change — the card has no dirty-check of its own; only the hook (comparing against the confirmed baseline) decides whether a real write is needed', () => {
    // A card-level "draft !== notes" gate used to skip this call — but
    // `notes` is exactly the value a FAILED save leaves showing (never
    // rolled back). Editing back to that same failed text would then look
    // "unchanged" here and never re-attempt the write, even though the
    // server never actually has it. See the `draft` prop's doc comment.
    const onSaveNotes = vi.fn();
    render(
      <ControlledCard
        initialDraft="hi"
        opp={opp}
        status="applied"
        onChangeStatus={() => {}}
        onSaveNotes={onSaveNotes}
        onSetReminder={() => {}}
        t={t}
      />,
    );
    fireEvent.blur(screen.getByPlaceholderText('tracker.notesPlaceholder'));
    expect(onSaveNotes).toHaveBeenCalledWith('o1', 'hi');
  });

  it('every keystroke calls onDraftChange(id, value) — this is what lets the caller keep the draft alive across a remount (e.g. a status-triggered column move); see use-tracker-data.ts', () => {
    const onDraftChange = vi.fn();
    render(
      <TrackerCard
        opp={opp}
        status="applied"
        draft="hi"
        onDraftChange={onDraftChange}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        t={t}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText('tracker.notesPlaceholder'), { target: { value: 'hi!' } });
    expect(onDraftChange).toHaveBeenCalledWith('o1', 'hi!');
  });

  it('is a pure controlled component: remounting (a different `key`, as page.tsx does across a status/identity change) with a DIFFERENT draft prop shows exactly that value — TrackerCard has no local memory of a prior render to leak', () => {
    const { rerender } = render(
      <TrackerCard
        key="a"
        opp={opp}
        status="applied"
        draft="leftover text from wherever this card was before"
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        t={t}
      />,
    );
    rerender(
      <TrackerCard
        key="b"
        opp={opp}
        status="applied"
        draft=""
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        t={t}
      />,
    );
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder')).toHaveValue('');
  });

  it('shows a visible, retryable error for a failed notes save, independent of the textarea itself', () => {
    const onRetryNotes = vi.fn();
    render(
      <TrackerCard
        opp={opp}
        status="applied"
        draft="hi"
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        notesError
        onRetryNotes={onRetryNotes}
        t={t}
      />,
    );
    expect(screen.getByText('tracker.notesSaveError')).toBeInTheDocument();
    fireEvent.click(screen.getByText('common.retry'));
    expect(onRetryNotes).toHaveBeenCalledWith('o1');
  });
});

describe('TrackerCard — leavingPending (REMOVE or dismiss confirmed in flight): the card is about to disappear, so a NEW notes edit has nowhere safe to land', () => {
  it('the textarea is disabled, and onChange/onBlur are fail-closed (defense-in-depth beyond `disabled`, since e.g. RTL\'s fireEvent bypasses it)', () => {
    const onDraftChange = vi.fn();
    const onSaveNotes = vi.fn();
    render(
      <TrackerCard
        opp={opp}
        status="applied"
        draft="hi"
        onDraftChange={onDraftChange}
        onChangeStatus={() => {}}
        onSaveNotes={onSaveNotes}
        onSetReminder={() => {}}
        leavingPending
        t={t}
      />,
    );
    const textarea = screen.getByPlaceholderText('tracker.notesPlaceholder');
    expect(textarea).toBeDisabled();
    fireEvent.change(textarea, { target: { value: 'a new edit that has nowhere to land' } });
    expect(onDraftChange).not.toHaveBeenCalled();
    fireEvent.blur(textarea);
    expect(onSaveNotes).not.toHaveBeenCalled();
  });

  it('a visible notes error/Retry stays visible during leavingPending, but the Retry button is disabled and fail-closed — retrying a notes save while the row may be about to be deleted/hidden would either land after it\'s gone or race the leave\'s own flush', () => {
    const onRetryNotes = vi.fn();
    render(
      <TrackerCard
        opp={opp}
        status="applied"
        draft="hi"
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        notesError
        onRetryNotes={onRetryNotes}
        leavingPending
        t={t}
      />,
    );
    expect(screen.getByText('tracker.notesSaveError')).toBeInTheDocument(); // still visible
    const retryBtn = screen.getByText('common.retry');
    expect(retryBtn).toBeDisabled();
    fireEvent.click(retryBtn);
    expect(onRetryNotes).not.toHaveBeenCalled();
  });
});

describe('TrackerCard — status/reminder controls (exclusive channel)', () => {
  it('statusPending disables the status menu trigger and the reminder preset buttons, but never the notes textarea', () => {
    render(
      <TrackerCard
        opp={opp}
        status="applied"
        draft="hi"
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        statusPending
        t={t}
      />,
    );
    const statusTrigger = screen.getByRole('button', { name: /statusMenu\.ariaTrigger:Test Lab/ });
    // InteractionStatusMenu's trigger deliberately never uses the native
    // `disabled` attribute — aria-disabled + a click guard instead, so it
    // stays focusable throughout a pending write (see its doc comment).
    expect(statusTrigger).toHaveAttribute('aria-disabled', 'true');
    for (const label of ['tracker.remind3', 'tracker.remind7', 'tracker.remind14']) {
      expect(screen.getByText(label).closest('button')).toBeDisabled();
    }
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder')).not.toBeDisabled();
  });

  it('a reminder set with an existing date shows the clear button, disabled while statusPending', () => {
    render(
      <TrackerCard
        opp={opp}
        status="applied"
        draft="hi"
        onDraftChange={() => {}}
        remindAt="2030-01-01"
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        statusPending
        t={t}
      />,
    );
    expect(screen.getByLabelText('tracker.clearReminder')).toBeDisabled();
  });

  it('shows a visible, retryable error for a failed status/reminder write', () => {
    const onRetryStatus = vi.fn();
    render(
      <TrackerCard
        opp={opp}
        status="applied"
        draft="hi"
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        statusError
        onRetryStatus={onRetryStatus}
        t={t}
      />,
    );
    expect(screen.getByText('tracker.statusSaveError')).toBeInTheDocument();
    fireEvent.click(screen.getByText('common.retry'));
    expect(onRetryStatus).toHaveBeenCalledWith('o1');
  });

  it('notesError and statusError render independently — one does not imply or hide the other', () => {
    render(
      <TrackerCard
        opp={opp}
        status="applied"
        draft="hi"
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        statusError
        notesError
        t={t}
      />,
    );
    expect(screen.getByText('tracker.statusSaveError')).toBeInTheDocument();
    expect(screen.getByText('tracker.notesSaveError')).toBeInTheDocument();
  });
});

describe('TrackerCard — a reminder is only offered where one would be delivered', () => {
  const PRESETS = ['tracker.remind3', 'tracker.remind7', 'tracker.remind14'];

  function renderCard(
    opportunity: Record<string, unknown>,
    status: 'contacted' | 'applied' | 'rejected',
    onSetReminder = () => {},
  ) {
    return render(
      <TrackerCard
        opp={opportunity as never}
        status={status}
        remindAt={opportunity.remindAt as string | undefined}
        draft=""
        onDraftChange={() => {}}
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={onSetReminder}
        t={t}
      />,
    );
  }

  it('a current listing shows its deadline and the presets', () => {
    renderCard(liveListing({ deadline: '2099-12-31' }), 'applied');
    expect(screen.getByText('2099-12-31')).toBeInTheDocument();
    for (const key of PRESETS) expect(screen.getByText(key)).toBeInTheDocument();
    expect(screen.queryByText('tracker.reminderUnavailable')).toBeNull();
  });

  it('a live faculty contact gets the presets and no deadline', () => {
    // The majority case for reminders, and the one a listing-shaped gate
    // would have removed the feature from entirely.
    renderCard(liveFaculty({ deadline: '2099-12-31' }), 'contacted');
    for (const key of PRESETS) expect(screen.getByText(key)).toBeInTheDocument();
    expect(screen.queryByText('2099-12-31')).toBeNull();
    expect(screen.queryByText('tracker.reminderUnavailable')).toBeNull();
  });

  it('a rejected row on a live listing gets no presets — the cron never selects it', () => {
    renderCard(liveListing(), 'rejected');
    for (const key of PRESETS) expect(screen.queryByText(key)).toBeNull();
    // The copy is about the state, not the target: this listing is perfectly
    // live, and it is the status that makes the reminder undeliverable.
    expect(screen.getByText('tracker.reminderUnavailable')).toBeInTheDocument();
  });

  it.each([
    ['closed', deadListing(CLOSED_TRUTH, { deadline: '2099-12-31' })],
    ['reference-only', deadListing(REFERENCE_TRUTH, { deadline: '2099-12-31' })],
    ['unreviewed kind', unknownKind({ deadline: '2099-12-31' })],
  ])('a %s target shows no stale deadline and no presets', (_label, opportunity) => {
    renderCard(opportunity, 'applied');
    expect(screen.queryByText('2099-12-31')).toBeNull();
    for (const key of PRESETS) expect(screen.queryByText(key)).toBeNull();
    expect(screen.getByText('tracker.reminderUnavailable')).toBeInTheDocument();
  });

  it('an existing reminder on a closed target keeps its date and Clear, and says it will not send', () => {
    // All three at once. Folding the warning into the no-reminder branch
    // meant the case that most needs it — a date the student can see, which
    // will never fire — was the only one that never showed it.
    const onSetReminder = vi.fn();
    renderCard(
      deadListing(CLOSED_TRUTH, { remindAt: '2030-01-01' }),
      'applied',
      onSetReminder,
    );
    expect(screen.getByText(/2030-01-01/)).toBeInTheDocument();
    expect(screen.getByText('tracker.reminderWontSend')).toBeInTheDocument();
    expect(screen.queryByText('tracker.reminderUnavailable')).toBeNull();
    for (const key of PRESETS) expect(screen.queryByText(key)).toBeNull();

    fireEvent.click(screen.getByLabelText('tracker.clearReminder'));
    expect(onSetReminder).toHaveBeenCalledWith('o1', null);
  });

  it('links to source_url in preference to url, whatever the posture', () => {
    const { container } = renderCard(
      deadListing(CLOSED_TRUTH, {
        source_url: 'https://example.edu/scraped',
        url: 'https://example.edu/display',
      }),
      'applied',
    );
    expect(container.querySelector('a')?.getAttribute('href'))
      .toBe('https://example.edu/scraped');
  });
});

describe('TrackerCard — notes cannot exceed what the column accepts', () => {
  it('caps the textarea at the CHECK constraint', () => {
    // interactions_notes_length is CHECK (length(notes) <= 2000). Pasting a
    // professor's reply past that produced a save that could never succeed:
    // Postgres rejected it, Retry replayed the same over-long draft forever,
    // and the text stayed on screen looking saved until a reload took it. The
    // same draft also blocked "Not interested", which hands the notes to the
    // dismiss write in one statement.
    render(
      <ControlledCard
        opp={opp}
        status="applied"
        onChangeStatus={() => {}}
        onSaveNotes={() => {}}
        onSetReminder={() => {}}
        t={t}
      />,
    );
    expect(screen.getByPlaceholderText('tracker.notesPlaceholder'))
      .toHaveAttribute('maxlength', '2000');
  });
});
