import { afterEach, describe, it, expect } from 'vitest';
import {
  loadPresets,
  savePresets,
  upsertPreset,
  removePreset,
  parsePresetsArray,
} from './filter-presets';
import type { FilterPreset } from './filter-presets';

afterEach(() => {
  localStorage.clear();
});

const PRESET_A: FilterPreset = {
  id: 'p_a',
  name: 'Paid + Urgent',
  filters: { paid: 'yes', intl: '', source: '', onCampus: '', deadline: '7', minScore: 60 },
  sortBy: 'deadline',
  tab: 'all',
};

const PRESET_B: FilterPreset = {
  id: 'p_b',
  name: 'Intl Friendly Research',
  filters: { paid: '', intl: 'yes', source: '', onCampus: '', deadline: '', minScore: 0 },
  sortBy: 'score',
  tab: 'high_priority',
};

describe('loadPresets / savePresets', () => {
  it('returns empty array when localStorage is empty', () => {
    expect(loadPresets()).toEqual([]);
  });

  it('roundtrips a single preset', () => {
    savePresets([PRESET_A]);
    const loaded = loadPresets();
    expect(loaded).toHaveLength(1);
    expect(loaded[0]).toEqual(PRESET_A);
  });

  it('roundtrips multiple presets preserving order', () => {
    savePresets([PRESET_A, PRESET_B]);
    expect(loadPresets().map(p => p.id)).toEqual(['p_a', 'p_b']);
  });

  it('returns [] on malformed JSON', () => {
    localStorage.setItem('ofe_filter_presets', '{not json');
    expect(loadPresets()).toEqual([]);
  });

  it('returns [] when stored value is not an array', () => {
    localStorage.setItem('ofe_filter_presets', JSON.stringify({ some: 'object' }));
    expect(loadPresets()).toEqual([]);
  });

  it('filters out malformed entries inside the array', () => {
    localStorage.setItem(
      'ofe_filter_presets',
      JSON.stringify([
        PRESET_A,
        { id: 42 },
        null,
        { id: 'p_c', name: 'ok', filters: {} as unknown },
        'string entry',
      ]),
    );
    const loaded = loadPresets();
    const ids = loaded.map(p => p.id);
    expect(ids).toContain('p_a');
    expect(ids).toContain('p_c');
    expect(ids).not.toContain(42);
    expect(ids.length).toBe(2);
  });
});

describe('upsertPreset', () => {
  it('adds a new preset', () => {
    const out = upsertPreset([PRESET_A], PRESET_B);
    expect(out).toHaveLength(2);
  });

  it('replaces a preset with the same name', () => {
    const updated = { ...PRESET_A, id: 'p_a2', filters: { ...PRESET_A.filters, minScore: 80 } };
    const out = upsertPreset([PRESET_A], updated);
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe('p_a2');
    expect(out[0].filters.minScore).toBe(80);
  });
});

describe('removePreset', () => {
  it('removes a preset by id', () => {
    const out = removePreset([PRESET_A, PRESET_B], 'p_a');
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe('p_b');
  });

  it('is a no-op when id is not present', () => {
    const out = removePreset([PRESET_A], 'nonexistent');
    expect(out).toEqual([PRESET_A]);
  });
});

describe('parsePresetsArray', () => {
  it('returns the stable EMPTY reference for non-array input', () => {
    const a = parsePresetsArray(null);
    const b = parsePresetsArray({ not: 'an array' });
    const c = parsePresetsArray('string');
    const d = parsePresetsArray(undefined);
    expect(a).toEqual([]);
    expect(a).toBe(b);
    expect(b).toBe(c);
    expect(c).toBe(d);
  });

  it('returns the stable EMPTY reference when all entries are malformed', () => {
    const a = parsePresetsArray([null, 42, 'string', { id: 1 }]);
    const b = parsePresetsArray([]);
    expect(a).toEqual([]);
    expect(a).toBe(b);
  });

  it('returns only valid presets when input mixes good and bad entries', () => {
    const result = parsePresetsArray([
      PRESET_A,
      { id: 42 },
      null,
      PRESET_B,
      'garbage',
      { id: 'p_c', name: 'no filters' },
    ]);
    expect(result.map((p) => p.id)).toEqual(['p_a', 'p_b']);
  });

  it('roundtrips through savePresets + loadPresets so the new write path works', () => {
    savePresets([PRESET_A, PRESET_B]);
    const loaded = loadPresets();
    expect(loaded).toEqual([PRESET_A, PRESET_B]);
  });

  it('savePresets([]) removes the storage key (matches custom-imports pattern)', () => {
    savePresets([PRESET_A]);
    expect(localStorage.getItem('ofe_filter_presets')).not.toBeNull();
    savePresets([]);
    expect(localStorage.getItem('ofe_filter_presets')).toBeNull();
  });

  it('savePresets dispatches a storage event so same-tab readers re-render', () => {
    const fired: string[] = [];
    const listener = (e: StorageEvent) => fired.push(e.key ?? '');
    window.addEventListener('storage', listener);
    try {
      savePresets([PRESET_A]);
    } finally {
      window.removeEventListener('storage', listener);
    }
    expect(fired).toEqual(['ofe_filter_presets']);
  });
});
