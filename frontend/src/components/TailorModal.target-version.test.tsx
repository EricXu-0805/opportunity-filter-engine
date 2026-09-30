import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import type { Opportunity, ProfileData } from '@/lib/types';
import { advanceOwnerEpoch, readUserScopedEntry, syncLocalIdentityOwner } from '@/lib/identity-owner';
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }) }; });
const api = vi.hoisted(() => ({ tailor: vi.fn(), extract: vi.fn(), status: vi.fn() }));
vi.mock('@/lib/api', () => ({ tailorResume: api.tailor, extractResumeBullets: api.extract, getTailorStatus: api.status }));
import TailorModal from './TailorModal';

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
const copied = vi.fn(async (_text: string) => {});
const A = `wt1:${'a'.repeat(64)}`, B = `wt1:${'b'.repeat(64)}`;
const OWNER = 'target-version-owner', ID = 'target-version-opportunity';
const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior', is_international: false,
  research_interests: 'sensors', skills: [], resume_text: '• My original sensor work' };
const target: Opportunity = { id: ID, title: 'Sensor research', organization: 'UIUC', source_type: 'manual', record_kind: 'listing',
  opportunity_type: 'research', paid: 'unknown', location: 'Urbana', on_campus: true, description_clean: 'Research on sensors', keywords: ['sensors'],
  eligibility: { international_friendly: 'unknown', skills_required: [], preferred_year: [], majors: [], citizenship_required: null },
  application: { requires_resume: 'yes', contact_method: 'email', application_effort: 'unknown' }, metadata: { is_active: true, confidence_score: 1 },
  writing_target_version: A };
function withVersion(version: unknown): Opportunity {
  const copy = { ...target } as unknown as Record<string, unknown>;
  if (version === undefined) delete copy.writing_target_version; else copy.writing_target_version = version;
  return copy as unknown as Opportunity;
}
const response = (version: unknown = A, text = 'Verified target suggestion') => ({ opportunity_id: ID, pipeline_version: 'w13.3',
  generated_at: '2026-09-25T12:00:00Z', target_version: version, method: 'ai', warnings: [],
  tailored_bullets: [{ text, source_evidence: 'My original sensor work', source_index: 0 }] });
const base = { isOpen: true, onClose: vi.fn(), profile, target, opportunityId: ID, opportunityTitle: target.title, ownerReady: true, ownerScopeKey: OWNER };
const input = () => screen.getByPlaceholderText('tailor.bulletsPlaceholder');
const generate = () => screen.getByRole('button', { name: /^tailor\.(generate|regenerate)$/ });
const fullText = (text: string) => (_: string, element: Element | null) => element?.textContent === text;
async function drain() { await act(async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); }); }
async function ready() { await waitFor(() => expect(screen.queryByText('tailor.rulesChecking')).not.toBeInTheDocument()); await drain(); }
function stored() { const value = readUserScopedEntry(`ofe_tailor_draft_${OWNER}:${ID}`); return value.status === 'present' ? value.value : null; }
function pending<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; }
beforeEach(async () => {
  vi.resetAllMocks(); Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copied } }); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  advanceOwnerEpoch(null); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  api.status.mockResolvedValue({ ai_available: true, pipeline_version: 'w13.3' }); api.tailor.mockResolvedValue(response());
  api.extract.mockResolvedValue({ method: 'ai', bullets: ['Fresh source extraction'], pipeline_version: 'w13.3', generated_at: '2026-09-25T12:00:00Z' });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor); else Reflect.deleteProperty(navigator, 'clipboard'); });

describe('Tailor authoritative target version', () => {
  it('submits the exact verified version and accepts only its matching receipt', async () => {
    render(<TailorModal {...base} />); await ready(); fireEvent.click(generate());
    // Wait only for the dispatch; a changed call shape then fails with the
    // argument diff instead of a polling timeout.
    await waitFor(() => expect(api.tailor).toHaveBeenCalled());
    expect(api.tailor).toHaveBeenCalledExactlyOnceWith(profile, ID, ['My original sensor work'],
      { locale: 'en', expectedPipelineVersion: 'w13.3', expectedTargetVersion: A });
    await waitFor(() => expect(screen.getAllByText(fullText('Verified target suggestion')).length).toBeGreaterThan(0));
  });
  it.each([undefined, '', `wt1:${'A'.repeat(64)}`, ` ${A}`])('does not generate without a valid server target token (%s)', async version => {
    render(<TailorModal {...base} target={withVersion(version)} />); await ready();
    fireEvent.change(input(), { target: { value: 'My retained manual text' } }); fireEvent.click(generate()); await waitFor(() => expect(generate()).toBeEnabled()); await drain();
    expect(api.tailor).not.toHaveBeenCalled(); expect(input()).toHaveValue('My retained manual text');
    expect(screen.getByText('tailor.targetVersionUnavailable')).toBeInTheDocument();
    const review = screen.queryByRole('button', { name: 'tailor.reviewDraft' });
    if (review) { fireEvent.click(review); await drain(); fireEvent.click(generate()); await drain(); }
    expect(api.tailor).not.toHaveBeenCalled(); expect(input()).toHaveValue('My retained manual text');
  });
  it.each([undefined, null, B, `wt1:${'A'.repeat(64)}`])('keeps the previous output and manual draft when the response version is %s', async version => {
    render(<TailorModal {...base} />); await ready(); fireEvent.click(generate());
    await waitFor(() => expect(screen.getAllByText(fullText('Verified target suggestion')).length).toBeGreaterThan(0));
    fireEvent.change(input(), { target: { value: 'Preserved manual wording 王' } }); await drain(); const saved = stored();
    api.tailor.mockResolvedValueOnce({ ...response(A, 'Unverified replacement'), target_version: version }); fireEvent.click(generate());
    await waitFor(() => expect(api.tailor).toHaveBeenCalledTimes(2)); await waitFor(() => expect(generate()).toBeEnabled());
    expect(screen.queryByText(fullText('Unverified replacement'))).not.toBeInTheDocument();
    // The existing error view hides output cards, but copying must still use
    // the last accepted result, never the rejected response.
    fireEvent.click(screen.getByRole('button', { name: 'tailor.copyAll' }));
    await waitFor(() => expect(copied).toHaveBeenCalledWith('• Verified target suggestion'));
    expect(input()).toHaveValue('Preserved manual wording 王'); expect(stored()).toBe(saved);
  });
  it('keeps the draft on a stale-target 409 without automatic retry and requires review after the new target arrives', async () => {
    const view = render(<TailorModal {...base} />); await ready(); fireEvent.click(generate());
    await waitFor(() => expect(screen.getAllByText(fullText('Verified target suggestion')).length).toBeGreaterThan(0));
    fireEvent.change(input(), { target: { value: 'Retained after server target changed' } }); await drain(); const saved = stored();
    api.tailor.mockRejectedValueOnce(Object.assign(new Error('server private message'), { status: 409, code: 'WRITING_TARGET_CHANGED' }));
    fireEvent.click(generate()); await waitFor(() => expect(screen.getByText('tailor.targetVersionChanged')).toBeInTheDocument()); await drain();
    expect(api.tailor).toHaveBeenCalledTimes(2); expect(input()).toHaveValue('Retained after server target changed'); expect(stored()).toBe(saved);
    expect(screen.queryByText('server private message')).not.toBeInTheDocument();
    view.rerender(<TailorModal {...base} target={{ ...target, writing_target_version: B }} />); await ready();
    fireEvent.click(generate()); await drain(); expect(api.tailor).toHaveBeenCalledTimes(2);
    // Generate must finish its native SHA checks and refuse the stale draft
    // before the explicit review button can accept the user's next action.
    await waitFor(() => expect(screen.getByRole('button', { name: 'tailor.reviewDraft' })).toBeEnabled());
    expect(api.tailor).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'tailor.reviewDraft' }));
    await waitFor(() => expect(screen.queryByTestId('tailor-draft-review')).not.toBeInTheDocument());
    api.tailor.mockResolvedValueOnce(response(B, 'New target verified suggestion')); fireEvent.click(generate());
    await waitFor(() => expect(api.tailor).toHaveBeenCalledTimes(3));
    expect(api.tailor.mock.calls[2][3]).toMatchObject({ expectedTargetVersion: B });
    await waitFor(() => expect(screen.getAllByText(fullText('New target verified suggestion')).length).toBeGreaterThan(0));
  });
  it('retires a pending response when only the same-ID target version changes and keeps manual text', async () => {
    const result = pending<ReturnType<typeof response>>(); api.tailor.mockReturnValueOnce(result.promise);
    const view = render(<TailorModal {...base} />); await ready(); fireEvent.click(generate());
    await waitFor(() => expect(api.tailor).toHaveBeenCalledOnce());
    view.rerender(<TailorModal {...base} target={{ ...target, writing_target_version: B }} />); await ready();
    fireEvent.change(input(), { target: { value: 'Latest human text after target changed' } });
    await act(async () => { result.resolve(response(A, 'Late old target output')); }); await drain();
    expect(screen.queryByText(fullText('Late old target output'))).not.toBeInTheDocument(); expect(input()).toHaveValue('Latest human text after target changed');
    expect(api.tailor).toHaveBeenCalledOnce();
  });
  it('does not add a target token to source extraction', async () => {
    render(<TailorModal {...base} target={withVersion(undefined)} />); await ready();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.extractFromResume' }));
    await waitFor(() => expect(api.extract).toHaveBeenCalled());
    expect(api.extract).toHaveBeenCalledExactlyOnceWith(profile.resume_text, { expectedPipelineVersion: 'w13.3' });
    await waitFor(() => expect(input()).toHaveValue('Fresh source extraction')); expect(api.tailor).not.toHaveBeenCalled();
  });
});
