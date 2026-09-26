import { test, expect, request as apiRequest, type Page, type TestInfo } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { inflateRawSync } from 'node:zlib';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { TargetResumeAiEvidence } from '../src/lib/target-resume-ai-protocol';
import { TARGET_RESUME_PLAN_VERSION, type TargetResumePlanRequest, type TargetResumePlanResponse } from '../src/lib/target-resume-plan-protocol';
import type { TargetResumeV1 } from '../src/lib/target-resume';
import type { ProfileData, ResumeFact, ResumeMasterV1 } from '../src/lib/types';
import type { TargetResumeExportRequest } from '../src/lib/target-resume-export-protocol';

// Browser acceptance of already-checked receipts, followed by real local file
// rendering. Server semantic rejection is covered separately by route tests;
// this fixture must never be described as an end-to-end real-model evaluation.
const TARGET = 'uiuc-siebel-ugresearch';
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const FRONTEND = `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3200)}`;
const RAW_PRIVATE = 'RAW PRIVATE MASTER — not a visible résumé field';
const NAME = 'Selection student 王';
const BAD_CLAIM = 'I built a Python parser.';
const ORIGINAL = {
  'team-role': 'My role: I wrote parser tests. Outcome: My team built a Python parser. I did not build the parser.',
  'readings-role': 'Compared instrument readings; I assisted and did not lead the project.',
  'calibration-role': 'Documented the final calibration procedure and recorded the instrument readings.',
};
const SHORTER = 'Documented the final calibration procedure.';
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
const compact = (text: string) => text.replace(/\s/gu, '');
const exportPanel = (page: Page) => page.getByRole('region', { name: 'Export current résumé', exact: true });
const planPanel = (page: Page, zh: boolean) => page.getByRole('region', { name: zh ? '简历选材' : 'Résumé content plan', exact: true });
const lines = (draft: TargetResumeV1) => draft.document.sections.flatMap(section => section.blocks.flatMap(block => block.lines.map(line => ({ section, block, line }))));
function profile(): ProfileData {
  const master: ResumeMasterV1 = { version: 1, id: 'selection-master', revision: 1, source_signature: null,
    basics: { name: fact('name', NAME), email: fact('email', 'synthetic@fixture.invalid'), links: [] },
    education: [{ id: 'education', school: fact('school', 'Example University'), details: [] }],
    activities: Object.keys(ORIGINAL).map((id, index) => ({ id: `project-${index}`, kind: 'project', title: fact(`title-${index}`, `Project ${index + 1}`), details: [{ id, revision: 1 }] })),
    publications: [], skills: [], other_sections: [], section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [],
  };
  return { institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore', name: NAME,
    is_international: false, research_interests: 'instrumentation', seeking_types: ['research'], skills: [], coursework: [], resume_text: RAW_PRIVATE, resume_master: master,
    experience_entries: [...Object.entries(ORIGINAL).map(([id, text]) => ({ id, text, revision: 1, status: 'confirmed' as const, source: { kind: 'manual' as const } })),
      { id: 'unreferenced', text: 'Compared temperature records.', revision: 1, status: 'confirmed', source: { kind: 'manual' } },
      { id: 'pending', text: 'Draft experience awaiting confirmation.', revision: 1, status: 'candidate', source: { kind: 'manual' } }],
  };
}
async function account() {
  expect(STUB).toBe('http://127.0.0.1:54321'); expect(FRONTEND).toBe('http://127.0.0.1:3200');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(`${STUB}/auth/v1/signup`, { data: {} }); expect(signup.status()).toBe(200);
    const session = await signup.json();
    // Only the loopback stub accepts these synthetic formal-user claims.
    session.user = { ...session.user, is_anonymous: false, email: 'selection@fixture.invalid', app_metadata: { provider: 'email', providers: ['email'] } };
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
  const description = Array.from(draft.target_snapshot.description);
  if (description.length) return { field: 'description', requirement_index: null, start: 0, end: Math.min(description.length, 80), quote: description.slice(0, 80).join('') };
  const index = draft.target_snapshot.requirements.findIndex(value => value.length > 0); expect(index).toBeGreaterThanOrEqual(0);
  const quote = Array.from(draft.target_snapshot.requirements[index]);
  return { field: 'requirement', requirement_index: index, start: 0, end: Math.min(quote.length, 80), quote: quote.slice(0, 80).join('') };
}
function checkedReply(request: TargetResumePlanRequest): TargetResumePlanResponse {
  const blocks = request.draft.document.sections.filter(section => section.kind !== 'basics').flatMap(section => section.blocks.map(block => ({ section, block })));
  return { version: 1, check_version: 'target-resume-source-checks-v1', pipeline_version: TARGET_RESUME_PLAN_VERSION, request_id: request.request_id, document_id: request.draft.id,
    opportunity_id: TARGET, document_signature: request.document_signature, base: structuredClone(request.draft.base), options: { ...request.options },
    manifest: blocks.map(({ section, block }) => ({ section_id: section.id, block_id: block.id, line_ids: block.lines.map(line => line.id) })),
    scope: { unreferenced_experience_ids: ['unreferenced'], pending_experience_ids: ['pending'], stale_experience_ids: [], unmapped_range_count: 0 },
    method: 'ai', complete: true, reason_code: null, logical_calls: 1, provider_attempts_upper_bound: 2,
    items: blocks.map(({ section, block }) => {
      const experience = block.lines.find(line => line.evidence.kind === 'experience');
      const source = experience ?? block.lines[0];
      const action = experience?.evidence.id === 'readings-role' ? 'omit' : experience ? 'compress' : 'keep';
      return { section_id: section.id, block_id: block.id, action,
        reason: 'Synthetic selection advice for testing explicit choices; this is not an evaluation of model quality.',
        target_evidence: [targetEvidence(request.draft)],
        source_evidence: [{ unit_id: source.id, start: 0, end: Array.from(source.original).length, quote: source.original }],
        rewrites: action !== 'compress' || !experience ? [] : [experience.evidence.id === 'team-role'
          ? { unit_id: experience.id, status: 'skipped', reason_code: 'ungrounded_rewrite', proposed_text: null }
          : { unit_id: experience.id, status: 'suggested', reason_code: null, proposed_text: SHORTER }],
      };
    }),
  };
}
async function setup(page: Page, info: TestInfo, denial?: { code: string; status: number }) {
  const owner = await account(); const zh = info.project.name === 'mobile-chrome';
  const copy = (en: string, cn: string) => zh ? cn : en;
  if (zh) await page.setViewportSize({ width: 390, height: 844 });
  const audit = { external: [] as string[], pageErrors: [] as string[], consoleErrors: [] as string[], unexpectedWriting: [] as string[],
    badResponses: [] as { path: string; status: number }[], networkFailures: [] as { path: string; error: string | null }[],
    plans: [] as TargetResumePlanRequest[], exports: [] as TargetResumeExportRequest[], writes: [] as { path: string; body: Record<string, unknown> }[], reads: [] as string[] };
  await page.context().route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['http://127.0.0.1:3200', 'http://127.0.0.1:8200', 'http://127.0.0.1:54321'].includes(url.origin)) { audit.external.push(url.origin); return route.abort('blockedbyclient'); }
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
  await page.route('**/api/tailor/full-target/selection-plan', route => {
    expect(route.request().method()).toBe('POST');
    const request = route.request().postDataJSON() as TargetResumePlanRequest; audit.plans.push(request);
    expect(request.draft.opportunity_id).toBe(TARGET);
    if (denial && audit.plans.length === 2) return route.fulfill({ status: denial.status, json: { detail: { code: denial.code } } });
    return route.fulfill({ json: checkedReply(request) });
  });
  const modal = page.getByRole('dialog', { name: copy('Target résumé', '目标简历'), exact: true });
  const editor = (id: string) => modal.locator(`textarea[id$="-${id}"]`);
  const open = async () => {
    await page.goto(`/opportunities/${TARGET}`);
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
    await info.attach('selection-plan-flow-audit', { body: JSON.stringify(audit, null, 2), contentType: 'application/json' });
    await owner.http.dispose();
    expect(audit.external).toEqual([]); expect(audit.pageErrors).toEqual([]); expect(audit.unexpectedWriting).toEqual([]); expect(audit.badResponses).toEqual(denial ? [{ path: '/api/tailor/full-target/selection-plan', status: denial.status }] : []);
    for (const write of audit.writes.filter(item => item.path !== '/rest/v1/rpc/commit_target_resume_with_provenance_cas')) {
      expect(write.path).toBe('/rest/v1/analytics_events');
      expect(write.body).toEqual({ device_id: owner.session.user.id, event: 'match_opened', props: { opportunity_id: TARGET } });
    }
  };
  return { owner, zh, copy, audit, modal, editor, open, save, done };
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
    expect(file.text).not.toContain(RAW_PRIVATE); expect(file.text).not.toContain(BAD_CLAIM);
    if (stem === 'accepted-current') {
      expect(compact(file.text)).not.toContain(compact(ORIGINAL['readings-role']));
      expect(compact(file.text)).not.toContain(compact(ORIGINAL['team-role']));
    }

  }
  await info.attach(`${stem}-extracted-content`, { body: JSON.stringify({ expected_texts: texts, pdf: pdf.text, docx: docx.text }, null, 2), contentType: 'application/json' });
}

for (const mode of ['selection-only', 'selection-and-compression'] as const) test(`${mode} preserves hidden content and separates shorter wording through history and export`, async ({ page }, info) => {
  test.setTimeout(120_000);
  const f = await setup(page, info);
  const panel = planPanel(page, f.zh);
  try {
    await f.open();
    // Hide the first experience before planning. Its full original must still
    // reach the request and appear in the review, without automatic inclusion.
    const initial = await f.save(0);
    const teamUnit = lines(initial).find(({ line }) => line.evidence.id === 'team-role')!;
    await f.modal.getByTestId(`target-block-${teamUnit.block.id}`).getByRole('checkbox', { name: f.copy('Include whole block 1', '选用完整内容块 1'), exact: true }).uncheck();
    const baseline = await f.save(1);
    expect(lines(baseline).find(({ line }) => line.evidence.id === 'team-role')!.block.included).toBe(false);
    await panel.getByRole('button', { name: f.copy('Generate content plan', '生成选材建议'), exact: true }).click();
    await expect(panel.locator('[data-plan-block-id]')).toHaveCount(4);
    expect(f.audit.plans).toHaveLength(1); expect(f.audit.plans[0].draft).toEqual(baseline);
    expect(f.audit.plans[0].options.target_pages).toBe(1);
    const omitted = lines(baseline).find(({ line }) => line.evidence.id === 'readings-role')!;
    const shortened = lines(baseline).find(({ line }) => line.evidence.id === 'calibration-role')!;
    await expect(panel.getByRole('button', { name: f.copy('Apply selected content choices', '应用所选安排'), exact: true })).toBeDisabled();
    for (const checkbox of await panel.getByRole('checkbox').all()) await expect(checkbox).not.toBeChecked();
    await expect(panel.locator(`[data-plan-block-id="${teamUnit.block.id}"]`)).toContainText(ORIGINAL['team-role']);
    await expect(panel.getByRole('checkbox', { name: `Use shorter wording: ${teamUnit.line.id}`, exact: true })).toHaveCount(0);
    await expect(panel).toContainText(f.copy('The candidate failed source checks. Current wording is kept.', '候选短稿未通过来源核对，保留当前稿。'));
    await panel.getByText(f.copy('Materials outside this draft', '未进入本稿的材料'), { exact: true }).click();
    await expect(panel).toContainText(f.copy('Confirmed experiences outside this draft: 1', '未进入本稿的已确认经历：1'));
    await expect(panel).toContainText(f.copy('Pending experiences: 1', '待确认经历：1'));
    await panel.getByRole('checkbox', { name: `Use content choice: ${omitted.block.id}`, exact: true }).check();
    await panel.getByRole('checkbox', { name: `Use content choice: ${shortened.block.id}`, exact: true }).check();
    if (mode === 'selection-and-compression') await panel.getByRole('checkbox', { name: `Use shorter wording: ${shortened.line.id}`, exact: true }).check();
    await panel.getByText(f.copy('Compare complete draft before applying', '应用前对比完整稿'), { exact: true }).click();
    const before = panel.getByRole('region', { name: f.copy('Before content choices', '选材前全文'), exact: true });
    const after = panel.getByRole('region', { name: f.copy('After selected content choices', '采用所选安排后全文'), exact: true });
    await expect(before).toContainText(ORIGINAL['readings-role']); await expect(after).not.toContainText(ORIGINAL['readings-role']);
    await expect(after).not.toContainText(ORIGINAL['team-role']);
    await expect(f.editor(shortened.line.id)).toHaveValue(shortened.line.text);
    await expect(after).toContainText(mode === 'selection-only' ? shortened.line.text : SHORTER);
    await after.scrollIntoViewIfNeeded(); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
    await page.screenshot({ path: info.outputPath(`selection-preview-${mode}-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
    await panel.getByRole('button', { name: f.copy('Apply selected content choices', '应用所选安排'), exact: true }).click();
    const expected = structuredClone(baseline);
    for (const { block, line } of lines(expected)) {
      if (block.id === omitted.block.id) block.included = false;
      if (mode === 'selection-and-compression' && line.id === shortened.line.id) line.text = SHORTER;
      await expect(f.editor(line.id)).toHaveValue(line.text);
    }
    const accepted = await f.save(2); expect(accepted).toEqual(expected);
    const provenanceWrites = f.audit.writes.filter(write => write.path === '/rest/v1/rpc/commit_target_resume_with_provenance_cas');
    const appliedProvenance = provenanceWrites.at(-1)!.body.p_provenance as { events: { kind: string; changes: { field: string; line_id: string | null; check: { version: string } | null }[] }[] };
    expect(appliedProvenance.events.some(event => event.kind === 'manual')).toBe(true);
    const appliedChanges = appliedProvenance.events.filter(event => event.kind === 'plan').flatMap(event => event.changes);
    expect(appliedChanges.some(change => change.field === 'included')).toBe(true);
    expect(appliedChanges.filter(change => change.check !== null)).toHaveLength(mode === 'selection-and-compression' ? 1 : 0);
    for (const change of appliedChanges.filter(change => change.check !== null)) {
      expect(change.line_id).toBe(shortened.line.id);
      expect(change.check!.version).toBe('target-resume-source-checks-v1');
    }
    expect(appliedChanges.some(change => change.line_id === teamUnit.line.id)).toBe(false);

    expect(accepted.base_snapshot).toEqual(baseline.base_snapshot);
    await expectFiles(page, info, f, expected, 'accepted-current');
    await f.modal.locator('summary').filter({ hasText: f.copy('Version history', '版本历史') }).click();
    await f.modal.getByRole('button', { name: f.copy('Load latest 20 versions', '读取最近 20 个版本'), exact: true }).click();
    await f.modal.getByRole('button', { name: f.zh ? /^查看版本 1 ·/ : /^View version 1 ·/ }).click();
    const restored = await f.save(3, true); expect(restored).toEqual(initial);
    expect(f.audit.writes.filter(write => write.path === '/rest/v1/rpc/commit_target_resume_with_provenance_cas').at(-1)!.body.p_provenance).toBeNull();
    for (const { line } of lines(initial)) await expect(f.editor(line.id)).toHaveValue(line.text);
    await expectFiles(page, info, f, initial, 'restored-baseline');
    expect(f.audit.plans).toHaveLength(1);
    const targetWrites = f.audit.writes.filter(item => item.path === '/rest/v1/rpc/commit_target_resume_with_provenance_cas');
    expect(targetWrites.map(item => item.body.p_expected_revision)).toEqual([0, 1, 2, 3]);
    const currentProfile = await f.owner.http.get(`${STUB}/rest/v1/profiles?id=eq.${f.owner.session.user.id}&select=*`, { headers: { Authorization: `Bearer ${f.owner.session.access_token}` } });
    expect(currentProfile.status()).toBe(200);
    const stored = (await currentProfile.json())[0]; expect(stored.revision).toBe(1);
    expect(stored.profile_data.resume_master).toEqual(f.owner.profile.resume_master);
    expect(stored.profile_data.experience_entries).toEqual(f.owner.profile.experience_entries);
    expect(stored.profile_data.resume_text).toBe(RAW_PRIVATE);
    await exportPanel(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(`restored-export-${mode}-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
  } finally { await f.done(); }
});

test('an authoritative target refusal retires an earlier selected plan without changing the saved draft', async ({ page }, info) => {
  const zh = info.project.name === 'mobile-chrome';
  const denial = { code: zh ? 'TARGET_NOT_ACTIONABLE' : 'target_changed', status: 409 };
  const f = await setup(page, info, denial), panel = planPanel(page, f.zh);
  try {
    await f.open(); const baseline = await f.save(0);
    const omitted = lines(baseline).find(({ line }) => line.evidence.id === 'readings-role')!;
    await panel.getByRole('button', { name: f.copy('Generate content plan', '生成选材建议'), exact: true }).click();
    await panel.getByRole('checkbox', { name: `Use content choice: ${omitted.block.id}`, exact: true }).check();
    await expect(panel.getByRole('button', { name: f.copy('Apply selected content choices', '应用所选安排'), exact: true })).toBeEnabled();
    await panel.getByRole('button', { name: f.copy('Generate content plan', '生成选材建议'), exact: true }).click();
    await expect(panel.getByRole('alert')).toBeVisible();
    await expect(panel.locator('[data-plan-block-id]')).toHaveCount(0);
    await expect(panel.getByRole('button', { name: f.copy('Apply selected content choices', '应用所选安排'), exact: true })).toHaveCount(0);
    await expect(f.editor(omitted.line.id)).toHaveValue(ORIGINAL['readings-role']);
    await expect(f.modal.getByRole('button', { name: f.copy('Save target draft', '保存目标文稿'), exact: true })).toBeDisabled();
    // The refusal blocks both AI surfaces for this opened target. Reopening
    // rechecks current materials before a fresh request; old choices stay gone.
    await expect(panel.getByRole('button', { name: f.copy('Generate content plan', '生成选材建议'), exact: true })).toBeDisabled();
    await expect(f.modal.getByRole('region', { name: 'AI adaptation suggestions', exact: true }).getByRole('button', { name: f.copy('Generate AI suggestions', '生成 AI 建议'), exact: true })).toBeDisabled();
    await f.modal.getByRole('button', { name: f.copy('Close target résumé', '关闭目标简历'), exact: true }).click();
    await expect(f.modal).not.toBeVisible();
    await page.getByRole('button', { name: f.copy('Renovate Resume', '简历翻新'), exact: true }).click();
    await expect(f.modal).toBeVisible();
    await panel.getByRole('button', { name: f.copy('Generate content plan', '生成选材建议'), exact: true }).click();
    await expect(panel.locator('[data-plan-block-id]')).toHaveCount(4);
    for (const checkbox of await panel.getByRole('checkbox').all()) await expect(checkbox).not.toBeChecked();
    await expect(panel.getByRole('button', { name: f.copy('Apply selected content choices', '应用所选安排'), exact: true })).toBeDisabled();
    expect(f.audit.plans).toHaveLength(3);
    expect(f.audit.plans.every(plan => JSON.stringify(plan.draft) === JSON.stringify(baseline))).toBe(true);
    expect(f.audit.writes.filter(write => write.path === '/rest/v1/rpc/commit_target_resume_with_provenance_cas')).toHaveLength(1);
    await panel.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(`refusal-recovered-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
  } finally { await f.done(); }
});

test('provenance stays paired through in-flight edits, two-window conflict and history restore', async ({ page }, info) => {
  test.setTimeout(120_000);
  const f = await setup(page, info), panel = planPanel(page, f.zh);
  let other: Page | undefined;
  try {
    await f.open(); const initial = await f.save(0);
    const unit = lines(initial).find(({ line }) => line.evidence.id === 'calibration-role')!;
    await panel.getByRole('button', { name: f.copy('Generate content plan', '生成选材建议'), exact: true }).click();
    await panel.getByRole('checkbox', { name: `Use shorter wording: ${unit.line.id}`, exact: true }).check();
    await panel.getByRole('button', { name: f.copy('Apply selected content choices', '应用所选安排'), exact: true }).click();
    await f.save(1);
    const records = f.modal.locator('details').filter({ has: page.locator('summary').getByText(f.copy('Change records', '修改记录'), { exact: true }) });
    await records.locator('summary').click();
    await expect(records).toContainText('target-resume-source-checks-v1');
    await expect(records).toContainText('Synthetic selection advice');
    await records.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
    await records.screenshot({ path: info.outputPath(`provenance-accepted-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
    // A second real page opens the same stored revision before the first saves again.
    other = await page.context().newPage();
    const secondErrors: string[] = []; other.on('pageerror', error => secondErrors.push(error.message));
    await other.route('**/auth/v1/user', route => route.fulfill({ json: f.owner.session.user }));
    await other.route('**/auth/v1/token?grant_type=refresh_token', route => route.fulfill({ json: f.owner.session }));
    await other.goto(`/opportunities/${TARGET}`);
    await other.getByRole('button', { name: f.copy('Renovate Resume', '简历翻新'), exact: true }).click();
    const secondModal = other.getByRole('dialog', { name: f.copy('Target résumé', '目标简历'), exact: true });
    const secondEditor = secondModal.locator(`textarea[id$="-${unit.line.id}"]`);
    await expect(secondEditor).toHaveValue(SHORTER);
    await f.editor(unit.line.id).fill('Manual wording A.');
    let release!: () => void; let dispatched!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    const entered = new Promise<void>(resolve => { dispatched = resolve; });
    const savePattern = '**/rest/v1/rpc/commit_target_resume_with_provenance_cas';
    await page.route(savePattern, async route => { dispatched(); await held; await route.continue(); }, { times: 1 });
    const responsePending = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/rpc/commit_target_resume_with_provenance_cas');
    await f.modal.getByRole('button', { name: f.copy('Save target draft', '保存目标文稿'), exact: true }).click();
    await entered;
    await f.editor(unit.line.id).fill('Manual wording B.');
    release(); const saved = await (await responsePending).json();
    expect(saved).toMatchObject({ status: 'saved', revision: 3 });
    expect(lines(saved.doc).find(({ line }) => line.id === unit.line.id)!.line.text).toBe('Manual wording A.');
    await expect(f.editor(unit.line.id)).toHaveValue('Manual wording B.');
    await expect(f.modal.getByText(f.copy('Unsaved local edits', '本地编辑尚未保存'), { exact: true })).toBeVisible();
    await f.save(3);
    const latestWrite = f.audit.writes.filter(write => write.path.endsWith('/commit_target_resume_with_provenance_cas')).at(-1)!;
    const recorded = latestWrite.body.p_provenance as { events: { kind: string; changes: { field: string; line_id: string; before: string; after: string; check: unknown }[] }[] };
    const latest = recorded.events.flatMap(event => event.changes.map(change => ({ kind: event.kind, ...change }))).filter(change => change.line_id === unit.line.id && change.field === 'text').at(-1)!;
    expect(latest).toMatchObject({ kind: 'manual', before: SHORTER, after: 'Manual wording B.', check: null });
    await secondEditor.fill('Stale second-window wording.');
    const conflictPending = other.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/rpc/commit_target_resume_with_provenance_cas');
    await secondModal.getByRole('button', { name: f.copy('Save target draft', '保存目标文稿'), exact: true }).click();
    const conflict = await (await conflictPending).json(); expect(conflict).toMatchObject({ status: 'conflict', revision: 4 });
    expect(conflict.provenance).toEqual(recorded);
    await expect(secondEditor).toHaveValue('Stale second-window wording.');
    await secondModal.getByRole('button', { name: f.copy('Discard local edits and load server version', '放弃本地编辑并载入服务器版本'), exact: true }).click();
    await expect(secondEditor).toHaveValue('Manual wording B.');
    // Editing back to an earlier AI string remains a manual event.
    await f.editor(unit.line.id).fill(SHORTER); await f.save(4);
    const back = f.audit.writes.filter(write => write.path.endsWith('/commit_target_resume_with_provenance_cas')).at(-1)!.body.p_provenance as typeof recorded;
    expect(back.events.at(-1)).toMatchObject({ kind: 'manual', changes: [{ field: 'text', before: SHORTER, after: SHORTER, check: null }] });
    await f.modal.locator('summary').filter({ hasText: f.copy('Version history', '版本历史') }).click();
    await f.modal.getByRole('button', { name: f.copy('Load latest 20 versions', '读取最近 20 个版本'), exact: true }).click();
    await f.modal.getByRole('button', { name: f.zh ? /^查看版本 2 ·/ : /^View version 2 ·/ }).click();
    await f.save(5, true);
    const restored = f.audit.writes.filter(write => write.path.endsWith('/commit_target_resume_with_provenance_cas')).at(-1)!.body.p_provenance as typeof recorded;
    expect(restored.events).toHaveLength(1); expect(restored.events[0].kind).toBe('plan');
    expect(restored.events[0].changes[0].check).toMatchObject({ version: 'target-resume-source-checks-v1' });
    expect(secondErrors).toEqual([]);
    await info.attach('provenance-conflict-and-restore', { body: JSON.stringify({ recorded, conflict, back, restored }, null, 2), contentType: 'application/json' });
    if (!await records.evaluate(node => (node as HTMLDetailsElement).open)) await records.locator('summary').click();
    await records.evaluate(node => node.scrollIntoView({ block: 'center' }));
    await expect(records.getByText('Recorded check version: target-resume-source-checks-v1', { exact: true }).or(records.getByText('记录的检查版本: target-resume-source-checks-v1', { exact: true }))).toBeVisible();
    await expect(records).toContainText('target-resume-source-checks-v1');
    await expect(records).not.toContainText('Manual wording B.');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
    await records.screenshot({ path: info.outputPath(`provenance-history-${f.zh ? 'zh' : 'en'}.png`), animations: 'disabled' });
  } finally { await other?.close(); await f.done(); }
});
