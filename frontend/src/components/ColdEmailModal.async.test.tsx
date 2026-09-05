import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ColdEmailResponse, EmailVariant, ProfileData } from '@/lib/types';
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

  it('does not start an old generation or template refetch after extraction finishes for a closed dialog', async () => {
    const extraction = deferred<{ bullets: string[] }>();
    api.extract.mockReturnValue(extraction.promise);
    const view = openModal({ ...profile, resume_text: 'Built a robot.' });
    await waitFor(() => expect(api.extract).toHaveBeenCalledTimes(1));
    view.show({ isOpen: false });
    await act(async () => { extraction.resolve({ bullets: ['Built a robot.'] }); });
    expect(api.stream).not.toHaveBeenCalled();
    expect(api.generate).not.toHaveBeenCalled();
    expect(api.variants).toHaveBeenCalledTimes(1);
  });

  it('keeps a successful AI draft when its slower, enriched templates arrive', async () => {
    const templates = deferred<{ variants: EmailVariant[] }>();
    api.extract.mockResolvedValue({ bullets: ['Built a robot.'] });
    api.variants.mockResolvedValueOnce({ variants: [variant('A')] }).mockReturnValueOnce(templates.promise);
    api.stream.mockResolvedValue(aiDraft('AI grounded draft'));
    openModal({ ...profile, resume_text: 'Built a robot.' });
    await screen.findByDisplayValue('AI grounded draft');
    await act(async () => { templates.resolve({ variants: [variant('enriched')] }); });
    expect(screen.getByDisplayValue('AI grounded draft')).toBeInTheDocument();
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
