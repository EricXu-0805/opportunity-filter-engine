import { getDeviceId, supabase } from './supabase';

export interface SavedSearchFilters {
  paid: '' | 'yes' | 'no';
  intl: '' | 'yes' | 'no';
  source: string;
  onCampus: '' | 'yes' | 'no';
  deadline: '' | '7' | '14' | '30' | 'passed';
  minScore: number;
}

export type SortBy = 'score' | 'deadline' | 'newest';

export interface SavedSearch {
  id: string;
  name: string;
  query: string;
  filters: SavedSearchFilters;
  sort_by: SortBy;
  tab: string;
  created_at: string;
  updated_at: string;
}

export interface SavedSearchInput {
  name: string;
  query?: string;
  filters: SavedSearchFilters;
  sort_by?: SortBy;
  tab?: string;
}

interface SavedSearchRow {
  id: string;
  name: string;
  query: string;
  filters_json: SavedSearchFilters;
  sort_by: SortBy;
  tab: string;
  created_at: string;
  updated_at: string;
}

function rowToSearch(r: SavedSearchRow): SavedSearch {
  return {
    id: r.id,
    name: r.name,
    query: r.query,
    filters: r.filters_json,
    sort_by: r.sort_by,
    tab: r.tab,
    created_at: r.created_at,
    updated_at: r.updated_at,
  };
}

export async function listSavedSearches(): Promise<SavedSearch[]> {
  const deviceId = await getDeviceId();
  if (!deviceId) return [];

  const { data, error } = await supabase
    .from('saved_searches')
    .select('id, name, query, filters_json, sort_by, tab, created_at, updated_at')
    .eq('device_id', deviceId)
    .order('updated_at', { ascending: false });

  if (error || !data) {
    if (error && !error.message?.toLowerCase().includes('does not exist')) {
      console.warn('[ofe] listSavedSearches failed:', error.message);
    }
    return [];
  }

  return (data as SavedSearchRow[]).map(rowToSearch);
}

export async function saveSearch(input: SavedSearchInput): Promise<SavedSearch | null> {
  const deviceId = await getDeviceId();
  if (!deviceId) return null;

  const trimmedName = input.name.trim();
  if (!trimmedName) return null;

  const row = {
    device_id: deviceId,
    name: trimmedName.slice(0, 80),
    query: input.query ?? '',
    filters_json: input.filters,
    sort_by: input.sort_by ?? 'score',
    tab: input.tab ?? 'all',
  };

  const { data, error } = await supabase
    .from('saved_searches')
    .insert(row)
    .select('id, name, query, filters_json, sort_by, tab, created_at, updated_at')
    .single();

  if (error || !data) {
    console.warn('[ofe] saveSearch failed:', error?.message);
    return null;
  }

  return rowToSearch(data as SavedSearchRow);
}

export async function updateSavedSearch(
  id: string,
  patch: Partial<SavedSearchInput>,
): Promise<boolean> {
  const deviceId = await getDeviceId();
  if (!deviceId) return false;

  const row: Record<string, unknown> = { updated_at: new Date().toISOString() };
  if (patch.name !== undefined) {
    const trimmed = patch.name.trim();
    if (!trimmed) return false;
    row.name = trimmed.slice(0, 80);
  }
  if (patch.query !== undefined) row.query = patch.query;
  if (patch.filters !== undefined) row.filters_json = patch.filters;
  if (patch.sort_by !== undefined) row.sort_by = patch.sort_by;
  if (patch.tab !== undefined) row.tab = patch.tab;

  const { error } = await supabase
    .from('saved_searches')
    .update(row)
    .eq('device_id', deviceId)
    .eq('id', id);

  if (error) {
    console.warn('[ofe] updateSavedSearch failed:', error.message);
    return false;
  }
  return true;
}

export async function removeSavedSearch(id: string): Promise<boolean> {
  const deviceId = await getDeviceId();
  if (!deviceId) return false;

  const { error } = await supabase
    .from('saved_searches')
    .delete()
    .eq('device_id', deviceId)
    .eq('id', id);

  if (error) {
    console.warn('[ofe] removeSavedSearch failed:', error.message);
    return false;
  }
  return true;
}
