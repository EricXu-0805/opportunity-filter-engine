/**
 * TailorModal (R71 PR-2) — frontend tests.
 *
 * Mirrors ColdEmailModal.test.tsx: stable t-mock so the modal's
 * effects don't loop, single mocked `tailorResume` whose resolved
 * value drives the rendered output.
 *
 * Assertions intentionally check t-key strings (e.g. 'tailor.generate')
 * rather than English copy — `useT` in the test env returns keys
 * verbatim, so this keeps i18n changes from breaking the regex
 * matchers (R70-F lesson).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

vi.mock('@/i18n/client', () => {
  const stableT = (key: string, vars?: Record<string, string | number>) => {
    if (!vars) return key;
    const parts = Object.entries(vars).map(([, v]) => String(v));
    return parts.length > 0 ? `${key}:${parts.join('|')}` : key;
  };
  const stableSetLocale = () => {};
  return {
    useT: () => ({ t: stableT, locale: 'en' as const, setLocale: stableSetLocale }),
  };
});

const mockTailorResume = vi.fn();
const mockGetTailorStatus = vi.fn();
const mockExtractResumeBullets = vi.fn();
vi.mock('@/lib/api', () => ({
  tailorResume: (...args: unknown[]) => mockTailorResume(...args),
  getTailorStatus: (...args: unknown[]) => mockGetTailorStatus(...args),
  extractResumeBullets: (...args: unknown[]) => mockExtractResumeBullets(...args),
}));

import TailorModal from './TailorModal';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import type { ProfileData, TailorResponse } from '@/lib/types';

// R71-G word-diff splits bullet text into per-word <span>/<ins>/<del>
// nodes, so getByText(/whole sentence/) no longer matches — testing-library
// only reads an element's *direct* text nodes. Match on assembled
// textContent instead; the diff preserves the full string there.
const fullText = (s: string) => (_content: string, el: Element | null): boolean =>
  el?.textContent === s;

function makeProfile(overrides: Partial<ProfileData> = {}): ProfileData {
  return {
    institution: 'UIUC',
    college: 'Grainger',
    major: 'CS',
    grade: 'Sophomore',
    is_international: false,
    research_interests: 'machine learning',
    skills: [{ name: 'Python', level: 'experienced' }],
    coursework: ['CS 225'],
    resume_text: '',
    ...overrides,
  };
}

const OWNER = 'owner-1';
const OWNER2 = 'owner-2';

const baseProps = {
  isOpen: true,
  onClose: vi.fn(),
  opportunityId: 'opp-123',
  opportunityTitle: 'Some research opportunity',
  ownerReady: true,
  ownerScopeKey: OWNER,
};

// Owner-scoped draft key (C1-R2B) — replaces the pre-scoping
// 'ofe_tailor_draft_opp-123' format used throughout this file's existing
// persistence assertions.
const DRAFT_KEY = `ofe_tailor_draft_${OWNER}:opp-123`;
const DRAFT_KEY_OWNER2 = `ofe_tailor_draft_${OWNER2}:opp-123`;
const LEGACY_DRAFT_KEY = 'ofe_tailor_draft_opp-123';

describe('TailorModal', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    // R71-F: every test starts with a clean localStorage so a leftover
    // draft from a previous test can't leak into the next one's
    // "initial state" assertions.
    window.localStorage.clear();
    // R71-G: default the status probe to "AI available" so the
    // unavailable banner stays hidden and pre-existing assertions are
    // untouched. Tests that exercise the banner override this.
    mockGetTailorStatus.mockResolvedValue({ ai_available: true });
  });

  it('does not render when closed', () => {
    render(<TailorModal {...baseProps} isOpen={false} profile={makeProfile()} />);
    expect(screen.queryByText('tailor.title')).toBeNull();
  });

  it('renders the header + empty state on open', () => {
    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    expect(screen.getByText('tailor.title')).toBeTruthy();
    expect(screen.getByText('tailor.noBulletsYet')).toBeTruthy();
    // Generate button is the primary CTA and starts disabled when empty
    // because parseBullets() returns [].
    const generate = screen.getByRole('button', { name: /tailor\.generate/ });
    expect(generate.hasAttribute('disabled')).toBe(true);
  });

  it('pre-fills bullets from profile.resume_text when bullet-shaped lines exist', () => {
    const profile = makeProfile({
      resume_text:
        'EDUCATION\n• Built a thermal sensor in Java for ME 270 capstone\n- Wrote 12-page final lab report\nthis is not bullet-shaped',
    });
    render(<TailorModal {...baseProps} profile={profile} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    expect(textarea.value).toContain('Built a thermal sensor in Java for ME 270 capstone');
    expect(textarea.value).toContain('Wrote 12-page final lab report');
    expect(textarea.value).not.toContain('EDUCATION');
    expect(textarea.value).not.toContain('this is not bullet-shaped');
  });

  it('calls tailorResume with parsed bullets and renders AI variant on success', async () => {
    const resp: TailorResponse = {
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        {
          text: 'Implemented Python ML experiments in CS 225 coursework',
          source_evidence: 'Python; CS 225',
          source_index: 0,
        },
      ],
    };
    mockTailorResume.mockResolvedValueOnce(resp);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder');
    fireEvent.change(textarea, { target: { value: 'Worked on Python projects in CS 225' } });

    const generate = screen.getByRole('button', { name: /tailor\.generate/ });
    fireEvent.click(generate);

    await waitFor(() =>
      // R71-D: locale flows from useT().locale ('en' in the test env)
      // through tailorResume's options arg.
      expect(mockTailorResume).toHaveBeenCalledWith(
        expect.objectContaining({ major: 'CS' }),
        'opp-123',
        ['Worked on Python projects in CS 225'],
        { locale: 'en' },
      ),
    );

    await waitFor(() => {
      // R71-G: tailored text is word-diff-split, so match on textContent.
      expect(
        screen.getAllByText(fullText('Implemented Python ML experiments in CS 225 coursework')).length,
      ).toBeGreaterThanOrEqual(1);
    });
    // Method chip reflects success path.
    expect(screen.getByText('tailor.methodAi')).toBeTruthy();
    // R71-E: side-by-side renders both labels + the matching original
    // (looked up via source_index=0 against the submitted snapshot).
    expect(screen.getByText('tailor.originalRowLabel')).toBeTruthy();
    expect(screen.getByText('tailor.tailoredRowLabel')).toBeTruthy();
    // R71-G: the original-side diff line preserves the full original
    // string in its textContent even though it's split into word spans.
    expect(
      screen.getAllByText(fullText('Worked on Python projects in CS 225')).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it('R71-E: pairs each tailored bullet with its original via source_index', async () => {
    /* The model returns bullets in submitted order but the second one
       has a different source_index (1) — we should pair the LEFT side
       of card-2 with the user's bullet at index 1, not index 0.
       Defensive against future backend reordering. */
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        {
          text: 'Used Python at CS 225 to model thermal flow',
          source_evidence: 'Python; CS 225',
          source_index: 0,
        },
        {
          text: 'Implemented Python sims for fluid dynamics coursework',
          source_evidence: 'Python coursework',
          source_index: 1,
        },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'thermal flow project\nfluid dynamics project' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => {
      // Both original lines render in their card's original-side diff row;
      // R71-G word-diff splits them into spans, so match on textContent.
      expect(screen.getAllByText(fullText('thermal flow project')).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(fullText('fluid dynamics project')).length).toBeGreaterThanOrEqual(1);
      // Two pairs of section labels.
      expect(screen.getAllByText('tailor.originalRowLabel').length).toBe(2);
      expect(screen.getAllByText('tailor.tailoredRowLabel').length).toBe(2);
    });
  });

  it('R71-F: restores saved draft from localStorage on open + clears flag on edit', async () => {
    /* Pre-populate the storage slot for this opp so opening the modal
       should hydrate from it rather than the (empty) heuristic
       prefill. The "Restored" chip is the visible affordance. */
    window.localStorage.setItem(
      DRAFT_KEY,
      'previously saved bullet 1\npreviously saved bullet 2',
    );

    render(<TailorModal {...baseProps} profile={makeProfile()} />);

    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    expect(textarea.value).toBe('previously saved bullet 1\npreviously saved bullet 2');
    expect(screen.getByText('tailor.draftRestored')).toBeTruthy();

    // Editing clears the "restored" badge so the chip doesn't linger
    // forever once the user has acknowledged it and started typing.
    fireEvent.change(textarea, { target: { value: 'now editing this' } });
    expect(screen.queryByText('tailor.draftRestored')).toBeNull();
  });

  it('R71-F: persists draft to localStorage on textarea change', async () => {
    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder');
    fireEvent.change(textarea, { target: { value: 'newly typed bullet' } });

    await waitFor(() => {
      expect(
        window.localStorage.getItem(DRAFT_KEY),
      ).toBe('newly typed bullet');
    });
  });

  it('R71-F: clear-draft button wipes the textarea + storage slot', async () => {
    window.localStorage.setItem(DRAFT_KEY, 'kept across reload');
    render(<TailorModal {...baseProps} profile={makeProfile()} />);

    fireEvent.click(screen.getByRole('button', { name: /tailor\.clearDraftAria/ }));

    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    expect(textarea.value).toBe('');
    expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull();
    // Chip disappears once cleared.
    expect(screen.queryByText('tailor.draftRestored')).toBeNull();
  });

  it('R71-F: per-bullet copy button writes that bullet to the clipboard', async () => {
    /* jsdom doesn't ship a clipboard implementation; we install a
       writable spy and verify the button calls it with just the one
       bullet's text (not all bullets — that's what Copy All does). */
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        { text: 'tailored bullet A', source_evidence: 'Python', source_index: 0 },
        { text: 'tailored bullet B', source_evidence: 'CS 225', source_index: 1 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'orig A\norig B' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => {
      // Two per-bullet copy buttons rendered (one per accepted bullet).
      expect(screen.getAllByRole('button', { name: /tailor\.copyBulletAria/ }).length).toBe(2);
    });

    // Click the second one — should grab "tailored bullet B" only.
    const copyButtons = screen.getAllByRole('button', { name: /tailor\.copyBulletAria/ });
    fireEvent.click(copyButtons[1]);

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('tailored bullet B');
    });
  });

  it('R71-E: hides the original row when fallback echoes the same text', async () => {
    /* method === "fallback" → backend returns the user's own bullets
       verbatim with source_evidence === 'original'. Showing the same
       text twice (original + tailored) adds noise without value, so
       the modal collapses to a single section. */
    mockTailorResume.mockResolvedValueOnce({
      method: 'fallback',
      warnings: ['llm_not_configured'],
      tailored_bullets: [
        {
          text: 'unchanged bullet text',
          source_evidence: 'original',
          source_index: 0,
        },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'unchanged bullet text' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => {
      // Bullet still renders (in the tailored slot) but the row
      // labels are suppressed because original === tailored.
      expect(screen.getByText(/unchanged bullet text/)).toBeTruthy();
      expect(screen.queryByText('tailor.originalRowLabel')).toBeNull();
      expect(screen.queryByText('tailor.tailoredRowLabel')).toBeNull();
    });
  });

  it('surfaces a fabrication warning when backend rejects every bullet', async () => {
    const resp: TailorResponse = {
      method: 'fallback',
      warnings: [
        'bullet_0_rejected_fabrication: pytorch,kubernetes',
        'all_bullets_rejected',
      ],
      tailored_bullets: [
        { text: 'Designed a thermal sensor in Java', source_evidence: 'original', source_index: 0 },
      ],
    };
    mockTailorResume.mockResolvedValueOnce(resp);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder');
    fireEvent.change(textarea, { target: { value: 'Designed a thermal sensor in Java' } });

    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => {
      // The fabrication-caught key wins over the catch-all because
      // pickWarningMessage scans for it first.
      expect(screen.getByText('tailor.warnings.fabricationCaught')).toBeTruthy();
      expect(screen.getByText('tailor.methodFallback')).toBeTruthy();
      // User still sees their original bullet — but the text appears
      // BOTH in the textarea (value attribute survives getAllByText)
      // and in the rendered bullets list. getAllByText keeps the
      // assertion honest about the duplication.
      const matches = screen.getAllByText(/Designed a thermal sensor in Java/);
      expect(matches.length).toBeGreaterThanOrEqual(1);
      // Source label renders the "original" sentinel.
      expect(screen.getByText('tailor.sourceOriginal')).toBeTruthy();
    });
  });

  it('renders the llmUnavailable warning when backend has no provider', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'fallback',
      warnings: ['llm_not_configured'],
      tailored_bullets: [
        { text: 'original bullet 1', source_evidence: 'original', source_index: 0 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'original bullet 1' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => {
      expect(screen.getByText('tailor.warnings.llmUnavailable')).toBeTruthy();
    });
  });

  it('shows an inline error and try-again when tailorResume throws', async () => {
    mockTailorResume.mockRejectedValueOnce(new Error('API 500: boom'));

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'sample bullet' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => {
      expect(screen.getByText(/API 500: boom/)).toBeTruthy();
      expect(screen.getByRole('button', { name: /tailor\.tryAgain/ })).toBeTruthy();
    });
  });

  it('toggles button label to "regenerate" once a result is rendered', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        { text: 'Tailored bullet 1', source_evidence: 'Python', source_index: 0 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'original' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => {
      // After success, button flips from generate -> regenerate.
      expect(screen.getByRole('button', { name: /tailor\.regenerate/ })).toBeTruthy();
      expect(screen.queryByRole('button', { name: /tailor\.generate$/ })).toBeNull();
    });
  });

  it('R71-G: shows the AI-unavailable banner when status probe returns false', async () => {
    mockGetTailorStatus.mockResolvedValue({ ai_available: false });

    render(<TailorModal {...baseProps} profile={makeProfile()} />);

    await waitFor(() => {
      expect(screen.getByText('tailor.aiUnavailableBanner')).toBeTruthy();
    });
  });

  it('R71-G: hides the AI-unavailable banner when AI is configured', async () => {
    mockGetTailorStatus.mockResolvedValue({ ai_available: true });

    render(<TailorModal {...baseProps} profile={makeProfile()} />);

    // Let the probe resolve, then assert the banner never appears.
    await waitFor(() => expect(mockGetTailorStatus).toHaveBeenCalled());
    expect(screen.queryByText('tailor.aiUnavailableBanner')).toBeNull();
  });

  it('R71-G: shows a coverage line when some bullets are dropped (partial AI result)', async () => {
    // Submit 2 bullets but the backend (post anti-fabrication) returns 1.
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: ['bullet_1_rejected_fabrication: pytorch'],
      tailored_bullets: [
        { text: 'Grounded rewrite kept', source_evidence: 'Python', source_index: 0 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'kept bullet\ndropped bullet' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => {
      // t-mock renders vars as "key:n|total" → 1 rewritten of 2 submitted.
      expect(screen.getByText('tailor.coverage:1|2')).toBeTruthy();
    });
  });

  it('R71-G: no coverage line when every submitted bullet comes back', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        { text: 'Rewrite A', source_evidence: 'Python', source_index: 0 },
        { text: 'Rewrite B', source_evidence: 'CS 225', source_index: 1 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'bullet A\nbullet B' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => expect(screen.getByText('tailor.methodAi')).toBeTruthy());
    expect(screen.queryByText(/^tailor\.coverage/)).toBeNull();
  });

  it('R71-G: smart-extract button is hidden when the profile has no resume text', () => {
    render(<TailorModal {...baseProps} profile={makeProfile({ resume_text: '' })} />);
    expect(screen.queryByRole('button', { name: /tailor\.extractFromResume/ })).toBeNull();
  });

  it('R71-G: smart-extract loads LLM-extracted bullets into the draft', async () => {
    mockExtractResumeBullets.mockResolvedValueOnce({
      method: 'ai',
      bullets: ['Dark bullet one with no glyph', 'Dark bullet two with no glyph'],
    });

    const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
    render(<TailorModal {...baseProps} profile={profile} />);

    const extractBtn = screen.getByRole('button', { name: /tailor\.extractFromResume/ });
    fireEvent.click(extractBtn);

    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    await waitFor(() => {
      expect(textarea.value).toBe('Dark bullet one with no glyph\nDark bullet two with no glyph');
    });
    // Promoted draft is persisted so it survives a close/reopen.
    expect(window.localStorage.getItem(DRAFT_KEY)).toBe(
      'Dark bullet one with no glyph\nDark bullet two with no glyph',
    );
  });

  it('R71-G: smart-extract leaves the draft untouched when nothing is found', async () => {
    mockExtractResumeBullets.mockResolvedValueOnce({ method: 'heuristic', bullets: [] });

    const profile = makeProfile({ resume_text: 'just a header, no bullets here' });
    render(<TailorModal {...baseProps} profile={profile} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'my own typing' } });

    fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));

    await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalled());
    // Empty result is a no-op — the user's typing stays put.
    expect(textarea.value).toBe('my own typing');
  });

  it('R71-G: "use as new originals" promotes the AI rewrite into the draft', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        { text: 'Rewritten bullet one', source_evidence: 'Python', source_index: 0 },
        { text: 'Rewritten bullet two', source_evidence: 'CS 225', source_index: 1 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'orig one\norig two' } });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /tailor\.useAsOriginals/ })).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole('button', { name: /tailor\.useAsOriginals/ }));

    // Draft now holds the tailored text, one bullet per line.
    expect(textarea.value).toBe('Rewritten bullet one\nRewritten bullet two');
    // Storage persisted the promoted draft too.
    expect(window.localStorage.getItem(DRAFT_KEY)).toBe(
      'Rewritten bullet one\nRewritten bullet two',
    );
    // Result panel resets — CTA flips back to generate, promote button gone.
    expect(screen.getByRole('button', { name: /tailor\.generate/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /tailor\.useAsOriginals/ })).toBeNull();
  });

  it('R71-G: "use as new originals" is absent for fallback results', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'fallback',
      warnings: ['llm_not_configured'],
      tailored_bullets: [
        { text: 'original bullet', source_evidence: 'original', source_index: 0 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'original bullet' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => expect(screen.getByText('tailor.methodFallback')).toBeTruthy());
    // Fallback's tailored === original, so promotion would be a no-op — hidden.
    expect(screen.queryByRole('button', { name: /tailor\.useAsOriginals/ })).toBeNull();
  });

  it('R71-G: keeps the banner hidden when the status probe rejects', async () => {
    mockGetTailorStatus.mockRejectedValue(new Error('network down'));

    render(<TailorModal {...baseProps} profile={makeProfile()} />);

    await waitFor(() => expect(mockGetTailorStatus).toHaveBeenCalled());
    expect(screen.queryByText('tailor.aiUnavailableBanner')).toBeNull();
  });

  it('parses bullet-prefixed lines from the textarea before sending', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: '• first bullet\n- second bullet\n  3) third bullet' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() =>
      expect(mockTailorResume).toHaveBeenCalledWith(
        expect.any(Object),
        'opp-123',
        ['first bullet', 'second bullet', 'third bullet'],
        { locale: 'en' },
      ),
    );
  });

  it('R73: rejecting a bullet excludes it from "use as originals"', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        { text: 'Kept rewrite', source_evidence: 'Python', source_index: 0 },
        { text: 'Rejected rewrite', source_evidence: 'CS 225', source_index: 1 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'orig one\norig two' } });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: /tailor\.rejectBulletAria/ }).length).toBe(2),
    );
    // Reject the second bullet, then promote — only the kept one carries over.
    fireEvent.click(screen.getAllByRole('button', { name: /tailor\.rejectBulletAria/ })[1]);
    fireEvent.click(screen.getByRole('button', { name: /tailor\.useAsOriginals/ }));
    expect(textarea.value).toBe('Kept rewrite');
  });

  it('R73: editing a bullet overrides its text on promote', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        { text: 'Original rewrite', source_evidence: 'Python', source_index: 0 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'orig one' } });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /tailor\.editBulletAria/ })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole('button', { name: /tailor\.editBulletAria/ }));
    // In edit mode the edit button is replaced by a labeled textarea.
    const editArea = screen.getByLabelText('tailor.editBulletAria') as HTMLTextAreaElement;
    fireEvent.change(editArea, { target: { value: 'My hand-edited bullet' } });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.save/ }));

    fireEvent.click(screen.getByRole('button', { name: /tailor\.useAsOriginals/ }));
    expect(textarea.value).toBe('My hand-edited bullet');
  });

  it('R73: restoring a rejected bullet re-includes it', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'ai',
      warnings: [],
      tailored_bullets: [
        { text: 'Bullet one', source_evidence: 'Python', source_index: 0 },
        { text: 'Bullet two', source_evidence: 'CS 225', source_index: 1 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'a\nb' } });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: /tailor\.rejectBulletAria/ }).length).toBe(2),
    );
    fireEvent.click(screen.getAllByRole('button', { name: /tailor\.rejectBulletAria/ })[0]);
    const restore = await screen.findByRole('button', { name: /tailor\.restoreBulletAria/ });
    fireEvent.click(restore);

    fireEvent.click(screen.getByRole('button', { name: /tailor\.useAsOriginals/ }));
    expect(textarea.value).toBe('Bullet one\nBullet two');
  });

  it('R73: review controls are absent on fallback results', async () => {
    mockTailorResume.mockResolvedValueOnce({
      method: 'fallback',
      warnings: ['llm_not_configured'],
      tailored_bullets: [
        { text: 'original bullet', source_evidence: 'original', source_index: 0 },
      ],
    } satisfies TailorResponse);

    render(<TailorModal {...baseProps} profile={makeProfile()} />);
    fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
      target: { value: 'original bullet' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));

    await waitFor(() => expect(screen.getByText('tailor.methodFallback')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /tailor\.editBulletAria/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /tailor\.rejectBulletAria/ })).toBeNull();
  });

  // Nested (not sibling) describe blocks below — they must share the outer
  // beforeEach (vi.resetAllMocks + localStorage.clear + the getTailorStatus
  // default) or every mocked call inside them silently returns undefined.
  describe('C1-R2B: session lifecycle epoch (close invalidates in-flight work even with no reopen follow-up)', () => {
    it('N1 (Generate) pending, then close and reopen WITHOUT ever issuing N2: N1 resolving late must not apply — loading is false in the reopened modal, and no stale result ever appears', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.generating')).toBeTruthy();

      // Close.
      rerender(<TailorModal {...baseProps} isOpen={false} profile={makeProfile()} />);
      // Reopen — deliberately no second Generate.
      rerender(<TailorModal {...baseProps} isOpen profile={makeProfile()} />);
      expect(screen.queryByText('tailor.generating')).toBeNull(); // fresh open, not loading

      // N1 finally resolves, late.
      await act(async () => {
        resolveN1?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'STALE N1 result', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText('tailor.generating')).toBeNull(); // still not loading — N1's finally didn't re-flip it
      expect(screen.queryByText(fullText('STALE N1 result'))).toBeNull(); // N1's result never appeared
      expect(screen.queryByText('tailor.methodAi')).toBeNull();
    });

    it('N1 (Generate) pending, close, reopen, THEN N2 is issued and resolves first: N1 resolving even later must not overwrite N2\'s result or its loading state', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      let resolveN2: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      rerender(<TailorModal {...baseProps} isOpen={false} profile={makeProfile()} />);
      rerender(<TailorModal {...baseProps} isOpen profile={makeProfile()} />);

      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN2 = r; }));
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet two' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(2));
      expect(screen.getByText('tailor.generating')).toBeTruthy();

      // N2 resolves first — the modal's actual current result.
      await act(async () => {
        resolveN2?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'N2 real result', source_evidence: 'x', source_index: 0 }],
        });
      });
      await waitFor(() => expect(screen.getAllByText(fullText('N2 real result')).length).toBeGreaterThanOrEqual(1));
      expect(screen.queryByText('tailor.generating')).toBeNull();

      // N1 (superseded twice over — by the close AND by N2) finally resolves, even later.
      await act(async () => {
        resolveN1?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'STALE N1 result', source_evidence: 'x', source_index: 0 }],
        });
      });

      // N2's result is still the only thing showing — untouched by N1.
      expect(screen.getAllByText(fullText('N2 real result')).length).toBeGreaterThanOrEqual(1);
      expect(screen.queryByText(fullText('STALE N1 result'))).toBeNull();
      expect(screen.queryByText('tailor.generating')).toBeNull(); // N1's finally didn't re-flip loading
    });

    it('Extract analog: N1 pending, close, reopen WITHOUT a replacement extract: N1 resolving late must not write stale bullets into the reopened draft or into storage', async () => {
      let resolveN1: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      const { rerender } = render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.extracting')).toBeTruthy();

      rerender(<TailorModal {...baseProps} isOpen={false} profile={profile} />);
      rerender(<TailorModal {...baseProps} isOpen profile={profile} />);
      expect(screen.queryByText('tailor.extracting')).toBeNull(); // fresh open, not extracting

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      const freshValue = textarea.value; // whatever the reopened modal legitimately shows

      await act(async () => {
        resolveN1?.({ method: 'ai', bullets: ['STALE extracted bullet'] });
      });

      expect(textarea.value).toBe(freshValue); // untouched by N1's late result
      expect(window.localStorage.getItem(DRAFT_KEY)).not.toBe('STALE extracted bullet');
    });

    // C1-R2B red-team correction: an earlier version of these tests clicked
    // close and THEN manually re-rendered with isOpen=false/true BEFORE
    // resolving N1 — since isOpen genuinely changing on ITS OWN already
    // invalidates via the useLayoutEffect, that shape passes even with
    // invalidateAndClose deleted (reverted to a bare onClick={onClose}),
    // proving nothing about invalidateAndClose specifically. Each test
    // below resolves N1 IMMEDIATELY after the close action — with isOpen
    // still `true` in the component's own props the whole time (no
    // rerender at all) — so ONLY a synchronous ref bump inside the close
    // handler itself (not a later prop round-trip) can save it. Verified
    // against a reverted (bare `onClose`) implementation: all three fail.
    it('the X button: click, then resolve N1 IMMEDIATELY (isOpen never actually changes) — invalidateAndClose\'s own synchronous bump is what drops it', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      fireEvent.click(screen.getByRole('button', { name: /tailor\.closeAria/ }));
      expect(baseProps.onClose).toHaveBeenCalled();

      // No rerender — isOpen is still `true` in this instance's own props.
      await act(async () => {
        resolveN1?.({
          method: 'ai', warnings: [],
          tailored_bullets: [{ text: 'STALE N1 via X button', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText(fullText('STALE N1 via X button'))).toBeNull();
    });

    it('the backdrop click: same immediate-resolve proof', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const { container } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      const backdrop = container.querySelector('.backdrop-blur-sm')!;
      fireEvent.click(backdrop);
      expect(baseProps.onClose).toHaveBeenCalled();

      await act(async () => {
        resolveN1?.({
          method: 'ai', warnings: [],
          tailored_bullets: [{ text: 'STALE N1 via backdrop', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText(fullText('STALE N1 via backdrop'))).toBeNull();
    });

    it('Escape: same immediate-resolve proof', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      fireEvent.keyDown(document, { key: 'Escape' });
      expect(baseProps.onClose).toHaveBeenCalled();

      await act(async () => {
        resolveN1?.({
          method: 'ai', warnings: [],
          tailored_bullets: [{ text: 'STALE N1 via Escape', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText(fullText('STALE N1 via Escape'))).toBeNull();
    });

    it('a REAL close via the X button, followed by a genuine reopen: N1 resolving late is STILL dropped (both the immediate synchronous bump AND the eventual prop round-trip protect it)', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      fireEvent.click(screen.getByRole('button', { name: /tailor\.closeAria/ }));
      expect(baseProps.onClose).toHaveBeenCalled();

      // Parent reflects the close, then a reopen — mirrors what onClose
      // actually causes in the real MatchCard/OpportunityDetail wiring.
      rerender(<TailorModal {...baseProps} isOpen={false} profile={makeProfile()} />);
      rerender(<TailorModal {...baseProps} isOpen profile={makeProfile()} />);
      expect(screen.queryByText('tailor.generating')).toBeNull();

      await act(async () => {
        resolveN1?.({
          method: 'ai', warnings: [],
          tailored_bullets: [{ text: 'STALE N1 via real close+reopen', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText(fullText('STALE N1 via real close+reopen'))).toBeNull();
      expect(screen.queryByText('tailor.generating')).toBeNull();
    });

    // Tail1-3: the three tests above prove invalidateAndClose's synchronous
    // bump for a pending GENERATE (mockTailorResume). Extract
    // (mockExtractResumeBullets) shares the same close handler, but nothing
    // exercised the "close, then resolve immediately with isOpen never
    // actually changing" shape for it specifically — the "Extract analog"
    // test above (~line 786) only covers close-THEN-reopen via rerender,
    // which (per the correction comment above these Generate tests) proves
    // nothing about invalidateAndClose's OWN synchronous bump, since a real
    // isOpen flip alone already invalidates via the layout effect.
    // Assertion style mirrors the three Generate tests above exactly: only
    // "the stale result never leaks" is checked, not that `extracting`
    // itself clears — with isOpen genuinely never changing (onClose here is
    // a bare spy, matching production's real modal-stays-mounted-renders-
    // null architecture: `if (!isOpen) return null;`), nothing else would
    // ever re-render this instance to observe a cleared spinner, and
    // nothing user-visible depends on it while the modal renders null
    // anyway. What actually matters — and what invalidateAndClose actually
    // protects — is that the stale extract never overwrites the draft.
    it('Extract via the X button: click, then resolve IMMEDIATELY (isOpen never actually changes) — invalidateAndClose\'s own synchronous bump is what drops it', async () => {
      let resolveExtract: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveExtract = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));

      fireEvent.click(screen.getByRole('button', { name: /tailor\.closeAria/ }));
      expect(baseProps.onClose).toHaveBeenCalled();

      // No rerender — isOpen is still `true` in this instance's own props.
      await act(async () => {
        resolveExtract?.({ method: 'ai', bullets: ['STALE extract via X button'] });
      });

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(textarea.value).not.toBe('STALE extract via X button');
      expect(window.localStorage.getItem(DRAFT_KEY)).not.toBe('STALE extract via X button');
    });

    it('Extract via the backdrop click: same immediate-resolve proof', async () => {
      let resolveExtract: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveExtract = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      const { container } = render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));

      const backdrop = container.querySelector('.backdrop-blur-sm')!;
      fireEvent.click(backdrop);
      expect(baseProps.onClose).toHaveBeenCalled();

      await act(async () => {
        resolveExtract?.({ method: 'ai', bullets: ['STALE extract via backdrop'] });
      });

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(textarea.value).not.toBe('STALE extract via backdrop');
      expect(window.localStorage.getItem(DRAFT_KEY)).not.toBe('STALE extract via backdrop');
    });

    it('Extract via Escape: same immediate-resolve proof', async () => {
      let resolveExtract: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveExtract = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));

      fireEvent.keyDown(document, { key: 'Escape' });
      expect(baseProps.onClose).toHaveBeenCalled();

      await act(async () => {
        resolveExtract?.({ method: 'ai', bullets: ['STALE extract via Escape'] });
      });

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(textarea.value).not.toBe('STALE extract via Escape');
      expect(window.localStorage.getItem(DRAFT_KEY)).not.toBe('STALE extract via Escape');
    });
  });

  describe('C1-R2B: genuine same-session double-request races (N1 and N2 genuinely overlap in flight — resolving N1 FIRST, while N2 is still pending, must not disturb N2)', () => {
    // These reuse the two mechanisms the component itself already relies
    // on to legitimately re-enable a CTA while an older promise is still
    // unsettled underneath: (Generate) a real close+reopen, whose
    // open-effect clears `loading`; (Extract) a manual draft edit, which
    // invalidates the pending extract in place. Both leave the OLDER
    // promise genuinely unresolved. The key difference from the lifecycle
    // tests above is ORDER: those resolve N2 first (so `loading` is
    // already false by the time N1's stale settle arrives — a broken
    // finally guard wouldn't be observable there, since it would just set
    // an already-false flag to false again). Here N1 settles FIRST, while
    // N2 is still genuinely pending, so a broken guard is directly visible
    // as N2's spinner disappearing or N1's stale content leaking through.
    it('Generate: N1 pending, close+reopen re-enables the button, N2 starts, and N1 settles WHILE N2 is still pending — N2\'s spinner must survive untouched, and N1 must never leak into resp-gated UI (including parts not hidden behind the loading spinner)', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      let resolveN2: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      rerender(<TailorModal {...baseProps} isOpen={false} profile={makeProfile()} />);
      rerender(<TailorModal {...baseProps} isOpen profile={makeProfile()} />);
      expect(screen.queryByText('tailor.generating')).toBeNull(); // N1's promise is STILL unsettled underneath

      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN2 = r; }));
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet two' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(2));
      expect(screen.getByText('tailor.generating')).toBeTruthy(); // N2 now pending, N1 STILL unsettled

      // N1 settles FIRST — the opposite order from the lifecycle tests
      // above — so `loading` is still legitimately true right now.
      await act(async () => {
        resolveN1?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'STALE N1 while N2 pending', source_evidence: 'x', source_index: 0 }],
        });
      });
      // N2's spinner must be untouched by N1's stale settle...
      expect(screen.getByText('tailor.generating')).toBeTruthy();
      // ...and N1 must not leak into the footer buttons, which are NOT
      // gated behind `loading` (unlike the bullet list) — a weaker
      // assertion here would pass even with the guard deleted, since N2's
      // own later resolve unconditionally overwrites `resp` and would mask
      // a transient leak by the time the test could otherwise observe it.
      expect(screen.queryByText('tailor.methodAi')).toBeNull();
      expect(screen.queryByRole('button', { name: /tailor\.useAsOriginals/ })).toBeNull();

      await act(async () => {
        resolveN2?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'N2 genuine result', source_evidence: 'x', source_index: 0 }],
        });
      });
      await waitFor(() => expect(screen.getAllByText(fullText('N2 genuine result')).length).toBeGreaterThanOrEqual(1));
      expect(screen.queryByText('tailor.generating')).toBeNull();
      expect(screen.queryByText(fullText('STALE N1 while N2 pending'))).toBeNull();
    });

    it('Generate: same close+reopen race but N1 REJECTS while N2 is still pending — must not paint an error or clear N2\'s spinner, and must not block N2\'s eventual result from rendering', async () => {
      let rejectN1: ((e: Error) => void) | undefined;
      let resolveN2: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((_, rej) => { rejectN1 = rej; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      rerender(<TailorModal {...baseProps} isOpen={false} profile={makeProfile()} />);
      rerender(<TailorModal {...baseProps} isOpen profile={makeProfile()} />);
      expect(screen.queryByText('tailor.generating')).toBeNull();

      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN2 = r; }));
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet two' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(2));
      expect(screen.getByText('tailor.generating')).toBeTruthy();

      await act(async () => {
        rejectN1?.(new Error('STALE N1 failure'));
      });
      expect(screen.getByText('tailor.generating')).toBeTruthy(); // N2 spinner untouched by N1's stale rejection

      // N2 resolves normally — if N1's catch block had painted `error`
      // (guard removed), that error state would survive N2's own success
      // path (which only ever calls setResp, never clears error) and
      // permanently block the result view, since the render tree treats
      // `!loading && error` as taking priority over the bullet list.
      await act(async () => {
        resolveN2?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'N2 genuine result after stale reject', source_evidence: 'x', source_index: 0 }],
        });
      });
      await waitFor(() =>
        expect(screen.getAllByText(fullText('N2 genuine result after stale reject')).length).toBeGreaterThanOrEqual(1),
      );
      expect(screen.queryByText('tailor.generating')).toBeNull();
      expect(screen.queryByText(/STALE N1 failure/)).toBeNull();
      expect(screen.queryByRole('button', { name: /tailor\.tryAgain/ })).toBeNull();
    });

    it('Extract: N1 pending, a manual edit invalidates it (re-enabling the button) and N2 starts while N1 is still genuinely unsettled — N1 settling late must not touch N2\'s extracting state or the textarea, and N2\'s own result must still land correctly', async () => {
      let resolveN1: ((v: { method: string; bullets: string[] }) => void) | undefined;
      let resolveN2: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.extracting')).toBeTruthy();

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      fireEvent.change(textarea, { target: { value: 'manual edit invalidates N1' } });
      expect(screen.queryByText('tailor.extracting')).toBeNull(); // N1 invalidated in place, button live again — N1's promise is STILL unsettled

      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveN2 = r; }));
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(2));
      expect(screen.getByText('tailor.extracting')).toBeTruthy(); // N2 now pending

      // N1 — genuinely still in flight this whole time — resolves now, late.
      await act(async () => {
        resolveN1?.({ method: 'ai', bullets: ['STALE N1 bullet while N2 pending'] });
      });
      // The textarea is always rendered (never gated behind `extracting`),
      // so this is a direct, ungated proof N1's stale write never landed.
      expect(textarea.value).toBe('manual edit invalidates N1');
      expect(screen.getByText('tailor.extracting')).toBeTruthy(); // N2's spinner untouched by N1's stale settle

      await act(async () => {
        resolveN2?.({ method: 'ai', bullets: ['N2 genuine extracted bullet'] });
      });
      await waitFor(() => expect(textarea.value).toBe('N2 genuine extracted bullet'));
      expect(screen.queryByText('tailor.extracting')).toBeNull();
      expect(window.localStorage.getItem(DRAFT_KEY)).toBe('N2 genuine extracted bullet');
    });
  });

  describe('C1-R2B: profile CONTENT changing mid-flight is itself a staleness bug — `profile` is a direct input to both tailorResume() and the extract heuristic, so a result computed against the OLD profile must never land after the modal has moved on to a NEW one, even with no second request ever issued', () => {
    // Root-cause note: the reset-on-open effect keyed off `heuristicPrefill`
    // (derived from profile.resume_text alone) already happened to reset
    // `loading`/`extracting` whenever resume_text specifically changed — but
    // sessionEpochRef never tracked profile at all, and OTHER profile
    // fields (major, college, skills, ...) are equally part of what
    // tailorResume() sends to the backend. A change to any of those fields
    // left both the reset effect AND stillCurrent() blind, so a Generate/
    // Extract already in flight could still land its OLD-profile result
    // into a modal now showing different profile context. Each pair below
    // varies a field OTHER than resume_text (so heuristicPrefill itself
    // does NOT move) to isolate exactly that gap.
    it('Generate: profile content changes (major CS -> ECE, resume_text unchanged) while N1 is pending and NO N2 is ever issued — the stale Generate must be invalidated: loading recovers immediately, and N1\'s late settle must not land a result computed against the old profile', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const profileA = makeProfile({ major: 'CS' });
      const { rerender } = render(<TailorModal {...baseProps} profile={profileA} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.generating')).toBeTruthy();

      const profileB = makeProfile({ major: 'ECE' }); // resume_text ('') is identical to profileA's
      rerender(<TailorModal {...baseProps} profile={profileB} />);
      expect(screen.queryByText('tailor.generating')).toBeNull(); // the stale Generate is invalidated the moment the profile context moves

      await act(async () => {
        resolveN1?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'STALE result computed against the OLD profile', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText(fullText('STALE result computed against the OLD profile'))).toBeNull();
      expect(screen.queryByText('tailor.methodAi')).toBeNull();
      expect(screen.queryByRole('button', { name: /tailor\.useAsOriginals/ })).toBeNull();
      expect(screen.queryByText('tailor.generating')).toBeNull(); // no re-flip from N1's guarded finally
    });

    it('Generate: same profile-content-change race but N1 REJECTS late — must not paint a stale error either', async () => {
      let rejectN1: ((e: Error) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((_, rej) => { rejectN1 = rej; }));

      const profileA = makeProfile({ major: 'CS' });
      const { rerender } = render(<TailorModal {...baseProps} profile={profileA} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      const profileB = makeProfile({ major: 'ECE' });
      rerender(<TailorModal {...baseProps} profile={profileB} />);
      expect(screen.queryByText('tailor.generating')).toBeNull();

      await act(async () => {
        rejectN1?.(new Error('STALE rejection computed against the OLD profile'));
      });

      expect(screen.queryByText(/STALE rejection computed against the OLD profile/)).toBeNull();
      expect(screen.queryByRole('button', { name: /tailor\.tryAgain/ })).toBeNull();
      expect(screen.queryByText('tailor.generating')).toBeNull();
    });

    it('Extract: profile content changes (major CS -> ECE, resume_text unchanged) while N1 is pending and NO N2 is ever issued — the stale Extract must be invalidated: extracting recovers immediately, and N1\'s late settle must not write a bullet computed against the old profile into the draft or storage', async () => {
      let resolveN1: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const sharedResumeText = 'Research Assistant\nDid a bunch of things';
      const profileA = makeProfile({ major: 'CS', resume_text: sharedResumeText });
      const { rerender } = render(<TailorModal {...baseProps} profile={profileA} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.extracting')).toBeTruthy();

      const profileB = makeProfile({ major: 'ECE', resume_text: sharedResumeText }); // heuristicPrefill is IDENTICAL — only `major` moved
      rerender(<TailorModal {...baseProps} profile={profileB} />);
      expect(screen.queryByText('tailor.extracting')).toBeNull(); // the stale Extract is invalidated even though heuristicPrefill never changed

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      const freshValue = textarea.value;

      await act(async () => {
        resolveN1?.({ method: 'ai', bullets: ['STALE bullet computed against the OLD profile'] });
      });

      expect(textarea.value).toBe(freshValue); // untouched by N1's late, profile-stale result
      expect(window.localStorage.getItem(DRAFT_KEY)).not.toBe('STALE bullet computed against the OLD profile');
    });

    it('a same-content profile re-render (a brand NEW object, identical field values — e.g. a parent re-fetch that resolves to the same data) must NOT invalidate an in-flight Generate: this is not a real context change', async () => {
      let resolveN: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN = r; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      // A fresh object, but every field matches makeProfile()'s defaults —
      // fingerprinting must compare CONTENT, not object identity.
      rerender(<TailorModal {...baseProps} profile={makeProfile()} />);
      expect(screen.getByText('tailor.generating')).toBeTruthy(); // still pending, untouched by the no-op re-render

      await act(async () => {
        resolveN?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'still valid despite same-content rerender', source_evidence: 'x', source_index: 0 }],
        });
      });

      await waitFor(() =>
        expect(screen.getAllByText(fullText('still valid despite same-content rerender')).length).toBeGreaterThanOrEqual(1),
      );
      expect(screen.getByText('tailor.methodAi')).toBeTruthy();
    });

    it('a same-content profile re-render with a DIFFERENT property insertion order (same fields, reversed) must NOT invalidate an in-flight Generate — the fingerprint must be canonical (key-order-independent), not a naive JSON.stringify', async () => {
      let resolveN: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN = r; }));

      const profile = makeProfile();
      const { rerender } = render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      // Exact same key/value pairs as `profile`, but with property
      // insertion order reversed — e.g. what a backend re-fetch or a merge
      // step could plausibly produce for semantically-identical data. A
      // naive `JSON.stringify(profile)` fingerprint is order-sensitive and
      // would treat this as a genuine content change.
      const reordered = Object.fromEntries(Object.entries(profile).reverse()) as ProfileData;
      rerender(<TailorModal {...baseProps} profile={reordered} />);
      expect(screen.getByText('tailor.generating')).toBeTruthy(); // still pending, untouched by the reorder

      await act(async () => {
        resolveN?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'valid despite reordered-content rerender', source_evidence: 'x', source_index: 0 }],
        });
      });

      await waitFor(() =>
        expect(screen.getAllByText(fullText('valid despite reordered-content rerender')).length).toBeGreaterThanOrEqual(1),
      );
      expect(screen.getByText('tailor.methodAi')).toBeTruthy();
    });

    // Tail3: the existing tests in this describe only ever vary `major` or
    // `resume_text` — the two fields tailorResume()/the extract heuristic
    // directly consume. canonicalFingerprint is supposed to hash the WHOLE
    // profile (see its call site: `canonicalFingerprint(profile)`, not some
    // hand-picked subset), so a regression that narrowed it to just
    // `{major, resume_text}` would pass every test above and still silently
    // let a stale Generate/Extract survive a skills/research_interests
    // change. `skills` is additionally a NESTED array-of-objects — proving
    // this invalidates also exercises canonicalFingerprint's recursion into
    // array elements, not just its top-level key handling.
    it('Generate: skills/research_interests change (major & resume_text held constant) while N1 is pending — the fingerprint must react to every field, including nested ones, not just major/resume_text', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const profileA = makeProfile({
        major: 'CS',
        resume_text: '',
        research_interests: 'machine learning',
        skills: [{ name: 'Python', level: 'experienced' }],
      });
      const { rerender } = render(<TailorModal {...baseProps} profile={profileA} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.generating')).toBeTruthy();

      const profileB = makeProfile({
        major: 'CS', // unchanged
        resume_text: '', // unchanged
        research_interests: 'computer vision', // changed
        skills: [{ name: 'Rust', level: 'beginner' }], // changed, and nested inside an array
      });
      rerender(<TailorModal {...baseProps} profile={profileB} />);
      expect(screen.queryByText('tailor.generating')).toBeNull(); // invalidated even though major/resume_text never moved

      await act(async () => {
        resolveN1?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'STALE result computed against the OLD skills/interests', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText(fullText('STALE result computed against the OLD skills/interests'))).toBeNull();
      expect(screen.queryByText('tailor.methodAi')).toBeNull();
      expect(screen.queryByText('tailor.generating')).toBeNull();
    });
  });

  describe('C1-R2B: ownerScopeKey switching mid-flight (no unmount) invalidates a pending Generate/Extract the same way a profile-content change does', () => {
    it('Generate: ownerScopeKey switches from U1 to U2 while N1 is pending, isOpen never flips false — loading recovers immediately, and N1\'s late result must never render into U2\'s session', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.generating')).toBeTruthy();

      rerender(<TailorModal {...baseProps} ownerScopeKey={OWNER2} profile={makeProfile()} />);
      expect(screen.queryByText('tailor.generating')).toBeNull(); // the stale Generate is invalidated the moment the owner scope moves

      await act(async () => {
        resolveN1?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'STALE result computed under the OLD owner', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText(fullText('STALE result computed under the OLD owner'))).toBeNull();
      expect(screen.queryByText('tailor.methodAi')).toBeNull();
      expect(screen.queryByText('tailor.generating')).toBeNull(); // no re-flip from N1's guarded finally
    });

    it('Extract: ownerScopeKey switches from U1 to U2 while N1 is pending, isOpen never flips false — extracting recovers immediately, and N1\'s late bullets must never be written under EITHER owner\'s key', async () => {
      let resolveN1: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      const { rerender } = render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.extracting')).toBeTruthy();

      const setItemSpy = vi.spyOn(window.localStorage, 'setItem');
      rerender(<TailorModal {...baseProps} ownerScopeKey={OWNER2} profile={profile} />);
      expect(screen.queryByText('tailor.extracting')).toBeNull(); // invalidated the moment the owner scope moves

      await act(async () => {
        resolveN1?.({ method: 'ai', bullets: ['STALE bullet computed under the OLD owner'] });
      });

      const badCalls = setItemSpy.mock.calls.filter(([, value]) => value === 'STALE bullet computed under the OLD owner');
      expect(badCalls).toEqual([]);
      expect(window.localStorage.getItem(DRAFT_KEY)).not.toBe('STALE bullet computed under the OLD owner');
      expect(window.localStorage.getItem(DRAFT_KEY_OWNER2)).not.toBe('STALE bullet computed under the OLD owner');
    });
  });

  describe('C1-R2B: ownerReady dropping mid-flight (no owner switch, no close) invalidates a pending Generate the same way — a background load hiccup, not just an identity switch, must supersede in-flight work', () => {
    it('Generate: ownerReady flips true->false while N1 is pending, ownerScopeKey/opportunityId/isOpen all UNCHANGED — loading recovers immediately, and N1\'s late result must never render', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet one' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));
      expect(screen.getByText('tailor.generating')).toBeTruthy();

      rerender(<TailorModal {...baseProps} ownerReady={false} profile={makeProfile()} />);
      expect(screen.queryByText('tailor.generating')).toBeNull(); // invalidated the moment readiness drops, with no other prop changing

      await act(async () => {
        resolveN1?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'STALE result computed while owner briefly went not-ready', source_evidence: 'x', source_index: 0 }],
        });
      });

      expect(screen.queryByText(fullText('STALE result computed while owner briefly went not-ready'))).toBeNull();
      expect(screen.queryByText('tailor.methodAi')).toBeNull();
      expect(screen.queryByText('tailor.generating')).toBeNull();
    });
  });

  describe('C1-R2B: combined identity-switch privacy proof (a REAL unmount, mirroring MatchList\'s remount-on-identity-change) and same-uid preservation', () => {
    it('deferred Extract crossing a real U1->U2 unmount: U1 starts an extract, the instance unmounts (a real identity switch), U1\'s extract resolves LATE — a fresh U2 instance for the SAME opportunity stays completely clean', async () => {
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, OWNER);
      let resolveExtract: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveExtract = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      const { unmount } = render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));

      // The real identity switch: MatchList's identityGeneration-keyed
      // Fragment tears this whole subtree down.
      unmount();
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, OWNER2);

      // U1's extract finally resolves, AFTER the unmount.
      await act(async () => {
        resolveExtract?.({ method: 'ai', bullets: ['STALE U1 extracted bullet'] });
      });

      // A fresh U2 instance opens the SAME opportunity.
      render(<TailorModal {...baseProps} ownerScopeKey={OWNER2} profile={profile} />);
      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(textarea.value).toBe(''); // no trace of U1's stale extract — clean
      expect(window.localStorage.getItem(DRAFT_KEY_OWNER2)).toBeNull();
    });

    it('deferred Extract crossing a real U1->U2 unmount, WITH an explicit post-unmount identity sweep of U1\'s key (mirrors identity-owner.ts\'s real USER_SCOPED_PREFIXES cleanup): U1\'s stale extract resolving AFTER the sweep must not resurrect the just-cleaned key', async () => {
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, OWNER);
      let resolveExtract: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveExtract = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      const { unmount } = render(<TailorModal {...baseProps} profile={profile} />);
      // U1 has a real draft of their own, saved under their scoped key,
      // BEFORE ever touching Extract — this is what the real sweep has
      // something to clean up.
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
        target: { value: 'U1 own draft before extracting' },
      });
      await waitFor(() => expect(window.localStorage.getItem(DRAFT_KEY)).toBe('U1 own draft before extracting'));

      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));

      // The real identity switch: MatchList's identityGeneration-keyed
      // Fragment tears this whole subtree down...
      unmount();
      // ...and identity-owner.ts's own USER_SCOPED_PREFIXES sweep runs on a
      // real owner switch, explicitly removing every key under U1's scope
      // (this component's own doc comments call this out as the mechanism
      // that eventually cleans up an owner-scoped key — it is simulated
      // here directly rather than by importing that module, since this is
      // TailorModal's own storage-write contract under test, not the
      // sweep's matching logic).
      window.localStorage.removeItem(DRAFT_KEY);
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, OWNER2);

      // U1's extract finally resolves, AFTER both the unmount AND the sweep.
      await act(async () => {
        resolveExtract?.({ method: 'ai', bullets: ['STALE bullet that must not resurrect the swept key'] });
      });

      // The swept key must stay swept — a mount-awareness regression would
      // have this stale `saveDraft` call recreate it with stale content,
      // silently undoing the sweep's own cleanup.
      expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull();
      // And it must never have landed under U2's key either — the closure
      // captured ctx.ownerScopeKey as OWNER at call time, not whatever
      // ownerScopeKey happens to be live when the promise settles.
      expect(window.localStorage.getItem(DRAFT_KEY_OWNER2)).toBeNull();
    });

    it('deferred Generate crossing a real U1->U2 unmount: U1\'s stale AI result must never appear for a fresh U2 instance on the SAME opportunity', async () => {
      let resolveN1: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN1 = r; }));

      const { unmount } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'U1 bullet' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      unmount(); // real identity switch — the whole subtree is torn down

      await act(async () => {
        resolveN1?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'STALE U1 generate result', source_evidence: 'x', source_index: 0 }],
        });
      });

      // A fresh U2 instance, same opportunity.
      render(<TailorModal {...baseProps} ownerScopeKey={OWNER2} profile={makeProfile()} />);
      expect(screen.queryByText(fullText('STALE U1 generate result'))).toBeNull();
      expect(screen.queryByText('tailor.methodAi')).toBeNull();
      expect(screen.getByText('tailor.noBulletsYet')).toBeTruthy(); // U2's genuinely fresh, empty state
    });

    it('a same-uid re-observation (isOpen/opportunityId/ownerScopeKey/ownerReady all UNCHANGED — e.g. TOKEN_REFRESHED bubbling down) must NOT invalidate an in-flight Generate: it resolves and applies normally', async () => {
      let resolveN: ((v: TailorResponse) => void) | undefined;
      mockTailorResume.mockReturnValueOnce(new Promise((r) => { resolveN = r; }));

      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: 'bullet' } });
      fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
      await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));

      // A benign re-render with every identity-relevant prop value IDENTICAL
      // — mirrors a same-uid auth re-observation propagating down as a
      // same-value prop update, not a real transition.
      rerender(<TailorModal {...baseProps} profile={makeProfile()} />);
      expect(screen.getByText('tailor.generating')).toBeTruthy(); // still pending, untouched

      await act(async () => {
        resolveN?.({
          method: 'ai',
          warnings: [],
          tailored_bullets: [{ text: 'still valid result', source_evidence: 'x', source_index: 0 }],
        });
      });

      await waitFor(() => expect(screen.getAllByText(fullText('still valid result')).length).toBeGreaterThanOrEqual(1));
      expect(screen.getByText('tailor.methodAi')).toBeTruthy();
    });
  });

  describe('C1-R2B: a manual draft edit invalidates a pending Extract (latest user intent wins)', () => {
    it('Extract pending, user types a manual edit, THEN Extract resolves: the manual text wins in both the textarea and storage', async () => {
      let resolveExtract: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveExtract = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(screen.getByText('tailor.extracting')).toBeTruthy(); // spinner showing
      fireEvent.change(textarea, { target: { value: 'my own fresher typing' } });

      // The spinner/button recovers IMMEDIATELY on the manual edit itself —
      // not only once the (now-invalidated) extract eventually resolves.
      // Without the synchronous setExtracting(false) at the edit site, the
      // invalidated extract's own guarded finally correctly skips clearing
      // it (stillCurrent() is false), which would otherwise leave this
      // stuck true forever.
      expect(screen.queryByText('tailor.extracting')).toBeNull();
      expect(screen.getByRole('button', { name: /tailor\.extractFromResume/ })).not.toBeDisabled();

      await act(async () => {
        resolveExtract?.({ method: 'ai', bullets: ['stale extracted bullet'] });
      });

      expect(textarea.value).toBe('my own fresher typing'); // manual intent wins
      expect(screen.queryByText('tailor.extracting')).toBeNull(); // still recovered after the late resolve
      await waitFor(() => expect(window.localStorage.getItem(DRAFT_KEY)).toBe('my own fresher typing'));
    });

    it('Extract pending, user clicks "Clear draft", THEN Extract resolves: the cleared (empty) draft is not resurrected', async () => {
      window.localStorage.setItem(DRAFT_KEY, 'a previously saved draft');
      let resolveExtract: ((v: { method: string; bullets: string[] }) => void) | undefined;
      mockExtractResumeBullets.mockReturnValueOnce(new Promise((r) => { resolveExtract = r; }));

      const profile = makeProfile({ resume_text: 'Research Assistant\nDid a bunch of things' });
      render(<TailorModal {...baseProps} profile={profile} />);
      fireEvent.click(screen.getByRole('button', { name: /tailor\.extractFromResume/ }));
      await waitFor(() => expect(mockExtractResumeBullets).toHaveBeenCalledTimes(1));

      fireEvent.click(screen.getByRole('button', { name: /tailor\.clearDraftAria/ }));
      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(textarea.value).toBe('');

      await act(async () => {
        resolveExtract?.({ method: 'ai', bullets: ['stale extracted bullet'] });
      });

      expect(textarea.value).toBe(''); // still cleared — extract's stale result did not resurrect it
      expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull();
    });
  });

  describe('C1-R2B: legacy (pre-owner-scoping) drafts are NEVER read, shown, or migrated — not even with a matching LOCAL_IDENTITY_OWNER marker', () => {
    it('a legacy opp-only draft is never surfaced, even when the marker matches ownerScopeKey exactly — matching a marker is not unforgeable proof of ownership (multi-tab/delayed-write residual risk), so it is never trusted', async () => {
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, OWNER);
      window.localStorage.setItem(LEGACY_DRAFT_KEY, 'legacy content — must never surface');

      render(<TailorModal {...baseProps} profile={makeProfile()} />);

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(textarea.value).toBe(''); // heuristic prefill is empty — legacy content never read
      expect(window.localStorage.getItem(LEGACY_DRAFT_KEY)).toBe('legacy content — must never surface'); // untouched — never migrated, never deleted
      expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull(); // never written to the scoped key either
    });

    it('a DELAYED legacy write — a stale U1 tab writing the old opp-only key AFTER the LOCAL_IDENTITY_OWNER marker has already moved to U2 — is never shown or migrated to U2', async () => {
      // The marker already reflects U2 (the current, confirmed owner)...
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, OWNER2);
      // ...but a stale U1 browser tab, unaware of the switch, only now gets
      // around to writing the pre-scoping legacy key. A marker-match check
      // alone cannot distinguish this from a genuinely-U2 write — which is
      // exactly why this component never attempts that check at all.
      window.localStorage.setItem(LEGACY_DRAFT_KEY, 'U1 content written AFTER U2 took over');

      render(<TailorModal {...baseProps} ownerScopeKey={OWNER2} profile={makeProfile()} />);

      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(textarea.value).toBe(''); // U1's delayed write never surfaces for U2
      expect(window.localStorage.getItem(LEGACY_DRAFT_KEY)).toBe('U1 content written AFTER U2 took over'); // left exactly as-is
      expect(window.localStorage.getItem(DRAFT_KEY_OWNER2)).toBeNull(); // never claimed into U2's scoped key
    });

    it('a null ownerScopeKey never persists anything — the draft is ephemeral (in-memory only)', async () => {
      render(<TailorModal {...baseProps} ownerScopeKey={null} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
        target: { value: 'typed while unresolved' },
      });

      await waitFor(() => {
        // No key under the tailor-draft prefix was ever created.
        for (let i = 0; i < window.localStorage.length; i += 1) {
          const key = window.localStorage.key(i);
          expect(key?.startsWith('ofe_tailor_draft_')).toBe(false);
        }
      });
    });

    it('U1 and U2 opening the SAME opportunity never see each other\'s draft', async () => {
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, OWNER);
      const { unmount } = render(<TailorModal {...baseProps} profile={makeProfile()} />);
      fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), {
        target: { value: 'owner-1 private bullets' },
      });
      await waitFor(() => expect(window.localStorage.getItem(DRAFT_KEY)).toBe('owner-1 private bullets'));
      unmount();

      // U2 — a different owner, same opportunity, a genuinely fresh instance
      // (mirrors the real remount-on-identity-change wiring in MatchList).
      window.localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, OWNER2);
      render(<TailorModal {...baseProps} ownerScopeKey={OWNER2} profile={makeProfile()} />);
      const textarea2 = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      expect(textarea2.value).toBe(''); // U1's draft never surfaces for U2
      expect(window.localStorage.getItem(DRAFT_KEY_OWNER2)).toBeNull();
      // U1's own draft is still exactly where U1 left it.
      expect(window.localStorage.getItem(DRAFT_KEY)).toBe('owner-1 private bullets');
    });
  });

  describe('C1-R2B: ownerScopeKey changing on an ALREADY-OPEN modal (isOpen never flips false) must never leak a draft cross-owner', () => {
    it('U1 types a private draft; ownerScopeKey switches straight to U2 with the modal staying open the entire time — U1\'s text must NEVER be written under U2\'s key at ANY point (not just in the final settled state), and the UI must end up showing U2\'s own draft', async () => {
      const { rerender } = render(<TailorModal {...baseProps} profile={makeProfile()} />); // U1, isOpen=true throughout
      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      fireEvent.change(textarea, { target: { value: 'U1 PRIVATE draft' } });
      await waitFor(() => expect(window.localStorage.getItem(DRAFT_KEY)).toBe('U1 PRIVATE draft'));

      // U2's own draft already exists in storage — proves the UI ends up
      // showing U2's real content, not merely "not U1's".
      window.localStorage.setItem(DRAFT_KEY_OWNER2, 'U2 own draft');

      // Spy on the FULL call history of setItem/removeItem — a final-state
      // check alone is not enough here: React's act()-wrapped rerender
      // flushes the reset effect's cascading setDraft() synchronously
      // BEFORE returning control to this test, so a transient wrong write
      // from the FIRST effect-flush pass would already be silently
      // overwritten by a correct one from the SECOND pass by the time any
      // post-rerender assertion runs — self-healing in a way that would
      // mask exactly the race this test exists to catch. Recording every
      // call is the only way to prove the wrong write never happened at
      // all, not merely that it didn't survive.
      const setItemSpy = vi.spyOn(window.localStorage, 'setItem');

      // The owner switches — isOpen is NEVER flipped false here, unlike
      // MatchList's remount-by-key wiring. This is the exact race the
      // lastPersistedContextRef guard exists for: the reset effect and the
      // persist effect both fire in this SAME commit, and the persist
      // effect's `draft` closure is still "U1 PRIVATE draft" at the moment
      // it runs.
      rerender(<TailorModal {...baseProps} ownerScopeKey={OWNER2} profile={makeProfile()} />);

      // The definitive assertion: across EVERY setItem call made during
      // this whole rerender (including any cascading follow-up renders),
      // U2's key was never once paired with U1's text.
      const badCalls = setItemSpy.mock.calls.filter(
        ([key, value]) => key === DRAFT_KEY_OWNER2 && value === 'U1 PRIVATE draft',
      );
      expect(badCalls).toEqual([]);
      // U1's own key was also never touched by U2's arrival, at any point.
      const u1KeyTouched = setItemSpy.mock.calls.some(([key]) => key === DRAFT_KEY);
      expect(u1KeyTouched).toBe(false);

      // Final settled state: U1's key untouched, U2 sees U2's own draft.
      expect(window.localStorage.getItem(DRAFT_KEY)).toBe('U1 PRIVATE draft');
      await waitFor(() => expect(screen.getByPlaceholderText('tailor.bulletsPlaceholder')).toHaveValue('U2 own draft'));
      expect(window.localStorage.getItem(DRAFT_KEY_OWNER2)).toBe('U2 own draft');
    });

    it('same scenario but U2 has NO existing draft — U2 sees the heuristic prefill (or empty), and setItem is NEVER called with U2\'s key paired with U1\'s text at any point', async () => {
      const profile = makeProfile();
      const { rerender } = render(<TailorModal {...baseProps} profile={profile} />);
      const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
      fireEvent.change(textarea, { target: { value: 'another U1 secret' } });
      await waitFor(() => expect(window.localStorage.getItem(DRAFT_KEY)).toBe('another U1 secret'));

      const setItemSpy = vi.spyOn(window.localStorage, 'setItem');
      rerender(<TailorModal {...baseProps} ownerScopeKey={OWNER2} profile={profile} />);

      const badCalls = setItemSpy.mock.calls.filter(
        ([key, value]) => key === DRAFT_KEY_OWNER2 && value === 'another U1 secret',
      );
      expect(badCalls).toEqual([]);

      await waitFor(() => expect(screen.getByPlaceholderText('tailor.bulletsPlaceholder')).toHaveValue(''));
      expect(window.localStorage.getItem(DRAFT_KEY_OWNER2)).toBeNull();
      expect(window.localStorage.getItem(DRAFT_KEY)).toBe('another U1 secret'); // U1's own draft untouched
    });
  });
});
