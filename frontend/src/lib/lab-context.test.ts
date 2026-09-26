import { describe, expect, it } from 'vitest';
import fixture from '../../../tests/fixtures/lab-context-v1-golden.json';
import { parseLabContext, type LabContext } from './lab-context';
const source = () => structuredClone(fixture) as LabContext;
describe('website source contract', () => {
  it('preserves every paragraph and saved status without converting source access into reading', () => {
    const input = source(); const parsed = parseLabContext(input)!;
    expect(parsed).toEqual(input); expect(parsed.snapshot).not.toBe(input.snapshot);
    input.status = 'stale'; expect(parseLabContext(input)?.status).toBe('stale');
    expect(parseLabContext({version:1,status:'unavailable',snapshot:null})).not.toBeNull();
  });
  it('preserves Unicode codepoints at the exact section boundary', () => {
    const input = source(); input.snapshot!.pages[0].sections[0].text = '😀'.repeat(4000);
    expect(parseLabContext(input)).not.toBeNull();
    input.snapshot!.pages[0].sections[0].text += '😀'; expect(parseLabContext(input)).toBeNull();
  });
  it.each([
    (v:LabContext) => { (v as unknown as Record<string,unknown>).read = true; },
    (v:LabContext) => { v.status = 'unavailable'; },
    (v:LabContext) => { v.snapshot!.snapshot_version = 'rs1:' + 'a'.repeat(64); },
    (v:LabContext) => { v.snapshot!.checked_at = '2026-02-30T10:00:00Z'; },
    (v:LabContext) => { v.snapshot!.checked_at = '2026-09-26T24:00:00Z'; },
    (v:LabContext) => { v.snapshot!.checked_at = '2026-09-26T10:00:00+00:00'; },
    (v:LabContext) => { v.snapshot!.pages[0].source_url += '/someone-else'; },
    (v:LabContext) => { v.snapshot!.pages[0].sections[1].section_id = 's1'; },
    (v:LabContext) => { v.snapshot!.pages[0].sections[0].text = '   '; },
    (v:LabContext) => { v.snapshot!.pages[0].sections[0].text = '\u0000'; },
    (v:LabContext) => { v.snapshot!.pages[0].sections[0].text = '\ud800'; },
    (v:LabContext) => { v.snapshot!.pages[0].sections = []; },
    (v:LabContext) => { v.snapshot!.pages[0].sections = Array.from({length:7}, (_,i)=>({section_id:`s${i+1}`,heading:'',text:'x'.repeat(4000)})); },
    (v:LabContext) => { v.snapshot!.pages[0].kind = 'lab_website'; },
    (v:LabContext) => { v.snapshot!.pages.push(structuredClone(v.snapshot!.pages[0])); },
  ])('rejects malformed, truncated or conflicting source data %#', mutate => {
    const value = source(); mutate(value); expect(parseLabContext(value)).toBeNull();
  });
  it.each(['http://statistics.berkeley.edu/people/jane-doe','https://127.0.0.1/profile','https://[::1]/profile',
    'https://user:password@statistics.berkeley.edu/profile','https://statistics.berkeley.edu:443/profile',
    'https://statistics.berkeley.edu/people/jane-doe?','https://statistics.berkeley.edu/profile#bio',
    'https://statistics.berkeley.edu./profile','https://Statistics.berkeley.edu/profile','https://statistics.berkeley.edu/未编码',
    'https://statistics.berkeley.edu/a/../b', 'https://example.e-/', 'https://xn--example-9db.edu/', 'https://statistics.berkeley.edu/a^b', 'https://statistics.berkeley.edu', 'javascript:alert(1)', `https://${Array(4).fill('x'.repeat(63)).join('.')}.edu/`])('refuses noncanonical source URL %s', url => {
      const v = source(); v.snapshot!.record_source_url = url;
      v.snapshot!.pages[0].requested_url = url; v.snapshot!.pages[0].source_url = url;
      expect(parseLabContext(v)).toBeNull();
  });
  it('requires the second page to retain its actual profile link', () => {
    const v = source(); const s = v.snapshot!; const page = structuredClone(s.pages[0]);
    page.kind = 'lab_website'; page.requested_url = page.source_url = 'https://research.berkeley.edu/lab/';
    page.linked_from = {profile_url:s.record_source_url,anchor_text:'Research group',href:page.source_url}; s.pages.push(page);
    expect(parseLabContext(v)).not.toBeNull();
    page.linked_from.profile_url = 'https://statistics.berkeley.edu/people/other'; expect(parseLabContext(v)).toBeNull();
  });
});
