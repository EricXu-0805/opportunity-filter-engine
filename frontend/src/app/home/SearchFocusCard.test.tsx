import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import { SearchFocusCard } from './SearchFocusCard';

// The course list's release switch, as this branch ships it unless a test
// turns it off.
const release = vi.hoisted(() => ({ courseStatus: true }));
vi.mock('@/lib/release-scope', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/release-scope')>();
  return { ...actual, RELEASE_SCOPE: { ...actual.RELEASE_SCOPE, get courseStatus() { return release.courseStatus; } } };
});

const t = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${Object.values(vars).join(',')}` : key;

function renderCard(overrides: Partial<{ searchWeight: number; exploring: boolean }> = {}) {
  const setSearchWeight = vi.fn();
  const setExploring = vi.fn();
  render(
    <SearchFocusCard
      searchWeight={overrides.searchWeight ?? 50}
      setSearchWeight={setSearchWeight}
      exploring={overrides.exploring ?? false}
      setExploring={setExploring}
      t={t}
    />,
  );
  return { setSearchWeight, setExploring };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  release.courseStatus = true;
});

describe('SearchFocusCard — the course list switched off', () => {
  // Off, no course has a status, so the card says what it said before the
  // course list (review p2-b, M1).
  it.each([true, false])('says the subtitle and the experience end as the switch has them, on: %s', (on) => {
    release.courseStatus = on;
    renderCard({ searchWeight: 80 });
    const off = on ? '' : 'Off';
    for (const key of [`home.cards.searchFocusSubtitle${off}`, `home.form.searchWeightRight${off}`, `home.form.searchWeightExperience${off}`]) {
      expect(screen.getAllByText(key).length, key).toBeGreaterThan(0);
    }
  });

  it('keeps the words before the course list for the switched-off card, EN and ZH', async () => {
    const { dictionaries } = await import('@/i18n/dictionaries');
    const d = dictionaries as never as Record<string, { home: { form: Record<string, string>; cards: Record<string, string> } }>;
    expect([d.en.home.cards.searchFocusSubtitleOff, d.en.home.form.searchWeightRightOff, d.en.home.form.searchWeightExperienceOff])
      .toEqual(['Balance between what you want and what you have taken', 'Coursework', 'Leaning on the courses you have taken']);
    expect([d.zh.home.cards.searchFocusSubtitleOff, d.zh.home.form.searchWeightRightOff, d.zh.home.form.searchWeightExperienceOff])
      .toEqual(['在你想做的和你修过的之间取舍', '已修课程', '更看你修过的课']);
  });
});

describe('SearchFocusCard — explore toggle', () => {
  it('renders the explore switch unchecked by default', () => {
    renderCard();
    const sw = screen.getByRole('switch');
    expect(sw).toHaveAttribute('aria-checked', 'false');
  });

  it('toggles exploring on click', () => {
    const { setExploring } = renderCard({ exploring: false });
    fireEvent.click(screen.getByRole('switch'));
    expect(setExploring).toHaveBeenCalledWith(true);
  });

  it('disables the focus slider while exploring (explore widens, ignores the slider)', () => {
    renderCard({ exploring: true });
    expect(screen.getByRole('slider')).toBeDisabled();
  });

  it('keeps the slider enabled when not exploring', () => {
    renderCard({ exploring: false });
    expect(screen.getByRole('slider')).not.toBeDisabled();
  });
});

// M59 (axe `label`, critical): the slider had no accessible name, so a screen
// reader announced an unnamed "slider, 50". Its name is the card heading on
// screen, so a speech-input user can say the words they see (WCAG 2.5.3), and
// it reads the same sentence sighted users see under it.
describe('SearchFocusCard — slider for screen readers', () => {
  it.each([
    [20, 'home.form.searchWeightInterests'],
    [50, 'home.form.searchWeightBalanced'],
    [80, 'home.form.searchWeightExperience'],
  ])('at %i it is named and reads %s', (searchWeight, valueText) => {
    renderCard({ searchWeight });
    const slider = screen.getByRole('slider', { name: 'home.cards.searchFocusTitle' });
    expect(slider).toHaveAttribute('aria-valuetext', valueText);
    expect(screen.getByText(valueText)).toBeInTheDocument();
  });

  it('takes its name from the visible heading', () => {
    renderCard();
    const heading = screen.getByRole('heading', { level: 2 });
    expect(screen.getByRole('slider')).toHaveAccessibleName(heading.textContent ?? '');
    expect(screen.getByRole('slider')).toHaveAttribute('aria-labelledby', heading.id);
  });
});

// ---------------------------------------------------------------------------
// The slider may not promise that a resume changes the results
//
// It reweights the three scoring layers. The resume reaches the matcher as one
// boolean, `profile.resume_ready` (ranker.py:1152) — and for the 94.2% of the
// corpus that is a faculty contact, that boolean resolves to the same number
// for every candidate, so it shifts all scores equally and cannot reorder
// anything. Uploading a better resume changes no match.
//
// What the right-hand end actually raises is the readiness layer, whose only
// per-opportunity term is coursework overlap. So "Coursework" is both the true
// label and the actionable one: filling in courses is what makes that end do
// something, where polishing a resume is not.
//
// Measured before the rename, on production's own top 100 for a UIUC ECE
// sophomore: dragging to the right changed 12 of 100 results and never moved
// the top one; dragging left changed 35 and did.
// ---------------------------------------------------------------------------
describe('the slider names the signals it actually moves', () => {
  const dict = () => import('@/i18n/dictionaries');

  it('neither end claims the resume affects matching', async () => {
    const { dictionaries } = await dict();
    for (const locale of ['en', 'zh'] as const) {
      const form = (dictionaries as never as Record<string, { home: { form: Record<string, string> } }>)[locale].home.form;
      const copy = [
        form.searchWeightLeft, form.searchWeightRight,
        form.searchWeightInterests, form.searchWeightExperience,
        form.searchWeightBalanced,
      ].join(' ').toLowerCase();
      expect(copy).not.toContain('resume');
      expect(copy).not.toContain('简历');
    }
  });

  it('names coursework as the right-hand end in both languages', async () => {
    const { dictionaries } = await dict();
    const d = dictionaries as never as Record<string, { home: { form: Record<string, string> } }>;
    expect(d.en.home.form.searchWeightRight.toLowerCase()).toContain('coursework');
    expect(d.zh.home.form.searchWeightRight).toContain('课程');
  });

  // Checklist M13: the matcher counts every course but a planned one
  // (src/student_evidence.courses_counted_as_taken) — in progress and not
  // marked included — so no end of the slider may say only completed ones do.
  it('says every course but a planned one counts, never only the completed ones', async () => {
    const { dictionaries } = await dict();
    const d = dictionaries as never as Record<string, { home: { form: Record<string, string>; cards: Record<string, string> } }>;
    for (const locale of ['en', 'zh'] as const) {
      const { form, cards } = d[locale].home;
      const copy = [cards.searchFocusSubtitle, form.searchWeightRight, form.searchWeightExperience, form.searchWeightBalanced].join(' ');
      expect(copy, locale).not.toMatch(/completed|have taken|已修|修过/i);
    }
    // Planned as the student marked it: a status the résumé only suggests is
    // sent as not marked, and counted.
    expect(d.en.home.form.searchWeightExperience).toContain('marked as planned');
    expect(d.zh.home.form.searchWeightExperience).toContain('标为「计划修」');
  });
});
