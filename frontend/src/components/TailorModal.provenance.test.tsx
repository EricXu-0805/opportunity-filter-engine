import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import type { Opportunity, ProfileData, TailorResponse } from '@/lib/types';
import { advanceOwnerEpoch, captureOwnerToken, readUserScopedEntry, syncLocalIdentityOwner, writeUserScopedRaw } from '@/lib/identity-owner';
import { compareDraft, createBinding, createDraft, decodeDraft, encodeDraft } from '@/lib/tailor-draft';

vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }) }; });
const api = vi.hoisted(() => ({ tailor: vi.fn(), extract: vi.fn(), status: vi.fn() }));
vi.mock('@/lib/api', () => ({ tailorResume: api.tailor, extractResumeBullets: api.extract, getTailorStatus: api.status }));
import TailorModal from './TailorModal';

const OWNER = 'provenance-owner';
const OPP = 'provenance-target';
const KEY = `ofe_tailor_draft_${OWNER}:${OPP}`;
const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'sensors', skills: [{ name: 'Python', level: 'beginner' }],
  coursework: ['CS 225'], resume_text: '• Original complete sensor project' };
const target: Opportunity = { id: OPP, title: 'Sensor research', organization: 'UIUC', source_type: 'manual', record_kind: 'listing',
  opportunity_type: 'research', paid: 'unknown', location: 'Urbana', on_campus: true,
  description_clean: 'Student sensor research', keywords: ['sensors'],
  eligibility: { preferred_year: [], majors: [], skills_required: ['Python'], international_friendly: 'unknown', citizenship_required: null },
  application: { application_effort: 'unknown', requires_resume: 'yes', contact_method: 'email' },
  metadata: { is_active: true, confidence_score: 1 } };
const goodResponse: TailorResponse = { opportunity_id: OPP, pipeline_version: 'w13.2', generated_at: '2026-09-25T12:00:00+00:00',
  method: 'ai', warnings: [], tailored_bullets: [{ text: 'Retained model output', source_evidence: 'Original complete sensor project', source_index: 0 }] };
const base = { target, isOpen: true, onClose: vi.fn(), profile, opportunityId: OPP, opportunityTitle: target.title,
  ownerReady: true, ownerScopeKey: OWNER };
const input = () => screen.getByPlaceholderText('tailor.bulletsPlaceholder');
const generate = () => screen.getByRole('button', { name: /^tailor\.(generate|regenerate)$/ });
const type = (value: string) => fireEvent.change(input(), { target: { value } });
function raw(): string | null { const entry = readUserScopedEntry(KEY); return entry.status === 'present' ? entry.value : null; }
function saved() {
  const decoded = decodeDraft(raw() ?? '', OWNER, OPP);
  if (decoded.status !== 'v2') throw new Error('Expected a v2 draft in the confirmed owner namespace');
  return decoded.draft;
}
function seed(value: string) { expect(writeUserScopedRaw(KEY, value, captureOwnerToken())).toBe(true); }
async function settle() { await act(async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); }); }
async function ready() { await waitFor(() => expect(screen.queryByText('tailor.rulesChecking')).not.toBeInTheDocument()); await settle(); }
beforeEach(async () => {
  vi.resetAllMocks(); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  advanceOwnerEpoch(null); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  api.status.mockResolvedValue({ ai_available: true, pipeline_version: 'w13.2' });
  api.tailor.mockResolvedValue(goodResponse);
  api.extract.mockResolvedValue({ method: 'ai', bullets: ['Fresh extraction'], warnings: [], pipeline_version: 'w13.2', generated_at: '2026-09-25T12:00:00+00:00' });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('Tailor local draft provenance', () => {
  it('binds a new manual draft to the first complete target, then requires review for later same-ID criteria changes', async () => {
    // A result card intentionally lacks the complete public detail fields.
    const card = { id: OPP, title: target.title, organization: target.organization } as Opportunity;
    const view = render(<TailorModal {...base} target={card} targetChecking targetReady={false} />);
    type('Manual text entered while the full opportunity is loading'); await settle();
    expect(saved().origin.binding).toBeNull(); expect(api.tailor).not.toHaveBeenCalled();
    view.rerender(<TailorModal {...base} target={target} targetChecking={false} targetReady />); await ready();
    await waitFor(() => expect(saved().origin.binding).not.toBeNull());
    const firstBinding = saved().origin.binding;
    expect(input()).toHaveValue('Manual text entered while the full opportunity is loading');
    expect(screen.queryByTestId('tailor-draft-review')).not.toBeInTheDocument();
    fireEvent.click(generate());
    await waitFor(() => expect(api.tailor).toHaveBeenCalledExactlyOnceWith(profile, OPP,
      ['Manual text entered while the full opportunity is loading'], { locale: 'en', expectedPipelineVersion: 'w13.2' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'tailor.useAsOriginals' })).toBeInTheDocument());
    const changed = { ...target, eligibility: { ...target.eligibility, skills_required: ['Python', 'R'] } };
    view.rerender(<TailorModal {...base} target={changed} targetChecking={false} targetReady />);
    await waitFor(() => expect(screen.getByTestId('tailor-draft-review')).toBeInTheDocument());
    expect(input()).toHaveValue('Manual text entered while the full opportunity is loading');
    expect(saved().origin.binding).toEqual(firstBinding); expect(saved().review).toBeNull();
    fireEvent.click(generate()); await settle();
    expect(api.tailor).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'tailor.reviewDraft' })).toBeInTheDocument();
  });
  it('does not reassign initial manual text when the profile changes before the first complete target arrives', async () => {
    const card = { id: OPP, title: target.title, organization: target.organization } as Opportunity;
    const view = render(<TailorModal {...base} target={card} targetChecking targetReady={false} />);
    type('Manual text from the initially displayed profile'); await settle();
    const changedProfile = { ...profile, coursework: ['New independently loaded course'] };
    view.rerender(<TailorModal {...base} profile={changedProfile} target={card} targetChecking targetReady={false} />); await settle();
    view.rerender(<TailorModal {...base} profile={changedProfile} target={target} targetChecking={false} targetReady />); await ready();
    await waitFor(() => expect(screen.getByTestId('tailor-draft-review')).toBeInTheDocument());
    expect(input()).toHaveValue('Manual text from the initially displayed profile');
    expect(saved().origin.binding).toBeNull(); expect(saved().review).toBeNull();
    fireEvent.click(generate()); await settle();
    expect(api.tailor).not.toHaveBeenCalled(); expect(api.extract).not.toHaveBeenCalled();
    expect(input()).toHaveValue('Manual text from the initially displayed profile');
    expect(saved().origin.binding).toBeNull(); expect(saved().review).toBeNull();
  });
  it('never sends generation or extraction when the rendered full target belongs to another opportunity', async () => {
    render(<TailorModal {...base} target={{ ...target, id: 'another-target' }} />); await ready();
    const original = input().textContent;
    fireEvent.click(generate()); await settle();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.extractFromResume' })); await settle();
    expect(api.tailor).not.toHaveBeenCalled(); expect(api.extract).not.toHaveBeenCalled();
    expect(input()).toHaveValue(original);
    expect(saved().origin.binding).toBeNull();
  });
  it('a draft read error is not absence and never licenses prefill or an automatic overwrite', async () => {
    const old = encodeDraft(createDraft(OWNER, OPP, 'Unread saved human text', 'manual', await createBinding(profile, target, 'w13.2')));
    seed(old);
    const get = window.localStorage.getItem.bind(window.localStorage);
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(function (key) {
      if (key.includes(KEY)) throw new Error('Storage access denied');
      return get(key);
    });
    const writes = vi.spyOn(window.localStorage, 'setItem');
    render(<TailorModal {...base} />); await ready();
    expect(screen.getByText('tailor.draftReadFailed')).toBeInTheDocument(); expect(input()).toHaveValue('');
    type('Local text kept only in this editor'); await settle();
    expect(input()).toHaveValue('Local text kept only in this editor');
    expect(writes.mock.calls.filter(([key]) => key.includes(KEY))).toHaveLength(0);
    vi.restoreAllMocks(); expect(raw()).toBe(old); expect(api.tailor).not.toHaveBeenCalled();
  });
  it('malformed v2 storage stays untouched and is not treated as a new empty draft', async () => {
    const invalid = JSON.stringify({ version: 2, owner_id: OWNER, opportunity_id: OPP, text: 'Unread saved body', origin: { kind: ['manual'], binding: null }, review: null });
    seed(invalid); const writes = vi.spyOn(window.localStorage, 'setItem');
    render(<TailorModal {...base} />); await ready();
    expect(screen.getByText('tailor.draftUnreadable')).toBeInTheDocument(); expect(input()).toHaveValue('');
    type('Unsaved local correction'); await settle();
    expect(raw()).toBe(invalid); expect(writes.mock.calls.filter(([key]) => key.includes(KEY))).toHaveLength(0);
  });
  it.each(['quota', 'silent-noop'] as const)('reports %s writes and Retry saves the exact retained draft', async kind => {
    render(<TailorModal {...base} />); await ready(); const original = raw();
    const set = window.localStorage.setItem.bind(window.localStorage);
    const blocked = vi.spyOn(window.localStorage, 'setItem').mockImplementation(function (key, value) {
      if (key.includes(KEY)) { if (kind === 'quota') throw new DOMException('Quota exceeded', 'QuotaExceededError'); return; }
      set(key, value);
    });
    type('  Human edit\n完整尾项 🧪  ');
    await waitFor(() => expect(screen.getByText('tailor.draftSaveFailed')).toBeInTheDocument());
    expect(input()).toHaveValue('  Human edit\n完整尾项 🧪  '); expect(raw()).toBe(original);
    blocked.mockRestore(); fireEvent.click(screen.getByRole('button', { name: 'tailor.retrySave' }));
    await waitFor(() => expect(screen.queryByText('tailor.draftSaveFailed')).not.toBeInTheDocument());
    expect(saved().text).toBe('  Human edit\n完整尾项 🧪  ');
  });
  it('clear writes an intentional empty draft, so reopening does not resurrect the résumé heuristic', async () => {
    seed(encodeDraft(createDraft(OWNER, OPP, 'Old draft', 'manual', await createBinding(profile, target, 'w13.2'))));
    const view = render(<TailorModal {...base} />); await ready();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.clearDraftAria' })); await settle();
    expect(input()).toHaveValue(''); expect(saved().text).toBe('');
    view.rerender(<TailorModal {...base} isOpen={false} />); view.rerender(<TailorModal {...base} />); await ready();
    expect(input()).toHaveValue(''); expect(saved().text).toBe(''); expect(generate()).toBeDisabled();
  });
  it('reopening reads another tab’s latest same-target value without the old closure writing over it', async () => {
    const binding = await createBinding(profile, target, 'w13.2');
    seed(encodeDraft(createDraft(OWNER, OPP, 'First tab draft', 'manual', binding)));
    const view = render(<TailorModal {...base} />); await ready();
    const external = encodeDraft(createDraft(OWNER, OPP, 'Other tab latest draft', 'manual', binding)); seed(external);
    view.rerender(<TailorModal {...base} isOpen={false} />); expect(raw()).toBe(external);
    const writes = vi.spyOn(window.localStorage, 'setItem');
    view.rerender(<TailorModal {...base} />); await ready();
    expect(input()).toHaveValue('Other tab latest draft'); expect(saved().text).toBe('Other tab latest draft');
    for (const [key, value] of writes.mock.calls) if (key.includes(KEY)) expect(JSON.parse(value).text).toBe('Other tab latest draft');
  });
  it.each(['bad\u0000input', 'bad\ud800input'])('rejects invalid Unicode edits without crashing or replacing the previous text', async bad => {
    render(<TailorModal {...base} />); await ready(); type('Previous safe draft'); await settle(); const old = raw();
    type(bad); await settle();
    expect(screen.getByText('tailor.invalidDraftText')).toBeInTheDocument();
    expect(input()).toHaveValue('Previous safe draft'); expect(raw()).toBe(old);
    type('Corrected text'); await settle(); expect(screen.queryByText('tailor.invalidDraftText')).not.toBeInTheDocument(); expect(saved().text).toBe('Corrected text');
  });
  it.each([
    ['NUL', 'Manual\u0000right-side edit'],
    ['lone surrogate', 'Manual\ud800right-side edit'],
  ] as const)('keeps both drafts and reports invalid %s when promoting an inline edit', async (_kind, bad) => {
    render(<TailorModal {...base} />); await ready(); type('Previous safe left-side draft'); await settle();
    fireEvent.click(generate());
    await waitFor(() => expect(screen.getByRole('button', { name: 'tailor.useAsOriginals' })).toBeInTheDocument());
    const old = raw();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.editBulletAria' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'tailor.editBulletAria' }), { target: { value: bad } });
    expect(input()).toHaveValue('Previous safe left-side draft');
    expect(screen.getByRole('textbox', { name: 'tailor.editBulletAria' })).toHaveValue(bad);
    fireEvent.click(screen.getByRole('button', { name: 'tailor.save' }));
    const errors: unknown[] = [];
    const catchError = (event: ErrorEvent) => { errors.push(event.error); event.preventDefault(); };
    window.addEventListener('error', catchError);
    try {
      fireEvent.click(screen.getByRole('button', { name: 'tailor.useAsOriginals' })); await settle();
    } finally { window.removeEventListener('error', catchError); }
    expect(errors).toEqual([]);
    expect(input()).toHaveValue('Previous safe left-side draft'); expect(raw()).toBe(old);
    expect(screen.getByText('tailor.invalidDraftText')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'tailor.useAsOriginals' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.editBulletAria' }));
    expect(screen.getByRole('textbox', { name: 'tailor.editBulletAria' })).toHaveValue(bad);
    expect(api.tailor).toHaveBeenCalledOnce(); expect(api.extract).not.toHaveBeenCalled();
  });
  it('Use as originals preserves the output’s earlier binding after the profile changes', async () => {
    const initialBinding = await createBinding(profile, target, 'w13.2');
    const view = render(<TailorModal {...base} />); await ready();
    fireEvent.click(generate()); await waitFor(() => expect(screen.getByRole('button', { name: 'tailor.useAsOriginals' })).toBeInTheDocument());
    const nextProfile = { ...profile, skills: [{ name: 'Python', level: 'experienced' as const }], resume_text: '' };
    view.rerender(<TailorModal {...base} profile={nextProfile} />); await ready();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.useAsOriginals' })); await settle();
    expect(input()).toHaveValue('Retained model output');
    expect(saved().origin).toEqual({ kind: 'reviewed_output', binding: initialBinding }); expect(saved().review).toBeNull();
    expect(await compareDraft(saved(), await createBinding(nextProfile, target, 'w13.2'))).toBe('stale');
    expect(screen.getByTestId('tailor-draft-review')).toBeInTheDocument(); fireEvent.click(generate()); await settle();
    expect(api.tailor).toHaveBeenCalledOnce();
  });
  it.each(['unknown', 'stale'] as const)('%s text needs explicit exact-text review again after another edit', async kind => {
    if (kind === 'unknown') seed('Legacy unknown source');
    else seed(encodeDraft(createDraft(OWNER, OPP, 'Old source draft', 'manual', await createBinding({ ...profile, coursework: ['Old course'] }, target, 'w13.2'))));
    render(<TailorModal {...base} />); await ready();
    const origin = saved().origin; // the displayed legacy value may have been safely encoded, never rebound
    expect(screen.getByTestId('tailor-draft-review')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.reviewDraft' }));
    await waitFor(() => expect(screen.queryByTestId('tailor-draft-review')).not.toBeInTheDocument());
    expect(saved().origin).toEqual(origin); expect(saved().review).not.toBeNull();
    const reviewed = saved().review; type('Changed after my review'); await settle();
    await waitFor(() => expect(screen.getByTestId('tailor-draft-review')).toBeInTheDocument());
    expect(saved().review).toEqual(reviewed); expect(saved().origin).toEqual(origin);
    fireEvent.click(generate()); await settle(); expect(api.tailor).not.toHaveBeenCalled();
  });
  it.each([
    ['missing version', { pipeline_version: undefined }], ['wrong version', { pipeline_version: 'w13.1' }],
    ['missing timestamp', { generated_at: undefined }], ['wrong target', { opportunity_id: 'another-target' }],
  ] as const)('rejects a tailoring response with %s while preserving input and stored provenance', async (_case, change) => {
    api.tailor.mockResolvedValue({ ...goodResponse, ...change });
    render(<TailorModal {...base} />); await ready(); const old = raw();
    fireEvent.click(generate()); await waitFor(() => expect(api.tailor).toHaveBeenCalledOnce()); await settle();
    expect(screen.queryByRole('button', { name: 'tailor.useAsOriginals' })).not.toBeInTheDocument();
    expect(input()).toHaveValue('Original complete sensor project'); expect(raw()).toBe(old);
  });
  it.each([{ pipeline_version: undefined }, { pipeline_version: 'w13.1' }, { generated_at: 'not-a-date' }])('rejects unverified extraction metadata without replacing manual text', async change => {
    api.extract.mockResolvedValue({ method: 'ai', bullets: ['Unverified extraction'], pipeline_version: 'w13.2', generated_at: '2026-09-25T12:00:00+00:00', ...change });
    render(<TailorModal {...base} />); await ready(); type('Keep my manual draft'); await settle(); const old = raw();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.extractFromResume' }));
    await waitFor(() => expect(screen.getByText('resume.extractionFailed')).toBeInTheDocument());
    expect(input()).toHaveValue('Keep my manual draft'); expect(raw()).toBe(old);
  });
});
