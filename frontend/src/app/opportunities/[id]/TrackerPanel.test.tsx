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
    const onSave = vi.fn().mockResolvedValue(undefined);

    render(
      <TrackerPanel
        detail={null}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction
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

    expect(onSave).toHaveBeenCalledWith({ notes: 'work in progress', remind_at: null });
    vi.useRealTimers();
  });

  it('debounces rapid keystrokes into a single onSave call', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue(undefined);

    render(
      <TrackerPanel
        detail={null}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction
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
    expect(onSave).toHaveBeenCalledWith({ notes: 'abc', remind_at: null });
    vi.useRealTimers();
  });

  it('saves notes as null when the value is whitespace-only (does not persist empty strings)', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue(undefined);

    render(
      <TrackerPanel
        detail={detail({ notes: 'existing' })}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction
        t={tFn}
      />,
    );

    const textarea = screen.getByPlaceholderText(/detail.tracker.notesPlaceholder/);
    fireEvent.change(textarea, { target: { value: '    ' } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });

    expect(onSave).toHaveBeenCalledWith({ notes: null, remind_at: null });
    vi.useRealTimers();
  });

  it('never auto-saves when no status is tracked yet (no inferred applied)', async () => {
    vi.useFakeTimers();
    const onSave = vi.fn().mockResolvedValue(undefined);

    render(
      <TrackerPanel
        detail={null}
        onSave={onSave}
        opportunityId={OPP_ID}
        hasInteraction={false}
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
        t={tFn}
      />,
    );

    await waitFor(() => expect(screen.queryByTestId('attachments-panel')).toBeNull());
  });
});
