import { createHash, webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ColdEmailResponse, EmailVariant, ExperienceEntry, ExperienceUsage, ProfileData } from '@/lib/types';
import { advanceOwnerEpoch, captureOwnerToken } from '@/lib/identity-owner';

vi.mock('@/i18n/client', () => {
  const t = (key: string) => key;
  return { useT: () => ({ t }) };
});
const api = vi.hoisted(() => ({
  variants: vi.fn(), stream: vi.fn(), generate: vi.fn(), refine: vi.fn(), extract: vi.fn(),
}));
vi.mock('@/lib/api', () => ({
  getEmailVariants: api.variants,
  generateColdEmailStream: api.stream,
  generateColdEmail: api.generate,
  refineEmail: api.refine,
  extractResumeBullets: api.extract,
  getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/supabase', () => ({
  onAuthChange: () => () => {},
  confirmInteractionContact: vi.fn(),
  updateInteractionDetails: vi.fn(),
}));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
import ColdEmailModal from './ColdEmailModal';

const profile: ProfileData = {
  name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'robotics', skills: [], coursework: ['CS 225'],
};
const variant = (id: string): EmailVariant => ({
  id, label: `Template ${id}`, subject: `Subject ${id}`, body: `Draft ${id}`,
  recipient_email: `${id}@example.edu`, mailto_link: '',
});
const aiDraft = (body: string): ColdEmailResponse => ({
  ...variant('ai'), body, method: 'ai',
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
function openModal(initialProfile = profile) {
  const onClose = vi.fn();
  const props = { isOpen: true, onClose, profile: initialProfile, opportunityId: 'A', opportunityTitle: 'Lab' };
  const view = render(<ColdEmailModal {...props} />);
  return {
    ...view, onClose,
    show: (next: Partial<typeof props>) => view.rerender(<ColdEmailModal {...props} {...next} />),
  };
}
async function ready() {
  await screen.findByDisplayValue('Draft A');
  await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(1));
  await act(async () => {});
}
function requestEdit() {
  fireEvent.click(screen.getByRole('button', { name: 'coldEmail.quickActions.formal' }));
}
let ownerSequence = 0;
beforeEach(() => {
  advanceOwnerEpoch(`draft-owner-${++ownerSequence}`);
  api.variants.mockReset().mockImplementation((_profile: ProfileData, id: string) =>
    Promise.resolve({ variants: [variant(id)] }));
  // Automatic fallback leaves the template on screen.
  api.stream.mockReset().mockResolvedValue({ ...variant('fallback'), method: 'template' });
  api.generate.mockReset();
  api.refine.mockReset();
  api.extract.mockReset().mockResolvedValue({ bullets: [] });
  Element.prototype.scrollIntoView = vi.fn();
});

describe('cold email draft lifetime', () => {
  it('serializes refine requests and preserves a manual edit, even after an undo to the original text', async () => {
    const edit = deferred<{ body: string; method: string }>();
    api.refine.mockReturnValue(edit.promise);
    openModal();
    await ready();
    requestEdit();
    requestEdit();
    expect(api.refine).toHaveBeenCalledTimes(1);
    expect(screen.getByText('coldEmail.quickActions.shorter')).toBeDisabled();
    const textarea = screen.getByDisplayValue('Draft A');
    fireEvent.change(textarea, { target: { value: 'My manual draft' } });
    fireEvent.change(textarea, { target: { value: 'Draft A' } });
    await act(async () => { edit.resolve({ body: 'Late AI edit', method: 'llm' }); });
    expect(screen.getByDisplayValue('Draft A')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Late AI edit')).toBeNull();
    expect(screen.getByText('coldEmail.editSuperseded')).toBeInTheDocument();
    expect(screen.getByText('coldEmail.quickActions.shorter')).toBeEnabled();
  });

  it('releases the refine controls after failure and permits a new successful edit', async () => {
    api.refine.mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ body: 'New edit', method: 'llm' });
    openModal();
    await ready();
    requestEdit();
    await screen.findByText('coldEmail.editFailed');
    requestEdit();
    await screen.findByDisplayValue('New edit');
    expect(api.refine).toHaveBeenCalledTimes(2);
  });

  it.each(['target', 'close', 'profile'] as const)('does not apply an old refine after a %s change', async (change) => {
    const first = deferred<{ body: string; method: string }>();
    const second = deferred<{ body: string; method: string }>();
    api.refine.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const view = openModal();
    await ready();
    requestEdit();
    if (change === 'close') view.show({ isOpen: false });
    view.show(change === 'target' ? { opportunityId: 'B' }
      : change === 'profile' ? { profile: { ...profile, name: 'Updated Alex' } } : {});
    const expected = change === 'target' ? 'Draft B' : 'Draft A';
    await screen.findByDisplayValue(expected);
    if (change === 'profile') {
      fireEvent.click(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' }));
      await waitFor(() => expect(screen.queryByText('coldEmail.profileChanged')).toBeNull());
    }
    requestEdit();
    expect(api.refine).toHaveBeenCalledTimes(2);
    await act(async () => { first.resolve({ body: 'Old edit', method: 'llm' }); });
    expect(screen.queryByDisplayValue('Old edit')).toBeNull();
    expect(screen.getByRole('button', { name: 'coldEmail.quickActions.formal' })).toBeDisabled();
    await act(async () => { second.resolve({ body: 'Current edit', method: 'llm' }); });
    expect(screen.getByDisplayValue('Current edit')).toBeInTheDocument();
    expect(screen.queryByText('coldEmail.editing')).toBeNull();
  });

  it('drops an old variants response after a target switch', async () => {
    const first = deferred<{ variants: EmailVariant[] }>();
    api.variants.mockReturnValueOnce(first.promise);
    const view = openModal();
    view.show({ opportunityId: 'B' });
    await screen.findByDisplayValue('Draft B');
    await act(async () => { first.resolve({ variants: [variant('A')] }); });
    expect(screen.getByDisplayValue('Draft B')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Draft A')).toBeNull();
  });

  it('retires the draft on owner movement and never caches that owner’s delayed generation', async () => {
    const old = deferred<ColdEmailResponse>();
    api.stream.mockReturnValueOnce(old.promise);
    const view = openModal();
    await ready();
    act(() => { advanceOwnerEpoch('next-owner'); });
    expect(view.onClose).toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();
    await act(async () => { old.resolve(aiDraft('Private old result')); });
    view.show({ isOpen: false });
    view.show({});
    await screen.findByDisplayValue('Draft A');
    await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(2));
    expect(screen.queryByDisplayValue('Private old result')).toBeNull();
  });

  it('preserves a draft and pending refine on a same-owner observation', async () => {
    const edit = deferred<{ body: string; method: string }>();
    api.refine.mockReturnValue(edit.promise);
    const view = openModal();
    await ready();
    requestEdit();
    act(() => { advanceOwnerEpoch(captureOwnerToken().uid); });
    await act(async () => { edit.resolve({ body: 'Current owner result', method: 'llm' }); });
    expect(screen.getByDisplayValue('Current owner result')).toBeInTheDocument();
    expect(view.onClose).not.toHaveBeenCalled();
  });

  it('never extracts raw resume text and drops a generation completed after close', async () => {
    const pending = deferred<ColdEmailResponse>();
    api.stream.mockReturnValueOnce(pending.promise);
    const view = openModal({ ...profile, resume_text: 'Built a robot.' });
    await ready();
    expect(api.extract).not.toHaveBeenCalled();
    view.show({ isOpen: false });
    await act(async () => { pending.resolve(aiDraft('Retired raw-resume draft')); });
    expect(api.generate).not.toHaveBeenCalled();
    expect(api.variants).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByDisplayValue('Retired raw-resume draft')).toBeNull();
  });

  it('uses the confirmed library immediately without hidden extraction or template enrichment', async () => {
    api.stream.mockResolvedValue(aiDraft('AI grounded draft'));
    const entry = { id: 'robot', revision: 1, status: 'confirmed' as const,
      text: 'Built a robot.', source: { kind: 'manual' as const } };
    openModal({ ...profile, resume_text: 'Built a robot.', experience_entries: [entry] });
    await screen.findByDisplayValue('AI grounded draft');
    expect(api.extract).not.toHaveBeenCalled();
    expect(api.variants).toHaveBeenCalledTimes(1);
    expect(api.variants).toHaveBeenCalledWith(expect.objectContaining({ experience_entries: [entry] }), 'A');
    expect(api.stream).toHaveBeenCalledWith(expect.objectContaining({ experience_entries: [entry] }), 'A',
      { engine: 'ai', style: 'professional' }, expect.any(Function));
  });

  it('a late stream error does not launch a blocking fallback after unmount', async () => {
    const stream = deferred<ColdEmailResponse>();
    api.stream.mockReturnValue(stream.promise);
    const view = openModal();
    await ready();
    view.unmount();
    await act(async () => { stream.reject(new Error('late transport error')); });
    expect(api.generate).not.toHaveBeenCalled();
  });

  it('closes the session immediately when the parent has not yet applied the close request', async () => {
    const edit = deferred<{ body: string; method: string }>();
    api.refine.mockReturnValue(edit.promise);
    const view = openModal();
    await ready();
    requestEdit();
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.closeAria' }));
    expect(view.onClose).toHaveBeenCalledTimes(1);
    await act(async () => { edit.resolve({ body: 'Closed session result', method: 'llm' }); });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByDisplayValue('Closed session result')).toBeNull();
  });

  it('keeps a user-entered recipient when AI generation finishes later', async () => {
    const stream = deferred<ColdEmailResponse>();
    api.stream.mockReturnValue(stream.promise);
    openModal();
    await ready();
    fireEvent.change(screen.getByDisplayValue('A@example.edu'), { target: { value: 'chosen@example.edu' } });
    await act(async () => { stream.resolve(aiDraft('Late AI')); });
    expect(screen.getByDisplayValue('chosen@example.edu')).toBeInTheDocument();
  });

  it.each(['resolve', 'reject'] as const)('drops a clipboard %s after switching targets', async (outcome) => {
    const copy = deferred<void>();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText: vi.fn(() => copy.promise) },
    });
    const view = openModal();
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.copy' }));
    view.show({ opportunityId: 'B' });
    await screen.findByDisplayValue('Draft B');
    await act(async () => {
      if (outcome === 'resolve') copy.resolve();
      else copy.reject(new Error('clipboard denied'));
    });
    expect(screen.queryByText('coldEmail.copied')).toBeNull();
    expect(screen.queryByText('coldEmail.copyFailed')).toBeNull();
    expect(screen.queryByText('coldEmail.sentQuestion')).toBeNull();
  });
});

// M31: variants is the fresh authority for cache compatibility; neither a
// cached draft nor an older worker response can declare itself current.
describe('cold email pipeline cache compatibility', () => {
  it.each([
    { cached: 'pipeline-one', current: 'pipeline-one', reuse: true, label: 'same version' },
    { cached: 'pipeline-one', current: 'pipeline-two', reuse: false, label: 'changed version' },
    { cached: undefined, current: 'pipeline-two', reuse: false, label: 'missing cached version' },
    { cached: 'pipeline-one', current: undefined, reuse: false, label: 'missing current version' },
    { cached: undefined, current: undefined, reuse: false, label: 'both versions missing' },
    { cached: ' ', current: ' ', reuse: false, label: 'blank versions' },
  ])('$label: reuses only a compatible draft after reopening', async ({ cached, current, reuse }) => {
    api.variants
      .mockResolvedValueOnce({ variants: [variant('A')], pipeline_version: cached, corpus_version: 'same-corpus' })
      .mockResolvedValueOnce({ variants: [variant('A')], pipeline_version: current, corpus_version: 'same-corpus' });
    api.stream
      .mockResolvedValueOnce({ ...aiDraft('First AI draft'), pipeline_version: cached, corpus_version: 'same-corpus' })
      .mockResolvedValueOnce({ ...aiDraft('Regenerated AI draft'), pipeline_version: current, corpus_version: 'same-corpus' });
    const view = openModal();
    await screen.findByDisplayValue('First AI draft');
    view.show({ isOpen: false });
    view.show({ isOpen: true });
    await screen.findByDisplayValue(reuse ? 'First AI draft' : 'Regenerated AI draft');
    expect(api.variants).toHaveBeenCalledTimes(2);
    expect(api.stream).toHaveBeenCalledTimes(reuse ? 1 : 2);
    expect(api.generate).not.toHaveBeenCalled();
  });

  it('keeps manual edits when regeneration for a newer pipeline finishes late', async () => {
    const replacement = deferred<ColdEmailResponse>();
    api.variants
      .mockResolvedValueOnce({ variants: [variant('A')], pipeline_version: 'pipeline-one' })
      .mockResolvedValueOnce({ variants: [variant('A')], pipeline_version: 'pipeline-two' });
    api.stream
      .mockResolvedValueOnce({ ...aiDraft('Old pipeline draft'), pipeline_version: 'pipeline-one' })
      .mockReturnValueOnce(replacement.promise);
    const view = openModal();
    await screen.findByDisplayValue('Old pipeline draft');
    view.show({ isOpen: false });
    view.show({ isOpen: true });
    await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByDisplayValue('Draft A'), { target: { value: 'My own rewritten draft' } });
    await act(async () => {
      replacement.resolve({ ...aiDraft('New pipeline response'), pipeline_version: 'pipeline-two' });
    });
    expect(screen.getByDisplayValue('My own rewritten draft')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('New pipeline response')).toBeNull();
  });

  it('does not let an older AI worker response replace the version learned from variants', async () => {
    api.variants.mockResolvedValue({ variants: [variant('A')], pipeline_version: 'pipeline-current' });
    api.stream
      .mockResolvedValueOnce({ ...aiDraft('Old professional draft'), pipeline_version: 'pipeline-old' })
      .mockResolvedValueOnce({ ...aiDraft('Old warm draft'), pipeline_version: 'pipeline-old' })
      .mockResolvedValueOnce({ ...aiDraft('Current professional draft'), pipeline_version: 'pipeline-current' });
    openModal();
    await screen.findByDisplayValue('Old professional draft');
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.tone.warm' }));
    await screen.findByDisplayValue('Old warm draft');
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.tone.professional' }));
    await screen.findByDisplayValue('Current professional draft');
    expect(api.stream).toHaveBeenCalledTimes(3);
  });

  it('waits for target B variants even if the old target A response arrives first', async () => {
    const a = deferred<{ variants: EmailVariant[]; pipeline_version: string }>();
    const b = deferred<{ variants: EmailVariant[]; pipeline_version: string }>();
    api.variants.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    api.stream.mockResolvedValue({ ...aiDraft('Current target B draft'), pipeline_version: 'pipeline-B' });
    const view = openModal();
    await waitFor(() => expect(api.variants).toHaveBeenCalledTimes(1));
    view.show({ opportunityId: 'B' });
    await waitFor(() => expect(api.variants).toHaveBeenCalledTimes(2));
    await act(async () => {
      a.resolve({ variants: [variant('A')], pipeline_version: 'pipeline-A' });
    });
    expect(api.stream).not.toHaveBeenCalled();
    expect(screen.queryByDisplayValue('Draft A')).toBeNull();
    expect(screen.queryByRole('button', { name: 'coldEmail.aiVariantLabel' })).toBeNull();
    await act(async () => {
      b.resolve({ variants: [variant('B')], pipeline_version: 'pipeline-B' });
    });
    await screen.findByDisplayValue('Current target B draft');
    expect(api.stream.mock.calls.map((call) => call[1])).toEqual(['B']);
  });

  it('ignores a late version from another target before reusing the current target cache', async () => {
    const otherTarget = deferred<{ variants: EmailVariant[]; pipeline_version: string }>();
    api.variants
      .mockResolvedValueOnce({ variants: [variant('A')], pipeline_version: 'pipeline-A' })
      .mockReturnValueOnce(otherTarget.promise)
      .mockResolvedValueOnce({ variants: [variant('A')], pipeline_version: 'pipeline-A' });
    api.stream.mockResolvedValue({ ...aiDraft('Cached target A draft'), pipeline_version: 'pipeline-A' });
    const view = openModal();
    await screen.findByDisplayValue('Cached target A draft');
    view.show({ opportunityId: 'B' });
    await waitFor(() => expect(api.variants).toHaveBeenCalledTimes(2));
    expect(api.stream.mock.calls.map((call) => call[1])).toEqual(['A']);
    expect(screen.queryByRole('button', { name: 'coldEmail.aiVariantLabel' })).toBeNull();
    view.show({ opportunityId: 'A' });
    await screen.findByDisplayValue('Cached target A draft');
    await act(async () => {
      otherTarget.resolve({ variants: [variant('B')], pipeline_version: 'pipeline-B' });
    });
    fireEvent.click(screen.getByRole('button', { name: 'coldEmail.tone.professional' }));
    await act(async () => {});
    expect(screen.getByDisplayValue('Cached target A draft')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Draft B')).toBeNull();
    expect(api.stream.mock.calls.map((call) => call[1])).toEqual(['A']);
  });
});


describe('confirmed experience draft inputs', () => {
  beforeEach(() => vi.stubGlobal('crypto', webcrypto));
  afterEach(() => vi.unstubAllGlobals());
  const emptyUsage: ExperienceUsage = {
    version: 1, eligible_count: 0, selected: [], excluded: [], needs_review: false, notices: [],
  };
  const manual = (id: string, status: ExperienceEntry['status'] = 'confirmed'): ExperienceEntry => ({
    id, revision: 1, status, text: `Confirmed material ${id}`, source: { kind: 'manual' },
  });
  const used = (entry: ExperienceEntry): ExperienceUsage => ({
    ...emptyUsage, eligible_count: 1,
    selected: [{ id: entry.id, revision: entry.revision, excerpt: entry.text, source: entry.source }],
  });
  function variantsWith(usage: ExperienceUsage) {
    return { variants: [{ ...variant('A'), experience_usage: usage }], experience_usage: usage,
      pipeline_version: 'confirmed-v1', corpus_version: 'snapshot' };
  }

  it('shows only reported input excerpts, including a selected 13th entry from the source tail', async () => {
    const prefix = '🧪 Earlier paragraph.\n'.repeat(500);
    const quote = 'Built a spectroscopy instrument at the resume tail.';
    const raw = prefix + quote;
    const entries = Array.from({ length: 12 }, (_, index) => manual(`early-${index}`));
    const tail: ExperienceEntry = { id: 'tail', revision: 2, status: 'confirmed', text: quote,
      source: { kind: 'resume', signature: createHash('sha256').update(raw).digest('hex'), quote,
        start: Array.from(prefix).length, end: Array.from(raw).length } };
    entries.push(tail, manual('candidate-material', 'candidate'));
    const usage = { ...used(tail), eligible_count: 13, needs_review: true };
    api.variants.mockResolvedValue(variantsWith(usage));
    openModal({ ...profile, resume_text: raw, experience_entries: entries });
    await ready();
    expect(screen.getByText(quote)).toBeInTheDocument();
    expect(screen.queryByText('Confirmed material early-0')).toBeNull();
    expect(screen.queryByText('Confirmed material candidate-material')).toBeNull();
    expect(screen.getByText('coldEmail.experienceExplanation')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'coldEmail.experienceReviewCta' })).toHaveAttribute('href', '/#experience-library');
    expect(api.stream.mock.calls[0][0].experience_entries).toEqual(entries);
    expect(api.stream.mock.calls[0][0].resume_text).toBe(raw);
    expect(api.stream.mock.calls[0][2]).not.toHaveProperty('resumeBullets');
    expect(api.extract).not.toHaveBeenCalled();
  });

  it.each([
    ['experience_prompt_budget_omission', false],
    ['experience_prompt_budget_omission', true],
    ['experience_template_budget_omission', false],
    ['experience_template_budget_omission', true],
  ] as const)('explains %s with selected material=%s without claiming no confirmed experience', async (notice, selected) => {
    const entry = manual('confirmed-with-budget');
    const usage = { ...(selected ? used(entry) : emptyUsage), eligible_count: 2, notices: [notice] };
    api.variants.mockResolvedValue(variantsWith(usage));
    openModal({ ...profile, experience_entries: [entry] });
    await ready();
    expect(screen.getByText('coldEmail.experienceBudgetNote')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'coldEmail.experienceReviewCta' })).toHaveAttribute('href', '/#experience-library');
    expect(screen.queryByText('coldEmail.experienceNone')).toBeNull();
    expect(screen.queryByText('coldEmail.experienceReviewNeeded')).toBeNull();
    expect(screen.getByRole('button', { name: 'coldEmail.copy' })).toBeEnabled();
    if (selected) expect(screen.getByText(entry.text)).toBeInTheDocument();
  });

  it.each([false, true])('explains a partial local-refine receipt with listed material=%s without implying omitted input', async (selected) => {
    const entry = manual('retained-in-original-draft');
    api.variants.mockResolvedValue(variantsWith(emptyUsage));
    api.refine.mockResolvedValue({ body: 'Refined draft retaining confirmed experience', method: 'local', experience_usage: {
      ...(selected ? used(entry) : emptyUsage), eligible_count: 9, notices: ['experience_usage_receipt_limit'],
    } });
    openModal({ ...profile, experience_entries: [entry] });
    await ready();
    requestEdit();
    await screen.findByDisplayValue('Refined draft retaining confirmed experience');
    expect(screen.getByText('coldEmail.experienceReceiptLimit')).toBeVisible();
    expect(screen.queryByText('coldEmail.experienceNone')).toBeNull();
    expect(screen.queryByText('coldEmail.experienceBudgetNote')).toBeNull();
    expect(screen.queryByText('coldEmail.experienceReviewNeeded')).toBeNull();
    expect(screen.queryByRole('link', { name: 'coldEmail.experienceReviewCta' })).toBeNull();
    if (selected) expect(screen.getByText(entry.text)).toBeInTheDocument();
  });

  it('clears the omission notice and recovery link when another variant fits', async () => {
    const entry = manual('fits');
    api.variants.mockResolvedValue({ variants: [
      { ...variant('A'), experience_usage: { ...emptyUsage, eligible_count: 1, notices: ['experience_template_budget_omission'] } },
      { ...variant('B'), experience_usage: used(entry) },
    ] });
    openModal({ ...profile, experience_entries: [entry] });
    await ready();
    expect(screen.getByText('coldEmail.experienceBudgetNote')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Template B' }));
    expect(screen.queryByText('coldEmail.experienceBudgetNote')).toBeNull();
    expect(screen.queryByRole('link', { name: 'coldEmail.experienceReviewCta' })).toBeNull();
    expect(screen.getByText(entry.text)).toBeInTheDocument();
  });

  it('preserves a whole long excerpt and every actual local-refine input in the receipt', async () => {
    const entries = Array.from({ length: 9 }, (_, index) => manual(`local-${index}`));
    entries[0].text = 'I worked on instrumentation. '.repeat(24) + 'I did not lead the project.';
    api.variants.mockResolvedValue(variantsWith(emptyUsage));
    api.refine.mockResolvedValue({ body: 'Refined current draft', method: 'local', experience_usage: {
      ...emptyUsage, eligible_count: entries.length, selected: entries.flatMap((entry) => used(entry).selected),
    } });
    openModal({ ...profile, experience_entries: entries });
    await ready();
    requestEdit();
    await screen.findByDisplayValue('Refined current draft');
    for (const entry of entries) expect(screen.getByText(entry.text)).toBeInTheDocument();
    expect(screen.getByText(entries[0].text)).toHaveTextContent('I did not lead the project.');
  });

  it('does not block a student with no resume or confirmed experience', async () => {
    api.variants.mockResolvedValue(variantsWith(emptyUsage));
    openModal();
    await ready();
    expect(screen.getByText('coldEmail.experienceNone')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'coldEmail.experienceReviewCta' })).toBeNull();
    expect(screen.getByRole('button', { name: 'coldEmail.copy' })).toBeEnabled();
    expect(api.extract).not.toHaveBeenCalled();
  });

  it.each(['candidate', 'stale', 'rejected', 'withdrawn'] as const)('offers review only when needed for %s experience', async (kind) => {
    api.variants.mockResolvedValue(variantsWith(emptyUsage));
    const entry: ExperienceEntry = kind === 'stale'
      ? { id: 'source', revision: 1, status: 'confirmed', text: 'Source text',
        source: { kind: 'resume', signature: '0'.repeat(64), quote: 'Source text', start: 0, end: 11 } }
      : manual('entry', kind);
    openModal({ ...profile, resume_text: 'Source text', experience_entries: [entry] });
    await ready();
    await act(async () => {});
    if (kind === 'candidate' || kind === 'stale') {
      await screen.findByRole('link', { name: 'coldEmail.experienceReviewCta' });
    } else {
      expect(screen.queryByRole('link', { name: 'coldEmail.experienceReviewCta' })).toBeNull();
    }
    expect(screen.getByRole('button', { name: 'coldEmail.copy' })).toBeEnabled();
  });

  it.each(['revision', 'withdrawal', 'text', 'source', 'resume'] as const)('retires late generation and cache after an in-place %s change', async (change) => {
    const old = deferred<ColdEmailResponse>();
    api.stream.mockReturnValueOnce(old.promise);
    api.variants.mockResolvedValue(variantsWith(emptyUsage));
    const raw = 'Original source';
    const entry: ExperienceEntry = { id: 'evidence', revision: 1, status: 'confirmed', text: raw,
      source: { kind: 'resume', signature: createHash('sha256').update(raw).digest('hex'), quote: raw, start: 0, end: raw.length } };
    const input = { ...profile, resume_text: raw, experience_entries: [entry] };
    const view = openModal(input);
    await ready();
    if (change === 'revision') entry.revision = 2;
    if (change === 'withdrawal') entry.status = 'withdrawn';
    if (change === 'text') entry.text = 'Corrected confirmed material';
    if (change === 'source' && entry.source.kind === 'resume') entry.source.signature = '1'.repeat(64);
    if (change === 'resume') input.resume_text = 'Replaced source';
    view.show({ profile: input });
    expect(api.stream).toHaveBeenCalledTimes(1);
    expect(screen.getByText('coldEmail.profileChanged')).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue('Draft A'), { target: { value: 'My new manual draft' } });
    await act(async () => { old.resolve({ ...aiDraft('Withdrawn late evidence'), pipeline_version: 'confirmed-v1', corpus_version: 'snapshot', experience_usage: used(entry) }); });
    expect(screen.getByDisplayValue('My new manual draft')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Withdrawn late evidence')).toBeNull();
    view.show({ isOpen: false, profile: input });
    view.show({ profile: input });
    await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(2));
    expect(screen.queryByDisplayValue('Withdrawn late evidence')).toBeNull();
  });

  it('retires a refine and its material receipt when the supporting entry is withdrawn', async () => {
    const entry = manual('old');
    const old = deferred<{ body: string; method: string; experience_usage: ExperienceUsage }>();
    api.refine.mockReturnValueOnce(old.promise);
    api.variants.mockResolvedValue(variantsWith(used(entry)));
    const input = { ...profile, experience_entries: [entry] };
    const view = openModal(input);
    await ready();
    requestEdit();
    api.variants.mockResolvedValue(variantsWith(emptyUsage));
    entry.status = 'withdrawn'; entry.revision += 1;
    view.show({ profile: input });
    expect(api.variants).toHaveBeenCalledTimes(1);
    await screen.findByText('coldEmail.experienceUnavailable');
    fireEvent.change(screen.getByDisplayValue('Draft A'), { target: { value: 'Current draft without the entry' } });
    await act(async () => { old.resolve({ body: 'Old refine', method: 'llm', experience_usage: used(entry) }); });
    expect(screen.getByDisplayValue('Current draft without the entry')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Old refine')).toBeNull();
    expect(screen.queryByText(entry.text)).toBeNull();
  });

  it('does not restore old variant evidence after withdrawal while variants are still loading', async () => {
    const entry = manual('withdrawn-variant');
    const old = deferred<ReturnType<typeof variantsWith>>();
    const oldData = variantsWith(used(entry));
    oldData.variants[0].body = 'Old evidence template';
    api.variants.mockReturnValueOnce(old.promise).mockResolvedValueOnce(variantsWith(emptyUsage));
    const input = { ...profile, experience_entries: [entry] };
    const view = openModal(input);
    entry.status = 'withdrawn'; entry.revision += 1;
    view.show({ profile: input });
    await ready();
    fireEvent.change(screen.getByDisplayValue('Draft A'), { target: { value: 'Current manual body' } });
    await act(async () => { old.resolve(oldData); });
    expect(screen.getByDisplayValue('Current manual body')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Old evidence template')).toBeNull();
    expect(screen.queryByText(entry.text)).toBeNull();
    expect(api.stream).toHaveBeenCalledTimes(1);
  });

  it.each(['revision', 'source'] as const)('invalidates an already populated cache after an in-place %s change', async (change) => {
    api.variants.mockResolvedValue(variantsWith(emptyUsage));
    api.stream.mockResolvedValueOnce({ ...aiDraft('Cached old materials'), pipeline_version: 'confirmed-v1', corpus_version: 'snapshot' });
    const raw = 'Original source';
    const entry: ExperienceEntry = { id: 'cached', revision: 1, status: 'confirmed', text: raw,
      source: { kind: 'resume', signature: createHash('sha256').update(raw).digest('hex'), quote: raw, start: 0, end: raw.length } };
    const input = { ...profile, resume_text: raw, experience_entries: [entry] };
    const view = openModal(input);
    await screen.findByDisplayValue('Cached old materials');
    view.show({ isOpen: false, profile: input });
    if (change === 'revision') entry.revision += 1;
    if (change === 'source' && entry.source.kind === 'resume') entry.source.signature = '2'.repeat(64);
    view.show({ profile: input });
    await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(2));
    expect(screen.getByDisplayValue('Draft A')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Cached old materials')).toBeNull();
  });

  it('offers the profile review recovery link when malformed evidence prevents draft loading', async () => {
    api.variants.mockRejectedValueOnce(new Error('Invalid experience evidence'));
    openModal({ ...profile, experience_entries: [{ ...manual('invalid'), revision: 0 }] });
    await screen.findByText('Invalid experience evidence');
    expect(await screen.findByRole('link', { name: 'coldEmail.experienceReviewCta' })).toHaveAttribute('href', '/#experience-library');
    expect(api.stream).not.toHaveBeenCalled();
    expect(api.extract).not.toHaveBeenCalled();
  });

  it('follows the selected variant and later refinement receipt without claiming every entry appears', async () => {
    const one = manual('one'); const two = manual('two');
    api.variants.mockResolvedValue({ variants: [
      { ...variant('A'), experience_usage: used(one) },
      { ...variant('B'), experience_usage: used(two) },
    ], experience_usage: { ...used(one), selected: [...used(one).selected, ...used(two).selected] } });
    api.refine.mockResolvedValue({ body: 'Refined current draft', method: 'llm', experience_usage: emptyUsage });
    openModal({ ...profile, experience_entries: [one, two] });
    await ready();
    expect(screen.getByText(one.text)).toBeInTheDocument();
    expect(screen.queryByText(two.text)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Template B' }));
    expect(screen.getByText(two.text)).toBeInTheDocument();
    expect(screen.queryByText(one.text)).toBeNull();
    requestEdit();
    await screen.findByDisplayValue('Refined current draft');
    expect(screen.getByText('coldEmail.experienceNone')).toBeInTheDocument();
    expect(screen.queryByText(two.text)).toBeNull();
  });
});


describe('profile changes preserve the open email', () => {
  const updated = { ...profile, coursework: ['CS 225', 'CS 374'] };
  const regenerate = () => fireEvent.click(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' }));
  function editDraft() {
    fireEvent.change(screen.getByDisplayValue('Subject A'), { target: { value: 'My subject' } });
    fireEvent.change(screen.getByDisplayValue('Draft A'), { target: { value: 'My body' } });
    fireEvent.change(screen.getByDisplayValue('A@example.edu'), { target: { value: 'verified@example.edu' } });
  }
  function expectDraft() {
    expect(screen.getByDisplayValue('My subject')).toBeInTheDocument();
    expect(screen.getByDisplayValue('My body')).toBeInTheDocument();
    expect(screen.getByDisplayValue('verified@example.edu')).toBeInTheDocument();
  }
  it('keeps all manual fields and the unsent instruction, retires a refine, and waits for explicit regeneration', async () => {
    const old = deferred<{ body: string; method: string }>();
    api.refine.mockReturnValue(old.promise);
    const view = openModal(); await ready(); editDraft(); requestEdit();
    fireEvent.change(screen.getByRole('textbox', { name: 'coldEmail.requestLabel' }), { target: { value: 'My unsent request' } });
    view.show({ profile: updated });
    expectDraft();
    expect(screen.getByDisplayValue('My unsent request')).toBeInTheDocument();
    expect(screen.getByText('coldEmail.profileChanged')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'coldEmail.submitRequest' })).toBeDisabled();
    expect(api.variants).toHaveBeenCalledTimes(1); expect(api.stream).toHaveBeenCalledTimes(1);
    await act(async () => { old.resolve({ body: 'Old profile result', method: 'llm' }); });
    expectDraft(); expect(screen.queryByDisplayValue('Old profile result')).toBeNull();
  });
  it('keeps a deliberately cleared editor empty on profile change', async () => {
    const view = openModal(); await ready();
    for (const value of ['Subject A', 'Draft A', 'A@example.edu']) {
      fireEvent.change(screen.getByDisplayValue(value), { target: { value: '' } });
    }
    view.show({ profile: updated }); await act(async () => {});
    expect(screen.getByTestId('cold-email-editor-fields').querySelector('textarea')).toHaveValue('');
    expect(screen.getByText('coldEmail.profileChanged')).toBeInTheDocument();
    expect(api.variants).toHaveBeenCalledTimes(1);
  });
  it('regenerates only on request, uses the updated profile, and keeps the chosen recipient', async () => {
    const next = deferred<{ variants: EmailVariant[] }>();
    const view = openModal(); await ready(); editDraft(); view.show({ profile: updated });
    api.variants.mockReturnValueOnce(next.promise);
    api.stream.mockResolvedValueOnce(aiDraft('AI from updated profile'));
    regenerate(); expectDraft();
    expect(api.variants).toHaveBeenLastCalledWith(updated, 'A');
    await act(async () => { next.resolve({ variants: [variant('updated')] }); });
    await screen.findByDisplayValue('AI from updated profile');
    expect(api.stream).toHaveBeenLastCalledWith(updated, 'A', { engine: 'ai', style: 'professional' }, expect.any(Function));
    expect(screen.getByDisplayValue('verified@example.edu')).toBeInTheDocument();
    expect(screen.queryByText('coldEmail.profileChanged')).toBeNull();
  });
  it.each(['body', 'subject', 'recipient'] as const)('a later manual %s edit prevents regeneration from replacing any fields', async (field) => {
    const next = deferred<{ variants: EmailVariant[] }>();
    const view = openModal(); await ready(); editDraft(); view.show({ profile: updated });
    api.variants.mockReturnValueOnce(next.promise); regenerate();
    const oldValue = { body: 'My body', subject: 'My subject', recipient: 'verified@example.edu' }[field];
    const input = screen.getByDisplayValue(oldValue);
    fireEvent.change(input, { target: { value: field === 'recipient' ? 'later@example.edu' : 'Later manual change' } });
    fireEvent.change(input, { target: { value: oldValue } }); // Undo still counts as an intervening edit.
    await act(async () => { next.resolve({ variants: [variant('replacement')] }); });
    expectDraft(); expect(screen.getByText('coldEmail.editSuperseded')).toBeInTheDocument();
    expect(screen.getByText('coldEmail.profileChanged')).toBeInTheDocument();
    expect(api.stream).toHaveBeenCalledTimes(1);
  });
  it.each(['failure', 'empty'] as const)('preserves the editor after regeneration %s, then permits retry', async (kind) => {
    const view = openModal(); await ready(); editDraft(); view.show({ profile: updated });
    if (kind === 'failure') api.variants.mockRejectedValueOnce(new Error('offline'));
    else api.variants.mockResolvedValueOnce({ variants: [] });
    regenerate(); await screen.findByText('coldEmail.profileRegenerateFailed'); expectDraft();
    expect(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' })).toBeEnabled();
    regenerate(); await waitFor(() => expect(screen.queryByText('coldEmail.profileChanged')).toBeNull());
    expect(screen.getByDisplayValue('Draft A')).toBeInTheDocument();
  });
  it('keeps the editor with a profile recovery link when the updated name is missing', async () => {
    const view = openModal(); await ready(); editDraft(); view.show({ profile: { ...profile, name: '' } });
    regenerate(); expectDraft();
    expect(screen.getByRole('link', { name: 'coldEmail.nameRequiredCta' })).toBeInTheDocument();
    expect(api.variants).toHaveBeenCalledTimes(1);
  });
  it('retires regeneration when the profile changes again and keeps the unsaved draft', async () => {
    const next = deferred<{ variants: EmailVariant[] }>();
    const view = openModal(); await ready(); editDraft(); view.show({ profile: updated });
    api.variants.mockReturnValueOnce(next.promise); regenerate();
    view.show({ profile: { ...updated, research_interests: 'New interest' } });
    await act(async () => { next.resolve({ variants: [variant('obsolete')] }); });
    expectDraft(); expect(screen.queryByDisplayValue('Draft obsolete')).toBeNull();
    expect(screen.getByRole('button', { name: 'coldEmail.regenerateFromProfile' })).toBeEnabled();
    expect(api.stream).toHaveBeenCalledTimes(1);
  });
});
