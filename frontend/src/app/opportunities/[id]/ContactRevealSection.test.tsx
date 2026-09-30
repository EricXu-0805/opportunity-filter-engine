import { StrictMode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), auth: vi.fn(), subscribe: vi.fn(), modal: vi.fn(),
  owner: { uid: 'user-a' as string | null, epoch: 1, generation: 0 },
  ownerListeners: new Set<() => void>(),
}));
vi.mock('@/lib/api', () => ({
  getOpportunityById: (...args: unknown[]) => mocks.get(...args),
  ApiError: class extends Error { constructor(public status: number, public code: string, message: string, public retryable: boolean) { super(message); } },
}));
vi.mock('@/lib/supabase', () => ({
  getAuthState: (...args: unknown[]) => mocks.auth(...args),
  onAuthChange: (...args: unknown[]) => mocks.subscribe(...args),
}));
vi.mock('@/lib/identity-owner', () => ({
  captureOwnerToken: () => ({ ...mocks.owner }),
  isTokenOwnerStillCurrent: (owner: { uid: string | null; epoch: number }) => owner.uid === mocks.owner.uid && owner.epoch === mocks.owner.epoch,
  onLocalOwnerStateChange: (cb: () => void) => { mocks.ownerListeners.add(cb); return () => { mocks.ownerListeners.delete(cb); }; },
}));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: mocks.modal }) }));

import { ContactRevealSection, CONTACT_AUTH_TIMEOUT_MS } from './ContactRevealSection';
import { ApiError } from '@/lib/api';
import type { Opportunity } from '@/lib/types';
import type { AuthState } from '@/lib/supabase';
import { en, zh } from '@/i18n/dictionaries';

const t = (key: string) => key;
function makeOpp(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'opp-1', title: 'ML Research', organization: 'Test U', opportunity_type: 'research',
    paid: 'unknown', location: 'Campus', on_campus: true, description_clean: '', keywords: [],
    eligibility: { international_friendly: 'yes', preferred_year: [], majors: [], skills_required: [], citizenship_required: false },
    application: { application_effort: '', requires_resume: '', contact_method: 'email' },
    metadata: { is_active: true, confidence_score: 1 }, contact_email_status: 'sign_in_required', ...overrides,
  };
}
const anonState: AuthState = { session: null, user: null, isAnonymous: false, email: null };
function account(id = 'user-a', token = 'tok'): AuthState {
  return { session: { access_token: token } as never, user: { id } as never, isAnonymous: false, email: 'student@example.com' };
}
const revealed = { id: 'opp-1', contact_email: 'prof@example.edu', contact_email_status: 'revealed' };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
let notifyAuth: (state: AuthState) => void;
function mount(opp = makeOpp()) { return render(<ContactRevealSection opp={opp} t={t} />); }
function changeOwner(uid: string | null) {
  mocks.owner.uid = uid; mocks.owner.epoch += 1;
  mocks.ownerListeners.forEach(cb => cb());
}
beforeEach(() => {
  mocks.get.mockReset(); mocks.modal.mockReset(); mocks.auth.mockReset().mockResolvedValue(anonState);
  mocks.subscribe.mockReset().mockImplementation(cb => { notifyAuth = cb; return () => {}; });
  mocks.owner.uid = 'user-a'; mocks.owner.epoch = 1; mocks.owner.generation = 0; mocks.ownerListeners.clear();
});
afterEach(() => { vi.useRealTimers(); });

describe('contact states', () => {
  it('shows auth loading instead of asking a signed-in visitor to sign in', async () => {
    const pending = deferred<AuthState>(); mocks.auth.mockReturnValue(pending.promise); mocks.get.mockReturnValue(new Promise(() => {}));
    mount();
    expect(screen.getByTestId('contact-reveal-loading')).toHaveAttribute('role', 'status');
    expect(screen.queryByTestId('contact-sign-in')).toBeNull();
    await act(async () => pending.resolve(account()));
    expect(screen.getByTestId('contact-reveal-loading')).toBeInTheDocument();
  });
  it('keeps the sign-in CTA for an unauthenticated visitor without fetching', async () => {
    mount();
    expect(await screen.findByTestId('contact-sign-in')).toBeInTheDocument();
    fireEvent.click(screen.getByText('detail.contactSignInCta'));
    expect(mocks.modal).toHaveBeenCalledWith({ reason: 'contact-reveal' });
    expect(mocks.get).not.toHaveBeenCalled();
  });
  it('does not reveal for an anonymous Supabase session', async () => {
    mocks.auth.mockResolvedValue({ ...account(), isAnonymous: true }); mount();
    expect(await screen.findByTestId('contact-sign-in')).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
  });
  it('loads for a signed-in visitor, then reveals the verified address', async () => {
    const pending = deferred<unknown>(); mocks.auth.mockResolvedValue(account()); mocks.get.mockReturnValue(pending.promise);
    mount(); await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('contact-reveal-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('contact-sign-in')).toBeNull();
    expect(mocks.get).toHaveBeenCalledWith('opp-1', { signal: expect.any(AbortSignal) });
    await act(async () => pending.resolve(revealed));
    expect(screen.getByTestId('contact-email-link')).toHaveAttribute('href', 'mailto:prof%40example.edu');
  });
  it('shows an honest error on a failed GET and only retries on request', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(revealed);
    mount(); expect(await screen.findByTestId('contact-reveal-error')).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('contact-sign-in')).toBeNull();
    expect(mocks.get).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('detail.contactRetry'));
    expect(await screen.findByTestId('contact-email-link')).toHaveTextContent('prof@example.edu');
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });
  it.each([403, 404, 429, 500, 503, 504])('does not call HTTP %s an auth error or missing address', async status => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockRejectedValue(new ApiError(status, 'HTTP_ERROR', 'private diagnostics', false)); mount();
    expect(await screen.findByTestId('contact-reveal-error')).toHaveTextContent('detail.contactLoadError');
    expect(screen.queryByTestId('contact-sign-in')).toBeNull();
    expect(screen.queryByTestId('contact-unavailable')).toBeNull();
    expect(screen.queryByText('private diagnostics')).toBeNull();
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });
  it.each(['locked-200', '401'])('renders reauthentication after %s without retrying in a loop', async mode => {
    mocks.auth.mockResolvedValue(account());
    if (mode === '401') mocks.get.mockRejectedValue(new ApiError(401, 'AUTH', 'Sign in', false));
    else mocks.get.mockResolvedValue({ id: 'opp-1', contact_email_status: 'sign_in_required' });
    mount(); expect(await screen.findByTestId('contact-sign-in')).toHaveTextContent('detail.contactSessionRequired');
    fireEvent.click(screen.getByText('detail.contactSignInCta'));
    expect(mocks.modal).toHaveBeenCalledWith({ reason: 'contact-reveal', phase: 'signin' });
    act(() => notifyAuth(account('user-a', 'refreshed')));
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });
  it('lets the same account explicitly check again after refreshing sign-in', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValueOnce({ id: 'opp-1', contact_email_status: 'sign_in_required' }).mockResolvedValue(revealed);
    mount(); expect(await screen.findByTestId('contact-sign-in')).toBeInTheDocument();
    act(() => notifyAuth(account('user-a', 'new-token'))); expect(mocks.get).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('contact-check-again'));
    expect(await screen.findByTestId('contact-email-link')).toHaveTextContent('prof@example.edu'); expect(mocks.get).toHaveBeenCalledTimes(2);
  });
  it('moves a fetched unavailable contact out of the sign-in state', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue({ id: 'opp-1', contact_email_status: 'unavailable' }); mount();
    expect(await screen.findByTestId('contact-unavailable')).toHaveTextContent('detail.contactUnavailable');
    expect(screen.queryByTestId('contact-sign-in')).toBeNull(); expect(screen.queryByTestId('contact-email-link')).toBeNull();
  });
  it('shows initial unavailable without an auth lookup', () => {
    mount(makeOpp({ contact_email_status: 'unavailable' }));
    expect(screen.getByTestId('contact-unavailable')).toBeInTheDocument();
    expect(mocks.auth).not.toHaveBeenCalled(); expect(mocks.get).not.toHaveBeenCalled();
  });
  it('does not use an unbound cached revealed address before rechecking auth', async () => {
    mount(makeOpp({ contact_email_status: 'revealed', contact_email: 'cached@example.edu' }));
    expect(screen.queryByTestId('contact-email-link')).toBeNull();
    expect(await screen.findByTestId('contact-sign-in')).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
  });
  it('revalidates a cached revealed address for the current account', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue(revealed);
    mount(makeOpp({ contact_email_status: 'revealed', contact_email: 'cached@example.edu' }));
    expect(await screen.findByTestId('contact-email-link')).toHaveTextContent('prof@example.edu');
    expect(screen.queryByText('cached@example.edu')).toBeNull();
  });
  it.each([
    null, {}, { ...revealed, id: 'wrong-target' }, { ...revealed, contact_email: '' },
    { ...revealed, contact_email: 'prof@example.edu\nBcc:victim@example.edu' }, { ...revealed, contact_email_status: 'unknown' },
  ])('rejects an invalid response %j', async body => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue(body); mount();
    expect(await screen.findByTestId('contact-reveal-error')).toBeInTheDocument();
    expect(screen.queryByTestId('contact-email-link')).toBeNull();
  });
});

describe('auth and request lifecycle', () => {
  it('lets a live sign-in supersede a slow initial auth snapshot', async () => {
    const pending = deferred<AuthState>(); mocks.auth.mockReturnValue(pending.promise); mocks.get.mockResolvedValue(revealed); mount();
    act(() => notifyAuth(account()));
    expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument();
    await act(async () => pending.resolve(anonState));
    expect(screen.getByTestId('contact-email-link')).toBeInTheDocument(); expect(mocks.get).toHaveBeenCalledTimes(1);
  });
  it('does not let a late initial rejection replace a live signed-in state', async () => {
    const pending = deferred<AuthState>(); mocks.auth.mockReturnValue(pending.promise); mocks.get.mockResolvedValue(revealed); mount();
    act(() => notifyAuth(account())); expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument();
    await act(async () => pending.reject(new Error('old auth failure')));
    expect(screen.getByTestId('contact-email-link')).toBeInTheDocument();
  });
  it('reports an auth read rejection and allows an explicit retry', async () => {
    mocks.auth.mockRejectedValueOnce(new Error('storage failure')).mockResolvedValue(account()); mocks.get.mockResolvedValue(revealed); mount();
    expect(await screen.findByTestId('contact-reveal-error')).toHaveTextContent('detail.contactAuthError');
    expect(mocks.get).not.toHaveBeenCalled(); fireEvent.click(screen.getByText('detail.contactRetry'));
    expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument(); expect(mocks.auth).toHaveBeenCalledTimes(2);
  });
  it('bounds a stalled auth check and ignores its late resolution after retry', async () => {
    vi.useFakeTimers(); const pending = deferred<AuthState>();
    mocks.auth.mockReturnValueOnce(pending.promise).mockResolvedValue(anonState); mount();
    await act(async () => vi.advanceTimersByTime(CONTACT_AUTH_TIMEOUT_MS));
    expect(screen.getByTestId('contact-reveal-error')).toHaveTextContent('detail.contactAuthError');
    fireEvent.click(screen.getByText('detail.contactRetry')); await act(async () => {});
    expect(screen.getByTestId('contact-sign-in')).toBeInTheDocument();
    await act(async () => pending.resolve(account())); expect(screen.getByTestId('contact-sign-in')).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
  });
  it('clears a revealed email on sign-out', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue(revealed); mount();
    expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument();
    act(() => notifyAuth(anonState));
    expect(screen.queryByTestId('contact-email-link')).toBeNull(); expect(screen.getByTestId('contact-sign-in')).toBeInTheDocument();
  });
  it('aborts an in-flight reveal on logout and ignores its late success', async () => {
    const pending = deferred<unknown>(); mocks.auth.mockResolvedValue(account()); mocks.get.mockReturnValue(pending.promise); mount();
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1)); const signal = mocks.get.mock.calls[0][1].signal;
    act(() => notifyAuth(anonState)); expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(revealed));
    expect(screen.queryByTestId('contact-email-link')).toBeNull(); expect(screen.getByTestId('contact-sign-in')).toBeInTheDocument();
  });
  it('ignores previous account responses after account switching', async () => {
    const old = deferred<unknown>(); mocks.auth.mockResolvedValue(account()); mocks.get.mockReturnValueOnce(old.promise).mockResolvedValue({ ...revealed, contact_email: 'new@example.edu' }); mount();
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    act(() => notifyAuth(account('user-b')));
    expect(await screen.findByTestId('contact-email-link')).toHaveTextContent('new@example.edu');
    await act(async () => old.resolve(revealed)); expect(screen.getByTestId('contact-email-link')).toHaveTextContent('new@example.edu');
  });
  it('clears results at the shared owner fence before the auth callback arrives', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue(revealed); mount();
    expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument();
    mocks.auth.mockReturnValue(new Promise(() => {}));
    act(() => changeOwner('user-b'));
    expect(screen.queryByTestId('contact-email-link')).toBeNull(); expect(screen.getByTestId('contact-reveal-loading')).toBeInTheDocument();
  });
  it('does not accept an old account response after a same-uid sign-out/sign-in round trip', async () => {
    const old = deferred<unknown>(); mocks.auth.mockResolvedValue(account()); mocks.get.mockReturnValueOnce(old.promise).mockResolvedValue({ id: 'opp-1', contact_email_status: 'unavailable' }); mount();
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    act(() => { changeOwner(null); changeOwner('user-a'); });
    expect(await screen.findByTestId('contact-unavailable')).toBeInTheDocument();
    await act(async () => old.resolve(revealed)); expect(screen.queryByTestId('contact-email-link')).toBeNull();
  });
  it('clears a revealed result when the persisted owner generation changes', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue(revealed); mount();
    expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument();
    mocks.auth.mockReturnValue(new Promise(() => {}));
    act(() => { mocks.owner.generation += 1; window.dispatchEvent(new Event('storage')); });
    expect(screen.queryByTestId('contact-email-link')).toBeNull(); expect(screen.getByTestId('contact-reveal-loading')).toBeInTheDocument();
  });
  it('keeps one request across a same-account token refresh', async () => {
    const pending = deferred<unknown>(); mocks.auth.mockResolvedValue(account()); mocks.get.mockReturnValue(pending.promise); mount();
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1)); act(() => notifyAuth(account('user-a', 'new-token')));
    expect(mocks.get.mock.calls[0][1].signal.aborted).toBe(false);
    await act(async () => pending.resolve(revealed)); expect(screen.getByTestId('contact-email-link')).toBeInTheDocument(); expect(mocks.get).toHaveBeenCalledTimes(1);
  });
  it.each(['resolve', 'reject'] as const)('ignores a previous target %s and starts the new target without waiting', async outcome => {
    const old = deferred<unknown>(); mocks.auth.mockResolvedValue(account()); mocks.get.mockReturnValueOnce(old.promise).mockResolvedValue({ ...revealed, id: 'opp-2', contact_email: 'second@example.edu' });
    const view = mount(); await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1)); const signal = mocks.get.mock.calls[0][1].signal;
    view.rerender(<ContactRevealSection opp={makeOpp({ id: 'opp-2' })} t={t} />);
    expect(screen.queryByTestId('contact-email-link')).toBeNull(); expect(signal.aborted).toBe(true);
    expect(await screen.findByTestId('contact-email-link')).toHaveTextContent('second@example.edu');
    await act(async () => outcome === 'resolve' ? old.resolve(revealed) : old.reject(new Error('old failure')));
    expect(screen.getByTestId('contact-email-link')).toHaveTextContent('second@example.edu');
  });
  it('aborts on unmount and does not retain the old in-flight guard after StrictMode replay', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue(revealed);
    const view = render(<StrictMode><ContactRevealSection opp={makeOpp()} t={t} /></StrictMode>);
    expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument();
    const signal = mocks.get.mock.calls.at(-1)![1].signal; expect(signal.aborted).toBe(false);
    view.unmount(); expect(signal.aborted).toBe(true);
  });
});

describe('availability and copy', () => {
  it.each(['sign_in_required', 'revealed'] as const)('suppresses a known faculty contact prohibition even when status is %s', status => {
    const { container } = mount(makeOpp({ source_type: 'faculty_research', faculty_availability_status: 'not_accepting_undergraduates', contact_email_status: status, contact_email: 'prof@example.edu' }));
    expect(container).toBeEmptyDOMElement(); expect(mocks.auth).not.toHaveBeenCalled(); expect(mocks.get).not.toHaveBeenCalled();
  });
  it('does not turn research inactivity into a contact prohibition', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue({ ...revealed, source_type: 'faculty_research', faculty_availability_status: 'research_inactive' });
    mount(makeOpp({ source_type: 'faculty_research', faculty_availability_status: 'research_inactive' }));
    expect(await screen.findByTestId('contact-email-link')).toBeInTheDocument();
  });
  it('hides a late-revealed email when the refreshed faculty record now prohibits contact', async () => {
    mocks.auth.mockResolvedValue(account()); mocks.get.mockResolvedValue({ ...revealed, source_type: 'faculty_research', faculty_availability_status: 'not_accepting_undergraduates' }); const view = mount();
    await waitFor(() => expect(view.container).toBeEmptyDOMElement()); expect(screen.queryByTestId('contact-email-link')).toBeNull();
  });
  it('hides and aborts if the same target becomes blocked while fetching', async () => {
    const pending = deferred<unknown>(); mocks.auth.mockResolvedValue(account()); mocks.get.mockReturnValue(pending.promise); const view = mount();
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    view.rerender(<ContactRevealSection opp={makeOpp({ source_type: 'faculty_research', faculty_availability_status: 'not_accepting_undergraduates' })} t={t} />);
    expect(mocks.get.mock.calls[0][1].signal.aborted).toBe(true); await act(async () => pending.resolve(revealed)); expect(view.container).toBeEmptyDOMElement();
  });
  it('renders nothing for old payloads without a status flag', () => {
    const { container } = mount(makeOpp({ contact_email_status: undefined })); expect(container).toBeEmptyDOMElement(); expect(mocks.auth).not.toHaveBeenCalled();
  });
  it('uses recipient-neutral contact copy and defines concise recovery copy in both languages', () => {
    expect(en.detail.contactSignInPrompt.toLowerCase()).not.toContain('faculty'); expect(zh.detail.contactSignInPrompt).not.toMatch(/教授|教师/);
    expect(en.detail.contactVerifyHint.toLowerCase()).not.toContain('faculty'); expect(zh.detail.contactVerifyHint).not.toMatch(/教授|教师/);
    expect(en.detail.contactRetry).toBe('Retry'); expect(zh.detail.contactRetry).toBe('重试');
    for (const dictionary of [en, zh]) for (const key of ['contactLoading', 'contactLoadError', 'contactAuthError', 'contactUnavailable', 'contactSessionRequired'] as const) expect(dictionary.detail[key].length).toBeGreaterThan(2);
  });
});
