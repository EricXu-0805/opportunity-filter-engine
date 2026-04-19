import type { Opportunity } from './types';

export type SimilarOpportunity = Opportunity & { _similarity: number };

function serverApiBase(): string {
  return process.env.BACKEND_URL
    || process.env.NEXT_PUBLIC_API_URL
    || 'http://127.0.0.1:8000';
}

export async function fetchOpportunityServer(id: string): Promise<Opportunity | null> {
  const base = serverApiBase();
  const url = `${base.replace(/\/$/, '')}/api/opportunities/${encodeURIComponent(id)}`;
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

export async function fetchSimilarServer(id: string, limit = 5): Promise<SimilarOpportunity[]> {
  const base = serverApiBase();
  const url = `${base.replace(/\/$/, '')}/api/opportunities/${encodeURIComponent(id)}/similar?limit=${limit}`;
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const body = (await res.json()) as { opportunities: SimilarOpportunity[] };
    return body.opportunities ?? [];
  } catch {
    return [];
  }
}

export async function fetchOpportunityIdsServer(): Promise<string[]> {
  const base = serverApiBase();
  const url = `${base.replace(/\/$/, '')}/api/opportunities?limit=200`;
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const body = (await res.json()) as { opportunities?: Array<{ id: string }> };
    return (body.opportunities ?? []).map(o => o.id).filter(Boolean);
  } catch {
    return [];
  }
}
