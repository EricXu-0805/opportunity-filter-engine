import { describe, it, expect } from 'vitest';
import { translate, resolvePath, interpolate, normalizeLocale, isLocale } from './translate';
import { dictionaries, en, zh } from './dictionaries';

describe('resolvePath', () => {
  it('resolves nested paths to strings', () => {
    expect(resolvePath(en as never, 'common.loading')).toBe('Loading...');
    expect(resolvePath(en as never, 'nav.findMatches')).toBe('Find Matches');
  });

  it('returns undefined for missing keys', () => {
    expect(resolvePath(en as never, 'nope.gone')).toBeUndefined();
    expect(resolvePath(en as never, 'common.nonexistent')).toBeUndefined();
  });

  it('returns undefined when path resolves to a non-string', () => {
    expect(resolvePath(en as never, 'common')).toBeUndefined();
    expect(resolvePath(en as never, 'nav')).toBeUndefined();
  });
});

describe('interpolate', () => {
  it('substitutes {name} variables', () => {
    expect(interpolate('Hello, {who}!', { who: 'Alice' })).toBe('Hello, Alice!');
  });

  it('handles multiple variables', () => {
    expect(interpolate('{a}+{b}={c}', { a: 1, b: 2, c: 3 })).toBe('1+2=3');
  });

  it('leaves missing variables as placeholders', () => {
    expect(interpolate('Hi {name}', {})).toBe('Hi {name}');
  });

  it('casts numbers to strings', () => {
    expect(interpolate('{n} items', { n: 42 })).toBe('42 items');
  });
});

describe('translate', () => {
  it('returns EN text for an EN locale', () => {
    expect(translate('en', 'nav.dashboard')).toBe('Dashboard');
  });

  it('returns ZH text for a ZH locale', () => {
    expect(translate('zh', 'nav.dashboard')).toBe('仪表盘');
  });

  it('falls back to EN when key missing in ZH', () => {
    const out = translate('zh', 'common.loading');
    expect(out).toBe('加载中...');
  });

  it('falls back to path when missing in both', () => {
    expect(translate('en', 'totally.fake.key')).toBe('totally.fake.key');
    expect(translate('zh', 'totally.fake.key')).toBe('totally.fake.key');
  });

  it('interpolates variables', () => {
    expect(translate('en', 'home.hero.oppCount', { count: 1234 })).toBe('1234 active opportunities');
    expect(translate('zh', 'home.hero.oppCount', { count: 1234 })).toBe('1234 个活跃机会');
  });
});

describe('normalizeLocale', () => {
  it('matches zh-CN, zh-TW etc to zh', () => {
    expect(normalizeLocale('zh-CN')).toBe('zh');
    expect(normalizeLocale('zh-TW')).toBe('zh');
    expect(normalizeLocale('zh-Hans')).toBe('zh');
  });

  it('matches en-US, en-GB to en', () => {
    expect(normalizeLocale('en-US')).toBe('en');
    expect(normalizeLocale('en-GB')).toBe('en');
  });

  it('defaults to en for unknown languages', () => {
    expect(normalizeLocale('fr')).toBe('en');
    expect(normalizeLocale('ja-JP')).toBe('en');
    expect(normalizeLocale('')).toBe('en');
    expect(normalizeLocale(undefined)).toBe('en');
  });
});

describe('isLocale', () => {
  it('accepts supported locales', () => {
    expect(isLocale('en')).toBe(true);
    expect(isLocale('zh')).toBe(true);
  });

  it('rejects unsupported / malformed', () => {
    expect(isLocale('fr')).toBe(false);
    expect(isLocale(42)).toBe(false);
    expect(isLocale(null)).toBe(false);
  });
});

describe('dictionary parity', () => {
  type DeepObj = { [k: string]: string | DeepObj };

  function collectKeys(obj: DeepObj, prefix = ''): string[] {
    const out: string[] = [];
    for (const k of Object.keys(obj)) {
      const full = prefix ? `${prefix}.${k}` : k;
      const v = obj[k];
      if (typeof v === 'string') {
        out.push(full);
      } else if (v && typeof v === 'object') {
        out.push(...collectKeys(v, full));
      }
    }
    return out;
  }

  it('zh has all keys that en has', () => {
    const enKeys = collectKeys(en as never).sort();
    const zhKeys = collectKeys(zh as never).sort();
    const missing = enKeys.filter(k => !zhKeys.includes(k));
    expect(missing).toEqual([]);
  });

  it('en has all keys that zh has', () => {
    const enKeys = collectKeys(en as never).sort();
    const zhKeys = collectKeys(zh as never).sort();
    const missing = zhKeys.filter(k => !enKeys.includes(k));
    expect(missing).toEqual([]);
  });

  it('dictionaries object exposes both locales', () => {
    expect(dictionaries.en).toBeDefined();
    expect(dictionaries.zh).toBeDefined();
  });

  it('every ZH value containing {var} also contains it in EN', () => {
    const enKeys = collectKeys(en as never);
    for (const k of enKeys) {
      const enVal = translate('en', k);
      const zhVal = translate('zh', k);
      const enVars = enVal.match(/\{(\w+)\}/g) ?? [];
      const zhVars = zhVal.match(/\{(\w+)\}/g) ?? [];
      expect(new Set(zhVars), `placeholders mismatch at ${k}`).toEqual(new Set(enVars));
    }
  });
});
