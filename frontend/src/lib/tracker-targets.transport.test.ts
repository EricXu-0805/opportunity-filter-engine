import { createHash } from 'node:crypto';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.mock('./supabase', () => ({ getAuthState: vi.fn() }));
vi.mock('./api', () => ({ getShortlistOpportunities: vi.fn() }));
import { getAuthState } from './supabase';
import { captureOwnerToken } from './identity-owner';
import { OWNER, setupOwner } from './application-material.test-utils';
import { loadTrackerTargets } from './tracker-targets';

const auth = vi.mocked(getAuthState); const fetchMock = vi.fn<typeof fetch>();
const state = () => ({ user: { id: OWNER }, session: { user: { id: OWNER }, access_token: 'test-only-token' }, isAnonymous: false, email: null }) as Awaited<ReturnType<typeof getAuthState>>;
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const privateId = (n: number) => `private-import:cccccccc-cccc-4ccc-8ccc-${String(n).padStart(12, '0')}`;
const version = (id: string, revision: number) => 'pit1:' + createHash('sha256').update(JSON.stringify({ id, owner_id: OWNER, revision })).digest('hex');
const tracker = (id: string) => ({ id, title: 'Own lab note', organization: null, source_url: 'https://lab.example.edu/join', url: null,
  target_scope: 'private_import', verification: 'unverified', target_version: version(id, 2) });

// The API shares a per-IP request budget with every other default route; a
// Tracker load must not spend one request per private import.
function rateLimitedServer(budget: number, resolved: Set<string>) {
  let used = 0;
  fetchMock.mockImplementation(async (input, init) => {
    if (++used > budget) return json({ detail: 'Too many requests' }, 429);
    const url = new URL(String(input), 'https://app.example');
    if (init?.method === 'POST' && url.pathname.endsWith('/private-import-targets/resolved')) {
      const { ids } = JSON.parse(init.body as string) as { ids: string[] };
      return json({ version: 1, items: ids.map(id => resolved.has(id) ? { id, status: 'resolved', revision: 2, tracker: tracker(id) } : { id, status: 'deleted' }) });
    }
    return json({ detail: { code: 'private_target_deleted' } }, 409);
  });
}

beforeEach(async () => { await setupOwner(); auth.mockReset().mockResolvedValue(state()); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('loads thirty tracked private imports with one request instead of draining the shared rate budget', async () => {
  const ids = Array.from({ length: 30 }, (_, n) => privateId(n));
  rateLimitedServer(5, new Set([ids[0]]));
  const result = await loadTrackerTargets(ids, captureOwnerToken());
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(result.opportunities).toEqual([{ id: ids[0], title: 'Own lab note', organization: undefined, source_url: 'https://lab.example.edu/join', url: undefined }]);
  expect(result.unavailableIds).toEqual(ids.slice(1));
});

it('splits a very large Tracker into bounded batches', async () => {
  const ids = Array.from({ length: 150 }, (_, n) => privateId(n));
  rateLimitedServer(5, new Set());
  expect((await loadTrackerTargets(ids, captureOwnerToken())).unavailableIds).toEqual(ids);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls.map(([, init]) => JSON.parse(init!.body as string).ids.length)).toEqual([100, 50]);
});

it('still fails the load when the batch itself is refused, instead of showing targets as missing', async () => {
  rateLimitedServer(0, new Set());
  await expect(loadTrackerTargets([privateId(1)], captureOwnerToken())).rejects.toMatchObject({ code: 'unavailable' });
});
