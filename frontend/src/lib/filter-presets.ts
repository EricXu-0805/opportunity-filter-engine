export interface FilterPresetFilters {
  paid: '' | 'yes' | 'no';
  intl: '' | 'yes' | 'no';
  source: string;
  onCampus: '' | 'yes' | 'no';
  deadline: '' | '7' | '14' | '30' | 'passed';
  minScore: number;
}

export interface FilterPreset {
  id: string;
  name: string;
  filters: FilterPresetFilters;
  sortBy: 'score' | 'deadline' | 'newest';
  tab: string;
}

const PRESETS_KEY = 'ofe_filter_presets';

export function loadPresets(): FilterPreset[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(PRESETS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((p): p is FilterPreset =>
      p && typeof p.id === 'string' && typeof p.name === 'string' && p.filters,
    );
  } catch {
    return [];
  }
}

export function savePresets(presets: FilterPreset[]): void {
  try {
    localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
  } catch { /* quota */ }
}

export function upsertPreset(presets: FilterPreset[], preset: FilterPreset): FilterPreset[] {
  return [...presets.filter(p => p.name !== preset.name), preset];
}

export function removePreset(presets: FilterPreset[], id: string): FilterPreset[] {
  return presets.filter(p => p.id !== id);
}
