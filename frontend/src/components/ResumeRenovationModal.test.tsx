/**
 * ResumeRenovationModal — frontend tests.
 *
 * Mirrors TailorModal.test.tsx: stable t-mock (keys render verbatim), mocked
 * api + supabase modules whose resolved values drive the rendered output.
 * The variant-chain invariants are the point: rollback is a pure pointer
 * move (no network), edits append user variants, re-optimize appends an ai
 * variant only when the backend accepted it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { webcrypto } from 'node:crypto';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

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
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from '@/lib/identity-owner';
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

beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto);
  localStorage.clear();
  advanceOwnerEpoch('renovation-owner-a');
  await syncLocalIdentityOwner('renovation-owner-a');
  await waitFor(() => expect(isLocalOwnerReady('renovation-owner-a')).toBe(true));
  mockStructureResume.mockReset();
  mockRenovateResume.mockReset();
  mockOptimizeBullet.mockReset();
  mockSaveRenovation.mockReset().mockResolvedValue(undefined);
  mockLoadRenovation.mockReset().mockResolvedValue(null);
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => vi.unstubAllGlobals());

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
    expect(mockLoadRenovation).toHaveBeenCalledWith('opp-1', captureOwnerToken());
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
  it('copying the renovated résumé keeps de-emphasized bullets, placed lower', async () => {
    // "demote" is defined to the model as "kept but de-emphasized (placed
    // lower)" and the student sees a chip reading "De-emphasized". Dropping
    // those bullets deleted the student's own experience from the text they
    // pasted back into their résumé, with no warning.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const doc = makeDoc();
    doc.sections[0].bullets.push({
      id: 's1b3',
      base_text: 'Tutored intro statistics for two semesters',
      variants: [],
      current: -1,
      action: 'demote',
    });
    mockLoadRenovation.mockResolvedValue({
      doc: doc as unknown as Record<string, unknown>,
      base_snapshot: { sections: [] },
      method: 'ai',
      warnings: [],
      updated_at: '',
    });
    renderModal();
    await waitFor(() =>
      expect(screen.getByText('renovate.copyAll')).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText('renovate.copyAll'));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));

    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain('Tutored intro statistics for two semesters');
    // foreground first, keep next, de-emphasized last.
    expect(copied.indexOf('fault-tolerant data pipeline')).toBeLessThan(
      copied.indexOf('Led a robotics club project'),
    );
    expect(copied.indexOf('Led a robotics club project')).toBeLessThan(
      copied.indexOf('Tutored intro statistics'),
    );
  });

});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

const structuredResume = { sections: [{ id: 's1', heading: 'Projects', kind: 'projects',
  bullets: [{ id: 's1b1', text: 'Built a data pipeline' }] }], method: 'ai', warnings: [] };

async function switchRenovationOwner() {
  await act(async () => {
    advanceOwnerEpoch('renovation-owner-b');
    await syncLocalIdentityOwner('renovation-owner-b');
  });
}

function savedDoc(doc = makeDoc()) {
  return { doc, base_snapshot: { sections: [] }, method: 'ai', warnings: [], updated_at: '' };
}

describe('renovation owner and request lifecycle', () => {
  it('does not start renovation when structure finishes after unmount', async () => {
    const pending = deferred<typeof structuredResume>();
    mockStructureResume.mockReturnValue(pending.promise);
    const view = renderModal();
    fireEvent.click(await screen.findByText('renovate.start'));
    view.unmount();
    await act(async () => { pending.resolve(structuredResume); });
    expect(mockRenovateResume).not.toHaveBeenCalled();
    expect(mockSaveRenovation).not.toHaveBeenCalled();
  });

  it.each(['unmount', 'owner switch'] as const)('drops a generated doc after %s without saving it', async (change) => {
    const pending = deferred<RenovationDoc>();
    mockStructureResume.mockResolvedValue(structuredResume);
    mockRenovateResume.mockReturnValue(pending.promise);
    const view = renderModal();
    fireEvent.click(await screen.findByText('renovate.start'));
    await waitFor(() => expect(mockRenovateResume).toHaveBeenCalledTimes(1));
    if (change === 'unmount') view.unmount();
    else await switchRenovationOwner();
    await act(async () => { pending.resolve(makeDoc()); });
    expect(mockSaveRenovation).not.toHaveBeenCalled();
    expect(screen.queryByText('renovate.copyAll')).toBeNull();
  });

  it('drops an old saved-doc restore after an owner switch', async () => {
    const pending = deferred<ReturnType<typeof savedDoc>>();
    mockLoadRenovation.mockReturnValue(pending.promise);
    renderModal();
    await switchRenovationOwner();
    await act(async () => { pending.resolve(savedDoc()); });
    expect(screen.queryByText('renovate.restored')).toBeNull();
    expect(mockSaveRenovation).not.toHaveBeenCalled();
  });

  it('keeps a completed anonymous-owner generation bound to its original token', async () => {
    const originalOwner = captureOwnerToken();
    mockStructureResume.mockResolvedValue(structuredResume);
    mockRenovateResume.mockResolvedValue(makeDoc());
    renderModal();
    fireEvent.click(await screen.findByText('renovate.start'));
    // Same-owner re-observation is not a sign-out and must not discard work.
    await act(async () => { advanceOwnerEpoch(originalOwner.uid); await syncLocalIdentityOwner(originalOwner.uid); });
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    expect(mockSaveRenovation.mock.calls[0][5]).toEqual(originalOwner);
  });

  it('keeps an old source signature and stale warning when the source is removed and the doc edited', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc(makeDoc({ resume_sig: 'original-source' })));
    renderModal(makeProfile({ resume_text: '' }));
    expect(await screen.findByTestId('renovation-stale-resume')).toBeInTheDocument();
    fireEvent.click(screen.getAllByText('renovate.rollback')[0]);
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    expect(mockSaveRenovation.mock.calls[0][1].resume_sig).toBe('original-source');
    expect(screen.getByTestId('renovation-stale-resume')).toBeInTheDocument();
  });

  it('cannot apply a late bullet optimization over a newer manual edit', async () => {
    const pending = deferred<{ text: string; changed: boolean; source_evidence: string }>();
    mockLoadRenovation.mockResolvedValue(savedDoc());
    mockOptimizeBullet.mockReturnValue(pending.promise);
    renderModal();
    fireEvent.click((await screen.findAllByText('renovate.reoptimize'))[0]);
    fireEvent.click(screen.getAllByText('renovate.edit')[0]);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'A newer manual edit' } });
    fireEvent.click(screen.getByText('renovate.save'));
    await act(async () => { pending.resolve({ text: 'Late AI text', changed: true, source_evidence: '' }); });
    expect(screen.getByText(fullText('A newer manual edit'))).toBeInTheDocument();
    expect(screen.queryByText('Late AI text')).toBeNull();
    expect(mockSaveRenovation).toHaveBeenCalledTimes(1);
  });

  it('cannot save a late bullet optimization under a new owner', async () => {
    const pending = deferred<{ text: string; changed: boolean; source_evidence: string }>();
    mockLoadRenovation.mockResolvedValue(savedDoc());
    mockOptimizeBullet.mockReturnValue(pending.promise);
    renderModal();
    fireEvent.click((await screen.findAllByText('renovate.reoptimize'))[0]);
    await switchRenovationOwner();
    await act(async () => { pending.resolve({ text: 'Late AI text', changed: true, source_evidence: '' }); });
    expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
});

describe('renovation close and recovery boundaries', () => {
  it('invalidates immediately on Close even when the parent delays updating isOpen', async () => {
    const pending = deferred<RenovationDoc>();
    mockStructureResume.mockResolvedValue(structuredResume);
    mockRenovateResume.mockReturnValue(pending.promise);
    renderModal();
    fireEvent.click(await screen.findByText('renovate.start'));
    await waitFor(() => expect(mockRenovateResume).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'renovate.closeAria' }));
    await act(async () => { pending.resolve(makeDoc()); });
    expect(mockSaveRenovation).not.toHaveBeenCalled();
  });

  it('drops an old-target result after the same modal is repurposed', async () => {
    const pending = deferred<RenovationDoc>();
    mockStructureResume.mockResolvedValue(structuredResume);
    mockRenovateResume.mockReturnValue(pending.promise);
    const view = renderModal();
    fireEvent.click(await screen.findByText('renovate.start'));
    await waitFor(() => expect(mockRenovateResume).toHaveBeenCalled());
    view.rerender(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={makeProfile()}
      opportunityId="opp-2" opportunityTitle="Another lab" />);
    await act(async () => { pending.resolve(makeDoc()); });
    expect(mockSaveRenovation).not.toHaveBeenCalled();
    expect(screen.queryByText('renovate.copyAll')).toBeNull();
  });

  it('does not display a late saved receipt after an account switch', async () => {
    const pending = deferred<boolean>();
    mockLoadRenovation.mockResolvedValue(savedDoc());
    mockSaveRenovation.mockReturnValue(pending.promise);
    renderModal();
    fireEvent.click((await screen.findAllByText('renovate.rollback'))[0]);
    await switchRenovationOwner();
    await act(async () => { pending.resolve(true); });
    expect(screen.queryByText('renovate.saved')).toBeNull();
    expect(screen.queryByText('renovate.retrySave')).toBeNull();
  });

  it('recovers from an unavailable owner/load and can reopen under a ready anonymous owner', async () => {
    mockLoadRenovation.mockRejectedValueOnce(new Error('local data ownership is not confirmed for this read'));
    const view = renderModal();
    expect(await screen.findByText('renovate.restoreFailed')).toBeInTheDocument();
    expect(screen.queryByText('renovate.start')).toBeNull();
    await switchRenovationOwner();
    view.rerender(<ResumeRenovationModal isOpen={false} onClose={vi.fn()} profile={makeProfile()}
      opportunityId="opp-1" opportunityTitle="Lab" />);
    mockLoadRenovation.mockResolvedValueOnce(savedDoc());
    view.rerender(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={makeProfile()}
      opportunityId="opp-1" opportunityTitle="Lab" />);
    expect(await screen.findByText('renovate.restored')).toBeInTheDocument();
    expect(mockLoadRenovation.mock.lastCall?.[1].uid).toBe('renovation-owner-b');
  });
});

it('restarts restore with a fresh capability when the same anonymous owner becomes ready', async () => {
  advanceOwnerEpoch('renovation-ready-later');
  const pending = deferred<ReturnType<typeof savedDoc>>();
  mockLoadRenovation.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(savedDoc());
  renderModal();
  const originalToken = mockLoadRenovation.mock.calls[0][1];
  await act(async () => { await syncLocalIdentityOwner('renovation-ready-later'); });
  expect(await screen.findByText('renovate.restored')).toBeInTheDocument();
  expect(mockLoadRenovation).toHaveBeenCalledTimes(2);
  const readyToken = mockLoadRenovation.mock.calls[1][1];
  expect(readyToken.uid).toBe(originalToken.uid);
  expect(readyToken.generation).not.toBe(originalToken.generation);
  await act(async () => { pending.resolve(savedDoc(makeDoc({ resume_sig: 'stale-late-restore' }))); });
  expect(screen.queryByTestId('renovation-stale-resume')).toBeNull();
  fireEvent.click(screen.getAllByText('renovate.rollback')[0]);
  await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
  expect(mockSaveRenovation.mock.calls[0][5]).toEqual(readyToken);
});


describe('resume processing coverage persists with the generated document', () => {
  it('keeps partial extraction metadata and warnings in the saved review document', async () => {
    const processing = {
      input_characters: 8_100, ai_chunks: 1, heuristic_chunks: 1,
      chunks: [{ start: 0, end: 8_000, method: 'ai' }, { start: 8_000, end: 8_100, method: 'heuristic' }],
    };
    mockStructureResume.mockResolvedValue({
      sections: [{ id: 's1', heading: 'Projects', kind: 'projects', bullets: [{ id: 's1b1', text: 'Built a data pipeline' }] }],
      method: 'mixed', warnings: ['partial_ai_processing', 'bullet_selection_limited'], processing,
    });
    mockRenovateResume.mockResolvedValue(makeDoc());
    renderModal(makeProfile({ resume_text: 'x'.repeat(8_100) }));
    await screen.findByText('renovate.start');
    expect(screen.getByText('resume.processingLong')).toBeInTheDocument();
    fireEvent.click(screen.getByText('renovate.start'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    expect(mockSaveRenovation.mock.calls[0][1].processing).toEqual(processing);
    expect(mockSaveRenovation.mock.calls[0][1].warnings).toContain('partial_ai_processing');
    expect(screen.getByText('resume.processingCoverage:1|2|1')).toBeInTheDocument();
    expect(screen.getByText('resume.processingSelectionLimited')).toBeInTheDocument();
  });
});


function showProfile(view: ReturnType<typeof renderModal>, profile: ProfileData) {
  view.rerender(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={profile}
    opportunityId="opp-1" opportunityTitle="Prof. Doe's Lab" />);
}

function editFirstBullet(text: string) {
  fireEvent.click(screen.getAllByText('renovate.edit')[0]);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: text } });
}

describe('M42 restore failures never become an empty document', () => {
  it('offers retry after a read failure and blocks generation until the saved document is recovered', async () => {
    const pending = deferred<ReturnType<typeof savedDoc>>();
    mockLoadRenovation.mockRejectedValueOnce(new Error('private upstream detail')).mockReturnValueOnce(pending.promise);
    renderModal();
    expect(await screen.findByRole('alert')).toHaveTextContent('renovate.restoreFailed');
    expect(screen.queryByText('private upstream detail')).toBeNull();
    expect(screen.queryByText('renovate.start')).toBeNull();
    expect(screen.queryByText('renovate.rerun')).toBeNull();
    fireEvent.click(screen.getByText('renovate.restoreRetry'));
    expect(screen.queryByText('renovate.start')).toBeNull();
    expect(mockLoadRenovation).toHaveBeenCalledTimes(2);
    await act(async () => { pending.resolve(savedDoc()); });
    expect(screen.getByText('renovate.restored')).toBeInTheDocument();
    expect(mockStructureResume).not.toHaveBeenCalled();
    expect(mockRenovateResume).not.toHaveBeenCalled();
    expect(mockSaveRenovation).not.toHaveBeenCalled();
  });

  it('only a confirmed absent row after retry enables a new generation', async () => {
    mockLoadRenovation.mockRejectedValueOnce(new Error('invalid_saved_data')).mockResolvedValueOnce(null);
    renderModal();
    fireEvent.click(await screen.findByText('renovate.restoreRetry'));
    expect(await screen.findByText('renovate.start')).toBeInTheDocument();
    expect(mockStructureResume).not.toHaveBeenCalled();
    expect(mockSaveRenovation).not.toHaveBeenCalled();
  });

  it('does not escape recovery error just because the profile changes', async () => {
    mockLoadRenovation.mockRejectedValue(new Error('read failed'));
    const view = renderModal();
    await screen.findByText('renovate.restoreFailed');
    showProfile(view, makeProfile({ coursework: ['CS 374'] }));
    expect(screen.getByText('renovate.restoreFailed')).toBeInTheDocument();
    expect(screen.queryByText('renovate.start')).toBeNull();
    expect(mockLoadRenovation).toHaveBeenCalledTimes(1);
  });
});

describe('M43 complete profile content owns asynchronous work', () => {
  it.each(['skills', 'coursework', 'name', 'interests', 'status', 'revision', 'source', 'resume'] as const)(
    'retires structure after an in-place %s change without loading over local work', async (field) => {
      const input = makeProfile({ name: 'Original Student', experience_entries: [{ id: 'entry', revision: 1,
        status: 'confirmed', text: 'Built a pipeline', source: { kind: 'resume', signature: 'a'.repeat(64),
          quote: 'Built a pipeline', start: 0, end: 16 } }] });
      const pending = deferred<typeof structuredResume>();
      mockStructureResume.mockReturnValue(pending.promise);
      const view = renderModal(input);
      fireEvent.click(await screen.findByText('renovate.start'));
      await waitFor(() => expect(mockStructureResume).toHaveBeenCalledTimes(1));
      if (field === 'skills') input.skills[0].level = 'beginner';
      if (field === 'coursework') input.coursework!.push('CS 374');
      if (field === 'name') input.name = 'Corrected Student';
      if (field === 'interests') input.research_interests = 'robotics';
      if (field === 'status') input.experience_entries![0].status = 'withdrawn';
      if (field === 'revision') input.experience_entries![0].revision += 1;
      if (field === 'source' && input.experience_entries![0].source.kind === 'resume') input.experience_entries![0].source.signature = 'b'.repeat(64);
      if (field === 'resume') input.resume_text = 'Replacement source';
      showProfile(view, input);
      expect(screen.getByTestId('renovation-profile-changed')).toBeInTheDocument();
      await act(async () => { pending.resolve(structuredResume); });
      expect(mockRenovateResume).not.toHaveBeenCalled();
      expect(mockSaveRenovation).not.toHaveBeenCalled();
      expect(mockLoadRenovation).toHaveBeenCalledTimes(1);
      expect(screen.getByText('renovate.start')).toBeInTheDocument();
    },
  );

  it('keeps the original document and unfinished manual edit when profile change retires a rerun', async () => {
    const pending = deferred<RenovationDoc>();
    mockLoadRenovation.mockResolvedValue(savedDoc(makeDoc({ resume_sig: 'original-source' })));
    mockStructureResume.mockResolvedValue(structuredResume);
    mockRenovateResume.mockReturnValue(pending.promise);
    const input = makeProfile(); const view = renderModal(input);
    await screen.findByText('renovate.restored');
    editFirstBullet('My unfinished draft');
    fireEvent.click(screen.getByText('renovate.rerun'));
    await waitFor(() => expect(mockRenovateResume).toHaveBeenCalledTimes(1));
    input.skills[0].level = 'beginner';
    showProfile(view, input);
    expect(screen.getByRole('textbox')).toHaveValue('My unfinished draft');
    expect(mockRenovateResume.mock.calls[0][0].skills[0].level).toBe('experienced');
    await act(async () => { pending.resolve(makeDoc({ sections: [{ id: 'late', kind: 'projects', heading: 'LATE RESULT', bullets: [] }] })); });
    expect(screen.queryByText('LATE RESULT')).toBeNull();
    expect(screen.getByRole('textbox')).toHaveValue('My unfinished draft');
    fireEvent.click(screen.getByText('renovate.save'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    const stored = mockSaveRenovation.mock.calls[0][1];
    expect(stored.resume_sig).toBe('original-source');
    expect(stored).not.toHaveProperty('profile_sig');
    expect(stored.sections[0].bullets[0].variants.at(-1).text).toBe('My unfinished draft');
    expect(mockLoadRenovation).toHaveBeenCalledTimes(1);
  });

  it.each(['rejected request', 'no sections'] as const)('a %s rerun restores the previous document and unsaved edit', async (failure) => {
    mockLoadRenovation.mockResolvedValue(savedDoc());
    if (failure === 'no sections') mockStructureResume.mockResolvedValue({ sections: [], method: 'heuristic', warnings: [] });
    else { mockStructureResume.mockResolvedValue(structuredResume); mockRenovateResume.mockRejectedValue(new Error('Generation unavailable')); }
    renderModal(); await screen.findByText('renovate.restored');
    editFirstBullet('My pending manual wording');
    fireEvent.click(screen.getByText('renovate.rerun'));
    expect(await screen.findByRole('textbox')).toHaveValue('My pending manual wording');
    expect(screen.getByRole('alert')).toHaveTextContent(failure === 'no sections' ? 'renovate.noSections' : 'Generation unavailable');
    expect(screen.getByText('renovate.copyAll')).toBeInTheDocument();
    expect(mockSaveRenovation).not.toHaveBeenCalled();
  });

  it('retires a late bullet optimization while keeping an unsaved manual edit and the old provenance', async () => {
    const pending = deferred<{ text: string; changed: boolean; source_evidence: string }>();
    mockLoadRenovation.mockResolvedValue(savedDoc(makeDoc({ resume_sig: 'source-before-edit', profile_sig: 'v1:sha256:' + 'a'.repeat(64) })));
    mockOptimizeBullet.mockReturnValue(pending.promise);
    const view = renderModal();
    fireEvent.click((await screen.findAllByText('renovate.reoptimize'))[0]);
    editFirstBullet('Manual draft remains mine');
    showProfile(view, makeProfile({ coursework: ['CS 374'] }));
    await act(async () => { pending.resolve({ text: 'Retired AI wording', changed: true, source_evidence: '' }); });
    expect(screen.getByRole('textbox')).toHaveValue('Manual draft remains mine');
    expect(screen.queryByText('Retired AI wording')).toBeNull();
    expect(mockSaveRenovation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('renovate.save'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    expect(mockSaveRenovation.mock.calls[0][1].profile_sig).toBe('v1:sha256:' + 'a'.repeat(64));
    expect(mockSaveRenovation.mock.calls[0][1].resume_sig).toBe('source-before-edit');
  });

  it('accepts pending optimization across equal content with reordered object keys and does not reload', async () => {
    const pending = deferred<{ text: string; changed: boolean; source_evidence: string }>();
    mockLoadRenovation.mockResolvedValue(savedDoc()); mockOptimizeBullet.mockReturnValue(pending.promise);
    const input = makeProfile(); const view = renderModal(input);
    fireEvent.click((await screen.findAllByText('renovate.reoptimize'))[0]);
    const reordered = Object.fromEntries(Object.entries(input).reverse()) as unknown as ProfileData;
    reordered.skills = input.skills.map((skill) => Object.fromEntries(Object.entries(skill).reverse()) as unknown as typeof skill);
    showProfile(view, reordered);
    await act(async () => { pending.resolve({ text: 'Current accepted wording', changed: true, source_evidence: '' }); });
    expect(screen.getByText(fullText('Current accepted wording'))).toBeInTheDocument();
    expect(screen.queryByTestId('renovation-profile-changed')).toBeNull();
    expect(mockLoadRenovation).toHaveBeenCalledTimes(1);
    expect(mockSaveRenovation).toHaveBeenCalledTimes(1);
  });

  it('retires an old failed-save retry but preserves the editable draft', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc()); mockSaveRenovation.mockResolvedValue(false);
    const view = renderModal(); await screen.findByText('renovate.restored');
    editFirstBullet('My saved-attempt wording'); fireEvent.click(screen.getByText('renovate.save'));
    await screen.findByText('renovate.retrySave');
    showProfile(view, makeProfile({ research_interests: 'robotics' }));
    expect(screen.queryByText('renovate.retrySave')).toBeNull();
    expect(screen.getByText(fullText('My saved-attempt wording'))).toBeInTheDocument();
    expect(mockSaveRenovation).toHaveBeenCalledTimes(1);
  });

  it('never shows an old in-flight save receipt after profile change', async () => {
    const pending = deferred<boolean>();
    mockLoadRenovation.mockResolvedValue(savedDoc()); mockSaveRenovation.mockReturnValue(pending.promise);
    const view = renderModal(); fireEvent.click((await screen.findAllByText('renovate.rollback'))[0]);
    showProfile(view, makeProfile({ coursework: [] }));
    await act(async () => { pending.resolve(true); });
    expect(screen.queryByText('renovate.saved')).toBeNull();
    expect(screen.queryByText('renovate.retrySave')).toBeNull();
    expect(screen.getByText(fullText('Built a data pipeline'))).toBeInTheDocument();
  });

  it('stores only a digest on new generations and keeps legacy provenance unknown after manual saves', async () => {
    mockStructureResume.mockResolvedValue(structuredResume); mockRenovateResume.mockResolvedValue(makeDoc());
    mockSaveRenovation.mockResolvedValue(true);
    const view = renderModal(); fireEvent.click(await screen.findByText('renovate.start'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    const signature = mockSaveRenovation.mock.calls[0][1].profile_sig;
    expect(signature).toMatch(/^v1:sha256:[a-f0-9]{64}$/);
    expect(signature).not.toContain('Python');
    await waitFor(() => expect(screen.queryByTestId('renovation-profile-unknown')).toBeNull());
    showProfile(view, makeProfile({ skills: [] }));
    expect(screen.getByTestId('renovation-profile-changed')).toBeInTheDocument();
    fireEvent.click(screen.getByText('renovate.rerun'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(2));
    expect(mockSaveRenovation.mock.calls[1][1].profile_sig).not.toBe(signature);
  });

  it('keeps missing legacy profile provenance unknown instead of binding it to the current profile', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc()); renderModal();
    expect(await screen.findByTestId('renovation-profile-unknown')).toBeInTheDocument();
    fireEvent.click(screen.getAllByText('renovate.rollback')[0]);
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    expect(mockSaveRenovation.mock.calls[0][1]).not.toHaveProperty('profile_sig');
    expect(screen.getByTestId('renovation-profile-unknown')).toBeInTheDocument();
  });
});


describe('retired errors and follow-up attempts', () => {
  it.each(['structure', 'renovate', 'optimize'] as const)('ignores an old %s failure after changed-profile work succeeds', async (stage) => {
    const old = deferred<unknown>();
    mockStructureResume.mockResolvedValue(structuredResume);
    mockRenovateResume.mockResolvedValue(makeDoc());
    mockSaveRenovation.mockResolvedValue(true);
    if (stage === 'structure') mockStructureResume.mockReturnValueOnce(old.promise);
    if (stage === 'renovate') mockRenovateResume.mockReturnValueOnce(old.promise);
    if (stage === 'optimize') { mockLoadRenovation.mockResolvedValue(savedDoc()); mockOptimizeBullet.mockReturnValueOnce(old.promise); }
    const view = renderModal();
    if (stage === 'optimize') fireEvent.click((await screen.findAllByText('renovate.reoptimize'))[0]);
    else {
      fireEvent.click(await screen.findByText('renovate.start'));
      await waitFor(() => expect(stage === 'structure' ? mockStructureResume : mockRenovateResume).toHaveBeenCalledTimes(1));
    }
    showProfile(view, makeProfile({ coursework: ['CS 374'] }));
    fireEvent.click(screen.getByText(stage === 'optimize' ? 'renovate.rerun' : 'renovate.start'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    await act(async () => { old.reject(new Error('Obsolete private error')); });
    expect(screen.getByText('renovate.copyAll')).toBeInTheDocument();
    expect(screen.queryByText('Obsolete private error')).toBeNull();
    expect(screen.queryByText('renovate.bulletFailed')).toBeNull();
    expect(mockSaveRenovation).toHaveBeenCalledTimes(1);
  });

  it('does not leave a retired save retry or optimization lock on a failed rerun', async () => {
    const oldOptimization = deferred<{ text: string; changed: boolean; source_evidence: string }>();
    mockLoadRenovation.mockResolvedValue(savedDoc());
    mockSaveRenovation.mockResolvedValue(false);
    mockOptimizeBullet.mockReturnValueOnce(oldOptimization.promise);
    mockStructureResume.mockRejectedValue(new Error('New rerun failed'));
    renderModal(); fireEvent.click((await screen.findAllByText('renovate.rollback'))[0]);
    await screen.findByText('renovate.retrySave');
    fireEvent.click(screen.getAllByText('renovate.reoptimize')[0]);
    fireEvent.click(screen.getByText('renovate.rerun'));
    await screen.findByText('New rerun failed');
    expect(screen.queryByText('renovate.retrySave')).toBeNull();
    expect(screen.getAllByText('renovate.reoptimize')[0].closest('button')).toBeEnabled();
    await act(async () => { oldOptimization.resolve({ text: 'Old optimization', changed: true, source_evidence: '' }); });
    expect(screen.queryByText('Old optimization')).toBeNull();
    expect(mockSaveRenovation).toHaveBeenCalledTimes(1);
  });
});


describe('legacy user exits preserve unsaved work', () => {
  afterEach(() => vi.restoreAllMocks());

  function renderWithExits() {
    const onClose = vi.fn();
    const onOpenFull = vi.fn();
    const props = { isOpen: true, onClose, onOpenFull, profile: makeProfile(),
      opportunityId: 'opp-1', opportunityTitle: 'Lab' };
    const view = render(<ResumeRenovationModal {...props} />);
    return { ...view, props, onClose, onOpenFull };
  }

  function attemptExit(path: 'Escape' | 'backdrop' | 'close' | 'full') {
    if (path === 'Escape') fireEvent.keyDown(document, { key: 'Escape' });
    else if (path === 'backdrop') fireEvent.click(screen.getByRole('dialog').firstElementChild!);
    else fireEvent.click(screen.getByRole('button', { name: path === 'close' ? 'renovate.closeAria' : 'Open full target résumé' }));
  }

  it.each(['Escape', 'backdrop', 'close', 'full'] as const)(
    '%s retains the inline buffer when cancelled and exits only once when accepted', async (path) => {
      mockLoadRenovation.mockResolvedValue(savedDoc());
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
      const { onClose, onOpenFull } = renderWithExits();
      fireEvent.click((await screen.findAllByText('renovate.edit'))[0]);
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unsaved personal wording' } });
      attemptExit(path);
      expect(confirm).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('textbox')).toHaveValue('Unsaved personal wording');
      expect(onClose).not.toHaveBeenCalled(); expect(onOpenFull).not.toHaveBeenCalled();
      expect(mockSaveRenovation).not.toHaveBeenCalled();
      confirm.mockReturnValue(true);
      attemptExit(path);
      // A slow parent has not unmounted yet: a second action must not exit twice.
      attemptExit(path); fireEvent.keyDown(document, { key: 'Escape' });
      expect(confirm).toHaveBeenCalledTimes(2);
      expect(onClose).toHaveBeenCalledTimes(path === 'full' ? 0 : 1);
      expect(onOpenFull).toHaveBeenCalledTimes(path === 'full' ? 1 : 0);
    },
  );

  it('does not move focus as an inline edit changes the exit guard', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc());
    renderWithExits();
    fireEvent.click((await screen.findAllByText('renovate.edit'))[0]);
    const input = screen.getByRole('textbox');
    const user = userEvent.setup();
    await user.clear(input); await user.type(input, 'Continuous manual typing');
    expect(input).toHaveValue('Continuous manual typing'); expect(input).toHaveFocus();
  });

  it('warns during a pending save, permits explicit exit and ignores its late receipt', async () => {
    const pending = deferred<boolean>();
    mockLoadRenovation.mockResolvedValue(savedDoc());
    mockSaveRenovation.mockReturnValue(pending.promise);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { onClose } = renderWithExits();
    fireEvent.click((await screen.findAllByText('renovate.rollback'))[0]);
    await screen.findByText('renovate.saving');
    attemptExit('close'); expect(onClose).not.toHaveBeenCalled();
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('a save already in progress may still finish'));
    expect(screen.getByText(fullText('Built a data pipeline'))).toBeInTheDocument();
    confirm.mockReturnValue(true); attemptExit('close');
    await act(async () => pending.resolve(true));
    expect(onClose).toHaveBeenCalledTimes(1); expect(screen.queryByText('renovate.saved')).toBeNull();
  });

  it('retains failed-save work on cancelled switch and removes the guard after successful retry', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc()); mockSaveRenovation.mockResolvedValue(false);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { onOpenFull } = renderWithExits();
    fireEvent.click((await screen.findAllByText('renovate.rollback'))[0]);
    await screen.findByTestId('renovation-save-failed');
    attemptExit('full'); expect(onOpenFull).not.toHaveBeenCalled();
    expect(screen.getByText(fullText('Built a data pipeline'))).toBeInTheDocument();
    mockSaveRenovation.mockResolvedValue(true); fireEvent.click(screen.getByText('renovate.retrySave'));
    await screen.findByText('renovate.saved'); attemptExit('full');
    expect(onOpenFull).toHaveBeenCalledTimes(1); expect(confirm).toHaveBeenCalledTimes(1);
  });

  it('clears dirty private work on a real owner change without asking permission to retain it', async () => {
    const pending = deferred<boolean>();
    mockLoadRenovation.mockResolvedValue(savedDoc()); mockSaveRenovation.mockReturnValue(pending.promise);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { onClose, onOpenFull } = renderWithExits();
    fireEvent.click((await screen.findAllByText('renovate.rollback'))[0]);
    fireEvent.click(screen.getAllByText('renovate.edit')[0]);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Private unsaved wording' } });
    await switchRenovationOwner();
    expect(confirm).not.toHaveBeenCalled(); expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('textbox')).toBeNull(); expect(screen.queryByText('Private unsaved wording')).toBeNull();
    attemptExit('Escape'); attemptExit('full'); await act(async () => pending.resolve(false));
    expect(onClose).toHaveBeenCalledTimes(1); expect(onOpenFull).not.toHaveBeenCalled();
    expect(screen.queryByTestId('renovation-save-failed')).toBeNull();
  });

  it('allows a clean close without a prompt and resets the single-exit guard on reopening', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc());
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { props, rerender, onClose } = renderWithExits();
    await screen.findByText('renovate.restored'); attemptExit('close'); attemptExit('Escape');
    expect(onClose).toHaveBeenCalledTimes(1); expect(confirm).not.toHaveBeenCalled();
    rerender(<ResumeRenovationModal {...props} isOpen={false} />);
    rerender(<ResumeRenovationModal {...props} />);
    await screen.findByText('renovate.restored'); attemptExit('close');
    expect(onClose).toHaveBeenCalledTimes(2); expect(confirm).not.toHaveBeenCalled();
  });
});
