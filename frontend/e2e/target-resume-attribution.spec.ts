import { test, expect, request as apiRequest, type Page, type TestInfo } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { inflateRawSync } from 'node:zlib';
import { researchFixture, RESEARCH_TITLE, RESEARCH_ABSTRACT } from './research-fixture';
import { labFixture, LAB_TITLE, LAB_TEXT } from './lab-fixture';
import type { LabContext } from '../src/lib/lab-context';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { FULL_TARGET_AI_VERSION, type TargetResumeAiRequest, type TargetResumeAiResponse, type TargetResumeAiEvidence } from '../src/lib/target-resume-ai-protocol';
import { isCurrentTargetResumeContext, type TargetResumeV1 } from '../src/lib/target-resume';
import type { ProfileData, ResumeFact, ResumeMasterV1 } from '../src/lib/types';
import type { TargetResumeExportRequest } from '../src/lib/target-resume-export-protocol';

// Browser acceptance of already-checked receipts, followed by real local file
// rendering. Server semantic rejection is covered separately by route tests;
// this fixture must never be described as an end-to-end real-model evaluation.
const TARGET = 'uiuc-siebel-ugresearch';
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const FRONTEND = `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}`;
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8100);
const BACKEND = `http://127.0.0.1:${BACKEND_PORT}`;
const RESEARCH_PROXY = `http://127.0.0.1:${Number(process.env.E2E_RESEARCH_PROXY_PORT ?? BACKEND_PORT + 1)}`;
const RAW_PRIVATE = 'RAW PRIVATE MASTER — not a visible résumé field';
const NAME = 'Attribution student 王';
const MANUAL_NAME = 'Attribution student 王 — explicitly edited by the user';
const BAD_CLAIM = 'I built a Python parser.';
const ORIGINAL = {
  'team-role': 'My role: I wrote parser tests. Outcome: My team built a Python parser. I did not build the parser.',
  'readings-role': 'Compared instrument readings; I assisted and did not lead the project.',
  'calibration-role': 'Documented the final calibration procedure.',
};
const PROPOSED: Record<string, string> = {
  'readings-role': 'Assisted with comparing instrument readings; I did not lead the project.',
  'calibration-role': 'The final calibration procedure was documented by me.',
};
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
const compact = (text: string) => text.replace(/\s/gu, '');
const exportPanel = (page: Page) => page.getByRole('region', { name: 'Export current résumé', exact: true });
const aiPanel = (page: Page) => page.getByRole('region', { name: 'AI adaptation suggestions', exact: true });
const lines = (draft: TargetResumeV1) => draft.document.sections.flatMap(section => section.blocks.flatMap(block => block.lines.map(line => ({ section, block, line }))));
function profile(): ProfileData {
  const master: ResumeMasterV1 = { version: 1, id: 'attribution-master', revision: 1, source_signature: null,
    basics: { name: fact('name', NAME), email: fact('email', 'synthetic@fixture.invalid'), links: [] },
    education: [{ id: 'education', school: fact('school', 'Example University'), details: [] }],
    activities: Object.keys(ORIGINAL).map((id, index) => ({ id: `project-${index}`, kind: 'project', title: fact(`title-${index}`, `Project ${index + 1}`), details: [{ id, revision: 1 }] })),
    publications: [], skills: [], other_sections: [], section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [],
  };
  return { institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore', name: NAME,
    is_international: false, research_interests: 'instrumentation', seeking_types: ['research'], skills: [], coursework: [], resume_text: RAW_PRIVATE, resume_master: master,
    experience_entries: Object.entries(ORIGINAL).map(([id, text]) => ({ id, text, revision: 1, status: 'confirmed', source: { kind: 'manual' } })),
  };
}
async function account() {
  for (const endpoint of [STUB, FRONTEND, BACKEND]) {
    const url = new URL(endpoint); expect(url.hostname).toBe('127.0.0.1');
    expect(Number(url.port)).toBeGreaterThanOrEqual(1024); expect(Number(url.port)).toBeLessThanOrEqual(65535);
  }
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(`${STUB}/auth/v1/signup`, { data: {} }); expect(signup.status()).toBe(200);
    const session = await signup.json();
    // Only the loopback stub accepts these synthetic formal-user claims.
    session.user = { ...session.user, is_anonymous: false, email: 'attribution@fixture.invalid', app_metadata: { provider: 'email', providers: ['email'] } };
    const token = session.access_token.split('.');
    token[1] = Buffer.from(JSON.stringify({ ...JSON.parse(Buffer.from(token[1], 'base64url').toString()), is_anonymous: false })).toString('base64url');
    session.access_token = token.join('.');
    const value = profile();
    const result = await http.post(`${STUB}/rest/v1/rpc/commit_profile_patch_cas`, { headers: { Authorization: `Bearer ${session.access_token}` }, data: {
      p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: value,
    } });
    expect(result.status()).toBe(200); expect(await result.json()).toMatchObject({ status: 'applied', revision: 1 });
    return { http, session, profile: value };
  } catch (error) { await http.dispose(); throw error; }
}
function targetEvidence(draft: TargetResumeV1): TargetResumeAiEvidence {
  if (isCurrentTargetResumeContext(draft.target_snapshot) && draft.target_snapshot.lab.status === 'available') {
    const source = draft.target_snapshot.lab.snapshot!.pages[0].sections[0].text;
    return { field: 'lab_text', page_index: 0, section_index: 0, start: 0, end: Array.from(source).length, quote: source };
  }
  if (isCurrentTargetResumeContext(draft.target_snapshot) && draft.target_snapshot.research.status === 'available') {
    const source = draft.target_snapshot.research.snapshot!.works[0].abstract!;
    return { field: 'paper_abstract', paper_index: 0, start: 0, end: Array.from(source).length, quote: source };
  }
  const description = Array.from(draft.target_snapshot.description);
  if (description.length) return { field: 'description', requirement_index: null, start: 0, end: Math.min(description.length, 80), quote: description.slice(0, 80).join('') };
  const index = draft.target_snapshot.requirements.findIndex(value => value.length > 0); expect(index).toBeGreaterThanOrEqual(0);
  const quote = Array.from(draft.target_snapshot.requirements[index]);
  return { field: 'requirement', requirement_index: index, start: 0, end: Math.min(quote.length, 80), quote: quote.slice(0, 80).join('') };
}
function checkedReply(request: TargetResumeAiRequest): TargetResumeAiResponse {
  const units = lines(request.draft).filter(unit => unit.section.kind !== 'basics');
  const selected = units.filter(unit => request.selected_unit_ids.includes(unit.line.id));
  expect(selected.some(unit => unit.line.evidence.id === 'team-role')).toBe(true);
  return { version: 1, check_version: 'target-resume-source-checks-v2', pipeline_version: FULL_TARGET_AI_VERSION, request_id: request.request_id, document_id: request.draft.id,
    opportunity_id: TARGET, document_signature: request.document_signature, base: structuredClone(request.draft.base),
    manifest: { unit_ids: units.map(unit => unit.line.id), protected_unit_count: lines(request.draft).filter(unit => unit.section.kind === 'basics').length },
    method: 'partial', logical_calls: 1, provider_attempts_upper_bound: 2,
    receipts: selected.map(({ section, block, line }) => {
      const common = { unit_id: line.id, section_id: section.id, block_id: block.id, evidence: { ...line.evidence }, before_text: line.text };
      if (line.evidence.id === 'team-role') return { ...common, status: 'skipped', reason_code: 'ungrounded_rewrite', suggestion: null };
      return { ...common, status: 'suggested', reason_code: null, suggestion: { priority: 'normal', reason: 'Preserve the stated role while clarifying the wording.', target_evidence: [targetEvidence(request.draft)], proposed_text: PROPOSED[line.evidence.id] ?? null } };
    }),
  };
}
async function setup(page: Page, info: TestInfo, research?: 'available' | 'stale', labStatus?: 'available' | 'stale') {
  const owner = await account(); const zh = info.project.name === 'mobile-chrome';
  const copy = (en: string, cn: string) => zh ? cn : en;
  if (zh) await page.setViewportSize({ width: 390, height: 844 });
  const audit = { external: [] as string[], pageErrors: [] as string[], consoleErrors: [] as string[], unexpectedWriting: [] as string[],
    badResponses: [] as { path: string; status: number }[], networkFailures: [] as { path: string; error: string | null }[],
    suggestions: [] as TargetResumeAiRequest[], exports: [] as TargetResumeExportRequest[], writes: [] as { path: string; body: Record<string, unknown> }[], reads: [] as string[] };
  await page.context().route('**/*', route => {
    const url = new URL(route.request().url());
    if (![FRONTEND, BACKEND, STUB].includes(url.origin)) { audit.external.push(url.origin); return route.abort('blockedbyclient'); }
    if (/^\/api\/(cold-email|tailor)/.test(url.pathname)) { audit.unexpectedWriting.push(url.pathname); return route.abort('blockedbyclient'); }
    return route.continue();
  });
  page.on('pageerror', error => audit.pageErrors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') audit.consoleErrors.push(message.text()); });
  page.on('requestfailed', request => audit.networkFailures.push({ path: new URL(request.url()).pathname, error: request.failure()?.errorText ?? null }));
  page.on('response', response => { if (response.status() >= 400) audit.badResponses.push({ path: new URL(response.url()).pathname, status: response.status() }); });
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path === '/api/resume/full-target/export') audit.exports.push(request.postDataJSON());
    if (request.method() !== 'GET' && /\/rest\/v1\//.test(path)) audit.writes.push({ path, body: request.postDataJSON() });
    if (request.method() === 'GET' && /target_resume/.test(path)) audit.reads.push(path);
  });
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: zh ? 'zh' : 'en', url: FRONTEND }]);
  await page.addInitScript(({ session, keys, locale }) => {
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale); localStorage.setItem(keys.ONBOARDING_SEEN, '1');
  }, { session: owner.session, keys: STORAGE_KEYS, locale: zh ? 'zh' : 'en' });
  await page.route('**/auth/v1/user', route => route.fulfill({ json: owner.session.user }));
  await page.route('**/auth/v1/token?grant_type=refresh_token', route => route.fulfill({ json: owner.session }));
  await page.route('**/api/tailor/full-target/suggestions', route => {
    expect(route.request().method()).toBe('POST');
    const request = route.request().postDataJSON() as TargetResumeAiRequest; audit.suggestions.push(request);
    expect(request.draft.opportunity_id).toBe(TARGET);
    return route.fulfill({ json: checkedReply(request) });
  });
  const material = research ? researchFixture(research) : null;
  let labMaterial: LabContext | null = labStatus ? labFixture(labStatus) : null;
  const updateLab = async (next: LabContext) => {
    const response = await owner.http.post(`${RESEARCH_PROXY}/__fixture/lab/${TARGET}`, { data: { lab_context: next } });
    expect(response.status()).toBe(200); expect(await response.json()).toEqual({ lab_context: next }); labMaterial = next;
  };
  if (labMaterial) await updateLab(labMaterial);
  if (material) {
    const health = await owner.http.get(`${RESEARCH_PROXY}/__fixture/health`);
    expect(health.status()).toBe(200);
    expect(await health.json()).toEqual({ fixture: 'research-detail-proxy', upstream: BACKEND });
    const configured = await owner.http.post(`${RESEARCH_PROXY}/__fixture/research/${TARGET}`, { data: { research_context: material } });
    expect(configured.status()).toBe(200); expect(await configured.json()).toEqual({ research_context: material });
    // Next SSR reads the runtime fixture proxy. Production browser rewrites
    // were built for the real local backend,
    // so route its detail GET to the same controlled response without fetching
    // an external source or altering production data.
  }
  if (material || labMaterial) {
    await page.route(url => url.pathname === `/api/opportunities/${TARGET}`, async route => {
      const url = new URL(route.request().url());
      const response = await route.fetch({ url: `${RESEARCH_PROXY}${url.pathname}${url.search}`, maxRetries: 0 });
      expect(response.status()).toBe(200);
      const value = await response.json(); if (material) expect(value.research_context).toEqual(material); if (labMaterial) expect(value.lab_context).toEqual(labMaterial);
      await route.fulfill({ response });
    });
  }
  const modal = page.getByRole('dialog', { name: copy('Target résumé', '目标简历'), exact: true });
  const editor = (id: string) => modal.locator(`textarea[id$="-${id}"]`);
  const open = async () => {
    await page.goto(`/opportunities/${TARGET}`);
    if (research) await expect(page.getByRole('link', { name: RESEARCH_TITLE, exact: true }).first()).toHaveAttribute('href', 'https://doi.org/10.1234/synthetic-instrument-study');
    await page.getByRole('button', { name: copy('Renovate Resume', '简历翻新'), exact: true }).click();
    await expect(modal).toBeVisible();
    await modal.getByRole('button', { name: copy('Create from confirmed master', '从已确认母版创建'), exact: true }).click();
    await expect(modal.getByRole('textbox', { name: copy('Edit Full name', '编辑 姓名'), exact: true })).toHaveValue(NAME);
  };
  const save = async (revision: number, restore = false) => {
    const label = restore ? copy('Restore selected version as a new save', '将所选版本另存为新版本') : copy('Save target draft', '保存目标文稿');
    const button = modal.getByRole('button', { name: label, exact: true }); await expect(button).toBeEnabled();
    const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/rpc/commit_target_resume_with_provenance_cas'
      && response.request().postDataJSON().p_expected_revision === revision);
    await button.click(); const response = await pending; expect(response.status()).toBe(200);
    const result = await response.json(); expect(result).toMatchObject({ status: 'saved', revision: revision + 1 });
    await expect(modal.getByText(`${copy('Saved version', '已保存版本')} ${revision + 1}`, { exact: true })).toBeVisible();
    return result.doc as TargetResumeV1;
  };
  const done = async () => {
    try {
      if (material) {
        const observed = await owner.http.get(`${RESEARCH_PROXY}/__fixture/research/${TARGET}`);
        expect(observed.status()).toBe(200);
        const fixture = await observed.json();
        await info.attach('research-ssr-fixture-audit', { body: JSON.stringify(fixture, null, 2), contentType: 'application/json' });
        expect(fixture.research_context).toEqual(material);
      }
      if (labMaterial) {
        const observed = await owner.http.get(`${RESEARCH_PROXY}/__fixture/lab/${TARGET}`); expect(observed.status()).toBe(200);
        const value = await observed.json(); expect(value.lab_context).toEqual(labMaterial);
        await info.attach('lab-ssr-fixture-audit', { body: JSON.stringify(value, null, 2), contentType: 'application/json' });
      }
      await info.attach('attribution-flow-audit', { body: JSON.stringify(audit, null, 2), contentType: 'application/json' });
    } finally {
      if (material) { const cleared = await owner.http.delete(`${RESEARCH_PROXY}/__fixture/research/${TARGET}`); expect(cleared.status()).toBe(200); }
      if (labMaterial) { const cleared = await owner.http.delete(`${RESEARCH_PROXY}/__fixture/lab/${TARGET}`); expect(cleared.status()).toBe(200); }
      await owner.http.dispose();
    }
    expect(audit.external).toEqual([]); expect(audit.pageErrors).toEqual([]); expect(audit.unexpectedWriting).toEqual([]); expect(audit.badResponses).toEqual([]);
    for (const write of audit.writes.filter(item => item.path !== '/rest/v1/rpc/commit_target_resume_with_provenance_cas')) {
      expect(write.path).toBe('/rest/v1/analytics_events');
      expect(write.body).toEqual({ device_id: owner.session.user.id, event: 'match_opened', props: { opportunity_id: TARGET } });
    }
  };
  return { owner, zh, copy, audit, modal, editor, open, save, done, updateLab };
}
async function downloadFile(page: Page, format: 'pdf' | 'docx', info: TestInfo, stem: string, zh: boolean) {
  const pending = page.waitForEvent('download');
  await exportPanel(page).getByRole('button', { name: format === 'pdf' ? (zh ? '导出 PDF' : 'Export PDF') : (zh ? '导出 Word' : 'Export Word'), exact: true }).click();
  const download = await pending; expect(download.suggestedFilename()).toBe(`resume-${zh ? 'zh' : 'en'}.${format}`);
  const path = info.outputPath(`${stem}.${format}`); await download.saveAs(path); expect(await download.failure()).toBeNull();
  const bytes = await readFile(path); expect(bytes.length).toBeGreaterThan(100);
  await info.attach(`${stem}.${format}`, { path, contentType: format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
  return bytes;
}

async function readPdf(bytes: Buffer) {
  const { getDocument } = await import('pdfjs-dist/legacy/build/pdf.mjs');
  const task = getDocument({ data: new Uint8Array(bytes), useSystemFonts: false, isEvalSupported: false, disableFontFace: true });
  const pdf = await task.promise;
  try {
    const pages: string[] = [], links: string[] = [], sizes: number[][] = [];
    for (let number = 1; number <= pdf.numPages; number += 1) {
      const page = await pdf.getPage(number);
      const text = await page.getTextContent();
      pages.push(text.items.flatMap(item => 'str' in item ? [item.str] : []).join(''));
      sizes.push([page.view[2] - page.view[0], page.view[3] - page.view[1]]);
      for (const annotation of await page.getAnnotations()) if (typeof annotation.url === 'string') links.push(annotation.url);
    }
    return { text: pages.join('\n'), pages, links, sizes };
  } finally { await task.destroy(); }
}

// Read standard ZIP central-directory entries with Node built-ins. This checks
// the renderer's actual OOXML, not a second copy of its formatting algorithm.
function zipEntries(bytes: Buffer): Map<string, Buffer> {
  const end = bytes.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  expect(end).toBeGreaterThanOrEqual(0);
  const count = bytes.readUInt16LE(end + 10);
  let offset = bytes.readUInt32LE(end + 16);
  const entries = new Map<string, Buffer>();
  for (let i = 0; i < count; i += 1) {
    expect(bytes.readUInt32LE(offset)).toBe(0x02014b50);
    const method = bytes.readUInt16LE(offset + 10), size = bytes.readUInt32LE(offset + 20);
    const nameLength = bytes.readUInt16LE(offset + 28), extraLength = bytes.readUInt16LE(offset + 30), commentLength = bytes.readUInt16LE(offset + 32);
    const local = bytes.readUInt32LE(offset + 42);
    const name = bytes.subarray(offset + 46, offset + 46 + nameLength).toString('utf8');
    expect(bytes.readUInt32LE(local)).toBe(0x04034b50);
    const start = local + 30 + bytes.readUInt16LE(local + 26) + bytes.readUInt16LE(local + 28);
    const compressed = bytes.subarray(start, start + size);
    expect([0, 8]).toContain(method);
    entries.set(name, method === 0 ? compressed : inflateRawSync(compressed, { maxOutputLength: 64 * 1024 * 1024 }));
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function readDocx(page: Page, bytes: Buffer) {
  const entries = zipEntries(bytes);
  const documentXml = entries.get('word/document.xml')?.toString('utf8');
  expect(documentXml).toBeTruthy();
  const data = await page.evaluate(({ documentXml, relationships, settings, fonts }) => {
    const parser = new DOMParser();
    const parse = (xml: string) => {
      const doc = parser.parseFromString(xml, 'application/xml');
      if (doc.getElementsByTagName('parsererror').length) throw new Error('Invalid exported XML');
      return doc;
    };
    const w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
    const doc = parse(documentXml);
    const nodeText = (node: Node): string => {
      if (node.nodeType === Node.ELEMENT_NODE) {
        const element = node as Element;
        if (element.namespaceURI === w) {
          if (element.localName === 't') return element.textContent ?? '';
          if (element.localName === 'tab') return '\t';
          if (element.localName === 'br' || element.localName === 'cr') return '\n';
        }
      }
      return Array.from(node.childNodes).map(nodeText).join('');
    };
    return {
      paragraphs: Array.from(doc.getElementsByTagNameNS(w, 'p')).map(nodeText),
      textRuns: doc.getElementsByTagNameNS(w, 't').length,
      links: Array.from(parse(relationships).getElementsByTagName('Relationship'))
        .filter(item => item.getAttribute('Type')?.endsWith('/hyperlink')).map(item => item.getAttribute('Target')),
      protected: parse(settings).getElementsByTagNameNS(w, 'documentProtection').length,
      embedded: parse(fonts).getElementsByTagNameNS(w, 'embedRegular').length,
    };
  }, { documentXml: documentXml!, relationships: entries.get('word/_rels/document.xml.rels')!.toString('utf8'),
    settings: entries.get('word/settings.xml')!.toString('utf8'), fonts: entries.get('word/fontTable.xml')!.toString('utf8') });
  expect(data.textRuns).toBeGreaterThan(0);
  expect(data.protected).toBe(0);
  expect(data.embedded).toBeGreaterThanOrEqual(2);
  expect([...entries.keys()].filter(name => /^word\/fonts\/.*\.odttf$/.test(name)).length).toBeGreaterThanOrEqual(2);
  return { ...data, text: data.paragraphs.join('\n') };
}


async function expectFiles(page: Page, info: TestInfo, f: Awaited<ReturnType<typeof setup>>, expected: TargetResumeV1, stem: string) {
  const start = f.audit.exports.length;
  const pdf = await readPdf(await downloadFile(page, 'pdf', info, stem, f.zh));
  const docx = await readDocx(page, await downloadFile(page, 'docx', info, stem, f.zh));
  const texts = expected.document.sections.filter(section => section.included).flatMap(section => section.blocks.filter(block => block.included).flatMap(block => block.lines.filter(line => line.included).map(line => line.text)));
  expect(f.audit.exports).toHaveLength(start + 2);
  const requests = f.audit.exports.slice(start);
  expect(requests[0].projection).toEqual(requests[1].projection);
  for (const request of requests) {
    expect(request.projection.sections.flatMap(section => section.blocks.flatMap(block => block.lines.map(line => line.text)))).toEqual(texts);
    expect(JSON.stringify(request)).not.toContain(RAW_PRIVATE);
    expect(JSON.stringify(request)).not.toContain('provenance');
    expect(JSON.stringify(request)).not.toContain('target-resume-source-checks-v');
    expect(JSON.stringify(request)).not.toContain(BAD_CLAIM);
  }
  for (const file of [pdf, docx]) {
    let offset = 0; const normalized = compact(file.text);
    for (const value of texts) {
      const found = normalized.indexOf(compact(value), offset); expect(found, `${stem}: file preserves current line and order`).toBeGreaterThanOrEqual(offset);
      offset = found + compact(value).length;
    }
    expect(file.text).not.toContain('target-resume-source-checks-v');
    expect(file.text).not.toContain('Synthetic selection advice');
    expect(file.text).not.toContain('The laboratory studies instrument calibration and experimental design.');
    expect(file.text).not.toContain('官网完整段落');
    expect(file.text).not.toContain(RAW_PRIVATE); expect(file.text).not.toContain(BAD_CLAIM);
    if (stem === 'restored-baseline') {
      expect(compact(file.text)).not.toContain(compact(MANUAL_NAME));
      for (const proposed of Object.values(PROPOSED)) expect(compact(file.text)).not.toContain(compact(proposed));
    } else if (stem === 'accepted-current') expect(compact(file.text)).toContain(compact(MANUAL_NAME));
  }
  await info.attach(`${stem}-extracted-content`, { body: JSON.stringify({ expected_texts: texts, pdf: pdf.text, docx: docx.text }, null, 2), contentType: 'application/json' });
}

for (const mode of ['single', 'all-valid'] as const) test(`${mode} acceptance excludes skipped AI text through history and both real export formats`, async ({ page }, info) => {
  test.setTimeout(90_000);
  const f = await setup(page, info);
  try {
    await f.open(); const baseline = await f.save(0);
    await aiPanel(page).getByRole('button', { name: f.copy('Generate AI suggestions', '生成 AI 建议'), exact: true }).click();
    await expect(aiPanel(page).getByRole('checkbox', { name: /^Use rewrite:/ })).toHaveCount(2);
    expect(f.audit.suggestions).toHaveLength(1);
    const request = f.audit.suggestions[0]; expect(request.draft).toEqual(baseline);
    const team = lines(baseline).find(({ line }) => line.evidence.id === 'team-role')!.line;
    const valid = lines(baseline).filter(({ line }) => Object.hasOwn(PROPOSED, line.evidence.id)).map(({ line }) => line);
    await expect(aiPanel(page)).toContainText(f.copy('The proposed wording failed the source checks. Your wording is kept.', '建议未通过来源核对，保留现有表述。'));
    await expect(aiPanel(page).getByRole('checkbox', { name: `Use rewrite: ${team.id}`, exact: true })).toHaveCount(0);
    await expect(aiPanel(page).getByRole('article', { name: `AI rewrite ${team.id}`, exact: true })).toHaveCount(0);
    await expect(aiPanel(page).getByRole('checkbox', { name: f.copy('Use suggested section and block order', '使用建议的章节与内容块顺序'), exact: true })).toBeDisabled();
    await expect(f.editor(team.id)).toHaveValue(ORIGINAL['team-role']);
    const chosen = mode === 'single' ? valid.slice(0, 1) : valid;
    for (const line of chosen) await aiPanel(page).getByRole('checkbox', { name: `Use rewrite: ${line.id}`, exact: true }).check();
    await aiPanel(page).getByText(f.copy('Preview complete résumé before applying', '应用前对比完整简历'), { exact: true }).click();
    const before = aiPanel(page).getByRole('region', { name: f.copy('Before AI changes', '应用前全文'), exact: true });
    const after = aiPanel(page).getByRole('region', { name: f.copy('After selected AI changes', '应用所选建议后全文'), exact: true });
    await expect(before).toContainText(ORIGINAL['team-role']); await expect(after).toContainText(ORIGINAL['team-role']);
    await expect(after).not.toContainText(BAD_CLAIM);
    for (const line of valid) {
      const selected = chosen.some(value => value.id === line.id);
      await expect(after).toContainText(selected ? PROPOSED[line.evidence.id] : line.text);
      await expect(f.editor(line.id)).toHaveValue(line.text);
    }
    await after.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
    await page.screenshot({ path: info.outputPath(`mixed-review-${mode}-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
    await aiPanel(page).getByRole('button', { name: f.copy('Apply selected suggestions', '应用所选建议'), exact: true }).click();
    const expected = structuredClone(baseline);
    for (const { line } of lines(expected)) {
      if (chosen.some(value => value.id === line.id)) line.text = PROPOSED[line.evidence.id];
      await expect(f.editor(line.id)).toHaveValue(line.text);
    }
    // Explicit user editing is permitted and is exported as typed, without
    // being mislabeled as a newly validated AI suggestion.
    const name = lines(expected).find(({ line }) => line.evidence.id === 'name')!.line;
    await f.editor(name.id).fill(MANUAL_NAME); name.text = MANUAL_NAME;
    const accepted = await f.save(1); expect(accepted).toEqual(expected);
    await expectFiles(page, info, f, expected, 'accepted-current');
    await f.modal.locator('summary').filter({ hasText: f.copy('Version history', '版本历史') }).click();
    await f.modal.getByRole('button', { name: f.copy('Load latest 20 versions', '读取最近 20 个版本'), exact: true }).click();
    await f.modal.getByRole('button', { name: f.zh ? /^查看版本 1 ·/ : /^View version 1 ·/ }).click();
    await expect(f.modal.getByRole('region', { name: f.copy('Selected historical version preview', '所选历史版本预览'), exact: true })).toContainText(ORIGINAL['team-role']);
    const restored = await f.save(2, true); expect(restored).toEqual(baseline);
    for (const { line } of lines(baseline)) await expect(f.editor(line.id)).toHaveValue(line.text);
    await expectFiles(page, info, f, baseline, 'restored-baseline');
    expect(f.audit.suggestions).toHaveLength(1);
    const targetWrites = f.audit.writes.filter(item => item.path === '/rest/v1/rpc/commit_target_resume_with_provenance_cas');
    expect(targetWrites).toHaveLength(3); expect(targetWrites.map(item => item.body.p_expected_revision)).toEqual([0, 1, 2]);
    const currentProfile = await f.owner.http.get(`${STUB}/rest/v1/profiles?id=eq.${f.owner.session.user.id}&select=*`, { headers: { Authorization: `Bearer ${f.owner.session.access_token}` } });
    expect(currentProfile.status()).toBe(200);
    const value = await currentProfile.json(); expect(value).toHaveLength(1);
    expect(value[0]).toMatchObject({ id: f.owner.session.user.id, revision: 1 });
    const stored = value[0].profile_data;
    expect(stored.resume_master).toEqual(f.owner.profile.resume_master); expect(stored.experience_entries).toEqual(f.owner.profile.experience_entries); expect(stored.resume_text).toBe(RAW_PRIVATE);
    await exportPanel(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(`restored-export-${mode}-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
  } finally { await f.done(); }
});

for (const status of ['available', 'stale'] as const) test(`research ${status} source survives review, acceptance, save and real exports`, async ({ page }, info) => {
  test.setTimeout(120_000);
  const f = await setup(page, info, status);
  try {
    await f.open(); const baseline = await f.save(0);
    expect(isCurrentTargetResumeContext(baseline.target_snapshot)).toBe(true);
    await f.modal.getByText(f.copy('Target requirements and original materials', '目标要求与原始材料'), { exact: true }).click();
    const research = f.modal.getByTestId('saved-target-research');
    await expect(research.getByRole('link', { name: RESEARCH_TITLE, exact: true })).toHaveAttribute('href', 'https://doi.org/10.1234/synthetic-instrument-study');
    await research.getByText(f.copy('Abstract', '摘要'), { exact: true }).click();
    await expect(research).toContainText(RESEARCH_ABSTRACT);
    if (status === 'stale') await expect(research).toContainText(f.copy('AI does not use these papers.', 'AI 不使用这些旧论文。'));
    await research.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
    await research.screenshot({ path: info.outputPath(`research-${status}-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
    await aiPanel(page).getByRole('button', { name: f.copy('Generate AI suggestions', '生成 AI 建议'), exact: true }).click();
    const chosen = lines(baseline).find(({ line }) => line.evidence.id === 'readings-role')!.line;
    await aiPanel(page).getByRole('checkbox', { name: `Use rewrite: ${chosen.id}`, exact: true }).check();
    if (status === 'available') await expect(aiPanel(page)).toContainText(RESEARCH_ABSTRACT);
    await aiPanel(page).getByRole('button', { name: f.copy('Apply selected suggestions', '应用所选建议'), exact: true }).click();
    const accepted = await f.save(1);
    const p = f.audit.writes.filter(item => item.path.endsWith('/commit_target_resume_with_provenance_cas')).at(-1)!.body.p_provenance as { version: number; events: { changes: { target_evidence: TargetResumeAiEvidence[] }[] }[] };
    expect(p.version).toBe(3);
    const quotes = p.events.flatMap(event => event.changes.flatMap(change => change.target_evidence));
    expect(quotes.some(quote => quote.field === 'paper_abstract')).toBe(status === 'available');
    expect(accepted.document.sections.flatMap(section => section.blocks.flatMap(block => block.lines)).some(line => line.text.includes('laser interferometry'))).toBe(false);
    await expectFiles(page, info, f, accepted, `research-${status}`);
    await f.editor(chosen.id).fill('Temporary manual wording retained as a separate version.');
    await f.save(2);
    await f.modal.locator('summary').filter({ hasText: f.copy('Version history', '版本历史') }).click();
    await f.modal.getByRole('button', { name: f.copy('Load latest 20 versions', '读取最近 20 个版本'), exact: true }).click();
    await f.modal.getByRole('button', { name: f.zh ? /^查看版本 2 ·/ : /^View version 2 ·/ }).click();
    const preview = f.modal.getByRole('region', { name: f.copy('Selected historical version preview', '所选历史版本预览'), exact: true });
    await expect(preview).toContainText(PROPOSED['readings-role']);
    const restored = await f.save(3, true);
    expect(restored).toEqual(accepted);
    const historyPair = f.audit.writes.filter(item => item.path.endsWith('/commit_target_resume_with_provenance_cas')).at(-1)!.body.p_provenance;
    expect(historyPair).toEqual(p);
    await info.attach('research-provenance-pair', { body: JSON.stringify({ status, provenance: p }, null, 2), contentType: 'application/json' });
  } finally { await f.done(); }
});

for (const status of ['available', 'stale'] as const) test(`official website ${status}: full source, history, change gate and student-only exports`, async ({ page }, info) => {
  test.setTimeout(120_000);
  const f = await setup(page, info, undefined, status);
  try {
    await f.open(); const baseline = await f.save(0);
    expect(isCurrentTargetResumeContext(baseline.target_snapshot)).toBe(true);
    await f.modal.getByText(f.copy('Target requirements and original materials', '目标要求与原始材料'), { exact: true }).click();
    const sources = f.modal.getByRole('region', { name: f.copy('Faculty and lab website sources', '教授与实验室官网资料'), exact: true });
    await sources.locator('summary').filter({ hasText: LAB_TITLE }).click();
    await expect(sources).toContainText(LAB_TEXT);
    await expect(sources.getByRole('link', { name: f.copy('Open source page', '打开原始页面'), exact: true })).toHaveAttribute('href', 'https://example.edu/synthetic-researcher');
    if (status === 'stale') await expect(sources).toContainText(f.copy('excluded from new suggestions', '暂不用于新建议'));
    await sources.scrollIntoViewIfNeeded(); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
    await sources.screenshot({ path: info.outputPath(`official-${status}-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
    await aiPanel(page).getByRole('button', { name: f.copy('Generate AI suggestions', '生成 AI 建议'), exact: true }).click();
    const chosen = lines(baseline).find(({ line }) => line.evidence.id === 'readings-role')!.line;
    await aiPanel(page).getByRole('checkbox', { name: `Use rewrite: ${chosen.id}`, exact: true }).check();
    if (status === 'available') await expect(aiPanel(page)).toContainText(LAB_TEXT);
    await aiPanel(page).getByRole('button', { name: f.copy('Apply selected suggestions', '应用所选建议'), exact: true }).click();
    const accepted = await f.save(1);
    const pair = f.audit.writes.filter(w => w.path.endsWith('/commit_target_resume_with_provenance_cas')).at(-1)!.body.p_provenance as {version:number;events:{changes:{target_evidence:TargetResumeAiEvidence[]}[]}[]};
    expect(pair.version).toBe(3);
    const quotes = pair.events.flatMap(e => e.changes.flatMap(c => c.target_evidence));
    expect(quotes.some(q => q.field === 'lab_text')).toBe(status === 'available');
    await expectFiles(page, info, f, accepted, `official-${status}`);
    for (const request of f.audit.exports) expect(JSON.stringify(request)).not.toContain(LAB_TEXT);
    // A later manual edit and restore keep the exact old source/record pair.
    await f.editor(chosen.id).fill('Separate manual revision.'); await f.save(2);
    await f.modal.locator('summary').filter({ hasText: f.copy('Version history', '版本历史') }).click();
    await f.modal.getByRole('button', { name: f.copy('Load latest 20 versions', '读取最近 20 个版本'), exact: true }).click();
    await f.modal.getByRole('button', { name: f.zh ? /^查看版本 2 ·/ : /^View version 2 ·/ }).click();
    expect(await f.save(3, true)).toEqual(accepted);
    expect(f.audit.writes.filter(w => w.path.endsWith('/commit_target_resume_with_provenance_cas')).at(-1)!.body.p_provenance).toEqual(pair);
    // Publish a changed source after another suggestion is selected. A fresh
    // target read must retire that suggestion while retaining the saved text.
    await aiPanel(page).getByRole('button', { name: f.copy('Generate AI suggestions', '生成 AI 建议'), exact: true }).click();
    const untouched = lines(accepted).find(({ line }) => line.evidence.id === 'calibration-role')!.line;
    await aiPanel(page).getByRole('checkbox', { name: `Use rewrite: ${untouched.id}`, exact: true }).check();
    await f.updateLab(labFixture(status, '\nNew source revision; old drafts keep their saved source.'));
    const reread = page.waitForResponse(r => new URL(r.url()).pathname === `/api/opportunities/${TARGET}` && r.request().method() === 'GET');
    await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await reread;
    await expect(f.modal).toContainText(f.copy('This draft was created from different profile or target materials.', '此稿基于不同版本的资料或目标。'));
    await expect(aiPanel(page).getByRole('button', { name: f.copy('Generate AI suggestions', '生成 AI 建议'), exact: true })).toBeDisabled();
    await expect(f.editor(untouched.id)).toHaveValue(untouched.text);
    await expect(sources).not.toContainText('New source revision');
    expect(f.audit.suggestions).toHaveLength(2);
    await info.attach('official-provenance-pair', { body: JSON.stringify({ status, provenance: pair }, null, 2), contentType: 'application/json' });
  } finally { await f.done(); }
});
