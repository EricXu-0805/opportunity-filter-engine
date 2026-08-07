import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ACTOR_SESSION_KEY,
  adminFetch,
  DEFAULT_ACTOR,
  getAdminActor,
  setAdminActor,
} from './admin-api';

const fetchMock = vi.fn();

function headersOf(callIndex = 0): Record<string, string> {
  return fetchMock.mock.calls[callIndex][1].headers as Record<string, string>;
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ ok: true }),
  });
  vi.stubGlobal('fetch', fetchMock);
});

describe('adminFetch', () => {
  it('sends the admin token and never caches', async () => {
    await adminFetch('/admin/feedback', 'tok');
    expect(headersOf()['X-Admin-Token']).toBe('tok');
    expect(fetchMock.mock.calls[0][1].cache).toBe('no-store');
  });

  it('does not attach an actor label to reads', async () => {
    await adminFetch('/admin/ops/incidents', 'tok');
    expect(headersOf()['X-Admin-Actor']).toBeUndefined();
  });

  it('attaches the actor label to writes', async () => {
    await adminFetch('/admin/feedback/t1', 'tok', { method: 'PATCH', body: '{}' });
    expect(headersOf()['X-Admin-Actor']).toBe(DEFAULT_ACTOR);
  });

  it('uses the operator-typed label once one is stored', async () => {
    setAdminActor('ana');
    await adminFetch('/admin/ops/incidents/i1/retry', 'tok', { method: 'POST' });
    expect(headersOf()['X-Admin-Actor']).toBe('ana');
  });

  it('returns the response body as an error on a non-2xx', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => 'resolution required',
    });
    const res = await adminFetch('/admin/feedback/t1', 'tok', { method: 'PATCH' });
    expect(res).toEqual({ status: 400, error: 'resolution required' });
  });
});

describe('admin actor label', () => {
  it('defaults to the shared placeholder when nothing is stored', () => {
    expect(getAdminActor()).toBe(DEFAULT_ACTOR);
  });

  it('trims and persists the label per tab', () => {
    expect(setAdminActor('  ana  ')).toBe('ana');
    expect(sessionStorage.getItem(ACTOR_SESSION_KEY)).toBe('ana');
    expect(getAdminActor()).toBe('ana');
  });

  it('falls back to the default rather than storing a blank actor', () => {
    expect(setAdminActor('   ')).toBe(DEFAULT_ACTOR);
    expect(getAdminActor()).toBe(DEFAULT_ACTOR);
  });
});
