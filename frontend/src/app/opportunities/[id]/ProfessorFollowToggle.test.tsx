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
import { advanceOwnerEpoch, isLocalOwnerReady, OwnerMismatchError, syncLocalIdentityOwner } from '@/lib/identity-owner';

const PROFESSOR_ID = 'prof:v1:uiuc:11111111111111111111';

function follow(professorId: string) {
  return { professorId, professorName: 'Jane Doe', school: 'uiuc', createdAt: '' };
}

// The component now binds each write to the account that clicked and paints
// only if that account is still current. identity-owner is real here (only
// @/lib/supabase is mocked), so claim an owner the way the app does.
const OWNER_UID = '11111111-1111-4111-8111-111111111111';
async function claimOwner(): Promise<void> {
  advanceOwnerEpoch(OWNER_UID);
  await syncLocalIdentityOwner(OWNER_UID);
  for (let i = 0; i < 200 && !isLocalOwnerReady(OWNER_UID); i += 1) {
    await new Promise((r) => setTimeout(r, 0));
  }
  expect(isLocalOwnerReady(OWNER_UID)).toBe(true);
}

beforeEach(async () => {
  mockListProfessorFollows.mockReset().mockResolvedValue([]);
  mockFollowProfessor.mockReset().mockResolvedValue(undefined);
  mockUnfollowProfessor.mockReset().mockResolvedValue(undefined);
  await claimOwner();
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

    expect(mockFollowProfessor).toHaveBeenCalledWith(PROFESSOR_ID, expect.anything(), 'Jane Doe', 'uiuc');
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

    expect(mockUnfollowProfessor).toHaveBeenCalledWith(PROFESSOR_ID, expect.anything());
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


describe('ProfessorFollowToggle — a result that arrives after an owner switch', () => {
  it('does not flip the switch on for U2 when U1\'s follow resolves', async () => {
    // Before: persist() awaited followProfessor with no owner check and then
    // setFollowing(true) — U2 saw aria-checked="true" for a follow U1 made.
    mockListProfessorFollows.mockResolvedValue([]);
    let resolveWrite: () => void = () => {};
    mockFollowProfessor.mockImplementationOnce(() => new Promise<void>((r) => { resolveWrite = r; }));
    render(<ProfessorFollowToggle professorId={PROFESSOR_ID} professorName="Jane Doe" school="uiuc" />);
    const toggle = await screen.findByRole('switch');
    fireEvent.click(toggle);
    await waitFor(() => expect(mockFollowProfessor).toHaveBeenCalled());

    const U2 = '22222222-2222-4222-8222-222222222222';
    advanceOwnerEpoch(U2);
    await syncLocalIdentityOwner(U2);
    for (let i = 0; i < 200 && !isLocalOwnerReady(U2); i += 1) await new Promise((r) => setTimeout(r, 0));

    resolveWrite();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
    // The busy flag is not U1's data. Gating its reset on the token left U2
    // with a switch that could never be clicked again.
    expect(screen.getByRole('switch')).not.toBeDisabled();
  });

  it('a refusal for the SAME account is a visible failure, not a silent no-op', async () => {
    // The writer also refuses when local storage is blocked for the very
    // account on screen. Swallowing that as "an owner switch" left the switch
    // off with no error and no retry — indistinguishable from "it worked".
    mockFollowProfessor.mockRejectedValueOnce(new OwnerMismatchError());
    render(<ProfessorFollowToggle professorId={PROFESSOR_ID} professorName="Jane Doe" school="uiuc" />);
    const toggle = await screen.findByRole('switch');
    fireEvent.click(toggle);

    expect(await screen.findByText('detail.professorFollow.saveError')).toBeInTheDocument();
    expect(screen.getByText('detail.professorFollow.retry')).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(toggle).not.toBeDisabled();
  });

  it('mounted after the owner was established, a live switch reloads the follow state', async () => {
    // Before: the reload effect seeded its "last owner" from the first
    // callback it received. Mounted onto an already-established owner, the
    // first callback IS the switch — and it was swallowed as the seed, so U2
    // kept seeing U1's follow state until a full remount.
    mockListProfessorFollows.mockResolvedValue([follow(PROFESSOR_ID)]);
    render(<ProfessorFollowToggle professorId={PROFESSOR_ID} professorName="Jane Doe" school="uiuc" />);
    expect(await screen.findByRole('switch')).toHaveAttribute('aria-checked', 'true');
    expect(mockListProfessorFollows).toHaveBeenCalledTimes(1);

    mockListProfessorFollows.mockResolvedValue([]);
    const U2 = '22222222-2222-4222-8222-222222222222';
    advanceOwnerEpoch(U2);
    await syncLocalIdentityOwner(U2);
    for (let i = 0; i < 200 && !isLocalOwnerReady(U2); i += 1) await new Promise((r) => setTimeout(r, 0));

    await waitFor(() => expect(mockListProfessorFollows).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false'));
  });
});
