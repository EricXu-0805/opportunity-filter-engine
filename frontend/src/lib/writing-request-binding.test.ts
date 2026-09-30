import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileData } from './types';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
const auth = vi.hoisted(() => ({ token: vi.fn(), refresh: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: auth.refresh }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import { generateColdEmail, generateColdEmailStream, getEmailVariants, refineEmail, renovateResume, optimizeBullet, WRITING_AUTH_TIMEOUT_MS } from './api';
const profile: ProfileData = { name: 'Student', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  research_interests: 'robotics', is_international: false, skills: [], coursework: [] };
const TOKEN = 'wt1:' + 'b'.repeat(64);
const paths = ['email', 'stream', 'variants', 'refine', 'renovate', 'bullet'] as const;
type Path = typeof paths[number];
const fetchMock = vi.fn();
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
function pending<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function call(path: Path, token?: string) {
  const options = { expectedTargetVersion: token };
  switch (path) {
    case 'email': return generateColdEmail(profile, 'target', { ...options, engine: 'ai' });
    case 'stream': return generateColdEmailStream(profile, 'target', options);
    case 'variants': return getEmailVariants(profile, 'target', undefined, options);
    case 'refine': return refineEmail('Original body', 'Clearer', profile, 'target', options);
    case 'renovate': return renovateResume(profile, 'target', [], options);
    case 'bullet': return optimizeBullet(profile, 'target', 'Current', 'Original', options);
  }
}
function reply(path: Path) {
  const data = { opportunity_id: 'target', target_version: TOKEN, subject: 'Subject', body: 'Draft', recipient_status: 'sign_in_required' };
  return path === 'stream' ? new Response(`data: ${JSON.stringify({ stage: 'done', ...data })}\n\n`, { headers: { 'content-type': 'text/event-stream' } }) : json(data);
}
beforeEach(async () => { localStorage.clear(); advanceOwnerEpoch('writing-request-A'); await syncLocalIdentityOwner('writing-request-A'); auth.token.mockReset().mockResolvedValue('token-A'); auth.refresh.mockReset().mockResolvedValue('refreshed'); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); advanceOwnerEpoch(null); });

describe('server target token transport', () => {
  it('freezes stream profile arrays and evidence before waiting for credentials', async () => {
    const input = { ...profile, coursework: ['ECE 220'], additional_majors: ['Mathematics'],
      experience_entries: [{ id: 'entry', revision: 1, status: 'confirmed' as const, text: 'Recorded sensor readings.', source: { kind: 'manual' as const } }] };
    const token = pending<string>(); auth.token.mockReturnValue(token.promise); fetchMock.mockResolvedValue(reply('stream'));
    const outcome = generateColdEmailStream(input, 'target', { expectedTargetVersion: TOKEN });
    input.coursework.push('Later course'); input.additional_majors.push('Later major'); input.experience_entries[0].text = 'Changed later';
    token.resolve('same-token'); await outcome;
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      profile: { coursework: ['ECE 220'], secondary_interests: ['Mathematics'] },
      experience_evidence: { entries: [{ text: 'Recorded sensor readings.' }] },
    });
  });
  it.each(paths)('%s sends the server token unchanged', async path => {
    fetchMock.mockResolvedValue(reply(path));
    const data = await call(path, TOKEN);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ opportunity_id: 'target', expected_target_version: TOKEN });
    expect(data).toMatchObject({ opportunity_id: 'target', target_version: TOKEN });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  it.each(paths)('%s omits a legacy missing version but preserves an explicit invalid token for server rejection', async path => {
    fetchMock.mockImplementation(async () => reply(path));
    await call(path); await call(path, '');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).not.toHaveProperty('expected_target_version');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toHaveProperty('expected_target_version', '');
  });
});

describe('writing auth is bounded and never replays completed generation', () => {
  it.each(['email', 'variants'] as const)('%s keeps a locked recipient result without refresh or second POST', async path => {
    fetchMock.mockResolvedValue(reply(path));
    await expect(call(path, TOKEN)).resolves.toMatchObject({ recipient_status: 'sign_in_required' });
    expect(fetchMock).toHaveBeenCalledOnce(); expect(auth.refresh).not.toHaveBeenCalled();
  });
  it.each(['email', 'variants'] as const)('%s times out auth and does not POST after a late token', async path => {
    vi.useFakeTimers(); const deferred = pending<string>(); auth.token.mockReturnValue(deferred.promise);
    let error: unknown; void call(path, TOKEN).catch(value => { error = value; });
    await vi.advanceTimersByTimeAsync(WRITING_AUTH_TIMEOUT_MS);
    expect(error).toMatchObject({ code: 'WRITING_AUTH_TIMEOUT' }); expect(fetchMock).not.toHaveBeenCalled();
    deferred.resolve('late'); await vi.advanceTimersByTimeAsync(0); expect(fetchMock).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(['email', 'variants'] as const)('%s never combines old profile with a new owner token', async path => {
    const deferred = pending<string>(); auth.token.mockReturnValue(deferred.promise);
    const result = call(path, TOKEN).catch(value => value); advanceOwnerEpoch('writing-request-B'); deferred.resolve('token-B');
    expect(await result).toMatchObject({ code: 'WRITING_OWNER_CHANGED' }); expect(fetchMock).not.toHaveBeenCalled();
  });
  it.each(['email', 'variants'] as const)('%s ignores a late response after switching away and back', async path => {
    const deferred = pending<Response>(); fetchMock.mockReturnValue(deferred.promise);
    const result = call(path, TOKEN).catch(value => value);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    advanceOwnerEpoch('writing-request-B'); advanceOwnerEpoch('writing-request-A'); deferred.resolve(reply(path));
    expect(await result).toMatchObject({ code: 'WRITING_OWNER_CHANGED' }); expect(fetchMock).toHaveBeenCalledOnce();
  });
  it('does not expose credential lookup errors or silently downgrade them to an anonymous POST', async () => {
    auth.token.mockRejectedValue(new Error('sensitive auth details'));
    const error = await call('email', TOKEN).catch(value => value);
    expect(error).toMatchObject({ code: 'WRITING_AUTH_UNAVAILABLE' });
    expect(error.message).not.toContain('sensitive'); expect(fetchMock).not.toHaveBeenCalled();
  });
});

async function rebuildSameOwner() {
  const original = captureOwnerToken();
  const marker = JSON.parse(localStorage.getItem('ofe_local_identity_owner')!);
  localStorage.setItem('ofe_local_identity_owner', JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
  await syncLocalIdentityOwner(original.uid!);
  expect(captureOwnerToken()).toMatchObject({ uid: original.uid, epoch: original.epoch, generation: original.generation + 1 });
}
describe('writing generation isolation for the same account', () => {
  it.each(['email', 'variants', 'stream'] as const)('%s does not adopt a generation established after the request started', async path => {
    advanceOwnerEpoch('unresolved-writing-owner');
    expect(captureOwnerToken().generation).toBeLessThan(0);
    const token = pending<string>(); auth.token.mockReturnValue(token.promise); fetchMock.mockResolvedValue(reply(path));
    const outcome = call(path, TOKEN).catch(error => error);
    await syncLocalIdentityOwner('unresolved-writing-owner'); token.resolve('newly-established-token');
    expect(await outcome).toMatchObject({ code: path === 'stream' ? 'cancelled' : 'WRITING_OWNER_CHANGED' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it.each(['email', 'variants', 'stream'] as const)('%s cannot dispatch old material after the local generation is rebuilt during auth', async path => {
    const token = pending<string>(); auth.token.mockReturnValue(token.promise); fetchMock.mockResolvedValue(reply(path));
    const outcome = call(path, TOKEN).catch(error => error); await rebuildSameOwner(); token.resolve('same-account-token');
    expect(await outcome).toMatchObject({ code: path === 'stream' ? 'cancelled' : 'WRITING_OWNER_CHANGED' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it.each(['email', 'variants', 'stream'] as const)('%s rejects an old result after the local generation is rebuilt during fetch', async path => {
    const response = pending<Response>(); fetchMock.mockReturnValue(response.promise);
    const outcome = call(path, TOKEN).catch(error => error);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce()); await rebuildSameOwner(); response.resolve(reply(path));
    expect(await outcome).toMatchObject({ code: path === 'stream' ? 'cancelled' : 'WRITING_OWNER_CHANGED' });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
