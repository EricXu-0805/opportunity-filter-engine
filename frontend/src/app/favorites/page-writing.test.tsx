/* @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import type { ProfileData } from '@/lib/types';
import type { ProfileHydration } from '@/lib/profile-sync';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';
import { captureOwnerToken, enterLocalOnlyMode } from '@/lib/identity-owner';
import { writeLocalStorageJSON } from '@/lib/use-local-storage-json';
import { STORAGE_KEYS } from '@/lib/storage-keys';
const fixture = vi.hoisted(() => ({ state: {} as Record<string, unknown>, accepted: null as ((value: ProfileHydration) => void) | null,
  refresh: { status: 'ready', refresh: vi.fn(), checkForAction: vi.fn() } as unknown as ProfileRefreshState }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key, locale: 'en' }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ back: vi.fn() }) }));
vi.mock('@/lib/custom-imports', () => ({ useCustomImportStorageState: () => ({ status: 'ready', entries: [] }) }));
vi.mock('@/lib/use-profile-refresh', () => ({ useProfileRefresh: (_ready: boolean, accepted: typeof fixture.accepted) => {
  fixture.accepted = accepted; return fixture.refresh;
} }));
vi.mock('./use-favorites-data', () => ({ useFavoritesData: () => fixture.state }));
vi.mock('./use-saved-searches', () => ({ useSavedSearches: () => ({ savedSearches: [], digests: [] }) }));
vi.mock('@/components/StorageStatusBanner', () => ({ default: () => null }));
vi.mock('@/components/SaveFavoritesAnchor', () => ({ default: () => null }));
vi.mock('./FavoritesEmptyState', () => ({ FavoritesEmptyState: () => null }));
vi.mock('./FavoritesHeader', () => ({ FavoritesHeader: () => null }));
vi.mock('./SavedSearchesSection', () => ({ SavedSearchesSection: () => null }));
vi.mock('./SelectionFooter', () => ({ SelectionFooter: () => null }));
vi.mock('./OpportunityCard', () => ({ OpportunityCard: (props: {
  opp: unknown; onOpenEmailModal: (opp: unknown) => void; onOpenTailorModal: (opp: unknown) => void;
}) => <><button onClick={() => props.onOpenEmailModal(props.opp)}>Open email</button><button onClick={() => props.onOpenTailorModal(props.opp)}>Open tailor</button></> }));
interface EditorProps { isOpen: boolean; profile: ProfileData; profileAvailable?: boolean; targetReady?: boolean; profileRefresh?: ProfileRefreshState; onClose: () => void }
function Editor({ kind, ...props }: EditorProps & { kind: string }) {
  const [draft, setDraft] = useState('original');
  if (!props.isOpen) return null;
  return <section aria-label={kind}><input aria-label={`${kind} draft`} value={draft} onChange={e => setDraft(e.target.value)} />
    <span>{props.profile.name}</span><output data-testid={`${kind}-available`}>{String(props.profileAvailable)}</output>
    <output data-testid={`${kind}-target`}>{String(props.targetReady)}</output>
    <output data-testid={`${kind}-check`}>{String(props.profileRefresh?.checkForAction === fixture.refresh.checkForAction)}</output>
    <button onClick={props.onClose}>Close {kind}</button></section>;
}
vi.mock('@/components/CheckedColdEmailModal', () => ({ default: (props: EditorProps) => <Editor kind="email" {...props} /> }));
vi.mock('@/components/CheckedTailorModal', () => ({ default: (props: EditorProps) => <Editor kind="tailor" {...props} /> }));
import FavoritesPage from './page';
const profile = (name = 'Original student'): ProfileData => ({ name, institution: 'UIUC', major: 'CS', college: 'Engineering', grade: 'Sophomore', is_international: false,
  research_interests: 'research', skills: [], resume_text: 'Original source' });
const opportunity = { id: 'opp-1', title: 'Lab', source_type: 'campus_program', record_kind: 'listing',
  target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null } };
beforeEach(() => {
  enterLocalOnlyMode(); writeLocalStorageJSON(STORAGE_KEYS.PROFILE, profile(), captureOwnerToken());
  fixture.accepted = null;
  fixture.state = { serverOpportunities: [opportunity], loading: false, error: false, retry: vi.fn(), unavailableCount: 0,
    identityGeneration: 1, ownerScopeKey: 'local', ownerReady: true, handleRemove: vi.fn() };
});
describe('Favorites writing profile and draft lifetime', () => {
  it.each(['email', 'tailor'])('gives %s the checked journal candidate and keeps manual edits on profile deletion', async kind => {
    const view = render(<FavoritesPage />);
    fireEvent.click(screen.getByRole('button', { name: `Open ${kind}` }));
    fireEvent.change(await screen.findByLabelText(`${kind} draft`), { target: { value: 'Keep my manual draft' } });
    expect(screen.getByTestId(`${kind}-check`)).toHaveTextContent('true');
    act(() => { fixture.accepted?.({ token: captureOwnerToken(), profile: profile('Checked journal candidate'), baseProfile: profile('Cloud base'), revision: 2,
      source: 'cloud', hasPending: true, conflictKeys: [], conflicts: [], quarantineFailed: false } as ProfileHydration); });
    expect(screen.getByText('Checked journal candidate')).toBeVisible();
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE)!).name).toBe('Original student');
    act(() => { writeLocalStorageJSON(STORAGE_KEYS.PROFILE, null, captureOwnerToken()); });
    expect(screen.getByLabelText(`${kind} draft`)).toHaveValue('Keep my manual draft');
    expect(screen.getByTestId(`${kind}-available`)).toHaveTextContent('false');
    fireEvent.click(screen.getByRole('button', { name: `Close ${kind}` }));
    view.rerender(<FavoritesPage />);
    expect(screen.queryByLabelText(`${kind} draft`)).toBeNull();
  });
  it.each(['email', 'tailor'])('keeps %s mounted during shortlist reload and target loss, with target actions paused', async kind => {
    const view = render(<FavoritesPage />);
    fireEvent.click(screen.getByRole('button', { name: `Open ${kind}` }));
    fireEvent.change(await screen.findByLabelText(`${kind} draft`), { target: { value: 'Keep me' } });
    fixture.state = { ...fixture.state, loading: true, serverOpportunities: [] };
    view.rerender(<FavoritesPage />);
    expect(screen.getByLabelText(`${kind} draft`)).toHaveValue('Keep me');
    expect(screen.getByTestId(`${kind}-target`)).toHaveTextContent('false');
    fixture.state = { ...fixture.state, loading: false };
    view.rerender(<FavoritesPage />);
    expect(screen.getByLabelText(`${kind} draft`)).toHaveValue('Keep me');
    expect(screen.getByTestId(`${kind}-target`)).toHaveTextContent('false');
  });
});
