/**
 * ResumeRenovationModal — frontend tests.
 *
 * Mirrors TailorModal.test.tsx: stable t-mock (keys render verbatim), mocked
 * api + supabase modules whose resolved values drive the rendered output.
 * The variant-chain invariants are the point: rollback is a pure pointer
 * move (no network), edits append user variants, re-optimize appends an ai
 * variant only when the backend accepted it.
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

const mockStructureResume = vi.fn();
const mockRenovateResume = vi.fn();
const mockOptimizeBullet = vi.fn();
vi.mock('@/lib/api', () => ({
  structureResume: (...args: unknown[]) => mockStructureResume(...args),
  renovateResume: (...args: unknown[]) => mockRenovateResume(...args),
  optimizeBullet: (...args: unknown[]) => mockOptimizeBullet(...args),
}));

const mockSaveRenovation = vi.fn();
const mockLoadRenovation = vi.fn();
vi.mock('@/lib/supabase', () => ({
  saveRenovation: (...args: unknown[]) => mockSaveRenovation(...args),
  loadRenovation: (...args: unknown[]) => mockLoadRenovation(...args),
}));

import ResumeRenovationModal from './ResumeRenovationModal';
import type { ProfileData, RenovationDoc } from '@/lib/types';

// The word-diff splits changed bullet text into per-word nodes; match on
// assembled textContent instead (same helper as TailorModal.test).
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
    resume_text: '• Built a data pipeline\n• Led a robotics club project',
    ...overrides,
  };
}

function makeDoc(overrides: Partial<RenovationDoc> = {}): RenovationDoc {
  return {
    sections: [
      {
        id: 's1',
        heading: 'Projects',
        kind: 'projects',
        bullets: [
          {
            id: 's1b1',
            base_text: 'Built a data pipeline',
            variants: [
              {
                source: 'macro',
                text: 'Built a fault-tolerant data pipeline for ML workloads',
                source_evidence: 'Built a data pipeline',
              },
            ],
            current: 0,
            action: 'foreground',
          },
          {
            id: 's1b2',
            base_text: 'Led a robotics club project',
            variants: [],
            current: -1,
            action: 'keep',
          },
        ],
      },
    ],
    method: 'ai',
    warnings: [],
    ...overrides,
  };
}

beforeEach(() => {
  mockStructureResume.mockReset();
  mockRenovateResume.mockReset();
  mockOptimizeBullet.mockReset();
  mockSaveRenovation.mockReset().mockResolvedValue(undefined);
  mockLoadRenovation.mockReset().mockResolvedValue(null);
  Element.prototype.scrollIntoView = vi.fn();
});

function renderModal(profile = makeProfile()) {
  return render(
    <ResumeRenovationModal
      isOpen
      onClose={vi.fn()}
      profile={profile}
      opportunityId="opp-1"
      opportunityTitle="Prof. Doe's Lab"
    />,
  );
}

describe('ResumeRenovationModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <ResumeRenovationModal
        isOpen={false}
        onClose={vi.fn()}
        profile={makeProfile()}
        opportunityId="opp-1"
        opportunityTitle="X"
      />,
    );
    expect(container.firstChild).toBeNull();
    expect(mockLoadRenovation).not.toHaveBeenCalled();
  });

  it('shows the start CTA when no saved doc exists and a resume is on file', async () => {
    renderModal();
    expect(await screen.findByText('renovate.start')).toBeInTheDocument();
    expect(mockLoadRenovation).toHaveBeenCalledWith('opp-1');
  });

  it('asks for a resume when the profile has none', async () => {
    renderModal(makeProfile({ resume_text: '' }));
    expect(await screen.findByText('renovate.noResume')).toBeInTheDocument();
    expect(screen.queryByText('renovate.start')).toBeNull();
  });

  it('structure → renovate renders the doc and persists it', async () => {
    mockStructureResume.mockResolvedValue({
      sections: [
        {
          id: 's1', heading: 'Projects', kind: 'projects',
          bullets: [{ id: 's1b1', text: 'Built a data pipeline' }],
        },
      ],
      method: 'ai',
      warnings: [],
    });
    mockRenovateResume.mockResolvedValue(makeDoc());
    renderModal();

    fireEvent.click(await screen.findByText('renovate.start'));
    await waitFor(() =>
      expect(
        screen.getByText(fullText('Built a fault-tolerant data pipeline for ML workloads')),
      ).toBeInTheDocument(),
    );
    expect(mockStructureResume).toHaveBeenCalledTimes(1);
    expect(mockRenovateResume).toHaveBeenCalledTimes(1);
    // The renovated doc is persisted (doc + base snapshot).
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    expect(mockSaveRenovation.mock.calls[0][0]).toBe('opp-1');
    expect(screen.getByText('renovate.source.macro')).toBeInTheDocument();
    expect(screen.getByText('renovate.action.foreground')).toBeInTheDocument();
  });

  it('restores a saved doc without touching the pipeline APIs', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '2026-07-17T00:00:00Z',
    });
    renderModal();
    await waitFor(() =>
      expect(
        screen.getByText(fullText('Built a fault-tolerant data pipeline for ML workloads')),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText('renovate.restored')).toBeInTheDocument();
    expect(mockStructureResume).not.toHaveBeenCalled();
    expect(mockRenovateResume).not.toHaveBeenCalled();
  });

  it('rollback is a pure pointer move: shows base_text, calls no API', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    renderModal();
    await waitFor(() => expect(screen.getAllByText('renovate.rollback').length).toBeGreaterThan(0));

    // First bullet is on its macro variant; roll it back to base.
    fireEvent.click(screen.getAllByText('renovate.rollback')[0]);
    await waitFor(() =>
      expect(screen.getByText(fullText('Built a data pipeline'))).toBeInTheDocument(),
    );
    expect(mockOptimizeBullet).not.toHaveBeenCalled();
    expect(mockRenovateResume).not.toHaveBeenCalled();
    // The pointer move persists (the doc IS the history).
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalled());
    // Roll forward returns to the variant.
    fireEvent.click(screen.getAllByText('renovate.rollForward')[0]);
    await waitFor(() =>
      expect(
        screen.getByText(fullText('Built a fault-tolerant data pipeline for ML workloads')),
      ).toBeInTheDocument(),
    );
  });

  it('saving an edit appends a user variant', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    renderModal();
    await waitFor(() => expect(screen.getAllByText('renovate.edit').length).toBeGreaterThan(0));

    fireEvent.click(screen.getAllByText('renovate.edit')[0]);
    // Edit mode renders exactly one textbox (the button shares the aria-label).
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'My own phrasing of the pipeline work' } });
    fireEvent.click(screen.getByText('renovate.save'));

    await waitFor(() =>
      expect(
        screen.getByText(fullText('My own phrasing of the pipeline work')),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText('renovate.source.user')).toBeInTheDocument();
  });

  it('re-optimize appends an ai variant when the backend accepts', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    mockOptimizeBullet.mockResolvedValue({
      text: 'Engineered a resilient ETL pipeline powering ML experiments',
      source_evidence: 'Built a data pipeline',
      changed: true,
      warnings: [],
    });
    renderModal();
    await waitFor(() => expect(screen.getAllByText('renovate.reoptimize').length).toBeGreaterThan(0));

    fireEvent.click(screen.getAllByText('renovate.reoptimize')[0]);
    await waitFor(() =>
      expect(
        screen.getByText(fullText('Engineered a resilient ETL pipeline powering ML experiments')),
      ).toBeInTheDocument(),
    );
    expect(mockOptimizeBullet).toHaveBeenCalledWith(
      expect.anything(),
      'opp-1',
      'Built a fault-tolerant data pipeline for ML workloads', // current
      'Built a data pipeline', // base
      expect.any(Object),
    );
    expect(screen.getByText('renovate.source.ai')).toBeInTheDocument();
  });

  it('re-optimize declined (changed=false) keeps the text and says so', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    mockOptimizeBullet.mockResolvedValue({
      text: 'Built a fault-tolerant data pipeline for ML workloads',
      source_evidence: '',
      changed: false,
      warnings: ['bullet_rejected_fabrication: kubernetes'],
    });
    renderModal();
    await waitFor(() => expect(screen.getAllByText('renovate.reoptimize').length).toBeGreaterThan(0));

    fireEvent.click(screen.getAllByText('renovate.reoptimize')[0]);
    await waitFor(() =>
      expect(screen.getByText('renovate.bulletUnchanged')).toBeInTheDocument(),
    );
    // Still showing the macro variant — no phantom ai variant appended.
    expect(
      screen.getByText(fullText('Built a fault-tolerant data pipeline for ML workloads')),
    ).toBeInTheDocument();
    expect(screen.queryByText('renovate.source.ai')).toBeNull();
  });

  it('surfaces the fabrication warning banner from the renovate pass', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc({
        warnings: ['bullet_s1b1_rejected_fabrication: kubernetes'],
      }) as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: ['bullet_s1b1_rejected_fabrication: kubernetes'],
      updated_at: '',
    });
    renderModal();
    await waitFor(() =>
      expect(screen.getByText('renovate.warnings.fabricationCaught')).toBeInTheDocument(),
    );
  });
});

describe('W13 save truthfulness + staleness', () => {
  it('shows Saved only when persistence actually succeeded', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    mockSaveRenovation.mockResolvedValue(true);
    renderModal();
    await waitFor(() => expect(screen.getAllByText('renovate.rollback').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText('renovate.rollback')[0]);
    await waitFor(() => expect(screen.getByText('renovate.saved')).toBeInTheDocument());
    expect(screen.queryByTestId('renovation-save-failed')).toBeNull();
  });

  it('a failed save never shows Saved — it shows the retry state, and retry recovers', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    mockSaveRenovation.mockResolvedValue(false);
    renderModal();
    await waitFor(() => expect(screen.getAllByText('renovate.rollback').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText('renovate.rollback')[0]);

    await waitFor(() => expect(screen.getByTestId('renovation-save-failed')).toBeInTheDocument());
    expect(screen.queryByText('renovate.saved')).toBeNull();

    // Retry with a recovered backend → truthful Saved.
    mockSaveRenovation.mockResolvedValue(true);
    fireEvent.click(screen.getByText('renovate.retrySave'));
    await waitFor(() => expect(screen.getByText('renovate.saved')).toBeInTheDocument());
    expect(screen.queryByTestId('renovation-save-failed')).toBeNull();
  });

  it('a rejecting save (thrown error) also shows the retry state, not Saved', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    mockSaveRenovation.mockRejectedValue(new Error('network down'));
    renderModal();
    await waitFor(() => expect(screen.getAllByText('renovate.rollback').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText('renovate.rollback')[0]);
    await waitFor(() => expect(screen.getByTestId('renovation-save-failed')).toBeInTheDocument());
    expect(screen.queryByText('renovate.saved')).toBeNull();
  });

  it('flags a restored doc whose resume_sig no longer matches the profile resume', async () => {
    const doc = makeDoc() as unknown as Record<string, unknown>;
    (doc as { resume_sig?: string }).resume_sig = 'sig-of-an-older-resume';
    mockLoadRenovation.mockResolvedValue({
      doc,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '2026-07-17T00:00:00Z',
    });
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId('renovation-stale-resume')).toBeInTheDocument(),
    );
  });

  it('makes no staleness claim for legacy docs without a resume_sig', async () => {
    mockLoadRenovation.mockResolvedValue({
      doc: makeDoc() as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    renderModal();
    await waitFor(() => expect(screen.getByText('renovate.restored')).toBeInTheDocument());
    expect(screen.queryByTestId('renovation-stale-resume')).toBeNull();
  });
});
