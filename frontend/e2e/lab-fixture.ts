import { createHash } from 'node:crypto';
import type { LabContext, LabSnapshotV2 } from '../src/lib/lab-context';
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

export const LAB_CHAIN_TITLE = 'Synthetic lab research 王🧪';
export const LAB_CHAIN_LAST = 'Final complete research section. This is laboratory work, not the student’s experience. 第十节完整结尾😀。';
/** UI/history fixture on a different origin from the live Nielsen collector.
 * It proves generic historical parsing; it does not grant current collection. */
export function labChainFixture(status: 'available' | 'stale' = 'available', suffix = ''): LabContext & {snapshot: LabSnapshotV2} {
  const previous = labFixture(status).snapshot!;
  const profile = previous.record_source_url, home = 'https://synthetic-lab.example/';
  const checked = previous.checked_at;
  const pages: LabSnapshotV2['pages'] = [structuredClone(previous.pages[0]), {
    kind: 'lab_research', requested_url: home + 'research/', source_url: home + 'research/', page_title: LAB_CHAIN_TITLE,
    sections: Array.from({length: 10}, (_,i) => ({section_id:`s${i+1}`,heading:`Research topic ${i+1} 研究`,text: i===9 ? LAB_CHAIN_LAST + suffix : `Laboratory section ${i+1}. We preserve the whole paragraph, including limitations. 完整段落😀。` + suffix})),
  }];
  const documents: LabSnapshotV2['source_chain']['documents'] = [
    {role:'profile',requested_url:profile,source_url:profile,page_title:pages[0].page_title,checked_at:checked,body_sha256:'a'.repeat(64)},
    {role:'home',requested_url:home,source_url:home,page_title:'Synthetic lab homepage',checked_at:checked,body_sha256:'b'.repeat(64)},
    {role:'team',requested_url:home+'team/',source_url:home+'team/',page_title:'Synthetic lab team',checked_at:checked,body_sha256:'c'.repeat(64)},
    {role:'research',requested_url:home+'research/',source_url:home+'research/',page_title:pages[1].page_title,checked_at:checked,body_sha256:'d'.repeat(64)},
  ];
  const stored: Omit<LabSnapshotV2,'snapshot_version'> = {
    version:2,policy_version:2,source:'official_website',record_id:previous.record_id,record_source_url:profile,
    school:previous.school,department:previous.department,identity_name:previous.identity_name,checked_at:checked,pages,
    source_chain:{documents,links:[
      {from_url:profile,raw_href:home.slice(0,-1),anchor_text:'Lab website',to_url:home},
      {from_url:home,raw_href:'/team/',anchor_text:'Team',to_url:home+'team/'},
      {from_url:home,raw_href:'/research/',anchor_text:'Research',to_url:home+'research/'},
    ],identity:{source_url:home+'team/',full_name:previous.identity_name,role_text:'Professor in the Synthetic Department; website identity only.'}},
  };
  return {version:1,status,snapshot:{...stored,snapshot_version:'ls2:'+createHash('sha256').update(canonical(stored)).digest('hex')}};
}
