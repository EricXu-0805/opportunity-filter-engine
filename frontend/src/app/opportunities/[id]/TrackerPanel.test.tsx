import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { InteractionRecord } from '@/lib/supabase';

vi.mock('@/components/MarkdownPreview', () => ({
  default: ({ children }: { children: string }) => <div data-testid="md-preview">{children}</div>,
}));

vi.mock('@/components/AttachmentsPanel', () => ({
  default: ({ opportunityId }: { opportunityId: string }) => (
    <div data-testid="attachments-panel" data-opp={opportunityId} />
  ),
}));

vi.mock('@/components/StatusTimeline', () => ({
  default: ({
    opportunityId,
    fallbackType,
    fallbackUpdatedAt,
  }: {
    opportunityId: string;
    fallbackType: string;
    fallbackUpdatedAt: string;
  }) => (
    <div
      data-testid="status-timeline"
      data-opp={opportunityId}
      data-type={fallbackType}
      data-updated={fallbackUpdatedAt}
    />
  ),
}));

import { TrackerPanel } from './TrackerPanel';

const OPP_ID = 'opp-7';

function tFn(key: string) {
  return key;
}

function detail(overrides: Partial<InteractionRecord> = {}): InteractionRecord {
  return {
    id: 'i-1',
    device_id: 'dev-1',
    opportunity_id: OPP_ID,
    type: 'applied',
    notes: null,
    remind_at: null,
    updated_at: '2026-05-01T10:00:00Z',
    ...overrides,
  } as InteractionRecord;
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('TrackerPanel — collapse / expand', () => {
  it('renders the addButton label when there is no existing detail', () => {
    render(
      <TrackerPanel
        detail={null}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );
    expect(screen.getByText(/detail.tracker.addButton/)).toBeInTheDocument();
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  it('renders the openButton label and is pre-expanded when detail.notes already exists', () => {
    render(
      <TrackerPanel
        detail={detail({ notes: 'existing note' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );
    expect(screen.getByText(/detail.tracker.openButton/)).toBeInTheDocument();
    expect(screen.getByRole('tablist')).toBeInTheDocument();
  });

  it('clicking the toggle button flips aria-expanded', () => {
    render(
      <TrackerPanel
        detail={null}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );
    const toggle = screen.getByRole('button', { expanded: false });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('TrackerPanel — collapsed preview line', () => {
  it('truncates the notes preview at 40 characters with an ellipsis', () => {
    const longNote = 'A'.repeat(80);
    render(
      <TrackerPanel
        detail={detail({ notes: longNote })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );
    fireEvent.click(screen.getByRole('button', { expanded: true }));
    const preview = screen.getByText((content) => content.startsWith('A'.repeat(40)) && content.endsWith('…'));
    expect(preview).toBeInTheDocument();
  });

  it('shows the remind_at date in the collapsed view when present', () => {
    render(
      <TrackerPanel
        detail={detail({ remind_at: '2026-12-31' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );
    fireEvent.click(screen.getByRole('button', { expanded: true }));
    const preview = screen.getByRole('button');
    expect(preview.textContent).toContain('2026-12-31');
  });
});

describe('TrackerPanel — notes editor', () => {
  it('updates the textarea value and the char counter as the user types', () => {
    render(
      <TrackerPanel
        detail={null}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));

    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'hello' } });
    expect(textarea.value).toBe('hello');
    expect(screen.getByText(/5 \/ 2000/)).toBeInTheDocument();
  });

  it('honors the textarea maxLength=2000 attribute', () => {
    render(
      <TrackerPanel
        detail={null}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/) as HTMLTextAreaElement;
    expect(textarea.maxLength).toBe(2000);
  });

  it('clicking the Preview tab switches the active tab to preview', () => {
    render(
      <TrackerPanel
        detail={detail({ notes: '# Heading' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    const previewTab = screen.getByRole('tab', { name: /detail.tracker.previewTab/ });
    const editTab = screen.getByRole('tab', { name: /detail.tracker.editTab/ });

    expect(editTab).toHaveAttribute('aria-selected', 'true');
    expect(previewTab).toHaveAttribute('aria-selected', 'false');

    fireEvent.click(previewTab);

    expect(previewTab).toHaveAttribute('aria-selected', 'true');
    expect(editTab).toHaveAttribute('aria-selected', 'false');
  });

  it('Preview tab renders MarkdownPreview with the current notes', async () => {
    render(
      <TrackerPanel
        detail={detail({ notes: '# Hi' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    fireEvent.click(screen.getByRole('tab', { name: /detail.tracker.previewTab/ }));

    const md = await screen.findByTestId('md-preview');
    expect(md.textContent).toBe('# Hi');
  });

  it('Preview tab shows the previewEmpty placeholder when notes are blank', async () => {
    render(
      <TrackerPanel
        detail={null}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );

    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    fireEvent.click(screen.getByRole('tab', { name: /detail.tracker.previewTab/ }));

    expect(await screen.findByText(/detail.tracker.previewEmpty/)).toBeInTheDocument();
  });
});

describe('TrackerPanel — reminder date', () => {
  it('updates the remind_at state when the date picker changes', () => {
    render(
      <TrackerPanel
        detail={null}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));

    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: '2026-08-01' } });
    expect(dateInput.value).toBe('2026-08-01');
  });

  it('the Clear button appears only when remind_at is set and clicking it clears the date', () => {
    render(
      <TrackerPanel
        detail={detail({ remind_at: '2026-08-01' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    const clearBtn = screen.getByText(/common.clear/);
    fireEvent.click(clearBtn);

    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    expect(dateInput.value).toBe('');
    expect(screen.queryByText(/common.clear/)).toBeNull();
  });
});

describe('TrackerPanel — debounced save', () => {
  it('shows "saving" immediately, then "saved" after the 600ms debounce + onSave resolves', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });

    render(
      <TrackerPanel
        detail={null}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);
    fireEvent.change(textarea, { target: { value: 'work in progress' } });

    expect(screen.getByText(/common.saving/)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });

    expect(onSave).toHaveBeenCalledWith({ notes: 'work in progress' }); // sparse: remind_at was never dirty
    vi.useRealTimers();
  });

  it('debounces rapid keystrokes into a single onSave call', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });

    render(
      <TrackerPanel
        detail={null}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);

    fireEvent.change(textarea, { target: { value: 'a' } });
    fireEvent.change(textarea, { target: { value: 'ab' } });
    fireEvent.change(textarea, { target: { value: 'abc' } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({ notes: 'abc' }); // sparse: remind_at was never dirty
    vi.useRealTimers();
  });

  it('saves notes as null when the value is whitespace-only (does not persist empty strings)', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });

    render(
      <TrackerPanel
        detail={detail({ notes: 'existing' })}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);
    fireEvent.change(textarea, { target: { value: '    ' } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });

    expect(onSave).toHaveBeenCalledWith({ notes: null }); // sparse: remind_at was never dirty
    vi.useRealTimers();
  });

  it('never auto-saves when no status is tracked yet (no inferred applied)', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });

    render(
      <TrackerPanel
        detail={null}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );

    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);
    fireEvent.change(textarea, { target: { value: 'drafting thoughts' } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });

    expect(onSave).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('shows the pick-a-status hint while no status is tracked', () => {
    render(
      <TrackerPanel
        detail={null}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    expect(screen.getByText(/detail.tracker.statusFirst/)).toBeInTheDocument();
  });

  it('hides the pick-a-status hint once a status exists', () => {
    render(
      <TrackerPanel
        detail={detail({ notes: 'existing' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );
    expect(screen.queryByText(/detail.tracker.statusFirst/)).toBeNull();
  });
});

describe('TrackerPanel — child component mounting', () => {
  it('mounts StatusTimeline with the detail.type + detail.updated_at when both are present', async () => {
    render(
      <TrackerPanel
        detail={detail({ type: 'applied', updated_at: '2026-05-01T10:00:00Z', notes: 'open me' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    const timeline = await screen.findByTestId('status-timeline');
    expect(timeline.getAttribute('data-opp')).toBe(OPP_ID);
    expect(timeline.getAttribute('data-type')).toBe('applied');
    expect(timeline.getAttribute('data-updated')).toBe('2026-05-01T10:00:00Z');
  });

  it('mounts AttachmentsPanel only when hasInteraction is true', async () => {
    const { rerender } = render(
      <TrackerPanel
        detail={detail({ notes: 'expand' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );
    expect(await screen.findByTestId('attachments-panel')).toBeInTheDocument();

    rerender(
      <TrackerPanel
        detail={detail({ notes: 'expand' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction={false}
        reminderEligible
        t={tFn}
      />,
    );

    await waitFor(() => expect(screen.queryByTestId('attachments-panel')).toBeNull());
  });
});

describe('TrackerPanel — honest save failure (never "Saved" on a rejected onSave)', () => {
  it('shows an error state with a Retry action when onSave rejects, never "saved"', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockRejectedValue(new Error('network down'));

    render(
      <TrackerPanel
        detail={null}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);
    fireEvent.change(textarea, { target: { value: 'work in progress' } });

    await act(async () => { await vi.advanceTimersByTimeAsync(700); });

    expect(screen.queryByText(/common.saved/)).toBeNull();
    expect(screen.getByText(/detail.tracker.saveError/)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it('clicking Retry replays the save with the current notes/remindAt and shows "saved" on success', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ status: 'committed' });

    render(
      <TrackerPanel
        detail={null}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        t={tFn}
      />,
    );

    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);
    fireEvent.change(textarea, { target: { value: 'draft' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(screen.getByText(/detail.tracker.saveError/)).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByText(/common.retry/));
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(onSave).toHaveBeenCalledTimes(2);
    expect(onSave).toHaveBeenNthCalledWith(2, { notes: 'draft' }); // sparse: remind_at was never dirty
    expect(screen.getByText(/common.saved/)).toBeInTheDocument();
    expect(screen.queryByText(/detail.tracker.saveError/)).toBeNull();
    vi.useRealTimers();
  });
});

describe('TrackerPanel — N1/N2 monotonic revision (only the LATEST attempt may settle Saved/Error)', () => {
  afterEach(() => vi.useRealTimers());

  it('N1 in-flight; the user types N2 before N2\'s own debounce even fires — N1\'s completion (success) must not display Saved for a draft the user has already changed', async () => {
    vi.useFakeTimers();
    let resolveN1: ((v: { status: 'committed' }) => void) | undefined;
    const onSave = vi.fn().mockImplementation(() => new Promise((r) => { resolveN1 = r; }));
    render(<TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />);
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);

    fireEvent.change(textarea, { target: { value: 'N1' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(600); }); // N1's debounce fires — attemptSave starts, still in flight
    expect(onSave).toHaveBeenCalledTimes(1);

    fireEvent.change(textarea, { target: { value: 'N1N2' } }); // N2 typed — N1 still unresolved, N2's own 600ms hasn't elapsed

    await act(async () => { resolveN1?.({ status: 'committed' }); }); // N1 resolves late — must be a no-op for display
    expect(screen.queryByText(/common.saved/)).toBeNull();
    expect(screen.queryByText(/detail.tracker.saveError/)).toBeNull();
  });

  it('N1 in-flight; N2 typed before N2\'s debounce fires — N1\'s completion (FAILURE) must not display an error for a draft the user has already changed', async () => {
    vi.useFakeTimers();
    let rejectN1: ((e: Error) => void) | undefined;
    const onSave = vi.fn().mockImplementation(() => new Promise((_r, rej) => { rejectN1 = rej; }));
    render(<TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />);
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);

    fireEvent.change(textarea, { target: { value: 'N1' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(onSave).toHaveBeenCalledTimes(1);

    fireEvent.change(textarea, { target: { value: 'N1N2' } });

    await act(async () => { rejectN1?.(new Error('n1 failed')); });
    expect(screen.queryByText(/detail.tracker.saveError/)).toBeNull();
    expect(screen.queryByText(/common.saved/)).toBeNull();
  });

  it('N1 succeeds, then N2 (a fully separate later edit) fails: the final displayed state is N2\'s failure, not a lingering Saved from N1', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn()
      .mockResolvedValueOnce({ status: 'committed' })
      .mockRejectedValueOnce(new Error('n2 failed'));
    render(<TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />);
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);

    fireEvent.change(textarea, { target: { value: 'N1' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(screen.getByText(/common.saved/)).toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: 'N1N2' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/common.saved/)).toBeNull();
    expect(screen.getByText(/detail.tracker.saveError/)).toBeInTheDocument();
  });

  it('N1 fails, then N2 (a later edit) succeeds: the final displayed state is Saved, not a lingering error from N1', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn()
      .mockRejectedValueOnce(new Error('n1 failed'))
      .mockResolvedValueOnce({ status: 'committed' });
    render(<TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />);
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);

    fireEvent.change(textarea, { target: { value: 'N1' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(screen.getByText(/detail.tracker.saveError/)).toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: 'N1N2' } }); // a new edit — invalidates N1's failure immediately
    expect(screen.queryByText(/detail.tracker.saveError/)).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/common.saved/)).toBeInTheDocument();
  });

  it('both N1 and N2 fail: the final displayed error/Retry corresponds to N2, not N1', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn()
      .mockRejectedValueOnce(new Error('n1 failed'))
      .mockRejectedValueOnce(new Error('n2 failed'))
      .mockResolvedValueOnce({ status: 'committed' });
    render(<TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />);
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);

    fireEvent.change(textarea, { target: { value: 'N1' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    fireEvent.change(textarea, { target: { value: 'N1N2' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/detail.tracker.saveError/)).toBeInTheDocument();

    // Retry must replay N2's exact patch ('N1N2'), never N1's.
    await act(async () => {
      fireEvent.click(screen.getByText(/common.retry/));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(onSave).toHaveBeenNthCalledWith(3, { notes: 'N1N2' });
    expect(screen.getByText(/common.saved/)).toBeInTheDocument();
  });

  it('after a failure, ANY new edit immediately removes the stale Retry — clicking it again is impossible because it is gone', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockRejectedValueOnce(new Error('network down'));
    render(<TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />);
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);

    fireEvent.change(textarea, { target: { value: 'bad draft' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(screen.getByText(/common.retry/)).toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: 'bad draft, fixed' } });
    expect(screen.queryByText(/common.retry/)).toBeNull();
    expect(screen.queryByText(/detail.tracker.saveError/)).toBeNull();
  });

  it('a parent detail round-trip (an unrelated field\'s own save landing) never overwrites a dirty, uncommitted draft in the OTHER field', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    const { rerender } = render(
      <TrackerPanel detail={detail({ notes: undefined, remind_at: undefined })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />,
    );
    fireEvent.click(screen.getByRole('button', { expanded: false }));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'still typing, not yet saved' } });

    // Simulate a DIFFERENT save (e.g. a reminder set from elsewhere) landing
    // and the parent re-rendering with a detail that reflects it, while
    // notes remains whatever it was BEFORE this component ever touched it
    // (i.e. this rewrite did not originate from notes).
    rerender(
      <TrackerPanel detail={detail({ notes: undefined, remind_at: '2030-01-01' })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />,
    );
    expect(textarea.value).toBe('still typing, not yet saved'); // untouched
    vi.useRealTimers();
  });

  it('the most dangerous case: N1 (notes) is in flight, the user types N2 (notes, same field) before N1 resolves, N1 SUCCEEDS and the parent rewrites detail.notes to N1\'s value — the textarea must still show N2, and N2\'s own eventual save must send N2\'s patch, not N1\'s', async () => {
    vi.useFakeTimers();
    let resolveN1: ((v: { status: 'committed' }) => void) | undefined;
    const onSave = vi.fn()
      .mockImplementationOnce(() => new Promise((r) => { resolveN1 = r; }))
      .mockResolvedValueOnce({ status: 'committed' });
    const { rerender } = render(
      <TrackerPanel detail={detail({ notes: undefined, remind_at: undefined })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />,
    );
    fireEvent.click(screen.getByRole('button', { expanded: false }));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'N1' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(600); }); // N1's debounce fires — attemptSave starts, still in flight
    expect(onSave).toHaveBeenCalledTimes(1);

    fireEvent.change(textarea, { target: { value: 'N1N2' } }); // N2 typed — same field, N1 still unresolved
    expect(textarea.value).toBe('N1N2');

    // N1 SUCCEEDS. In the real app this makes the hook update
    // interactionDetail, and OpportunityDetail re-renders TrackerPanel with
    // the new `detail` prop reflecting N1's OWN value — simulate exactly
    // that round-trip here.
    await act(async () => { resolveN1?.({ status: 'committed' }); });
    rerender(
      <TrackerPanel detail={detail({ notes: 'N1', remind_at: undefined })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />,
    );
    expect(textarea.value).toBe('N1N2'); // NOT stomped back to N1 — the user's newer draft survives

    // N2's own debounce now fires and must send N2's patch, not N1's.
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(onSave).toHaveBeenNthCalledWith(2, { notes: 'N1N2' });
    vi.useRealTimers();
  });

  it('abandoned (precondition/generation moved on) never displays Saved', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValueOnce({ status: 'abandoned' });
    render(<TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />);
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);
    fireEvent.change(textarea, { target: { value: 'x' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(screen.queryByText(/common.saved/)).toBeNull();
    expect(screen.queryByText(/detail.tracker.saveError/)).toBeNull();
  });

  it('a reminder-only edit sends a sparse patch that never carries notes, using the SAME normalization as notes-only patches', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    render(
      <TrackerPanel detail={detail({ notes: '  existing  ', remind_at: undefined })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />,
    );
    // detail.notes is truthy, so the panel starts already expanded.
    expect(screen.getByRole('button', { expanded: true })).toBeInTheDocument();
    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: '2030-06-15' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).toHaveBeenCalledWith({ remind_at: '2030-06-15' }); // sparse: notes was never dirty, even though its RAW value has surrounding whitespace vs. the normalized baseline
  });
});

describe('TrackerPanel — writeReady gates every edit control', () => {
  afterEach(() => vi.useRealTimers());

  it('disables the textarea, date input, clear button, and Retry while writeReady is false', () => {
    render(
      <TrackerPanel
        detail={detail({ notes: 'existing', remind_at: '2030-01-01' })}
        onSave={vi.fn()}
        opportunityId={OPP_ID}
        hasInteraction
        reminderEligible
        writeReady={false}
        t={tFn}
      />,
    );
    expect(screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/)).toBeDisabled();
    expect(document.querySelector('input[type="date"]')).toBeDisabled();
    expect(screen.getByText(/common.clear/)).toBeDisabled();
  });

  it('a slow interaction read: typing while NOT writeReady is impossible (disabled), so a real detail landing later can never be auto-saved-over', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    const { rerender } = render(
      <TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible writeReady={false} t={tFn} />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/) as HTMLTextAreaElement;
    expect(textarea).toBeDisabled();

    // A disabled textarea cannot fire a real user "change" — but even if
    // something (e.g. a stray programmatic dispatch) got a value in there,
    // the debounced auto-save effect itself is gated on writeReady too.
    fireEvent.change(textarea, { target: { value: 'X' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).not.toHaveBeenCalled();

    // The real detail (Y) now lands, and writeReady flips true.
    rerender(
      <TrackerPanel detail={detail({ notes: 'Y' })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible writeReady t={tFn} />,
    );
    expect(textarea.value).toBe('Y'); // X was never treated as a real, dirty draft
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).not.toHaveBeenCalled(); // nothing dirty relative to the now-current baseline
  });

  it('a draft typed while NOT writeReady, once writeReady flips true, is retried automatically via the same dirty-tracking mechanism (never permanently abandoned)', async () => {
    vi.useFakeTimers();
    // Force the scenario by disabling AFTER the panel is already open with
    // a dirty draft (simulating writeReady flipping false mid-edit, e.g. a
    // status write starting), then flipping it back true.
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    const { rerender } = render(
      <TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible writeReady t={tFn} />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'dirty draft' } });

    // writeReady flips false BEFORE the 600ms debounce fires (e.g. a
    // status write started) — no save attempt happens, and any 'saving'
    // indicator clears rather than sticking.
    rerender(
      <TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible writeReady={false} t={tFn} />,
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).not.toHaveBeenCalled();
    expect(textarea.value).toBe('dirty draft'); // draft itself is never lost

    // writeReady flips back true — the still-dirty draft is retried
    // automatically, with no special "retry the abandoned attempt" logic
    // needed: the debounce-trigger effect re-evaluates because writeReady
    // is in its own dependency array.
    rerender(
      <TrackerPanel detail={null} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible writeReady t={tFn} />,
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).toHaveBeenCalledWith({ notes: 'dirty draft' });
  });

  it('typing then reverting to the baseline value before the 600ms debounce fires returns saveStatus to idle (never stuck on "saving")', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    render(
      <TrackerPanel detail={detail({ notes: 'baseline' })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />,
    );
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'baseline + edit' } });
    expect(screen.getByText(/common.saving/)).toBeInTheDocument(); // shown optimistically, before the 600ms timer

    fireEvent.change(textarea, { target: { value: 'baseline' } }); // reverted, BEFORE 600ms elapses
    expect(screen.queryByText(/common.saving/)).toBeNull(); // must not stay stuck showing "saving"

    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByText(/common.saving/)).toBeNull();
  });

  it('the parent baseline catching up to the current draft (e.g. another save already covered it) before the 600ms timer fires also returns saveStatus to idle', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    const { rerender } = render(
      <TrackerPanel detail={detail({ notes: 'old' })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />,
    );
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'new draft' } });
    expect(screen.getByText(/common.saving/)).toBeInTheDocument();

    // The parent's baseline advances to EXACTLY the current draft (e.g. an
    // out-of-band save covered it) before this component's own 600ms timer
    // ever fires — attemptSave's own dirty check then finds nothing to do.
    rerender(
      <TrackerPanel detail={detail({ notes: 'new draft' })} onSave={onSave} opportunityId={OPP_ID} hasInteraction reminderEligible t={tFn} />,
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByText(/common.saving/)).toBeNull(); // not stuck
  });
});

describe('TrackerPanel — a reminder is only offered where one would be delivered', () => {
  it('with nothing scheduled: no date input, and it says so', () => {
    render(
      <TrackerPanel
        detail={null} onSave={vi.fn()} opportunityId={OPP_ID}
        hasInteraction reminderEligible={false} t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    // Absent, not disabled: a disabled input still says "you may schedule one
    // here, later".
    expect(document.querySelector('input[type="date"]')).toBeNull();
    expect(screen.getByText('tracker.reminderUnavailable')).toBeInTheDocument();
    expect(screen.queryByText('tracker.reminderWontSend')).toBeNull();
  });

  it('with a date already set: the date and Clear survive, and both views say it will not send', async () => {
    // The student set that reminder. Removing it would be us editing their
    // record; the honest move is to keep it and say it is not going to fire —
    // including in the collapsed view, which is the only one a student
    // scanning the page ever sees.
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    render(
      <TrackerPanel
        detail={detail({ remind_at: '2026-12-31' })} onSave={onSave}
        opportunityId={OPP_ID} hasInteraction reminderEligible={false} t={tFn}
      />,
    );
    // Collapsed first — the panel opens itself because a reminder exists, so
    // close it to read the preview line.
    fireEvent.click(screen.getByRole('button', { expanded: true }));
    const collapsed = screen.getByRole('button');
    expect(collapsed.textContent).toContain('2026-12-31');
    expect(collapsed.textContent).toContain('tracker.reminderWontSend');

    fireEvent.click(collapsed);
    expect(screen.getByText('2026-12-31')).toBeInTheDocument();
    expect(document.querySelector('input[type="date"]')).toBeNull();
    expect(screen.getAllByText('tracker.reminderWontSend').length).toBeGreaterThan(0);
    expect(screen.queryByText('tracker.reminderUnavailable')).toBeNull();

    // Clearing is always allowed.
    fireEvent.click(screen.getByText(/common.clear/));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ remind_at: null }));
  });

  it('a date picked while eligible is never written if eligibility is lost before the debounce fires', async () => {
    // 600ms is long enough for a status change to land. A DOM-level hide
    // never sees a timer that is already scheduled.
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    const { rerender } = render(
      <TrackerPanel
        detail={detail()} onSave={onSave} opportunityId={OPP_ID}
        hasInteraction reminderEligible t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const input = document.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '2030-01-01' } });

    rerender(
      <TrackerPanel
        detail={detail()} onSave={onSave} opportunityId={OPP_ID}
        hasInteraction reminderEligible={false} t={tFn}
      />,
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });

    expect(onSave).not.toHaveBeenCalled();
    // No false success, and the draft goes back to what is actually stored —
    // showing the picked date beside "Saved" would be the worst of the three.
    expect(screen.queryByText(/common.saved/)).toBeNull();
    expect(document.querySelector('input[type="date"]')).toBeNull();
    vi.useRealTimers();
  });

  it('a failed date save is not replayed by Retry once eligibility is gone', async () => {
    // Retry replays the EXACT patch that failed, which was built while the
    // row was still eligible. The click can land in the same frame the new
    // prop commits, so the check has to be synchronous.
    const onSave = vi.fn().mockRejectedValueOnce(new Error('boom'));
    const { rerender } = render(
      <TrackerPanel
        detail={detail()} onSave={onSave} opportunityId={OPP_ID}
        hasInteraction reminderEligible t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const input = document.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '2030-01-01' } });
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    await screen.findByText(/detail.tracker.saveError/);

    rerender(
      <TrackerPanel
        detail={detail()} onSave={onSave} opportunityId={OPP_ID}
        hasInteraction reminderEligible={false} t={tFn}
      />,
    );
    // Immediately, in the same commit — no waiting on a debounce tick. A
    // date-only Retry that can no longer be accepted is a button whose only
    // possible outcome is to fail again, so it is withdrawn with the input.
    expect(screen.queryByText(/common.retry/)).toBeNull();
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/common.saved/)).toBeNull();
    expect(document.querySelector('input[type="date"]')).toBeNull();
  });

  it('a mixed notes+date failure keeps a notes-only Retry, and replaying it never carries the date', async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error('boom'));
    const { rerender } = render(
      <TrackerPanel
        detail={detail()} onSave={onSave} opportunityId={OPP_ID}
        hasInteraction reminderEligible t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    fireEvent.change(
      screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/),
      { target: { value: 'my own note' } },
    );
    fireEvent.change(
      document.querySelector('input[type="date"]') as HTMLInputElement,
      { target: { value: '2030-01-01' } },
    );
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toEqual({ notes: 'my own note', remind_at: '2030-01-01' });
    await screen.findByText(/detail.tracker.saveError/);

    rerender(
      <TrackerPanel
        detail={detail()} onSave={onSave} opportunityId={OPP_ID}
        hasInteraction reminderEligible={false} t={tFn}
      />,
    );

    // The notes half is still the student's. It does not even need a Retry:
    // withdrawing the date resets that draft to baseline, which leaves the
    // notes as the only dirty field, and the ordinary debounce writes them on
    // their own — without the date. Asserted on the patch, which is the thing
    // that matters; the absent Retry is a consequence of a save being in
    // flight, not of the notes having been dropped.
    onSave.mockResolvedValueOnce({ status: 'committed' });

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1][0]).toEqual({ notes: 'my own note' });
    expect(onSave.mock.calls[1][0]).not.toHaveProperty('remind_at');
  });

  it('notes still save on their own while reminders are blocked', async () => {
    // The gate is about reminders. Abandoning the whole patch would throw
    // away notes the student typed because of a rule about dates.
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue({ status: 'committed' });
    render(
      <TrackerPanel
        detail={detail()} onSave={onSave} opportunityId={OPP_ID}
        hasInteraction reminderEligible={false} t={tFn}
      />,
    );
    fireEvent.click(screen.getByText(/detail.tracker.addButton/));
    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);
    fireEvent.change(textarea, { target: { value: 'my own note' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });

    expect(onSave).toHaveBeenCalledWith({ notes: 'my own note' });
    vi.useRealTimers();
  });
});
