import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? '';
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? '';

// In production these MUST be set via Vercel env vars. We don't ship
// hardcoded fallbacks because (a) anyone cloning the repo would otherwise
// silently write to production, and (b) anon keys can be hammered with
// signInAnonymously() to flood the auth.users table.
//
// If the env vars are missing we still need a callable client so the rest
// of the app's optional-chained Supabase usage doesn't crash at import
// time — every method call is then a no-op that surfaces as 'local-only'
// storage status, which the StorageStatusBanner picks up.
const SUPABASE_CONFIGURED = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

if (!SUPABASE_CONFIGURED && typeof window !== 'undefined') {
  // eslint-disable-next-line no-console
  console.warn(
    '[ofe] NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are not set; ' +
    'profile/favorites/interactions will only persist in localStorage.',
  );
}

export const supabase: SupabaseClient = createClient(
  SUPABASE_URL || 'http://localhost:54321',
  SUPABASE_ANON_KEY || 'public-anon-key-not-set',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      storageKey: 'ofe_auth',
      detectSessionInUrl: false,
    },
  },
);

const FAV_FALLBACK_KEY = 'ofe_favs_fallback';

export type StorageStatus = 'synced' | 'local-only' | 'unknown';

let lastStorageStatus: StorageStatus = 'unknown';
let lastStorageError: string | null = null;
const storageListeners = new Set<() => void>();

function setStorageStatus(next: StorageStatus, error?: string | null) {
  if (lastStorageStatus === next && lastStorageError === (error ?? null)) return;
  lastStorageStatus = next;
  lastStorageError = error ?? null;
  storageListeners.forEach(fn => { try { fn(); } catch { /* ignore */ } });
}

export function getStorageStatus(): { status: StorageStatus; error: string | null } {
  return { status: lastStorageStatus, error: lastStorageError };
}

export function onStorageStatusChange(cb: () => void): () => void {
  storageListeners.add(cb);
  return () => { storageListeners.delete(cb); };
}

function readFavFallback(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = localStorage.getItem(FAV_FALLBACK_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? new Set(arr as string[]) : new Set();
  } catch { return new Set(); }
}

function writeFavFallback(set: Set<string>): void {
  if (typeof window === 'undefined') return;
  try { localStorage.setItem(FAV_FALLBACK_KEY, JSON.stringify(Array.from(set))); } catch { /* quota */ }
}

let anonSignInPromise: Promise<string | null> | null = null;

async function ensureAnonSession(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user?.id) {
    setStorageStatus('synced');
    return session.user.id;
  }
  if (anonSignInPromise) return anonSignInPromise;
  anonSignInPromise = (async () => {
    const { data, error } = await supabase.auth.signInAnonymously();
    if (error) {
      const hint = error.message?.toLowerCase().includes('anonymous')
        ? 'Anonymous sign-ins are disabled for this Supabase project.'
        : error.message;
      console.warn('[ofe] anonymous sign-in failed:', error.message);
      setStorageStatus('local-only', hint || error.message);
      anonSignInPromise = null;
      return null;
    }
    setStorageStatus('synced');
    return data.user?.id ?? null;
  })();
  const result = await anonSignInPromise;
  anonSignInPromise = null;
  return result;
}

export async function getDeviceId(): Promise<string | null> {
  return ensureAnonSession();
}

export async function saveProfile(profileData: Record<string, unknown>): Promise<void> {
  const id = await ensureAnonSession();
  if (!id) return;

  const now = new Date().toISOString();

  const { error } = await supabase
    .from('profiles')
    .upsert(
      { id, profile_data: profileData, updated_at: now },
      { onConflict: 'id' },
    );

  if (error) console.warn('Failed to sync profile:', error.message);

  supabase
    .from('profile_versions')
    .insert({ device_id: id, profile_data: profileData, created_at: now })
    .then(({ error: vErr }) => {
      if (vErr && !vErr.message.includes('does not exist')) {
        console.warn('Failed to save profile version:', vErr.message);
      }
    });
}

function readLocalProfile(): Record<string, unknown> | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem('ofe_profile');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch { return null; }
}

export async function loadProfile(): Promise<Record<string, unknown> | null> {
  const local = readLocalProfile();
  const id = await ensureAnonSession();
  if (!id) return local;

  const { data, error } = await supabase
    .from('profiles')
    .select('profile_data')
    .eq('id', id)
    .single();

  if (error || !data) return local;
  return (data.profile_data as Record<string, unknown>) ?? local;
}

export async function getFavorites(): Promise<Set<string>> {
  const local = readFavFallback();
  const deviceId = await ensureAnonSession();
  if (!deviceId) {
    return local;
  }

  const { data, error } = await supabase
    .from('favorites')
    .select('opportunity_id')
    .eq('device_id', deviceId);

  if (error || !data) {
    console.warn('[ofe] getFavorites failed, using local fallback:', error?.message);
    setStorageStatus('local-only', error?.message ?? null);
    return local;
  }

  const remote = new Set(data.map((r: { opportunity_id: string }) => r.opportunity_id));

  const toPush = Array.from(local).filter(id => !remote.has(id));
  if (toPush.length > 0) {
    const rows = toPush.map(opportunity_id => ({ device_id: deviceId, opportunity_id }));
    const { error: insErr } = await supabase.from('favorites').insert(rows);
    if (!insErr) {
      toPush.forEach(id => remote.add(id));
      writeFavFallback(new Set());
    } else {
      console.warn('[ofe] favorites backfill failed:', insErr.message);
    }
  } else if (local.size > 0) {
    writeFavFallback(new Set());
  }

  writeFavFallback(remote);
  setStorageStatus('synced');
  return remote;
}

export async function toggleFavorite(opportunityId: string, isFaved: boolean): Promise<boolean> {
  const local = readFavFallback();
  if (isFaved) local.delete(opportunityId); else local.add(opportunityId);
  writeFavFallback(local);

  const deviceId = await ensureAnonSession();
  if (!deviceId) {
    return !isFaved;
  }

  if (isFaved) {
    const { error } = await supabase
      .from('favorites')
      .delete()
      .eq('device_id', deviceId)
      .eq('opportunity_id', opportunityId);
    if (error) {
      console.warn('[ofe] favorite delete failed:', error.message);
      setStorageStatus('local-only', error.message);
    } else {
      setStorageStatus('synced');
    }
    return false;
  }

  const { error } = await supabase
    .from('favorites')
    .insert({ device_id: deviceId, opportunity_id: opportunityId });
  if (error) {
    console.warn('[ofe] favorite insert failed:', error.message);
    setStorageStatus('local-only', error.message);
  } else {
    setStorageStatus('synced');
  }
  return true;
}

export type InteractionType = 'applied' | 'replied' | 'rejected' | 'interviewing' | 'dismissed';

export interface InteractionRecord {
  type: InteractionType;
  notes?: string;
  remind_at?: string;
  last_contacted_at?: string;
  updated_at?: string;
}

export async function trackInteraction(
  opportunityId: string,
  type: InteractionType,
): Promise<void> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return;

  await supabase.from('interactions').upsert(
    {
      device_id: deviceId,
      opportunity_id: opportunityId,
      interaction_type: type,
      updated_at: new Date().toISOString(),
    },
    { onConflict: 'device_id,opportunity_id' },
  );
}

export async function updateInteractionDetails(
  opportunityId: string,
  patch: { notes?: string | null; remind_at?: string | null; last_contacted_at?: string | null },
): Promise<void> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return;

  const { error } = await supabase
    .from('interactions')
    .update({ ...patch, updated_at: new Date().toISOString() })
    .eq('device_id', deviceId)
    .eq('opportunity_id', opportunityId);

  if (error) console.warn('Failed to update interaction details:', error.message);
}

export async function getInteractions(): Promise<Map<string, InteractionType>> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return new Map();

  const { data, error } = await supabase
    .from('interactions')
    .select('opportunity_id, interaction_type')
    .eq('device_id', deviceId);

  if (error || !data) return new Map();
  return new Map(
    data.map((r: { opportunity_id: string; interaction_type: InteractionType }) => [
      r.opportunity_id,
      r.interaction_type,
    ]),
  );
}

export async function getInteractionsFull(): Promise<Map<string, InteractionRecord>> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return new Map();

  const { data, error } = await supabase
    .from('interactions')
    .select('opportunity_id, interaction_type, notes, remind_at, last_contacted_at, updated_at')
    .eq('device_id', deviceId);

  if (error || !data) return new Map();
  return new Map(
    data.map((r: {
      opportunity_id: string;
      interaction_type: InteractionType;
      notes?: string;
      remind_at?: string;
      last_contacted_at?: string;
      updated_at?: string;
    }) => [
      r.opportunity_id,
      {
        type: r.interaction_type,
        notes: r.notes ?? undefined,
        remind_at: r.remind_at ?? undefined,
        last_contacted_at: r.last_contacted_at ?? undefined,
        updated_at: r.updated_at ?? undefined,
      } as InteractionRecord,
    ]),
  );
}

export async function getInteractionDetail(
  opportunityId: string,
): Promise<InteractionRecord | null> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return null;

  const { data, error } = await supabase
    .from('interactions')
    .select('interaction_type, notes, remind_at, last_contacted_at, updated_at')
    .eq('device_id', deviceId)
    .eq('opportunity_id', opportunityId)
    .maybeSingle();

  if (error || !data) return null;
  return {
    type: data.interaction_type,
    notes: data.notes ?? undefined,
    remind_at: data.remind_at ?? undefined,
    last_contacted_at: data.last_contacted_at ?? undefined,
    updated_at: data.updated_at ?? undefined,
  };
}

export async function removeInteraction(opportunityId: string): Promise<void> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return;
  await supabase.from('interactions').delete().eq('device_id', deviceId).eq('opportunity_id', opportunityId);
}
