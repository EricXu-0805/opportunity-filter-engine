/*
 * Follow toggle on the opportunity detail page. Renders only for records
 * carrying a canonical tracking id, reflects the persisted follow state
 * truthfully, and surfaces save/load failures with a retry instead of
 * pretending the switch flipped.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockListProfessorFollows = vi.fn();
const mockFollowProfessor = vi.fn();
const mockUnfollowProfessor = vi.fn();

vi.mock('@/lib/supabase', () => ({
  listProfessorFollows: (...args: unknown[]) => mockListProfessorFollows(...args),
  followProfessor: (...args: unknown[]) => mockFollowProfessor(...args),
  unfollowProfessor: (...args: unknown[]) => mockUnfollowProfessor(...args),
  isCanonicalProfessorId: (value: unknown) =>
    typeof value === 'string' && /^prof:v1:[a-z0-9-]{1,48}:[0-9a-f]{20}$/.test(value),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    locale: 'en',
    t: (key: string) => key,
  }),
}));

import { ProfessorFollowToggle } from './ProfessorFollowToggle';

const PROFESSOR_ID = 'prof:v1:uiuc:11111111111111111111';

function follow(professorId: string) {
  return { professorId, professorName: 'Jane Doe', school: 'uiuc', createdAt: '' };
}

beforeEach(() => {
  mockListProfessorFollows.mockReset().mockResolvedValue([]);
  mockFollowProfessor.mockReset().mockResolvedValue(undefined);
  mockUnfollowProfessor.mockReset().mockResolvedValue(undefined);
});

afterEach(() => cleanup());

describe('ProfessorFollowToggle', () => {
  it('renders nothing without a canonical professor id', () => {
    const { container } = render(
      <ProfessorFollowToggle professorId={undefined} professorName="X" school="uiuc" />,
    );
    expect(container).toBeEmptyDOMElement();

    const { container: junk } = render(
      <ProfessorFollowToggle professorId="faculty-uiuc-ada" professorName="X" school="uiuc" />,
    );
    expect(junk).toBeEmptyDOMElement();
    expect(mockListProfessorFollows).not.toHaveBeenCalled();
  });

  it('shows the persisted off state and follows with display fields', async () => {
    render(
      <ProfessorFollowToggle
        professorId={PROFESSOR_ID}
        professorName="Jane Doe"
        school="uiuc"
      />,
    );

    const toggle = await screen.findByRole('switch');
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    fireEvent.click(toggle);

    expect(mockFollowProfessor).toHaveBeenCalledWith(PROFESSOR_ID, 'Jane Doe', 'uiuc');
    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'true'));
  });

  it('shows the persisted on state and unfollows', async () => {
    mockListProfessorFollows.mockResolvedValue([follow(PROFESSOR_ID)]);

    render(
      <ProfessorFollowToggle
        professorId={PROFESSOR_ID}
        professorName="Jane Doe"
        school="uiuc"
      />,
    );

    const toggle = await screen.findByRole('switch');
    expect(toggle).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(toggle);

    expect(mockUnfollowProfessor).toHaveBeenCalledWith(PROFESSOR_ID);
    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'));
  });

  it('surfaces a load failure as a retryable error, not a false off state', async () => {
    mockListProfessorFollows.mockRejectedValueOnce(new Error('load failed'));
    mockListProfessorFollows.mockResolvedValueOnce([follow(PROFESSOR_ID)]);

    render(
      <ProfessorFollowToggle
        professorId={PROFESSOR_ID}
        professorName="Jane Doe"
        school="uiuc"
      />,
    );

    expect(await screen.findByText('detail.professorFollow.loadError')).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('detail.professorFollow.retry'));

    const toggle = await screen.findByRole('switch');
    expect(toggle).toHaveAttribute('aria-checked', 'true');
  });

  it('keeps the switch honest when a save fails, and retries the same target', async () => {
    mockFollowProfessor.mockRejectedValueOnce(new Error('save failed'));

    render(
      <ProfessorFollowToggle
        professorId={PROFESSOR_ID}
        professorName="Jane Doe"
        school="uiuc"
      />,
    );

    const toggle = await screen.findByRole('switch');
    fireEvent.click(toggle);

    expect(await screen.findByText('detail.professorFollow.saveError')).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    fireEvent.click(screen.getByText('detail.professorFollow.retry'));

    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'true'));
    expect(mockFollowProfessor).toHaveBeenCalledTimes(2);
  });
});
