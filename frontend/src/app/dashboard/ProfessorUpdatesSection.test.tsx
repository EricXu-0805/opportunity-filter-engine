/*
 * Dashboard "professor updates" section: real follows -> real verified events
 * from /api/professors/updates, with per-professor read/unread state. Honest
 * empty states — no follows, no verified updates yet — and an error state
 * that never fabricates an empty feed.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { ProfessorUpdateEvent } from '@/lib/types';

const mockListProfessorFollows = vi.fn();
const mockGetProfessorUpdateReads = vi.fn();
const mockMarkProfessorUpdatesRead = vi.fn();
const mockGetProfessorUpdates = vi.fn();

vi.mock('@/lib/supabase', () => ({
  listProfessorFollows: (...args: unknown[]) => mockListProfessorFollows(...args),
  getProfessorUpdateReads: (...args: unknown[]) => mockGetProfessorUpdateReads(...args),
  markProfessorUpdatesRead: (...args: unknown[]) => mockMarkProfessorUpdatesRead(...args),
}));

vi.mock('@/lib/api', () => ({
  getProfessorUpdates: (...args: unknown[]) => mockGetProfessorUpdates(...args),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    locale: 'en',
    t: (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key} ${JSON.stringify(vars)}` : key,
  }),
}));

import { ProfessorUpdatesSection, unreadEventIds } from './ProfessorUpdatesSection';

const PROF_A = 'prof:v1:uiuc:aaaaaaaaaaaaaaaaaaaa';
const PROF_B = 'prof:v1:stanford:bbbbbbbbbbbbbbbbbbbb';

function follow(professorId: string) {
  return { professorId, professorName: 'Jane Doe', school: 'uiuc', createdAt: '' };
}

function event(
  id: string,
  professorId: string,
  verifiedAt: string,
  extra: Partial<ProfessorUpdateEvent> = {},
): ProfessorUpdateEvent {
  return {
    event_id: `prof-event:v1:${id.padStart(24, '0')}`,
    professor_id: professorId,
    professor_name: 'Jane Doe',
    school: 'uiuc',
    verified_at: verifiedAt,
    source_url: 'https://ece.illinois.edu/people/jdoe',
    change_types: ['research_focus'],
    project_became_available: false,
    ...extra,
  };
}

beforeEach(() => {
  mockListProfessorFollows.mockReset().mockResolvedValue([]);
  mockGetProfessorUpdateReads.mockReset().mockResolvedValue(new Map());
  mockMarkProfessorUpdatesRead.mockReset().mockResolvedValue(undefined);
  mockGetProfessorUpdates.mockReset().mockResolvedValue({
    available: true, events: [], requested: 0, has_more: false,
  });
});

afterEach(() => cleanup());

describe('unreadEventIds', () => {
  const newest = event('2', PROF_A, '2026-07-15T00:00:00+00:00');
  const older = event('1', PROF_A, '2026-07-08T00:00:00+00:00');

  it('treats everything newer than the cursor as unread', () => {
    const unread = unreadEventIds(
      [newest, older],
      new Map([[PROF_A, older.event_id]]),
    );
    expect(unread).toEqual(new Set([newest.event_id]));
  });

  it('treats all events as unread without a cursor or with an unknown cursor', () => {
    expect(unreadEventIds([newest, older], new Map()).size).toBe(2);
    expect(
      unreadEventIds([newest, older], new Map([[PROF_A, 'prof-event:v1:' + 'f'.repeat(24)]])).size,
    ).toBe(2);
  });

  it('scopes cursors per professor', () => {
    const otherProf = event('9', PROF_B, '2026-07-20T00:00:00+00:00');
    const unread = unreadEventIds(
      [otherProf, newest],
      new Map([[PROF_A, newest.event_id]]),
    );
    expect(unread).toEqual(new Set([otherProf.event_id]));
  });
});

describe('ProfessorUpdatesSection', () => {
  it('shows the follow-a-professor empty state without calling the updates API', async () => {
    render(<ProfessorUpdatesSection />);

    expect(
      await screen.findByText('dashboard.professorUpdates.emptyTitle'),
    ).toBeInTheDocument();
    expect(mockGetProfessorUpdates).not.toHaveBeenCalled();
  });

  it('shows the truthful no-verified-updates state for follows without events', async () => {
    mockListProfessorFollows.mockResolvedValue([follow(PROF_A)]);
    mockGetProfessorUpdates.mockResolvedValue({
      available: false, events: [], requested: 1, has_more: false,
    });

    render(<ProfessorUpdatesSection />);

    expect(
      await screen.findByText('dashboard.professorUpdates.noUpdatesTitle'),
    ).toBeInTheDocument();
    expect(mockGetProfessorUpdates).toHaveBeenCalledWith([PROF_A]);
  });

  it('renders events with unread state and marks all read', async () => {
    const newest = event('2', PROF_A, '2026-07-15T00:00:00+00:00');
    const older = event('1', PROF_A, '2026-07-08T00:00:00+00:00');
    mockListProfessorFollows.mockResolvedValue([follow(PROF_A)]);
    mockGetProfessorUpdates.mockResolvedValue({
      available: true, events: [newest, older], requested: 1, has_more: false,
    });
    mockGetProfessorUpdateReads.mockResolvedValue(new Map([[PROF_A, older.event_id]]));

    render(<ProfessorUpdatesSection />);

    expect(await screen.findAllByText(/Jane Doe/)).toHaveLength(2);
    expect(screen.getByText('dashboard.professorUpdates.unread {"count":1}')).toBeInTheDocument();
    expect(screen.getAllByText('dashboard.professorUpdates.change.research_focus')).toHaveLength(2);
    expect(screen.getAllByRole('link', { name: /viewSource/ })[0]).toHaveAttribute(
      'href', 'https://ece.illinois.edu/people/jdoe',
    );

    fireEvent.click(screen.getByText('dashboard.professorUpdates.markAllRead'));

    expect(mockMarkProfessorUpdatesRead).toHaveBeenCalledWith([
      { professorId: PROF_A, lastReadEventId: newest.event_id },
    ]);
    await waitFor(() => {
      expect(
        screen.queryByText('dashboard.professorUpdates.unread {"count":1}'),
      ).not.toBeInTheDocument();
    });
  });

  it('highlights a project that became available', async () => {
    mockListProfessorFollows.mockResolvedValue([follow(PROF_A)]);
    mockGetProfessorUpdates.mockResolvedValue({
      available: true,
      events: [event('3', PROF_A, '2026-07-15T00:00:00+00:00', {
        change_types: ['project_availability'],
        project_became_available: true,
      })],
      requested: 1,
      has_more: false,
    });

    render(<ProfessorUpdatesSection />);

    expect(
      await screen.findByText('dashboard.professorUpdates.becameAvailable'),
    ).toBeInTheDocument();
  });

  it('shows an error state instead of a fake empty feed', async () => {
    mockListProfessorFollows.mockRejectedValue(new Error('load failed'));

    render(<ProfessorUpdatesSection />);

    expect(
      await screen.findByText('dashboard.professorUpdates.errorTitle'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('dashboard.professorUpdates.emptyTitle'),
    ).not.toBeInTheDocument();
  });
});
