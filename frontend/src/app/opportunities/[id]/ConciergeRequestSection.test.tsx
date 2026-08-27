import { render, screen, waitFor } from '@testing-library/react';
import { fireEvent } from '@testing-library/dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConciergeRequestSection } from './ConciergeRequestSection';

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

beforeEach(() => {
  vi.clearAllMocks();
  signedIn('student@illinois.edu');
  mocks.loadConciergeRequests.mockResolvedValue(new Set<string>());
  mocks.requestConciergeApply.mockResolvedValue(true);
});

describe('ConciergeRequestSection', () => {
  it('asks about THIS opportunity, not about the product in general', async () => {
    render(<ConciergeRequestSection opportunityId={OPP} t={t} />);

    fireEvent.click(await screen.findByTestId('concierge-request-submit'));

    await waitFor(() => {
      expect(mocks.requestConciergeApply).toHaveBeenCalledWith(
        OPP, 'student@illinois.edu',
      );
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
      expect(mocks.requestConciergeApply).toHaveBeenCalledWith(
        OPP, 'anon@illinois.edu',
      );
    });
  });
});
