import { PUBLIC_RELEASE_CACHE_VERSION } from './release-scope';
import type { Opportunity } from './types';

export type SimilarOpportunity = Opportunity & { _similarity: number };

function serverApiBase(): string {
  const isProduction = process.env.VERCEL_ENV === 'production'
    || process.env.NODE_ENV === 'production';
  return process.env.BACKEND_URL
    || process.env.NEXT_PUBLIC_API_URL
    || (isProduction
      ? 'https://opportunity-filter-engine-api.onrender.com'
      : 'http://127.0.0.1:8000');
}

function releaseScopedUrl(url: string): string {
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`;
}

export async function fetchOpportunityServer(id: string): Promise<Opportunity | null> {
  const base = serverApiBase();
  const url = releaseScopedUrl(
    `${base.replace(/\/$/, '')}/api/opportunities/${encodeURIComponent(id)}`,
  );
  try {
    const res = await fetch(url, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return null;
    return (await res.json()) as Opportunity;
  } catch {
    return null;
  }
}

const DETAIL_TIMEOUT_MS = 8000;

/**
 * Detail-page-only classification of the same GET /api/opportunities/{id}.
 * `not-found` is reserved for an explicit backend 400/404 (a real "no such
 * record"); everything else transport can do wrong — timeout, network error,
 * 429/5xx, a non-JSON body, a body missing `id`, or an `id` that doesn't
 * match what was requested — comes back `unavailable` so infrastructure
 * failure never renders as a false 404.
 */
export type OpportunityDetailOutcome =
  | { status: 'ok'; opportunity: Opportunity }
  | { status: 'not-found' }
  | { status: 'unavailable' };

export async function fetchOpportunityDetail(id: string): Promise<OpportunityDetailOutcome> {
  const base = serverApiBase();
  const url = releaseScopedUrl(
    `${base.replace(/\/$/, '')}/api/opportunities/${encodeURIComponent(id)}`,
  );
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DETAIL_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      next: { revalidate: 3600 },
      signal: controller.signal,
    });
    if (res.status === 400 || res.status === 404) return { status: 'not-found' };
    if (!res.ok) return { status: 'unavailable' };
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      return { status: 'unavailable' };
    }
    const opp = body as Partial<Opportunity> | null;
    if (!opp || typeof opp !== 'object' || typeof opp.id !== 'string' || opp.id.length === 0) {
      return { status: 'unavailable' };
    }
    if (opp.id !== id) return { status: 'unavailable' };
    return { status: 'ok', opportunity: opp as Opportunity };
  } catch {
    return { status: 'unavailable' };
  } finally {
    clearTimeout(timer);
  }
}

const SIMILAR_TIMEOUT_MS = 8000;

export async function fetchSimilarServer(id: string, limit = 5): Promise<SimilarOpportunity[]> {
  const base = serverApiBase();
  const url = releaseScopedUrl(
    `${base.replace(/\/$/, '')}/api/opportunities/${encodeURIComponent(id)}/similar?limit=${limit}`,
  );
  // Optional recommendation rail — bounded so a slow/hanging upstream can
  // never hold up the primary detail outcome it's awaited alongside; any
  // failure (including this timeout) degrades to [], same as always.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SIMILAR_TIMEOUT_MS);
  try {
    const res = await fetch(url, { next: { revalidate: 3600 }, signal: controller.signal });
    if (!res.ok) return [];
    const body = (await res.json()) as { opportunities: SimilarOpportunity[] };
    return body.opportunities ?? [];
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchOpportunityIdsServer(): Promise<string[]> {
  const base = serverApiBase();
  const url = releaseScopedUrl(
    `${base.replace(/\/$/, '')}/api/opportunities?limit=200`,
  );
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const body = (await res.json()) as { opportunities?: Array<{ id: string }> };
    return (body.opportunities ?? []).map(o => o.id).filter(Boolean);
  } catch {
    return [];
  }
}
