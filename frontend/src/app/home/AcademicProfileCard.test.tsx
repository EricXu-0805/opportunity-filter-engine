import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('@/lib/school-confirmation', () => ({
  persistHomeSchool: vi.fn(async () => ({ ok: true, synced: true, cacheCleared: true })),
}));


vi.mock('@/i18n/client', () => ({
  useLocale: () => 'en',
  useT: () => ({
    locale: 'en',
    t: (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key}:${Object.values(vars).join(',')}` : key,
  }),
}));

import { persistHomeSchool } from '@/lib/school-confirmation';
import { AcademicProfileCard } from './AcademicProfileCard';
import { DEFAULT_PROFILE } from './types';
import { translate } from '@/i18n/translate';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { makeProfileViewSnapshot, type ProfileViewSnapshot } from '@/lib/profile-sync';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import type { ProfileData } from '@/lib/types';

const t = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${Object.values(vars).join(',')}` : key;

/** The view the parent would have published from the hydration this card is
 *  showing. The card takes it as a prop — it never reads storage — so every
 *  test supplies one exactly as page.tsx does. */
function viewFor(overrides: Partial<ProfileData> = {}, revision = 1) {
  const owner = captureOwnerToken();
  const shown = { ...DEFAULT_PROFILE, ...overrides };
  return makeProfileViewSnapshot({
    baseProfile: shown,
    renderedProfile: shown,
    revision,
    token: owner,
    identityGeneration: owner.epoch,
    source: 'hydration',
  });
}

function renderCard(
  overrides: Partial<ProfileData> = {},
  viewSnapshot: ProfileViewSnapshot | null = viewFor(overrides),
) {
  const update = vi.fn();
  render(
    <AcademicProfileCard
      profile={{ ...DEFAULT_PROFILE, ...overrides }}
      update={update}
      viewSnapshot={viewSnapshot}
      t={t}
    />,
  );
  return { update };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AcademicProfileCard — school row + switcher entry', () => {
  it('keeps core opportunity types while hiding Fellowships', () => {
    renderCard();
    expect(screen.getByText('home.form.seekingResearch')).toBeInTheDocument();
    expect(screen.getByText('home.form.seekingInternship')).toBeInTheDocument();
    expect(screen.queryByText('home.form.seekingFellowship')).not.toBeInTheDocument();
  });

  it('shows the current school name and a Change button (default uiuc)', () => {
    renderCard();
    expect(screen.getByText('University of Illinois Urbana-Champaign')).toBeInTheDocument();
    expect(screen.getByText('home.form.changeSchool')).toBeInTheDocument();
  });

  it('treats a stored profile without home_school as UIUC (backward compat)', () => {
    renderCard({ home_school: undefined });
    expect(screen.getByText('University of Illinois Urbana-Champaign')).toBeInTheDocument();
    expect(document.querySelector('select#college')).toBeTruthy();
  });

  it('confirm persists the campus through the ordered helper, then closes', async () => {
    // The card no longer sets the field itself: persistHomeSchool writes the
    // one-key CAS patch, the confirmation receipt and the broadcast IN THAT
    // ORDER, and the broadcast is what updates the form. Calling update()
    // here would mark the field dirty for a save that may never land.
    const { update } = renderCard();
    fireEvent.click(screen.getByText('home.form.changeSchool'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('university-card-ucb'));
    fireEvent.click(screen.getByText('universitySwitcher.confirm'));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(persistHomeSchool).toHaveBeenCalledWith(
      'ucb',
      expect.objectContaining({ revision: 1, baseProfile: expect.anything() }),
      { confirm: true },
    );
    expect(update).not.toHaveBeenCalledWith('home_school', 'ucb');
  });

  it('a persist that does not land keeps the modal open and says so', async () => {
    vi.mocked(persistHomeSchool).mockResolvedValueOnce({ ok: false, reason: 'conflict' });
    renderCard();
    fireEvent.click(screen.getByText('home.form.changeSchool'));
    fireEvent.click(screen.getByTestId('university-card-ucb'));
    fireEvent.click(screen.getByText('universitySwitcher.confirm'));
    await waitFor(() => expect(screen.getByTestId('switcher-error')).toBeInTheDocument());
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('cancel closes the modal without updating the profile', () => {
    const { update } = renderCard();
    fireEvent.click(screen.getByText('home.form.changeSchool'));
    fireEvent.click(screen.getByText('common.cancel'));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(update).not.toHaveBeenCalled();
  });
});

describe('AcademicProfileCard — the baseline follows the snapshot on screen', () => {
  function lastView() {
    return vi.mocked(persistHomeSchool).mock.calls.at(-1)?.[1];
  }

  function switchTo(slug: string) {
    fireEvent.click(screen.getByText('home.form.changeSchool'));
    fireEvent.click(screen.getByTestId(`university-card-${slug}`));
    fireEvent.click(screen.getByText('universitySwitcher.confirm'));
  }

  it('the parent cleared the view (identity switched): the click writes NOTHING and says so', async () => {
    // useProfileForm drops its published view the instant an identity
    // transition is observed, before anything re-renders. This card is not
    // keyed by identity, so it stays on screen with nothing to act against —
    // and inventing a base at that point is exactly how one account's row
    // becomes another's.
    renderCard({ home_school: 'uiuc' }, null);
    await switchTo('ucb');
    expect(persistHomeSchool).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId('switcher-error')).toBeInTheDocument());
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('U1 -> U2 without unmounting: the click carries U1\'s OWN view, never a fresh U2 token', async () => {
    advanceOwnerEpoch('card-baseline-u1');
    await syncLocalIdentityOwner('card-baseline-u1');
    const u1View = viewFor({ home_school: 'uiuc', major: 'CS' }, 7);
    renderCard({ home_school: 'uiuc', major: 'CS' }, u1View);

    // U2 takes over the browser while this card is still mounted and still
    // holding U1's view.
    advanceOwnerEpoch('card-baseline-u2');
    await syncLocalIdentityOwner('card-baseline-u2');

    await switchTo('ucb');

    // The card must hand over the view it was given, unaltered. Capturing a
    // token at click time instead would pair U1's row and revision with a
    // currently-valid U2 token — a combination every downstream preflight
    // waves through, because each half looks legitimate on its own.
    const sent = lastView();
    expect(sent?.viewId).toBe(u1View.viewId);
    expect(sent?.token.uid).toBe('card-baseline-u1');
    expect(sent?.token.epoch).toBe(u1View.token.epoch);
  });

  it('a background write this card never accepted does not become its baseline', async () => {
    advanceOwnerEpoch('card-baseline-bg');
    await syncLocalIdentityOwner('card-baseline-bg');
    const accepted = viewFor({ home_school: 'uiuc', major: 'CS' }, 7);
    renderCard({ home_school: 'uiuc', major: 'CS' }, accepted);

    // Same owner, another tab. Nothing on this screen changed, so the pair the
    // person is choosing against is still revision 7 — a card that re-read
    // storage here would send their old choice wearing revision 9.
    localStorage.setItem(
      STORAGE_KEYS.PROFILE_SYNC,
      JSON.stringify({
        v: 1,
        confirmed: { revision: 9, profile: { major: 'Physics', home_school: 'mit' } },
      }),
    );

    await switchTo('ucb');

    const sent = lastView();
    expect(sent?.revision).toBe(7);
    expect(sent?.baseProfile).toMatchObject({ major: 'CS', home_school: 'uiuc' });
  });

  it('the view it hands over is frozen — nothing can edit the baseline it is judged against', () => {
    const accepted = viewFor({ home_school: 'uiuc', major: 'CS' }, 7);
    expect(() => {
      (accepted.baseProfile as unknown as Record<string, unknown>).major = 'tampered';
    }).toThrow();
    expect(accepted.baseProfile?.major).toBe('CS');
  });
});

describe('AcademicProfileCard — catalog vs free-text fallback', () => {
  it('uiuc keeps the cascading college/major dropdowns', async () => {
    renderCard({ home_school: 'uiuc' });
    expect(document.querySelector('select#college')).toBeTruthy();
    expect(document.querySelector('select#major')).toBeTruthy();
    expect(screen.queryByText('home.form.catalogPendingNote')).toBeNull();
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Grainger College of Engineering' })).toBeInTheDocument(),
    );
  });

  it('ucb renders cascading dropdowns from its catalog once loaded', async () => {
    renderCard({ home_school: 'ucb' });
    expect(document.querySelector('input#college')).toBeNull();
    expect(document.querySelector('select#college')).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Haas School of Business' })).toBeInTheDocument(),
    );
    expect((document.querySelector('select#college') as HTMLSelectElement).disabled).toBe(false);
    // UIUC's catalog must not bleed into UCB's dropdown.
    expect(screen.queryByRole('option', { name: 'Grainger College of Engineering' })).toBeNull();
    expect(screen.queryByText('home.form.catalogPendingNote')).toBeNull();
  });

  it('a ucb college cascades to its own majors in the major dropdown', async () => {
    renderCard({ home_school: 'ucb', college: 'Haas School of Business' });
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Spieker Undergraduate Business Program' })).toBeInTheDocument(),
    );
    expect((document.querySelector('select#major') as HTMLSelectElement).disabled).toBe(false);
  });

  it('zh: ucb college and major options render translated', async () => {
    const zhT = (key: string, vars?: Record<string, string | number>) => translate('zh', key, vars);
    render(
      <AcademicProfileCard
        profile={{ ...DEFAULT_PROFILE, home_school: 'ucb', college: 'College of Engineering' }}
        update={vi.fn()}
        viewSnapshot={null}
        t={zhT}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole('option', { name: '哈斯商学院' })).toBeInTheDocument(),
    );
    expect(screen.getByRole('option', { name: '电气工程与计算机科学' })).toBeInTheDocument();
  });

  it('a school without a catalog degrades college/major to free-text inputs with a note', () => {
    renderCard({ home_school: 'future-school' });
    const college = document.querySelector('input#college') as HTMLInputElement;
    const major = document.querySelector('input#major') as HTMLInputElement;
    expect(college).toBeTruthy();
    expect(major).toBeTruthy();
    expect(document.querySelector('select#college')).toBeNull();
    expect(document.querySelector('select#major')).toBeNull();
    expect(screen.getByText('home.form.catalogPendingNote')).toBeInTheDocument();
  });

  it('free-text inputs carry the stored college/major values (no data loss)', () => {
    renderCard({ home_school: 'future-school', college: 'College of Engineering', major: 'EECS' });
    expect((document.querySelector('input#college') as HTMLInputElement).value)
      .toBe('College of Engineering');
    expect((document.querySelector('input#major') as HTMLInputElement).value).toBe('EECS');
  });

  it('typing in the free-text college field calls update without touching major', () => {
    const { update } = renderCard({ home_school: 'future-school' });
    fireEvent.change(document.querySelector('input#college')!, {
      target: { value: 'College of Chemistry' },
    });
    expect(update).toHaveBeenCalledWith('college', 'College of Chemistry');
  });
});
