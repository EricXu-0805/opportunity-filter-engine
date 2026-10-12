import { describe, expect, it } from 'vitest';
import { importRedirectTarget, parseResourcesTab } from './resources-tab';

describe('parseResourcesTab', () => {
  it('selects Import only for tab=import and falls back to the guides', () => {
    expect(parseResourcesTab('import')).toBe('import');
    expect(parseResourcesTab(['import', 'guides'])).toBe('import');
    expect(parseResourcesTab(undefined)).toBe('guides');
    expect(parseResourcesTab('guides')).toBe('guides');
    expect(parseResourcesTab('IMPORT')).toBe('guides');
    expect(parseResourcesTab('')).toBe('guides');
  });
});

describe('importRedirectTarget', () => {
  it('sends a bare /import to the Resources page with the Import tab selected', () => {
    expect(importRedirectTarget({})).toBe('/resources?tab=import');
  });

  it('keeps every incoming query pair, repeated keys and encoding included', () => {
    expect(importRedirectTarget({ url: 'https://example.edu/a b?x=1&y=2', ref: ['one', 'two'] }))
      .toBe('/resources?url=https%3A%2F%2Fexample.edu%2Fa+b%3Fx%3D1%26y%3D2&ref=one&ref=two&tab=import');
  });

  it('lets the redirect decide the tab rather than an incoming tab value', () => {
    expect(importRedirectTarget({ tab: 'guides', lab: 'wet' })).toBe('/resources?lab=wet&tab=import');
  });
});
