import { createHash, webcrypto } from 'node:crypto';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import actual from './__fixtures__/private-email-api.json';
vi.mock('./supabase', () => ({ getAuthState: vi.fn() }));
import { getAuthState } from './supabase';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { DEFAULT_PROFILE } from '@/app/home/types';
import { getPrivateEmailContext, privateEmailKey, privateEmailVariants, validatePrivateEmail, type PrivateEmailContext } from './private-email';
import { PRIVATE_TARGET_MAX_BYTES, privateImportEmailRequest } from './private-import-target-api';
import { defaultEmailContactContext } from './email-contact-context';
import type { ProfileData } from './types';

const auth = vi.mocked(getAuthState);
const fetchMock = vi.fn<typeof fetch>();
const base = actual.get.cases[0].response;
const ownerId = base.owner_id;
const other = 'b1000000-0000-4000-8000-000000000001';
const id = base.id;
const options = () => ({ owner: captureOwnerToken() });
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
const clone = <T,>(value: T): T => structuredClone(value);
const state = (uid = ownerId) => ({ user: { id: uid }, session: { user: { id: uid }, access_token: 'synthetic-token' }, isAnonymous: false, email: null }) as Awaited<ReturnType<typeof getAuthState>>;
const profile = (): ProfileData => ({ ...clone(DEFAULT_PROFILE), name: 'Test Student', resume_text: '', experience_entries: [{ id: 'experience-0', revision: 1, status: 'confirmed', text: 'I built a Python parser for my class project.', source: { kind: 'manual' } }] });
const target = () => clone(base) as PrivateEmailContext;
const firstPost = () => clone(actual.post.cases[0].cases[0].response) as Record<string, unknown>;
const validPost = () => clone(actual.post.cases[0].cases[1].response) as Record<string, unknown>;
const validation = (context = target()) => validatePrivateEmail('Question', 'Could you tell me the application process?', 'recipient@example.edu', true, profile(), id, context, defaultEmailContactContext());

beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto);
  localStorage.clear(); advanceOwnerEpoch(ownerId); await syncLocalIdentityOwner(ownerId);
  auth.mockReset().mockResolvedValue(state()); fetchMock.mockReset();
  // Unexpected transport calls fail instead of ever reaching an actual server.
  fetchMock.mockRejectedValue(new Error('Unconfigured synthetic response'));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it.each(actual.get.cases.map((sample, i) => ({ sample, i })))('reads actual GET receipt $i without canonicalizing signed labels or URLs', async ({ sample }) => {
  fetchMock.mockResolvedValueOnce(json(sample.response, sample.status));
  expect(await getPrivateEmailContext(id, options())).toEqual(sample.response);
  const [url, init] = fetchMock.mock.calls[0];
  expect(String(url)).toContain(`/private-import-targets/${encodeURIComponent(id)}/email-context?expected_owner_id=${ownerId}`);
  expect(init).toMatchObject({ cache: 'no-store', redirect: 'error' });
  expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer synthetic-token');
  expect(init?.body).toBeUndefined();
});

for (const group of actual.post.cases) {
  for (const [index, sample] of group.cases.entries()) {
    it(`consumes actual ${group.label} ${sample.action} ${index} through the SDK`, async () => {
      fetchMock.mockResolvedValueOnce(json(sample.response, sample.status));
      const context = clone(group.context) as PrivateEmailContext;
      if (sample.action === 'variants') {
        const pending = privateEmailVariants(profile(), id, context, defaultEmailContactContext());
        if (sample.status === 409) await expect(pending).rejects.toMatchObject({ code: 'contact_blocked' });
        else expect(await pending).toEqual(sample.response);
      } else {
        const request = sample.request as typeof sample.request & { subject: string; body: string; recipient: string; contact_requirements_reviewed: boolean };
        expect(await validatePrivateEmail(request.subject, request.body, request.recipient, request.contact_requirements_reviewed, profile(), id, context, defaultEmailContactContext())).toEqual({ outcome: sample.response.outcome, issues: sample.response.issues });
      }
      expect(fetchMock).toHaveBeenCalledOnce();
      const [url, init] = fetchMock.mock.calls[0];
      expect(String(url).endsWith(`/cold-email/${sample.action}`)).toBe(true);
      expect(init).toMatchObject({ method: 'POST', cache: 'no-store', redirect: 'error' });
      const sent = JSON.parse(init?.body as string);
      expect(sent).toMatchObject({ expected_owner_id: ownerId, expected_target_version: context.writing_version, contact_context: { version: 1, purpose: 'first_contact' }, experience_evidence: { version: 2, resume_master: null, entries: profile().experience_entries } });
      expect(sent).not.toHaveProperty('opportunity'); expect(sent).not.toHaveProperty('description_raw');
    });
  }
}

type Mutation = [string, (value: Record<string, unknown>) => void];
const changes: Mutation[] = [
  ['wrong owner', v => { v.owner_id = other; }],
  ['wrong id', v => { v.id = 'private-import:b2000000-0000-4000-8000-000000000001'; }],
  ['public scope', v => { v.target_scope = 'public'; }],
  ['verified authority', v => { v.verification = 'verified'; }],
  ['provider allowed', v => { v.provider_allowed = true; }],
  ['extra authority', v => { v.target_truth = { actionable: true }; }],
  ['unknown purpose', v => { v.purpose = 'follow_up'; }],
  ['malformed source version', v => { v.source_version = 'current'; }],
  ['malformed writing version', v => { v.writing_version = 'pit1:' + 'a'.repeat(64); }],
  ['revision not bound to source hash', v => { v.revision = 2; }],
  ['wrong valid-format source hash', v => { v.source_version = 'pit1:' + '0'.repeat(64); }],
  ['wrong valid-format writing hash', v => { v.writing_version = 'pwt1:' + '0'.repeat(64); }],
  ['unsafe scheme', v => { v.source_url = 'javascript:alert(1)'; }],
  ['URL credentials', v => { v.source_url = 'https://user:pass@example.edu/'; }],
  ['URL backslash', v => { v.source_url = 'https://example.edu\\secret'; }],
  ['URL control', v => { v.source_url = 'https://example.edu/\nsecret'; }],
  ['excerpt without enrichment', v => { v.import_source = { ...base.import_source, llm_enriched: false }; }],
  ['unknown source marked enriched', v => { v.import_source = { ...base.import_source, description_source: 'unknown', ai_input_scope: 'unknown' }; }],
  ['array source label', v => { v.import_source = { ...base.import_source, description_source: ['pasted_text'] }; }],
  ['array input label', v => { v.import_source = { ...base.import_source, ai_input_scope: ['source_excerpt'] }; }],
  ['array policy state', v => { v.contact_policy = { state: ['unknown'], reason: 'policy_review_required', quotes: [] }; }],
  ['array policy reason', v => { v.contact_policy = { state: 'unknown', reason: ['policy_review_required'], quotes: [] }; }],
  ['unknown with blocked reason', v => { v.contact_policy = { state: 'unknown', reason: 'no_email', quotes: [] }; }],
  ['unknown with quote', v => { v.contact_policy = { state: 'unknown', reason: 'policy_review_required', quotes: [{ start: 0, end: 3, quote: 'ban', restriction: 'no_email' }] }; }],
];
it.each(changes)('rejects GET %s', async (_label, mutate) => {
  const value = clone(base) as Record<string, unknown>; mutate(value);
  fetchMock.mockResolvedValueOnce(json(value));
  await expect(getPrivateEmailContext(id, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
});

// An account copy can say the whole text was sent: the parser stamps full_source
// when every saved word reached the model. The label still needs the recorded
// enrichment and a page or pasted text, as source_excerpt needs its enrichment.
// Each case re-signs the projection, so only the label decides.
function resigned(importSource: Record<string, unknown>) {
  const value = clone(base) as Record<string, unknown>;
  value.import_source = importSource;
  const projection = Object.fromEntries(Object.entries(value).filter(([key]) => key !== 'writing_version'));
  value.writing_version = 'pwt1:' + createHash('sha256').update(privateEmailKey(projection as unknown as PrivateEmailContext)!).digest('hex');
  return value;
}
it.each(['pasted_text', 'page_text'])('reads a full-source label for %s', async (source) => {
  const value = resigned({ version: 1, description_source: source, ai_input_scope: 'full_source', llm_enriched: true });
  fetchMock.mockResolvedValueOnce(json(value));
  expect((await getPrivateEmailContext(id, options())).import_source).toEqual(value.import_source);
});
it.each([
  ['without recorded enrichment', { description_source: 'pasted_text', llm_enriched: false }],
  ['for a historical page excerpt', { description_source: 'page_excerpt', llm_enriched: true }],
  ['for an unknown source', { description_source: 'unknown', llm_enriched: false }],
])('rejects a full-source label %s', async (_label, labels) => {
  fetchMock.mockResolvedValueOnce(json(resigned({ version: 1, ai_input_scope: 'full_source', ...labels })));
  await expect(getPrivateEmailContext(id, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
});

const quoteChanges: Mutation[] = [
  ['negative offset', q => { q.start = -1; }],
  ['fractional offset', q => { q.start = 1.5; }],
  ['UTF16 offset for emoji', q => { q.quote = '😀'; q.start = 0; q.end = 2; }],
  ['source-cap overflow', q => { q.start = 5 * 1024 * 1024; q.end = 5 * 1024 * 1024 + Array.from(String(q.quote)).length; }],
  ['array restriction', q => { q.restriction = ['no_email']; }],
  ['oversized quotation', q => { q.quote = 'x'.repeat(2001); q.start = 0; q.end = 2001; }],
];
it.each(quoteChanges)('rejects blocked receipt with %s', async (_label, mutate) => {
  const value = clone(actual.get.cases[1].response); mutate(value.contact_policy.quotes[0]);
  fetchMock.mockResolvedValueOnce(json(value));
  await expect(getPrivateEmailContext(id, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
});

const postChanges: Mutation[] = [
  ['owner', v => { v.owner_id = other; }],
  ['id', v => { v.opportunity_id = 'public-opportunity'; }],
  ['old writing version', v => { v.target_version = 'pwt1:' + 'f'.repeat(64); }],
  ['wrong source version', v => { v.source_version = 'pit1:' + 'f'.repeat(64); }],
  ['official authority', v => { v.verification = 'official'; }],
  ['public scope', v => { v.target_scope = 'public'; }],
  ['different policy context', v => { v.private_context = clone(actual.get.cases[1].response); }],
  ['wrong context purpose receipt', v => { v.contact_context_receipt = { version: 1, purpose: 'follow_up', context_sig: '0'.repeat(64) }; }],
  ['provider generation', v => { v.method = 'llm'; }],
  ['public condition receipt', v => { v.target_conditions = { version: 1, record_kind: 'listing', conditions: [], template_request: null }; }],
  ['variant public condition receipt', v => { const variants = v.variants as Record<string, unknown>[]; variants[0].target_conditions = { version: 1, record_kind: 'faculty_contact', conditions: [], template_request: null }; }],
  ['discovered recipient', v => { v.recipient_status = 'available'; v.recipient_email = 'invented@example.edu'; }],
];
it.each(postChanges)('rejects POST variant %s', async (_label, mutate) => {
  const value = firstPost(); mutate(value); fetchMock.mockResolvedValueOnce(json(value));
  await expect(privateEmailVariants(profile(), id, target(), defaultEmailContactContext())).rejects.toBeTruthy();
});

it.each([
  ['array outcome', { outcome: ['ready'], issues: [] }],
  ['array issue', { outcome: 'review_required', issues: [['contact_blocked']] }],
  ['repeated issue', { outcome: 'review_required', issues: ['contact_blocked', 'contact_blocked'] }],
  ['ready with a blocking issue', { outcome: 'ready', issues: ['contact_blocked'] }],
  ['review without issue', { outcome: 'review_required', issues: [] }],
] as const)('rejects validate %s', async (_label, changes) => {
  fetchMock.mockResolvedValueOnce(json({ ...validPost(), ...changes }));
  await expect(validation()).rejects.toMatchObject({ code: 'invalid_receipt' });
});

it.each(['listing', 'faculty_contact'])('rejects validate receipt claiming %s condition authority', async recordKind => {
  fetchMock.mockResolvedValueOnce(json({ ...validPost(), target_conditions: { version: 1, record_kind: recordKind, conditions: [], template_request: null } }));
  await expect(validation()).rejects.toMatchObject({ code: 'invalid_receipt' });
});

it('rejects a fabricated stated qualification even when its outer record kind stays unverified', async () => {
  const value = firstPost();
  value.target_conditions = { version: 1, record_kind: 'unverified', template_request: null, conditions: [{
    field: 'eligibility.min_gpa', category: 'eligibility', status: 'stated', value: 3.0, usage: 'usable', reason: 'source_stated',
    sources: [{ quote: 'Minimum GPA is 3.0.', source_url: 'https://example.edu/source', checked_at: '2026-09-29T05:00:00Z' }],
  }] };
  fetchMock.mockResolvedValueOnce(json(value));
  await expect(privateEmailVariants(profile(), id, target(), defaultEmailContactContext())).rejects.toMatchObject({ code: 'invalid_receipt' });
});

it('requires the still-current owner before POST and does not fall back to public routing', async () => {
  const old = target(); advanceOwnerEpoch(other); await syncLocalIdentityOwner(other);
  await expect(privateEmailVariants(profile(), id, old, defaultEmailContactContext())).rejects.toMatchObject({ code: 'invalid_receipt' });
  expect(auth).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
});

it('preserves stale/deleted/blocked server errors and does not retry any POST', async () => {
  for (const [code, expected] of [['private_target_changed', 'changed'], ['private_target_deleted', 'deleted'], ['private_email_contact_blocked', 'contact_blocked']] as const) {
    fetchMock.mockResolvedValueOnce(json({ detail: { code } }, 409));
    await expect(privateEmailVariants(profile(), id, target(), defaultEmailContactContext())).rejects.toMatchObject({ code: expected });
  }
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it('sends a schema-valid long non-Latin resume on the private route instead of failing it as too large on the client', async () => {
  // 45,000 CJK characters is within the backend resume cap (60,000 characters) but about 135 KB of UTF-8.
  const large = { ...profile(), resume_text: '中'.repeat(45_000) };
  fetchMock.mockResolvedValueOnce(json(firstPost()));
  expect(await privateEmailVariants(large, id, target(), defaultEmailContactContext())).toEqual(firstPost());
  fetchMock.mockResolvedValueOnce(json(validPost()));
  await expect(validatePrivateEmail('Question', 'Could you tell me the application process?', 'recipient@example.edu', true, large, id, target(), defaultEmailContactContext())).resolves.toMatchObject({ outcome: validPost().outcome });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string).experience_evidence.resume_text).toHaveLength(45_000);
});

it('still refuses a body above the private route body limit before any request', async () => {
  const oversized = { resume_text: 'x'.repeat(PRIVATE_TARGET_MAX_BYTES + 65536) };
  await expect(privateImportEmailRequest(id, 'variants', oversized, options())).rejects.toMatchObject({ code: 'too_large' });
  expect(auth).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
});
