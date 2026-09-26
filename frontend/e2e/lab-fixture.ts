import { createHash } from 'node:crypto';
import type { LabContext } from '../src/lib/lab-context';
// Synthetic historical/public snapshot for UI acceptance only. This does not
// claim that the reviewed collector supports this school or website template.
export const LAB_TITLE = 'Synthetic laboratory source 王🧪';
export const LAB_TEXT = 'The laboratory studies instrument calibration and experimental design.\nThis entire second paragraph belongs to the laboratory, not the student. 官网完整段落😀用于相关性。';
const canonical = (value: unknown): string => Array.isArray(value) ? `[${value.map(canonical).join(',')}]`
  : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical((value as Record<string,unknown>)[k])}`).join(',')}}` : JSON.stringify(value);
export function labFixture(status: 'available' | 'stale' = 'available', suffix = ''): LabContext {
  const url = 'https://example.edu/synthetic-researcher';
  const snapshot = { version: 1 as const, source: 'official_website' as const, record_id: 'uiuc-siebel-ugresearch', record_source_url: url,
    school: 'uiuc', department: 'Synthetic Department', identity_name: 'Synthetic Researcher', policy_version: 1 as const,
    checked_at: new Date(Date.now() - (status === 'stale' ? 40 * 86400000 : 60000)).toISOString().replace(/\.\d{3}Z$/, 'Z'),
    pages: [{ kind: 'faculty_profile' as const, requested_url: url, source_url: url, page_title: LAB_TITLE,
      identity_text: 'Synthetic Researcher', linked_from: null, sections: [{ section_id: 's1', heading: 'Laboratory methods 官网研究', text: LAB_TEXT + suffix }] }],
  };
  return { version: 1, status, snapshot: { ...snapshot, snapshot_version: 'ls1:' + createHash('sha256').update(canonical(snapshot)).digest('hex') } };
}
