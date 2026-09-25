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
import { createHash, webcrypto } from 'node:crypto';
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

import ActualResumeRenovationModal from './ResumeRenovationModal';

// Normal callers supply the complete public target. Explicit undefined in
// malformed/legacy tests still reaches production unchanged.
function ResumeRenovationModal(props: React.ComponentProps<typeof ActualResumeRenovationModal>) {
  return <ActualResumeRenovationModal targetKey={JSON.stringify({ ...targetA, id: props.opportunityId })} {...props} />;
}
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from '@/lib/identity-owner';
import type { Opportunity, ProfileData, RenovationDoc } from '@/lib/types';

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
    target_sig: targetFixtureSignature(targetA),
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
      expect(screen.getByTestId('renovation-source-review')).toBeInTheDocument(),
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
    expect(screen.queryByTestId('renovation-source-review')).toBeNull();
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
    expect(await screen.findByTestId('renovation-source-review')).toBeInTheDocument();
    fireEvent.click(screen.getAllByText('renovate.rollback')[0]);
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledTimes(1));
    expect(mockSaveRenovation.mock.calls[0][1].resume_sig).toBe('original-source');
    expect(screen.getByTestId('renovation-source-review')).toBeInTheDocument();
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
  expect(screen.queryByTestId('renovation-source-review')).toBeNull();
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
      expect(screen.getByTestId('renovation-action-error')).toHaveTextContent('Your profile changed');
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
    expect(screen.queryByTestId('renovation-source-review')).toBeNull();
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
    expect(screen.getByTestId('renovation-source-review')).toBeInTheDocument();
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


describe('legacy registered browser close request', () => {
  it('uses the same current inline-edit guard and clears registration when unmounted', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc());
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const onClose = vi.fn();
    let request: (() => boolean) | null = null;
    const register = vi.fn((next: (() => boolean) | null) => { request = next; });
    const view = render(<ResumeRenovationModal isOpen onClose={onClose} profile={makeProfile()}
      opportunityId="opp-1" opportunityTitle="Lab" onCloseRequestChange={register} />);
    fireEvent.click((await screen.findAllByText('renovate.edit'))[0]);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Exact private edit' } });
    expect(request).not.toBeNull();
    act(() => expect(request!()).toBe(false));
    expect(onClose).not.toHaveBeenCalled(); expect(screen.getByRole('textbox')).toHaveValue('Exact private edit');
    confirm.mockReturnValue(true);
    act(() => expect(request!()).toBe(true));
    expect(onClose).toHaveBeenCalledOnce();
    act(() => expect(request!()).toBe(true)); expect(onClose).toHaveBeenCalledOnce();
    view.unmount(); expect(request).toBeNull();
  });
});


describe('bullet editor cloud refresh', () => {
  it('keeps the unsaved edit and ignores old optimization after checking returns unchanged', async () => {
    const pending = deferred<{ text: string; changed: boolean; source_evidence: string }>();
    mockLoadRenovation.mockResolvedValue(savedDoc()); mockOptimizeBullet.mockReturnValue(pending.promise);
    const p = makeProfile(); const view = renderModal(p);
    fireEvent.click((await screen.findAllByText('renovate.reoptimize'))[0]);
    editFirstBullet('Retain my unsubmitted bullet');
    const refresh = vi.fn().mockResolvedValue(true);
    const show = (status: 'checking' | 'ready') => view.rerender(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={p} opportunityId="opp-1" opportunityTitle="Prof. Doe's Lab" profileRefresh={{ status, refresh }} />);
    show('checking');
    expect(screen.getByRole('textbox')).toHaveValue('Retain my unsubmitted bullet');
    expect(screen.getAllByText('renovate.reoptimize')[0].closest('button')).toBeDisabled();
    show('ready');
    await act(async () => { pending.resolve({ text: 'Late optimization', changed: true, source_evidence: '' }); });
    expect(screen.getByRole('textbox')).toHaveValue('Retain my unsubmitted bullet');
    expect(screen.queryByText(fullText('Late optimization'))).toBeNull(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
});


it('keeps the bullet draft after profile removal and rejects late optimization even after restoration', async () => {
  const pending = deferred<{ text: string; changed: boolean; source_evidence: string }>();
  mockLoadRenovation.mockResolvedValue(savedDoc()); mockOptimizeBullet.mockReturnValue(pending.promise);
  const p = makeProfile(); const view = renderModal(p);
  fireEvent.click((await screen.findAllByText('renovate.reoptimize'))[0]);
  editFirstBullet('Keep my bullet after removal');
  const show = (profileAvailable: boolean) => view.rerender(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={p} opportunityId="opp-1" opportunityTitle="Prof. Doe's Lab" profileAvailable={profileAvailable} />);
  show(false);
  expect(screen.getByTestId('profile-refresh-status')).toHaveTextContent('Your profile is no longer available.');
  expect(screen.getByRole('textbox')).toHaveValue('Keep my bullet after removal');
  expect(screen.getAllByText('renovate.reoptimize')[0].closest('button')).toBeDisabled();
  show(true);
  await act(async () => { pending.resolve({ text: 'Late removal optimization', changed: true, source_evidence: '' }); });
  expect(screen.getByRole('textbox')).toHaveValue('Keep my bullet after removal');
  expect(screen.queryByText(fullText('Late removal optimization'))).toBeNull(); expect(mockSaveRenovation).not.toHaveBeenCalled();
});

describe('legacy renovation per-action profile checks', () => {
  it.each(['start', 'optimize'] as const)('does not issue %s requests while the latest-profile check is unresolved', async (entry) => {
    const profile = makeProfile(), check = deferred<import('@/lib/use-profile-refresh').ProfileActionReceipt | null>();
    const checkForAction = vi.fn(() => check.promise), refresh = vi.fn().mockResolvedValue(true);
    if (entry === 'optimize') mockLoadRenovation.mockResolvedValue(savedDoc());
    mockStructureResume.mockResolvedValue(structuredResume); mockRenovateResume.mockResolvedValue(makeDoc());
    mockOptimizeBullet.mockResolvedValue({ text: 'Checked wording', changed: true, source_evidence: '' });
    render(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-1" opportunityTitle="Lab" profileRefresh={{ status: 'ready', refresh, checkForAction }} />);
    fireEvent.click(entry === 'start' ? await screen.findByText('renovate.start') : (await screen.findAllByText('renovate.reoptimize'))[0]);
    // Either the read boundary or the model boundary must have started. This
    // does not infer successful gating merely from waiting a fixed duration.
    await waitFor(() => expect(checkForAction.mock.calls.length + mockStructureResume.mock.calls.length + mockOptimizeBullet.mock.calls.length).toBeGreaterThan(0));
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockOptimizeBullet).not.toHaveBeenCalled();
    expect(mockRenovateResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
    expect(checkForAction).toHaveBeenCalledTimes(1);
    await act(async () => { check.resolve(null); });
  });
});


describe('checked legacy renovation intents', () => {
  const receipt = (profile: ProfileData): import('@/lib/use-profile-refresh').ProfileActionReceipt => ({
    checkId: 1, owner: captureOwnerToken(), revision: 2, source: 'cloud', profile: structuredClone(profile),
  });
  function harness(profile = makeProfile(), stored = false) {
    if (stored) mockLoadRenovation.mockResolvedValue(savedDoc());
    const check = deferred<import('@/lib/use-profile-refresh').ProfileActionReceipt | null>();
    const checkForAction = vi.fn(() => check.promise), refresh = vi.fn().mockResolvedValue(true);
    const show = (p: ProfileData, extra: Partial<React.ComponentProps<typeof ResumeRenovationModal>> = {}) =>
      <ResumeRenovationModal isOpen onClose={vi.fn()} profile={p} opportunityId="opp-1" opportunityTitle="Lab"
        profileRefresh={{ status: 'ready', refresh, checkForAction }} {...extra} />;
    const view = render(show(profile));
    return { ...view, check, checkForAction, show };
  }
  it('uses the checked full source only after the matching profile and target are committed', async () => {
    mockStructureResume.mockResolvedValue(structuredResume); mockRenovateResume.mockResolvedValue(makeDoc());
    const old = makeProfile(), fresh = makeProfile({ resume_text: 'Complete new source including its final paragraph', coursework: ['New confirmed course'] });
    const view = harness(old);
    fireEvent.click(await screen.findByText('renovate.start'));
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    await act(async () => view.check.resolve(receipt(fresh)));
    expect(mockStructureResume).not.toHaveBeenCalled();
    view.rerender(view.show(fresh, { targetChecking: true, targetReady: false }));
    expect(mockStructureResume).not.toHaveBeenCalled();
    view.rerender(view.show(fresh));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledOnce());
    expect(mockStructureResume).toHaveBeenCalledExactlyOnceWith(fresh.resume_text, { locale: 'en' });
    expect(mockRenovateResume).toHaveBeenCalledExactlyOnceWith(fresh, 'opp-1', structuredResume.sections, { locale: 'en' });
  });
  it('rejects a queued bullet operation when checking discovers new source, preserving unsaved text', async () => {
    const old = makeProfile(), fresh = makeProfile({ resume_text: 'New full source', coursework: ['Updated course'] });
    const view = harness(old, true);
    await screen.findByText('renovate.copyAll'); editFirstBullet('Keep my unsaved first bullet');
    fireEvent.click(screen.getByText('renovate.reoptimize'));
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    view.rerender(view.show(fresh));
    await act(async () => view.check.resolve(receipt(fresh)));
    await screen.findByTestId('renovation-source-review');
    expect(screen.getByRole('textbox')).toHaveValue('Keep my unsaved first bullet');
    expect(screen.getByText('Led a robotics club project')).toBeInTheDocument();
    expect(mockOptimizeBullet).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
  it('does not revive a bullet intent if the profile changes away and back during its check', async () => {
    const old = makeProfile(), view = harness(old, true);
    fireEvent.click((await screen.findAllByText('renovate.reoptimize'))[0]);
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    view.rerender(view.show(makeProfile({ coursework: ['Temporary new source'] })));
    view.rerender(view.show(old));
    await act(async () => view.check.resolve(receipt(old)));
    await screen.findByTestId('renovation-source-review');
    expect(mockOptimizeBullet).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
  it.each(['typing', 'target update', 'owner switch', 'close'] as const)('retires a pending check after %s without model calls', async (change) => {
    const profile = makeProfile(), view = harness(profile, true);
    await screen.findByText('renovate.copyAll'); editFirstBullet('Original inline draft');
    fireEvent.click(screen.getByText('renovate.reoptimize'));
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    const checked = receipt(profile);
    if (change === 'typing') fireEvent.change(screen.getByRole('textbox'), { target: { value: 'New inline draft during read' } });
    else if (change === 'target update') view.rerender(view.show(profile, { targetKey: JSON.stringify(targetB) }));
    else if (change === 'owner switch') await switchRenovationOwner();
    else view.rerender(view.show(profile, { isOpen: false }));
    await act(async () => view.check.resolve(checked));
    expect(mockOptimizeBullet).not.toHaveBeenCalled(); expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
    if (change === 'typing' || change === 'target update') expect(screen.getByRole('textbox')).toHaveValue(change === 'typing' ? 'New inline draft during read' : 'Original inline draft');
    else expect(screen.queryByRole('textbox')).toBeNull();
  });
  it('keeps an inline draft when the check fails, then checks again before explicit regeneration', async () => {
    mockStructureResume.mockResolvedValue(structuredResume); mockRenovateResume.mockResolvedValue(makeDoc());
    const profile = makeProfile(), view = harness(profile, true);
    await screen.findByText('renovate.copyAll'); editFirstBullet('Keep on unavailable check');
    fireEvent.click(screen.getByText('renovate.rerun'));
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    await act(async () => view.check.resolve(null));
    expect(await screen.findByTestId('renovation-action-error')).toHaveTextContent('Could not check your profile');
    expect(screen.getByRole('textbox')).toHaveValue('Keep on unavailable check');
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
    view.checkForAction.mockResolvedValue(receipt(profile));
    fireEvent.click(screen.getByText('renovate.rerun'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledOnce());
    expect(view.checkForAction).toHaveBeenCalledTimes(2);
  });
  it('does not land an already-dispatched optimization after a new unsaved keystroke', async () => {
    const pending = deferred<{ text: string; changed: boolean; source_evidence: string }>();
    mockOptimizeBullet.mockReturnValue(pending.promise);
    const profile = makeProfile(), view = harness(profile, true);
    await screen.findByText('renovate.copyAll'); editFirstBullet('Unsaved answer before check');
    fireEvent.click(screen.getByText('renovate.reoptimize'));
    await waitFor(() => expect(view.checkForAction).toHaveBeenCalledOnce());
    await act(async () => view.check.resolve(receipt(profile)));
    await waitFor(() => expect(mockOptimizeBullet).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unsaved answer after dispatch' } });
    await act(async () => pending.resolve({ text: 'Late optimized second bullet', changed: true, source_evidence: '' }));
    expect(screen.getByRole('textbox')).toHaveValue('Unsaved answer after dispatch');
    expect(screen.queryByText(fullText('Late optimized second bullet'))).toBeNull(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
});


describe('legacy doc provenance before an explicit bullet request', () => {
  it.each(['profile', 'same-ID target'] as const)('requires rebuilding after %s has already changed before clicking optimize', async (changed) => {
    mockLoadRenovation.mockResolvedValue(savedDoc());
    mockOptimizeBullet.mockResolvedValue({ text: 'Wrong new-source optimization', changed: true, source_evidence: '' });
    const old = makeProfile(), fresh = changed === 'profile' ? makeProfile({ resume_text: 'An entirely new resume' }) : old;
    const refresh = vi.fn().mockResolvedValue(true);
    const checkForAction = vi.fn().mockImplementation(async () => ({ checkId: 1, owner: captureOwnerToken(), revision: 2, source: 'cloud', profile: fresh }));
    const show = (p: ProfileData, targetKey: string) => <ResumeRenovationModal isOpen onClose={vi.fn()} profile={p} opportunityId="opp-1" opportunityTitle="Lab" targetKey={targetKey} profileRefresh={{ status: 'ready', refresh, checkForAction }} />;
    const view = render(show(old, JSON.stringify(targetA)));
    await screen.findByText('renovate.copyAll'); editFirstBullet('Keep old-source manual input');
    view.rerender(show(fresh, changed === 'same-ID target' ? JSON.stringify(targetB) : JSON.stringify(targetA)));
    const optimize = screen.getByRole('button', { name: 'renovate.reoptimizeAria' });
    // Provenance changed before this click, so no read or model operation may
    // give this old document a new source. An explicit whole rebuild is needed.
    expect(optimize).toBeDisabled();
    fireEvent.click(optimize);
    expect(screen.getByRole('textbox')).toHaveValue('Keep old-source manual input');
    expect(checkForAction).not.toHaveBeenCalled(); expect(mockOptimizeBullet).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
});


it('retains stale target provenance after a failed rebuild, clearing it only after a successful explicit rebuild', async () => {
  mockLoadRenovation.mockResolvedValue(savedDoc());
  mockStructureResume.mockRejectedValueOnce(new Error('Controlled generation failure')).mockResolvedValue(structuredResume);
  mockRenovateResume.mockResolvedValue(makeDoc());
  const profile = makeProfile(), refresh = vi.fn().mockResolvedValue(true);
  const checkForAction = vi.fn().mockImplementation(async () => ({ checkId: 1, owner: captureOwnerToken(), revision: 2, source: 'cloud', profile }));
  const show = (targetKey: string) => <ResumeRenovationModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-1" opportunityTitle="Lab" targetKey={targetKey} profileRefresh={{ status: 'ready', refresh, checkForAction }} />;
  const view = render(show(JSON.stringify(targetA)));
  await screen.findByText('renovate.copyAll'); editFirstBullet('Keep my prior target edit');
  view.rerender(show(JSON.stringify(targetB)));
  expect(screen.getByRole('button', { name: 'renovate.reoptimizeAria' })).toBeDisabled();
  fireEvent.click(screen.getByText('renovate.rerun'));
  await screen.findByRole('alert');
  expect(screen.getByRole('textbox')).toHaveValue('Keep my prior target edit');
  expect(screen.getByRole('button', { name: 'renovate.reoptimizeAria' })).toBeDisabled();
  expect(screen.getByTestId('renovation-source-review')).toBeInTheDocument();
  expect(mockSaveRenovation).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('renovate.rerun'));
  await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledOnce());
  expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeEnabled();
  expect(screen.queryByTestId('renovation-source-review')).toBeNull();
});


describe('concise legacy source notices', () => {
  it('shows one stale-source notice when changed profile, raw resume, unknown provenance and stopped intent overlap', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc(makeDoc({ resume_sig: 'old-raw-signature' })));
    const old = makeProfile(), fresh = makeProfile({ resume_text: 'Updated raw source' });
    const view = renderModal(old);
    await screen.findByText('renovate.copyAll'); editFirstBullet('Keep my manual input');
    view.rerender(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={fresh} opportunityId="opp-1" opportunityTitle="Updated target" />);
    expect(screen.getByTestId('renovation-source-review')).toHaveTextContent('Profile or target changed. Your draft and edits are kept. Re-renovate before optimizing bullets.');
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.queryByTestId('renovation-action-error')).toBeNull();
    expect(screen.queryByTestId('renovation-profile-unknown')).toBeNull();
    expect(screen.queryByText('renovate.staleResume')).toBeNull();
    expect(screen.queryByText('renovate.profileChanged')).toBeNull();
    expect(screen.getByRole('textbox')).toHaveValue('Keep my manual input');
    expect(screen.getByRole('button', { name: 'renovate.reoptimizeAria' })).toBeDisabled();
  });
  it('leaves read failure and Retry with the shared banner, adding only the stale rebuild requirement', async () => {
    mockLoadRenovation.mockResolvedValue(savedDoc(makeDoc({ resume_sig: 'old-raw-signature' })));
    const p = makeProfile(), check = deferred<import('@/lib/use-profile-refresh').ProfileActionReceipt | null>();
    const checkForAction = vi.fn(() => check.promise), refresh = vi.fn().mockResolvedValue(true);
    const show = (status: 'ready' | 'failed') => <ResumeRenovationModal isOpen onClose={vi.fn()} profile={p} opportunityId="opp-1" opportunityTitle="Lab" profileRefresh={{ status, checkForAction, refresh }} />;
    const view = render(show('ready'));
    await screen.findByText('renovate.copyAll'); editFirstBullet('Keep through failed read');
    fireEvent.click(screen.getByText('renovate.rerun'));
    await waitFor(() => expect(checkForAction).toHaveBeenCalledOnce());
    view.rerender(show('failed'));
    await act(async () => check.resolve(null));
    expect(screen.getByTestId('profile-refresh-status')).toHaveTextContent('Could not check for profile updates. Your draft is kept.');
    expect(screen.getByTestId('renovation-source-review')).toHaveTextContent(/^Re-renovate before optimizing bullets\.$/);
    expect(screen.queryByTestId('renovation-action-error')).toBeNull();
    expect(screen.queryByTestId('renovation-profile-unknown')).toBeNull();
    expect(screen.getByRole('textbox')).toHaveValue('Keep through failed read');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refresh).toHaveBeenCalledOnce();
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
});


// Full public target fixtures intentionally share id/title; provenance must
// include nested requirements and other public material, not a display label.
const targetA = {
  id: 'opp-1', title: "Prof. Doe's Lab", organization: 'UIUC', opportunity_type: 'research',
  paid: 'unknown', location: 'Urbana', on_campus: true, description_clean: 'Research vision systems', keywords: ['vision'],
  eligibility: { international_friendly: 'yes', preferred_year: ['Sophomore', 'Junior'], majors: ['CS'], skills_required: ['Python'], citizenship_required: null },
  application: { application_effort: 'low', requires_resume: 'yes', contact_method: 'email' },
  metadata: { is_active: true, confidence_score: 0.9 },
} satisfies Opportunity;
const targetB = { ...targetA, eligibility: { ...targetA.eligibility, preferred_year: ['Junior', 'Senior'] } };
function canonicalTargetFixture(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalTargetFixture).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonicalTargetFixture(item)}`).join(',')}}`;
  return JSON.stringify(value);
}
const targetFixtureSignature = (target: unknown) => `v1:sha256:${createHash('sha256').update(canonicalTargetFixture(target)).digest('hex')}`;

describe('persisted full target provenance', () => {
  it('keeps a nested target change stale after closing and reopening the saved draft', async () => {
    const stored = Object.assign(makeDoc(), { target_sig: targetFixtureSignature(targetA) });
    mockLoadRenovation.mockResolvedValue(savedDoc(stored));
    const profile = makeProfile();
    const show = (isOpen: boolean, target: typeof targetA) => <ResumeRenovationModal isOpen={isOpen} onClose={vi.fn()} profile={profile} opportunityId="opp-1" opportunityTitle={targetA.title} targetKey={JSON.stringify(target)} />;
    const view = render(show(true, targetA));
    await screen.findByText('renovate.copyAll');
    view.rerender(show(true, targetB));
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    view.rerender(show(false, targetB));
    view.rerender(show(true, targetB));
    await screen.findByText('renovate.copyAll');
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    editFirstBullet('Keep editing the old target draft');
    expect(screen.getByRole('textbox')).toHaveValue('Keep editing the old target draft');
    expect(screen.getByRole('button', { name: 'renovate.copyAll' })).toBeEnabled();
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockOptimizeBullet).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
  it.each([undefined, 'not-a-target-digest'])('keeps an unbound older draft (%s) editable but requires explicit regeneration before optimization', async (target_sig) => {
    mockLoadRenovation.mockResolvedValue(savedDoc(makeDoc({ target_sig })));
    mockStructureResume.mockResolvedValue(structuredResume); mockRenovateResume.mockResolvedValue(makeDoc());
    render(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-1" opportunityTitle={targetA.title} targetKey={JSON.stringify(targetA)} />);
    await screen.findByText('renovate.copyAll');
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    expect(screen.getByTestId('renovation-source-review')).toHaveTextContent('saved target is unknown');
    editFirstBullet('Keep this unsaved answer until regeneration succeeds');
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('renovate.rerun'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledOnce());
    expect(mockSaveRenovation.mock.calls[0][1].target_sig).toBe(targetFixtureSignature(targetA));
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeEnabled();
  });
});

describe('full target digest boundaries', () => {
  it('accepts key-order-only changes and retains the target digest on a manual save', async () => {
    const reordered = Object.fromEntries(Object.entries({ ...targetA, eligibility: Object.fromEntries(Object.entries(targetA.eligibility).reverse()) }).reverse());
    mockLoadRenovation.mockResolvedValue(savedDoc());
    render(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-1" opportunityTitle={targetA.title} targetKey={JSON.stringify(reordered)} />);
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeEnabled());
    editFirstBullet('My manual wording'); fireEvent.click(screen.getByText('renovate.save'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledOnce());
    expect(mockSaveRenovation.mock.calls[0][1].target_sig).toBe(targetFixtureSignature(targetA));
    expect(mockSaveRenovation.mock.calls[0][1].sections[0].bullets[0].base_text).toBe('Built a data pipeline');
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockRenovateResume).not.toHaveBeenCalled();
  });
  it('does not rebind a stale saved target when the user saves or copies manual wording', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    mockLoadRenovation.mockResolvedValue(savedDoc());
    render(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-1" opportunityTitle={targetA.title} targetKey={JSON.stringify(targetB)} />);
    await screen.findByText('renovate.copyAll'); editFirstBullet('Keep this old-target manual version');
    fireEvent.click(screen.getByText('renovate.save'));
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledOnce());
    expect(mockSaveRenovation.mock.calls[0][1].target_sig).toBe(targetFixtureSignature(targetA));
    fireEvent.click(screen.getByText('renovate.copyAll'));
    await waitFor(() => expect(writeText).toHaveBeenCalledOnce());
    expect(writeText.mock.calls[0][0]).toContain('Keep this old-target manual version');
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    expect(mockOptimizeBullet).not.toHaveBeenCalled();
  });
  it.each([undefined, 'opaque-display-key', '[]', JSON.stringify({ ...targetA, id: 'different-opportunity' })])('keeps the draft but blocks derivation for invalid full target input %s', async (targetKey) => {
    mockLoadRenovation.mockResolvedValue(savedDoc());
    render(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-1" opportunityTitle={targetA.title} targetKey={targetKey} />);
    await screen.findByText('renovate.copyAll');
    expect(screen.getByText('renovate.rerun').closest('button')).toBeDisabled();
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    expect(screen.getByTestId('renovation-source-review')).toHaveTextContent('Could not verify the opportunity information');
    editFirstBullet('Still editable without a valid target');
    expect(screen.getByRole('textbox')).toHaveValue('Still editable without a valid target');
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockOptimizeBullet).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
  it('does not create provenance when SHA-256 is unavailable', async () => {
    vi.stubGlobal('crypto', { subtle: { digest: vi.fn().mockRejectedValue(new Error('crypto unavailable')) } });
    mockLoadRenovation.mockResolvedValue(savedDoc()); renderModal();
    await screen.findByText('renovate.copyAll');
    await waitFor(() => expect(screen.getByText('renovate.rerun').closest('button')).toBeDisabled());
    expect(screen.getByTestId('renovation-source-review')).toHaveTextContent('Could not verify the opportunity information');
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
  it.each(['target update', 'owner switch'] as const)('retires an intent waiting for target SHA after %s', async (change) => {
    const pending = deferred<ArrayBuffer>();
    const targetInput = canonicalTargetFixture(targetA);
    const originalDigest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(targetInput));
    const digest = vi.fn((algorithm: AlgorithmIdentifier, input: BufferSource) => {
      if (new TextDecoder().decode(input) === targetInput) return pending.promise;
      return webcrypto.subtle.digest(algorithm, input);
    });
    vi.stubGlobal('crypto', { subtle: { digest } });
    mockStructureResume.mockResolvedValue(structuredResume); mockRenovateResume.mockResolvedValue(makeDoc());
    const profile = makeProfile();
    const show = (target: typeof targetA) => <ResumeRenovationModal isOpen onClose={vi.fn()} profile={profile} opportunityId="opp-1" opportunityTitle={targetA.title} targetKey={JSON.stringify(target)} />;
    const view = render(show(targetA));
    fireEvent.click(await screen.findByText('renovate.start'));
    await screen.findByTestId('renovation-action-check');
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
    if (change === 'target update') view.rerender(show(targetB));
    else await switchRenovationOwner();
    await act(async () => { pending.resolve(originalDigest); });
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockRenovateResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
    if (change === 'target update') {
      fireEvent.click(screen.getByText('renovate.start'));
      await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledOnce());
      expect(mockSaveRenovation.mock.calls[0][1].target_sig).toBe(targetFixtureSignature(targetB));
    }
  });
});


describe('complete target input structure', () => {
  it.each([
    { id: 'opp-1' },
    { id: 'opp-1', title: targetA.title },
    { ...targetA, description_clean: 123 },
    { ...targetA, eligibility: { ...targetA.eligibility, preferred_year: [2] } },
    { ...targetA, application: { application_effort: 'low' } },
    { ...targetA, metadata: { confidence_score: 'high' } },
  ])('refuses incomplete or malformed target material %#', async (target) => {
    mockLoadRenovation.mockResolvedValue(savedDoc());
    render(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-1" opportunityTitle={targetA.title} targetKey={JSON.stringify(target)} />);
    await screen.findByText('renovate.copyAll');
    expect(screen.getByText('renovate.rerun').closest('button')).toBeDisabled();
    expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeDisabled();
    expect(screen.getByTestId('renovation-source-review')).toHaveTextContent('Could not verify the opportunity information');
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockOptimizeBullet).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
});

describe('public target projection compatibility', () => {
  // public_projection.py removes metadata.is_active; matches.py additionally
  // drops metadata and the detail-only eligibility/application fields.
  const publicDetail = { ...targetA, metadata: { confidence_score: 0.75, manually_reviewed: true } };
  const { metadata: detailMetadata, ...cardFields } = publicDetail;
  void detailMetadata;
  const publicCard = {
    ...cardFields,
    eligibility: { international_friendly: 'yes', skills_required: ['Python'] },
    application: { requires_resume: 'yes', contact_method: 'email' },
  };
  it.each([['detail', publicDetail], ['results card', publicCard]] as const)('generates and reopens a bound draft from the actual public %s shape', async (_surface, target) => {
    mockStructureResume.mockResolvedValue(structuredResume); mockRenovateResume.mockResolvedValue(makeDoc());
    const profile = makeProfile();
    const show = (isOpen: boolean) => <ResumeRenovationModal isOpen={isOpen} onClose={vi.fn()} profile={profile} opportunityId="opp-1" opportunityTitle={target.title} targetKey={JSON.stringify(target)} />;
    const view = render(show(true));
    const start = await screen.findByText('renovate.start');
    expect(start.closest('button')).toBeEnabled();
    fireEvent.click(start);
    await waitFor(() => expect(mockSaveRenovation).toHaveBeenCalledOnce());
    const saved = mockSaveRenovation.mock.calls[0][1] as RenovationDoc;
    expect(saved.target_sig).toBe(targetFixtureSignature(target));
    mockLoadRenovation.mockResolvedValue(savedDoc(saved));
    view.rerender(show(false)); view.rerender(show(true));
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'renovate.reoptimizeAria' })[0]).toBeEnabled());
    expect(mockStructureResume).toHaveBeenCalledOnce();
  });
  it.each([
    { ...publicDetail, metadata: { ...publicDetail.metadata, is_active: 'true' } },
    { ...publicCard, eligibility: { ...publicCard.eligibility, preferred_year: 'senior' } },
    { ...publicCard, application: { ...publicCard.application, application_effort: false } },
    { ...publicCard, metadata: [] },
  ])('still refuses a projected field with a malformed supplied value %#', async (target) => {
    render(<ResumeRenovationModal isOpen onClose={vi.fn()} profile={makeProfile()} opportunityId="opp-1" opportunityTitle={target.title} targetKey={JSON.stringify(target)} />);
    expect((await screen.findByText('renovate.start')).closest('button')).toBeDisabled();
    expect(mockStructureResume).not.toHaveBeenCalled(); expect(mockSaveRenovation).not.toHaveBeenCalled();
  });
});
