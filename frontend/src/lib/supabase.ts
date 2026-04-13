import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://mjpirkyduibkakvlbdko.supabase.co';
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1qcGlya3lkdWlia2FrdmxiZGtvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYwNDE5OTEsImV4cCI6MjA5MTYxNzk5MX0.EiXIL8YaWOqfGvAASkfzJcg9VvYdF_mS4Ftn8Eiv2aE';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

function getDeviceId(): string {
  if (typeof window === 'undefined') return '';
  let id = localStorage.getItem('ofe_device_id');
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem('ofe_device_id', id);
  }
  return id;
}

export async function saveProfile(profileData: Record<string, unknown>): Promise<void> {
  const id = getDeviceId();
  if (!id) return;

  const { error } = await supabase
    .from('profiles')
    .upsert(
      { id, profile_data: profileData, updated_at: new Date().toISOString() },
      { onConflict: 'id' },
    );

  if (error) console.warn('Failed to sync profile:', error.message);
}

export async function loadProfile(): Promise<Record<string, unknown> | null> {
  const id = getDeviceId();
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
  const deviceId = getDeviceId();
  if (!deviceId) return new Set();

  const { data, error } = await supabase
    .from('favorites')
    .select('opportunity_id')
    .eq('device_id', deviceId);

  if (error || !data) return new Set();
  return new Set(data.map((r: { opportunity_id: string }) => r.opportunity_id));
}

export async function toggleFavorite(opportunityId: string, isFaved: boolean): Promise<boolean> {
  const deviceId = getDeviceId();
  if (!deviceId) return isFaved;

  if (isFaved) {
    await supabase.from('favorites').delete().eq('device_id', deviceId).eq('opportunity_id', opportunityId);
    return false;
  } else {
    await supabase.from('favorites').insert({ device_id: deviceId, opportunity_id: opportunityId });
    return true;
  }
}
