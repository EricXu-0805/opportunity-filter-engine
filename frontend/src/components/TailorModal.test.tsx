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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

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

const baseProps = {
  isOpen: true,
  onClose: vi.fn(),
  opportunityId: 'opp-123',
  opportunityTitle: 'Some research opportunity',
};

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
      'ofe_tailor_draft_opp-123',
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
        window.localStorage.getItem('ofe_tailor_draft_opp-123'),
      ).toBe('newly typed bullet');
    });
  });

  it('R71-F: clear-draft button wipes the textarea + storage slot', async () => {
    window.localStorage.setItem('ofe_tailor_draft_opp-123', 'kept across reload');
    render(<TailorModal {...baseProps} profile={makeProfile()} />);

    fireEvent.click(screen.getByRole('button', { name: /tailor\.clearDraftAria/ }));

    const textarea = screen.getByPlaceholderText('tailor.bulletsPlaceholder') as HTMLTextAreaElement;
    expect(textarea.value).toBe('');
    expect(window.localStorage.getItem('ofe_tailor_draft_opp-123')).toBeNull();
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
    expect(window.localStorage.getItem('ofe_tailor_draft_opp-123')).toBe(
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
    expect(window.localStorage.getItem('ofe_tailor_draft_opp-123')).toBe(
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
});
