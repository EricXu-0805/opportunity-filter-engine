/**
 * A tailor draft saved before w14 (round-2 review, criteria 1 and 3).
 *
 * On main (w13.x) "Use kept as new originals" stored the kept rewrites as the draft text
 * (origin reviewed_output, version 2, no line sources). Those rewrites had no faithfulness
 * review and main wrote them in the UI locale. The draft used to reopen with only the generic
 * "materials changed" notice, after which the next /tailor sent the rewrite as its own
 * evidence. It now says what it holds and offers to start again from the résumé.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import type { Opportunity, ProfileData, TailorResponse } from '@/lib/types';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, writeUserScopedRaw } from '@/lib/identity-owner';
import { createBinding } from '@/lib/tailor-draft';

vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'zh' }) }; });
const api = vi.hoisted(() => ({ tailor: vi.fn(), extract: vi.fn(), status: vi.fn() }));
vi.mock('@/lib/api', () => ({ tailorResume: api.tailor, extractResumeBullets: api.extract, getTailorStatus: api.status }));
import TailorModal from './TailorModal';

const OWNER = 'legacy-owner';
const OPP = 'legacy-target';
const KEY = `ofe_tailor_draft_${OWNER}:${OPP}`;
const RESUME_LINE = 'Helped clean sensor data in Python for a class project';
const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'sensors', skills: [{ name: 'Python', level: 'beginner' }],
  coursework: ['CS 225'], resume_text: `• ${RESUME_LINE}` };
const target: Opportunity = { id: OPP, title: 'Sensor research', organization: 'UIUC', source_type: 'manual', record_kind: 'listing',
  writing_target_version: `wt1:${'a'.repeat(64)}`, opportunity_type: 'research', paid: 'unknown', location: 'Urbana', on_campus: true,
  description_clean: 'Student sensor research', keywords: ['sensors'],
  eligibility: { preferred_year: [], majors: [], skills_required: ['Python'], international_friendly: 'unknown', citizenship_required: null },
  application: { application_effort: 'unknown', requires_resume: 'yes', contact_method: 'email' },
  metadata: { is_active: true, confidence_score: 1 } };
// main's unreviewed rewrite of RESUME_LINE in the zh UI locale: it drops "Helped" and is in another language.
const LEGACY_REWRITE = '使用 Python 主导完成传感器数据清洗';
const base = { target, isOpen: true, onClose: vi.fn(), profile, opportunityId: OPP, opportunityTitle: target.title,
  ownerReady: true, ownerScopeKey: OWNER };
async function settle() { await act(async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); }); }

async function storeDraft(rules: string, extra: Record<string, unknown> = {}) {
  const binding = await createBinding(profile, target, rules);
  const draft = { version: 2, owner_id: OWNER, opportunity_id: OPP, text: LEGACY_REWRITE,
    origin: { kind: 'reviewed_output', binding }, review: null, ...extra };
  expect(writeUserScopedRaw(KEY, JSON.stringify(draft), captureOwnerToken())).toBe(true);
}

async function open() {
  render(<TailorModal {...base} />);
  await waitFor(() => expect(screen.queryByText('tailor.rulesChecking')).not.toBeInTheDocument()); await settle();
  await waitFor(() => expect(screen.getByTestId('tailor-draft-review')).toBeInTheDocument());
}

beforeEach(async () => {
  vi.resetAllMocks(); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  advanceOwnerEpoch(null); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  api.status.mockResolvedValue({ ai_available: true, pipeline_version: 'w14.1' });
  api.extract.mockResolvedValue({ bullets: [RESUME_LINE], method: 'heuristic', warnings: [],
    pipeline_version: 'w14.1', generated_at: '2026-10-03T00:00:00+00:00' });
  api.tailor.mockResolvedValue({ opportunity_id: OPP, pipeline_version: 'w14.1', target_version: `wt1:${'a'.repeat(64)}`,
    generated_at: '2026-10-03T00:00:00+00:00', method: 'ai', warnings: [],
    tailored_bullets: [{ text: LEGACY_REWRITE, source_evidence: LEGACY_REWRITE, source_index: 0, status: 'kept', reason_code: 'no_link' }] } satisfies TailorResponse);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('a tailor draft promoted on main (w13.x)', () => {
  it('says it holds unreviewed AI rewrites, not only that materials changed', async () => {
    await storeDraft('w13.6');
    await open();
    expect(screen.getByTestId('tailor-draft-legacy')).toHaveTextContent('tailor.draftLegacyRewrites');
    expect(screen.queryByText('tailor.draftChanged')).not.toBeInTheDocument();
  });

  it('can start again from the résumé, replacing the unreviewed rewrite before anything is sent', async () => {
    await storeDraft('w13.6');
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.useResumeLines' }));
    await waitFor(() => expect(api.extract).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByPlaceholderText('tailor.bulletsPlaceholder')).toHaveValue(RESUME_LINE));
    expect(screen.queryByTestId('tailor-draft-legacy')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^tailor\.(generate|regenerate)$/ }));
    await waitFor(() => expect(api.tailor).toHaveBeenCalledOnce());
    expect(api.tailor.mock.calls[0][2]).toEqual([RESUME_LINE]);
  });

  it('is sent as the student\'s own line only after they confirm it against the notice', async () => {
    await storeDraft('w13.6');
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.reviewDraft' }));
    await waitFor(() => expect(screen.queryByTestId('tailor-draft-review')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /^tailor\.(generate|regenerate)$/ }));
    await waitFor(() => expect(api.tailor).toHaveBeenCalledOnce());
    expect(api.tailor.mock.calls[0][2]).toEqual([LEGACY_REWRITE]);
  });
});

describe('a tailor draft promoted under reviewed rules', () => {
  it('keeps the generic notice when only the materials changed', async () => {
    await storeDraft('w14.0');
    await open();
    expect(screen.queryByTestId('tailor-draft-legacy')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'tailor.useResumeLines' })).not.toBeInTheDocument();
  });
});
