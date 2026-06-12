import { STORAGE_KEYS } from './storage-keys';
import { readLocalStorageJSON, writeLocalStorageJSON } from './use-local-storage-json';

export interface FilterPresetFilters {
  paid: '' | 'yes' | 'no';
  intl: '' | 'yes' | 'no';
  source: string;
  onCampus: '' | 'yes' | 'no';
  deadline: '' | '7' | '14' | '30' | 'passed';
  minScore: number;
  // Optional: presets saved before the discovery-scope facet shipped lack it.
  scope?: '' | 'campus' | 'open';
}

export interface FilterPreset {
  id: string;
  name: string;
  filters: FilterPresetFilters;
  sortBy: 'score' | 'deadline' | 'newest';
  tab: string;
}

const PRESETS_KEY = STORAGE_KEYS.FILTER_PRESETS;

// Stable empty-array sentinel so the transformer can return a referentially
// identical value for "no presets stored" across renders — required by
// useSyncExternalStore to avoid an infinite re-render loop.
const EMPTY_PRESETS: FilterPreset[] = [];

// Pure shape validator: drops entries that don't look like FilterPreset.
// Returns EMPTY_PRESETS (stable reference) when input is anything other
// than an array with at least one well-formed entry.
export function parsePresetsArray(raw: unknown): FilterPreset[] {
  if (!Array.isArray(raw)) return EMPTY_PRESETS;
  const valid = raw.filter((p): p is FilterPreset =>
    !!p
    && typeof (p as FilterPreset).id === 'string'
    && typeof (p as FilterPreset).name === 'string'
    && !!(p as FilterPreset).filters,
  );
  return valid.length === 0 ? EMPTY_PRESETS : valid;
}

export function loadPresets(): FilterPreset[] {
  return readLocalStorageJSON(PRESETS_KEY, parsePresetsArray);
}

export function savePresets(presets: FilterPreset[]): void {
  writeLocalStorageJSON(PRESETS_KEY, presets.length > 0 ? presets : null);
}

export function upsertPreset(presets: FilterPreset[], preset: FilterPreset): FilterPreset[] {
  return [...presets.filter(p => p.name !== preset.name), preset];
}

export function removePreset(presets: FilterPreset[], id: string): FilterPreset[] {
  return presets.filter(p => p.id !== id);
}
