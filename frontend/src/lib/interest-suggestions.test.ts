import { describe, expect, it } from 'vitest';

import { suggestInterests } from './interest-suggestions';

describe('suggestInterests', () => {
  it('falls back to the corpus-wide top domains when nothing is known', () => {
    const generic = suggestInterests();
    expect(generic).toContain('Machine Learning');
    expect(generic).toContain('Quantitative Finance');
    expect(generic.length).toBeLessThanOrEqual(12);
  });

  it('narrows to the field of the selected major', () => {
    const bio = suggestInterests('Molecular & Cellular Biology');
    expect(bio).toContain('Genomics');
    expect(bio).toContain('Neuroscience');
    expect(bio).not.toContain('Quantitative Finance');

    const econ = suggestInterests('Economics');
    expect(econ).toContain('Economics');
    expect(econ).toContain('Quantitative Finance');
    expect(econ).not.toContain('Genomics');
  });

  it('merges and de-duplicates across multiple matched fields', () => {
    const compEng = suggestInterests('Computer Engineering');
    // hits both the CS and ECE groups
    expect(compEng).toContain('Machine Learning');
    expect(compEng).toContain('Embedded Systems');
    expect(new Set(compEng).size).toBe(compEng.length); // no duplicates
    expect(compEng.length).toBeLessThanOrEqual(12);
  });

  it('uses the college only as a fallback when the major is blank', () => {
    const withCollege = suggestInterests('', 'Chemistry');
    expect(withCollege).toContain('Organic Chemistry');
  });

  it('lets a specific major override a broad college name', () => {
    // A Chemistry major in "Liberal Arts & Sciences" gets chemistry chips, not
    // humanities chips — the college is ignored once the major matches.
    const chem = suggestInterests('Chemistry', 'Liberal Arts & Sciences');
    expect(chem).toContain('Organic Chemistry');
    expect(chem).not.toContain('Music');
  });
});
