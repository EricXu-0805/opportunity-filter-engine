import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Opportunity, ProfileData, TailorResponse } from '@/lib/types';
import type { ProfileActionReceipt, ProfileRefreshState } from '@/lib/use-profile-refresh';
import { advanceOwnerEpoch, captureOwnerToken, readUserScopedEntry, syncLocalIdentityOwner } from '@/lib/identity-owner';

vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }) }; });
const api = vi.hoisted(() => ({ tailor: vi.fn(), extract: vi.fn(), status: vi.fn() }));
vi.mock('@/lib/api', () => ({ tailorResume: api.tailor, extractResumeBullets: api.extract, getTailorStatus: api.status }));
import TailorModal from './TailorModal';
const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'robots', skills: [], resume_text: 'Full saved résumé source' };
const response: TailorResponse = { opportunity_id: 'target-one', target_version: `wt1:${'a'.repeat(64)}`, pipeline_version: 'w13.3', generated_at: '2026-09-25T12:00:00+00:00', method: 'ai', warnings: [], tailored_bullets: [{ text: 'Original model suggestion', source_evidence: 'supplied evidence', source_index: 0 }] };
function publicTarget(id = 'target-one'): Opportunity {
  return { id, title: 'Target one', organization: 'UIUC', source_type: 'manual', record_kind: 'listing',
    writing_target_version: `wt1:${'a'.repeat(64)}`, opportunity_type: 'research', paid: 'unknown', location: 'Urbana', on_campus: true,
    description_clean: 'Student research', keywords: ['research'],
    eligibility: { preferred_year: [], majors: [], skills_required: [], international_friendly: 'unknown', citizenship_required: null },
    application: { application_effort: 'unknown', requires_resume: 'yes', contact_method: 'email' },
    metadata: { is_active: true, confidence_score: 1 },
    target_truth: { listing_state: 'open', accepting_state: 'accepting', actionable: true, reference_only: false,
      reason_code: null, verified_at: null, expires_at: null } };
}
const base = { target: publicTarget(), isOpen: true, onClose: vi.fn(), profile, opportunityId: 'target-one', opportunityTitle: 'Target one', ownerReady: true, ownerScopeKey: 'tailor-owner' };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function receipt(next: ProfileData | null = profile): ProfileActionReceipt {
  return { checkId: 1, owner: captureOwnerToken(), revision: 2, source: next ? 'cloud' : 'cloud-absent', profile: next };
}
async function drain() { await act(async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); }); }
function refresh(check: ProfileRefreshState['checkForAction'], status: ProfileRefreshState['status'] = 'ready'): ProfileRefreshState {
  return { status, refresh: vi.fn(async () => true), checkForAction: check };
}
function savedRaw(key: string): string | null {
  const entry = readUserScopedEntry(key);
  return entry.status === 'present' ? entry.value : localStorage.getItem(key);
}
const textarea = () => screen.getByPlaceholderText('tailor.bulletsPlaceholder');
const generate = () => screen.getByRole('button', { name: /^tailor\.(generate|regenerate)$/ });
function type(text = 'My unchanged manual bullet') { fireEvent.change(textarea(), { target: { value: text } }); }
beforeEach(async () => { vi.resetAllMocks(); localStorage.clear(); advanceOwnerEpoch(null); advanceOwnerEpoch('tailor-owner'); await syncLocalIdentityOwner('tailor-owner');
  api.status.mockResolvedValue({ ai_available: true, pipeline_version: 'w13.3' }); api.tailor.mockResolvedValue(response); api.extract.mockResolvedValue({ method: 'ai', bullets: ['New extracted source'], pipeline_version: 'w13.3', generated_at: '2026-09-25T12:00:00+00:00' }); });
afterEach(() => cleanup());

describe('Tailor profile preflight', () => {
  it('waits for fresh profile and target validation, then requires explicit review of retained manual input', async () => {
    const read = deferred<ProfileActionReceipt | null>(); const check = vi.fn(() => read.promise); const props = { ...base, profileRefresh: refresh(check) };
    const view = render(<TailorModal {...props} />); type(); fireEvent.click(generate()); await drain();
    expect(check).toHaveBeenCalledOnce(); expect(api.tailor).not.toHaveBeenCalled();
    const fresh = { ...profile, coursework: ['New course'], resume_text: '• New source must not replace my manual input' };
    read.resolve(receipt(fresh)); await drain(); expect(api.tailor).not.toHaveBeenCalled();
    view.rerender(<TailorModal {...props} profile={fresh} targetChecking targetReady={false} />); await drain(); expect(api.tailor).not.toHaveBeenCalled();
    expect(textarea()).toHaveValue('My unchanged manual bullet');
    view.rerender(<TailorModal {...props} profile={fresh} />); await drain();
    expect(api.tailor).not.toHaveBeenCalled();
    expect(textarea()).toHaveValue('My unchanged manual bullet');
    fireEvent.click(screen.getByRole('button', { name: 'tailor.reviewDraft' })); await drain();
    fireEvent.click(generate()); await drain();
    expect(check).toHaveBeenCalledTimes(3); // initial action, explicit review, then generation
    expect(api.tailor).toHaveBeenCalledExactlyOnceWith(fresh, 'target-one', ['My unchanged manual bullet'], { locale: 'en', expectedPipelineVersion: 'w13.3', expectedTargetVersion: `wt1:${'a'.repeat(64)}` });
  });
  it('extracts the latest complete résumé only after its receipt is rendered', async () => {
    const read = deferred<ProfileActionReceipt | null>(); const check = vi.fn(() => read.promise); const props = { ...base, profileRefresh: refresh(check) };
    const view = render(<TailorModal {...props} />); type(); fireEvent.click(screen.getByRole('button', { name: 'tailor.extractFromResume' })); await drain();
    expect(api.extract).not.toHaveBeenCalled(); const fresh = { ...profile, resume_text: '完整尾页🚀'.repeat(1000) };
    read.resolve(receipt(fresh)); await drain(); expect(api.extract).not.toHaveBeenCalled();
    view.rerender(<TailorModal {...props} profile={fresh} />); await drain(); expect(api.extract).toHaveBeenCalledExactlyOnceWith(fresh.resume_text, { expectedPipelineVersion: 'w13.3' });
  });
  it.each(['null', 'rejected', 'deleted'] as const)('keeps manual text on %s read and allows a fresh retry', async (kind) => {
    const read = deferred<ProfileActionReceipt | null>(); const check = vi.fn().mockImplementationOnce(() => read.promise).mockResolvedValue(receipt());
    render(<TailorModal {...base} profileRefresh={refresh(check)} />); type(); fireEvent.click(generate()); await drain();
    if (kind === 'rejected') read.reject(new Error('PRIVATE cloud text')); else read.resolve(kind === 'deleted' ? receipt(null) : null);
    await drain(); expect(api.tailor).not.toHaveBeenCalled(); expect(textarea()).toHaveValue('My unchanged manual bullet');
    expect(screen.getByText(/This action did not run/)).toBeTruthy(); expect(screen.queryByText('PRIVATE cloud text')).toBeNull();
    fireEvent.click(generate()); await drain(); expect(check).toHaveBeenCalledTimes(2); expect(api.tailor).toHaveBeenCalledOnce();
  });
  it('deduplicates double clicks and cancels the queued intent when the user edits', async () => {
    const read = deferred<ProfileActionReceipt | null>(); const check = vi.fn(() => read.promise);
    render(<TailorModal {...base} profileRefresh={refresh(check)} />); type(); fireEvent.click(generate()); fireEvent.click(generate()); await drain();
    expect(check).toHaveBeenCalledOnce(); type('New user text'); read.resolve(receipt()); await drain();
    expect(api.tailor).not.toHaveBeenCalled(); expect(textarea()).toHaveValue('New user text');
  });
  it('preserves the right-side inline edit buffer when a same-owner source changes', async () => {
    const check = vi.fn(async () => receipt()); const props = { ...base, profileRefresh: refresh(check) };
    const view = render(<TailorModal {...props} />); type(); fireEvent.click(generate()); await waitFor(() => expect(screen.getByText('tailor.methodAi')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'tailor.editBulletAria' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'tailor.editBulletAria' }), { target: { value: 'My unsaved right-side edit' } });
    view.rerender(<TailorModal {...props} profile={{ ...profile, major: 'Biology' }} />); await drain();
    expect(screen.getByRole('textbox', { name: 'tailor.editBulletAria' })).toHaveValue('My unsaved right-side edit'); expect(textarea()).toHaveValue('My unchanged manual bullet');
  });
  it.each(['profile', 'target'] as const)('keeps the editor but refuses source operations when %s is unavailable', async (kind) => {
    const check = vi.fn(async () => receipt()); const props = { ...base, profileRefresh: refresh(check) }; const view = render(<TailorModal {...props} />); type();
    view.rerender(<TailorModal {...props} {...(kind === 'profile' ? { profileAvailable: false } : { targetReady: false })} />);
    fireEvent.click(generate()); fireEvent.click(screen.getByRole('button', { name: 'tailor.extractFromResume' })); await drain();
    expect(check).not.toHaveBeenCalled(); expect(api.tailor).not.toHaveBeenCalled(); expect(api.extract).not.toHaveBeenCalled(); expect(textarea()).toHaveValue('My unchanged manual bullet');
  });
  it('retires a pending check on target change without sending a request under the new target', async () => {
    const read = deferred<ProfileActionReceipt | null>(); const check = vi.fn(() => read.promise); const props = { ...base, profileRefresh: refresh(check) };
    const view = render(<TailorModal {...props} />); type(); fireEvent.click(generate()); await drain();
    view.rerender(<TailorModal {...props} opportunityId="target-two" target={publicTarget("target-two")} />); read.resolve(receipt()); await drain(); expect(api.tailor).not.toHaveBeenCalled();
  });
  it('rejects an old generation response and clears its private editor content', async () => {
    const pending = deferred<TailorResponse>(); api.tailor.mockReturnValueOnce(pending.promise);
    render(<TailorModal {...base} profileRefresh={refresh(async () => receipt())} />); type('Old generation private text'); fireEvent.click(generate()); await drain();
    // Native SHA work is not exhausted by a fixed number of Promise turns.
    // Establish an in-flight request before retiring its owner generation.
    await waitFor(() => expect(api.tailor).toHaveBeenCalledOnce());
    await act(async () => { const marker = JSON.parse(localStorage.getItem('ofe_local_identity_owner')!);
      localStorage.setItem('ofe_local_identity_owner', JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
      window.dispatchEvent(new StorageEvent('storage', { key: 'ofe_local_identity_owner' })); await syncLocalIdentityOwner('tailor-owner'); });
    pending.resolve(response); await drain(); expect(screen.queryByText('tailor.methodAi')).toBeNull();
    expect(screen.queryByDisplayValue('Old generation private text')).toBeNull();
  });
  it('does not run after closing while the receipt is pending', async () => {
    const read = deferred<ProfileActionReceipt | null>(); render(<TailorModal {...base} profileRefresh={refresh(() => read.promise)} />);
    type(); fireEvent.click(generate()); await drain(); fireEvent.click(screen.getByRole('button', { name: 'tailor.closeAria' })); read.resolve(receipt()); await drain();
    expect(api.tailor).not.toHaveBeenCalled();
  });
  it.each(['queued', 'network'] as const)('same-ID target content changes retire %s work without clearing manual input', async (phase) => {
    const read = deferred<ProfileActionReceipt | null>(); const pending = deferred<TailorResponse>();
    const check = vi.fn(() => phase === 'queued' ? read.promise : Promise.resolve(receipt())); api.tailor.mockReturnValueOnce(pending.promise);
    const props = { ...base, targetKey: 'target version one', profileRefresh: refresh(check) };
    const view = render(<TailorModal {...props} />); type(); fireEvent.click(generate()); await drain();
    if (phase === 'network') {
      // Change the target after the real async provenance checks dispatch POST.
      await waitFor(() => expect(api.tailor).toHaveBeenCalledOnce());
    } else {
      await waitFor(() => expect(check).toHaveBeenCalledOnce());
      expect(api.tailor).not.toHaveBeenCalled();
    }
    view.rerender(<TailorModal {...props} targetKey="target version two" />); read.resolve(receipt()); pending.resolve(response); await drain();
    expect(api.tailor).toHaveBeenCalledTimes(phase === 'queued' ? 0 : 1); expect(screen.queryByText('tailor.methodAi')).toBeNull(); expect(textarea()).toHaveValue('My unchanged manual bullet');
  });
  it('does not revive a late network result when an unavailable source comes back unchanged', async () => {
    const pending = deferred<TailorResponse>(); api.tailor.mockReturnValueOnce(pending.promise);
    const props = { ...base, profileRefresh: refresh(async () => receipt()) }; const view = render(<TailorModal {...props} />);
    type(); fireEvent.click(generate()); await drain(); expect(api.tailor).toHaveBeenCalledOnce();
    view.rerender(<TailorModal {...props} profileAvailable={false} />); view.rerender(<TailorModal {...props} />);
    pending.resolve(response); await drain(); expect(screen.queryByText('tailor.methodAi')).toBeNull(); expect(textarea()).toHaveValue('My unchanged manual bullet');
  });
  it('a failed read preserves the saved inline rewrite, and subsequent user review cancels a retry', async () => {
    const read = deferred<ProfileActionReceipt | null>(); const check = vi.fn().mockResolvedValueOnce(receipt()).mockResolvedValueOnce(null).mockImplementationOnce(() => read.promise);
    render(<TailorModal {...base} profileRefresh={refresh(check)} />); type(); fireEvent.click(generate());
    // The provenance hashes use native async crypto. A fixed microtask drain
    // cannot establish that generation produced an editable result.
    fireEvent.click(await screen.findByRole('button', { name: 'tailor.editBulletAria' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'tailor.editBulletAria' }), { target: { value: 'Saved human revision' } });
    fireEvent.click(screen.getByRole('button', { name: 'tailor.save' })); fireEvent.click(generate());
    await screen.findByText(/This action did not run/);
    expect(check).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Saved human revision')).toBeTruthy(); expect(api.tailor).toHaveBeenCalledOnce();
    fireEvent.click(generate());
    await waitFor(() => expect(check).toHaveBeenCalledTimes(3));
    expect(screen.getByText('Checking the latest profile for this action…')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.rejectBulletAria' }));
    read.resolve(receipt()); await drain();
    expect(generate()).toBeEnabled();
    expect(api.tailor).toHaveBeenCalledOnce(); expect(screen.getByText('Saved human revision')).toBeTruthy();
  });
  it('never rebinds a stored manual draft to a changed résumé just because profile props refreshed', async () => {
    const props = { ...base, profileRefresh: refresh(async () => receipt()) }; const view = render(<TailorModal {...props} />); type();
    const key = 'ofe_tailor_draft_tailor-owner:target-one'; const original = savedRaw(key); expect(original).not.toBeNull();
    view.rerender(<TailorModal {...props} profile={{ ...profile, resume_text: 'Different full source' }} />); await drain();
    expect(savedRaw(key)).toBe(original); expect(textarea()).toHaveValue('My unchanged manual bullet');
  });

  it.each(['plain', 'null-envelope', 'legacy-resume-hash'] as const)('does not upgrade unknown %s draft provenance to the current résumé', async (format) => {
    const key = 'ofe_tailor_draft_tailor-owner:target-one';
    localStorage.setItem(key, format === 'plain' ? 'Unknown old source' : JSON.stringify({ t: 'Unknown old source', s: format === 'legacy-resume-hash' ? 'old-resume-hash-only' : null }));
    render(<TailorModal {...base} profileRefresh={refresh(async () => receipt())} />); await drain();
    expect(textarea()).toHaveValue('Unknown old source'); type('An explicit manual edit'); await drain();
    const saved = JSON.parse(savedRaw(key)!);
    expect(saved).toMatchObject({ version: 2, owner_id: 'tailor-owner', opportunity_id: 'target-one',
      text: 'An explicit manual edit', origin: { kind: 'unknown', binding: null }, review: null });
    expect(api.tailor).not.toHaveBeenCalled();
  });

});
