import { describe, it, expect } from 'vitest';
import { translate, resolvePath, interpolate, normalizeLocale, isLocale } from './translate';
import { dictionaries, en, zh } from './dictionaries';
import { sourceLabel } from '@/app/results/types';

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

  it('resolves keys that contain literal dots via exact-key match', () => {
    expect(resolvePath(zh as never, 'colleges.Michael G. Foster School of Business')).toBe('福斯特商学院');
    expect(resolvePath(en as never, 'colleges.Lyndon B. Johnson School of Public Affairs')).toBe(
      'Lyndon B. Johnson School of Public Affairs',
    );
  });

  it('still returns undefined for dotted keys absent from the namespace', () => {
    expect(resolvePath(en as never, 'colleges.No Such J. School')).toBeUndefined();
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

  it('translates non-UIUC catalog names under zh (UCB spot check)', () => {
    expect(translate('zh', 'majors.Electrical Engineering & Computer Sciences')).toBe('电气工程与计算机科学');
    expect(translate('zh', 'colleges.College of Letters and Science')).toBe('文理学院');
    expect(translate('en', 'majors.Electrical Engineering & Computer Sciences')).toBe(
      'Electrical Engineering & Computer Sciences',
    );
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

  it('publication strings resolve in both locales', () => {
    for (const key of [
      'card.recentWork',
      'detail.sections.recentWorks',
      'detail.recentWorksNote',
    ]) {
      expect(translate('en', key)).not.toBe(key);
      expect(translate('zh', key)).not.toBe(key);
      expect(translate('en', key)).not.toBe(translate('zh', key));
    }
  });

  it('retired unverified-publication labels stay gone (trust boundary)', () => {
    // The publication trust boundary EXCLUDES unverified works instead of
    // labeling them; resurrecting a label key would signal a fail-open UI.
    for (const key of [
      'card.recentWorkNameMatch',
      'detail.recentWorksNameMatch',
      'detail.recentWorksNoteUnverified',
    ]) {
      expect(translate('en', key)).toBe(key);
      expect(translate('zh', key)).toBe(key);
    }
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

// A student reads the source of every card and every filter row. The
// per-school label map covers 81 of the 329 slugs in the corpus, so the
// remaining 89.7% of records are named by composing the school's catalog name
// with one of four kind phrases — and both halves have to exist in both
// locales for that to read as a name rather than as a slug.
describe('composed source labels read as names in both locales', () => {
  const real = (locale: 'en' | 'zh') => (key: string) => translate(locale, key);

  it('names the school and the kind in English', () => {
    const t = real('en');
    expect(sourceLabel('jhu_faculty', t)).toBe('Johns Hopkins Faculty');
    expect(sourceLabel('uw_external_research', t)).toBe('UW Research (External / REU)');
    expect(sourceLabel('utexas_research_programs', t)).toBe('UT Austin Research Programs');
    expect(sourceLabel('wisc_labs', t)).toBe('UW–Madison Labs & Institutes');
  });

  it('names the school and the kind in Chinese', () => {
    const t = real('zh');
    expect(sourceLabel('jhu_faculty', t)).toBe('Johns Hopkins 教授');
    expect(sourceLabel('uw_external_research', t)).toBe('UW 校外研究（REU）');
    expect(sourceLabel('utexas_research_programs', t)).toBe('UT Austin 研究项目');
    expect(sourceLabel('wisc_labs', t)).toBe('UW–Madison 实验室与研究所');
  });

  it('never leaves a kind phrase untranslated in either locale', () => {
    for (const locale of ['en', 'zh'] as const) {
      for (const kind of ['faculty', 'research_programs', 'labs', 'external_research']) {
        const label = sourceLabel(`jhu_${kind}`, real(locale));
        expect(label.startsWith('Johns Hopkins ')).toBe(true);
        expect(label).not.toContain('results.filters.');
      }
    }
  });
});

// Three admin tables rendered nine, five and four blank column headers for
// months because t() was called on a dictionary subtree — which resolves to
// no string — and the tests handed back an object the real translator never
// produces. These assert against the real dictionary in both locales.
describe('admin table column headers resolve', () => {
  const GROUPS: Record<string, string[]> = {
    'admin.bySourceCols': [
      'source', 'total', 'emptyMajors', 'emptyKeywords', 'rolling',
      'missingDeadline', 'past', 'inactive', 'unreviewedRecordKind',
    ],
    'admin.collectorStatusCols': ['source', 'status', 'fetched'],
    'admin.worstFieldsCols': ['title', 'fields', 'source'],
  };

  it('every column name is a real string in en and zh', () => {
    for (const locale of ['en', 'zh'] as const) {
      for (const [group, names] of Object.entries(GROUPS)) {
        for (const name of names) {
          const value = translate(locale, `${group}.${name}`);
          expect(value, `${locale} ${group}.${name}`).not.toBe(`${group}.${name}`);
          expect(value.trim().length, `${locale} ${group}.${name}`).toBeGreaterThan(0);
        }
      }
      // And the subtree itself is NOT a usable label — the shape of the bug.
      for (const group of Object.keys(GROUPS)) {
        expect(translate(locale, group)).toBe(group);
      }
    }
  });
});
