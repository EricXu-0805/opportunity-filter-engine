import { describe, it, expect } from 'vitest';
import { loadPresets, savePresets, upsertPreset, removePreset } from './filter-presets';
import type { FilterPreset } from './filter-presets';

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
