import { useLayoutEffect, useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MatchResult, ProfileData } from '@/lib/types';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';

vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));
vi.mock('@/lib/api', () => ({ getGapAnalysis: vi.fn(), getResponsivenessSignals: vi.fn().mockResolvedValue({}) }));
interface EditorProps { onClose: () => void; onCloseRequestChange?: (request: (() => boolean) | null) => void; onOpenLegacy?: () => void; onOpenFull?: () => void }
function Editor({ label, onClose, onCloseRequestChange, onOpenLegacy, onOpenFull }: EditorProps & { label: string }) {
  const [text, setText] = useState('');
  const [confirming, setConfirming] = useState(false);
  useLayoutEffect(() => {
    onCloseRequestChange?.(() => {
      if (text) { setConfirming(true); return false; }
      onClose(); return true;
    });
    return () => onCloseRequestChange?.(null);
  }, [text, onClose, onCloseRequestChange]);
  return <div role="dialog" aria-label={label}>
    <input aria-label={`${label} edit`} value={text} onChange={(event) => setText(event.target.value)} />
    {confirming && <><button onClick={() => setConfirming(false)}>Keep edit</button><button onClick={onClose}>Discard edit</button></>}
    {onOpenLegacy && <button onClick={onOpenLegacy}>Use legacy editor</button>}
    {onOpenFull && <button onClick={onOpenFull}>Use full editor</button>}
  </div>;
}
vi.mock('./FullTargetResumeModal', () => ({ default: (props: EditorProps) => <Editor label="Full" {...props} /> }));
vi.mock('./ResumeRenovationModal', () => ({ default: (props: EditorProps) => <Editor label="Legacy" {...props} /> }));
vi.mock('./TailorModal', () => ({ default: ({ isOpen }: { isOpen: boolean }) => isOpen ? <div role="dialog" aria-label="Tailor" /> : null }));
import MatchCard from './MatchCard';

const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior', is_international: false, research_interests: '', skills: [] };
const match: MatchResult = {
  opportunity_id: 'opp', eligibility_score: 0.9, readiness_score: 0.8, upside_score: 0.7, final_score: 85,
  bucket: 'high_priority', reasons_fit: [], reasons_gap: [], next_steps: [], opportunity: {
    id: 'opp', title: 'Research', organization: 'UIUC', source_type: 'campus_program', opportunity_type: 'Research',
    paid: 'yes', location: 'Urbana', on_campus: true, description_clean: 'A research project.', keywords: [],
    target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null },
    eligibility: { international_friendly: 'yes', preferred_year: [], majors: [], skills_required: [], citizenship_required: false },
    application: { application_effort: 'medium', requires_resume: 'yes', contact_method: 'email' }, metadata: { is_active: true, confidence_score: 0.9 },
  },
};
const state = { __NA: true, nextTree: ['results'], filter: 'kept' };
function backEvent() {
  window.history.replaceState(state, '', '/results?q=robots');
  window.dispatchEvent(new PopStateEvent('popstate', { state }));
}
beforeEach(async () => {
  window.history.replaceState(state, '', '/results?q=robots');
  advanceOwnerEpoch('card-owner'); await syncLocalIdentityOwner('card-owner');
});
function card() { return render(<MatchCard match={match} profile={profile} onDraftEmail={vi.fn()} ownerReady ownerScopeKey="card-owner" />); }

describe('MatchCard real workspace close registration', () => {
  it('routes Back through the full editor, keeps refused edits, then releases one marker on discard', async () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    card(); fireEvent.click(screen.getByText('card.renovateResume'));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Full edit' }), { target: { value: 'Exact unsaved answers' } });
    const marker = window.history.state.__ofeResultsModal;
    act(backEvent);
    expect(screen.getByRole('textbox', { name: 'Full edit' })).toHaveValue('Exact unsaved answers');
    expect(window.history.state.__ofeResultsModal).toBe(marker);
    fireEvent.click(screen.getByText('Keep edit')); act(backEvent);
    fireEvent.click(screen.getByText('Discard edit'));
    expect(screen.queryByRole('dialog', { name: 'Full' })).toBeNull(); expect(back).toHaveBeenCalledOnce();
    expect(window.location.search).toBe('?q=robots');
  });
  it('replaces the registration when switching to legacy and does not apply a stale editor guard to Tailor', async () => {
    vi.spyOn(window.history, 'back').mockImplementation(() => {});
    card(); fireEvent.click(screen.getByText('card.renovateResume'));
    fireEvent.click(await screen.findByText('Use legacy editor'));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Legacy edit' }), { target: { value: 'Legacy unsaved' } });
    act(backEvent);
    expect(screen.getByRole('textbox', { name: 'Legacy edit' })).toHaveValue('Legacy unsaved');
    fireEvent.click(screen.getByText('Discard edit'));
    fireEvent.click(screen.getByText('card.tailorResume')); await screen.findByRole('dialog', { name: 'Tailor' });
    act(backEvent); expect(screen.queryByRole('dialog', { name: 'Tailor' })).toBeNull();
    expect(screen.queryByText('Keep edit')).toBeNull();
  });
});
