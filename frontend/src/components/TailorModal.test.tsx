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
vi.mock('@/lib/api', () => ({
  tailorResume: (...args: unknown[]) => mockTailorResume(...args),
}));

import TailorModal from './TailorModal';
import type { ProfileData, TailorResponse } from '@/lib/types';

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
      expect(screen.getByText(/Implemented Python ML experiments in CS 225 coursework/)).toBeTruthy();
    });
    // Method chip reflects success path.
    expect(screen.getByText('tailor.methodAi')).toBeTruthy();
    // R71-E: side-by-side renders both labels + the matching original
    // (looked up via source_index=0 against the submitted snapshot).
    expect(screen.getByText('tailor.originalRowLabel')).toBeTruthy();
    expect(screen.getByText('tailor.tailoredRowLabel')).toBeTruthy();
    // The original bullet text appears both in the textarea (value)
    // AND in the rendered comparison card, so getAllByText returns >=2.
    expect(
      screen.getAllByText(/Worked on Python projects in CS 225/).length,
    ).toBeGreaterThanOrEqual(2);
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
      // Both original lines should render as their tailored card's
      // line-through prefix.
      expect(screen.getByText(/^thermal flow project$/)).toBeTruthy();
      expect(screen.getByText(/^fluid dynamics project$/)).toBeTruthy();
      // Two pairs of section labels.
      expect(screen.getAllByText('tailor.originalRowLabel').length).toBe(2);
      expect(screen.getAllByText('tailor.tailoredRowLabel').length).toBe(2);
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
});
