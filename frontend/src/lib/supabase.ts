import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://mjpirkyduibkakvlbdko.supabase.co';
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1qcGlya3lkdWlia2FrdmxiZGtvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYwNDE5OTEsImV4cCI6MjA5MTYxNzk5MX0.EiXIL8YaWOqfGvAASkfzJcg9VvYdF_mS4Ftn8Eiv2aE';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storageKey: 'ofe_auth',
    detectSessionInUrl: false,
  },
});

let anonSignInPromise: Promise<string | null> | null = null;

async function ensureAnonSession(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.user?.id) return session.user.id;
  if (anonSignInPromise) return anonSignInPromise;
  anonSignInPromise = (async () => {
    const { data, error } = await supabase.auth.signInAnonymously();
    if (error) {
      console.warn('[ofe] anonymous sign-in failed:', error.message);
      anonSignInPromise = null;
      return null;
    }
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

export async function loadProfile(): Promise<Record<string, unknown> | null> {
  const id = await ensureAnonSession();
  if (!id) return null;

  const { data, error } = await supabase
    .from('profiles')
    .select('profile_data')
    .eq('id', id)
    .single();

  if (error || !data) return null;
  return data.profile_data as Record<string, unknown>;
}

export async function getFavorites(): Promise<Set<string>> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return new Set();

  const { data, error } = await supabase
    .from('favorites')
    .select('opportunity_id')
    .eq('device_id', deviceId);

  if (error || !data) return new Set();
  return new Set(data.map((r: { opportunity_id: string }) => r.opportunity_id));
}

export async function toggleFavorite(opportunityId: string, isFaved: boolean): Promise<boolean> {
  const deviceId = await ensureAnonSession();
  if (!deviceId) return isFaved;

  if (isFaved) {
    await supabase.from('favorites').delete().eq('device_id', deviceId).eq('opportunity_id', opportunityId);
    return false;
  } else {
    await supabase.from('favorites').insert({ device_id: deviceId, opportunity_id: opportunityId });
    return true;
  }
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
