import { render, screen, waitFor } from '@testing-library/react';
import { fireEvent } from '@testing-library/dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConciergeRequestSection } from './ConciergeRequestSection';
import { advanceOwnerEpoch, isLocalOwnerReady, OwnerMismatchError, syncLocalIdentityOwner } from '@/lib/identity-owner';

const mocks = vi.hoisted(() => ({
  getAuthState: vi.fn(),
  loadConciergeRequests: vi.fn(),
  requestConciergeApply: vi.fn(),
}));

vi.mock('@/lib/supabase', () => mocks);
vi.mock('@/lib/analytics', () => ({ track: vi.fn() }));

const t = (path: string) => path;
const OPP = 'faculty-ece-47919b71';

function signedIn(email: string | null) {
  mocks.getAuthState.mockResolvedValue({
    session: {}, user: {}, isAnonymous: !email, email,
  });
}

// The component now binds each write to the account that clicked and paints
// only if that account is still current. identity-owner is real here (only
// @/lib/supabase is mocked), so claim an owner the way the app does.
const OWNER_UID = '11111111-1111-4111-8111-111111111111';
async function claimOwner(): Promise<void> {
  advanceOwnerEpoch(OWNER_UID);
  await syncLocalIdentityOwner(OWNER_UID);
  for (let i = 0; i < 200 && !isLocalOwnerReady(OWNER_UID); i += 1) {
    await new Promise((r) => setTimeout(r, 0));
  }
  expect(isLocalOwnerReady(OWNER_UID)).toBe(true);
}

beforeEach(async () => {
  vi.clearAllMocks();
  signedIn('student@illinois.edu');
  mocks.loadConciergeRequests.mockResolvedValue(new Set<string>());
  mocks.requestConciergeApply.mockResolvedValue(true);
  await claimOwner();
});

describe('ConciergeRequestSection', () => {
  it('asks about THIS opportunity, not about the product in general', async () => {
    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);

    fireEvent.click(await screen.findByTestId('concierge-request-submit'));

    await waitFor(() => {
      expect(mocks.requestConciergeApply).toHaveBeenCalledWith(OPP, 'student@illinois.edu', {}, expect.anything());
    });
  });

  it('shows the already-asked state instead of inviting a second request', async () => {
    mocks.loadConciergeRequests.mockResolvedValue(new Set([OPP]));

    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);

    expect(await screen.findByTestId('concierge-requested')).toBeInTheDocument();
    expect(screen.queryByTestId('concierge-request-submit')).not.toBeInTheDocument();
  });

  it('a request for a DIFFERENT opportunity does not answer for this one', async () => {
    mocks.loadConciergeRequests.mockResolvedValue(new Set(['faculty-cs-other']));

    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);

    expect(await screen.findByTestId('concierge-request-submit')).toBeInTheDocument();
    expect(screen.queryByTestId('concierge-requested')).not.toBeInTheDocument();
  });

  it('renders nothing while it does not yet know whether they already asked', async () => {
    // A read that failed returns null, which is not "you have not asked". The
    // worse outcome of guessing is drawing a fresh button under a request that
    // already exists, so the section stays absent instead.
    mocks.loadConciergeRequests.mockResolvedValue(null);

    const { container } = render(<ConciergeRequestSection opportunityId={OPP} t={t} />);

    await waitFor(() => expect(mocks.loadConciergeRequests).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('a write that did not land is never shown as a recorded request', async () => {
    // The one outcome worse than the button: the student believes they asked,
    // stops asking, and nobody ever sees it.
    mocks.requestConciergeApply.mockResolvedValue(false);

    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);
    fireEvent.click(await screen.findByTestId('concierge-request-submit'));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'detail.concierge.failed',
    );
    expect(screen.queryByTestId('concierge-requested')).not.toBeInTheDocument();
    expect(screen.getByTestId('concierge-request-submit')).toBeInTheDocument();
  });

  it('asks an anonymous student where to reach them', async () => {
    signedIn(null);

    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);

    const field = await screen.findByLabelText('detail.concierge.emailPlaceholder');
    fireEvent.change(field, { target: { value: 'anon@illinois.edu' } });
    fireEvent.click(screen.getByTestId('concierge-request-submit'));

    await waitFor(() => {
      expect(mocks.requestConciergeApply).toHaveBeenCalledWith(OPP, 'anon@illinois.edu', {}, expect.anything());
    });
  });
});


describe('ConciergeRequestSection — a result that arrives after an owner switch', () => {
  it('does not show U1\'s "requested" state on U2\'s screen', async () => {
    // Before: the submit awaited requestConciergeApply with no owner check and
    // then set requested=true — so a request U1 made landed as "already asked"
    // on whoever was signed in when the write resolved.
    let resolveWrite: (v: boolean) => void = () => {};
    mocks.requestConciergeApply.mockImplementationOnce(() => new Promise<boolean>((r) => { resolveWrite = r; }));
    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);
    fireEvent.click(await screen.findByTestId('concierge-request-submit'));
    await waitFor(() => expect(mocks.requestConciergeApply).toHaveBeenCalled());

    // The browser becomes U2 while U1's write is still in flight.
    const U2 = '22222222-2222-4222-8222-222222222222';
    advanceOwnerEpoch(U2);
    await syncLocalIdentityOwner(U2);
    for (let i = 0; i < 200 && !isLocalOwnerReady(U2); i += 1) await new Promise((r) => setTimeout(r, 0));

    resolveWrite(true);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('concierge-requested')).toBeNull();
    // The busy flag is not U1's data: U2 must be able to ask.
    expect(screen.getByTestId('concierge-request-submit')).not.toBeDisabled();
  });

  it('a refusal for the SAME account is shown as a failed request', async () => {
    mocks.requestConciergeApply.mockRejectedValueOnce(new OwnerMismatchError());
    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);
    fireEvent.click(await screen.findByTestId('concierge-request-submit'));

    expect(await screen.findByRole('alert')).toHaveTextContent('detail.concierge.failed');
    expect(screen.queryByTestId('concierge-requested')).not.toBeInTheDocument();
    expect(screen.getByTestId('concierge-request-submit')).not.toBeDisabled();
  });

  it('mounted after the owner was established, a live switch reloads whether they already asked', async () => {
    mocks.loadConciergeRequests.mockResolvedValue(new Set([OPP]));
    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);
    expect(await screen.findByTestId('concierge-requested')).toBeInTheDocument();
    expect(mocks.loadConciergeRequests).toHaveBeenCalledTimes(1);

    mocks.loadConciergeRequests.mockResolvedValue(new Set<string>());
    const U2 = '22222222-2222-4222-8222-222222222222';
    advanceOwnerEpoch(U2);
    await syncLocalIdentityOwner(U2);
    for (let i = 0; i < 200 && !isLocalOwnerReady(U2); i += 1) await new Promise((r) => setTimeout(r, 0));

    await waitFor(() => expect(mocks.loadConciergeRequests).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByTestId('concierge-requested')).toBeNull());
  });
});
