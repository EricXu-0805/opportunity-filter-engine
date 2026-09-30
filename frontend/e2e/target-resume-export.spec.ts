import { test, expect, type Download, type Page, type Request, type Route, type TestInfo } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { inflateRawSync } from 'node:zlib';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ProfileData, ResumeFact, ResumeMasterV1 } from '../src/lib/types';
import type { TargetResumeExportRequest } from '../src/lib/target-resume-export-protocol';

// Real production UI -> real local renderer -> real downloaded bytes. Only the
// failure and delayed-delivery cases intercept exports; they never fabricate a
// successful PDF or DOCX. Stored profiles use the existing loopback auth/store.
const TARGET = 'uiuc-siebel-ugresearch';
const EXPORT_URL = '**/api/resume/full-target/export';
const RAW_PRIVATE = 'RAW SOURCE ONLY — do not export the entire source snapshot';
const CANDIDATE = 'UNCONFIRMED CANDIDATE MUST NOT BE EXPORTED';
const HIDDEN_DEGREE = 'EXCLUDED DEGREE MUST NOT BE EXPORTED';
const HIDDEN_BLOCK = 'EXCLUDED PROJECT MUST NOT BE EXPORTED';
const HIDDEN_SECTION = 'EXCLUDED SKILL MUST NOT BE EXPORTED';
const ORIGINAL_NAME = 'Alex 王';
const EDITED_NAME = 'Alex 王 — current manual draft';
const LINK = 'https://example.test/student/research';
const LONG_WORD = 'L'.repeat(6_004) + '终';
const LONG_URL = `https://example.test/${'long-path-'.repeat(70)}complete-url-tail`;
const LAST_ITEM = 'FINAL INCLUDED ITEM — 完整最后一项 🧪';
const panel = (page: Page) => page.getByRole('region', { name: 'Export current résumé', exact: true });
const dialog = (page: Page) => page.getByRole('dialog', { name: 'Target résumé', exact: true });
const compact = (text: string) => text.replace(/\s/gu, '');
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });

function profile(stress = false): ProfileData {
  const master: ResumeMasterV1 = {
    version: 1, id: 'export-master', revision: 1, source_signature: null,
    basics: { name: fact('name', ORIGINAL_NAME), email: fact('email', 'synthetic-student@example.edu'),
      links: [{ id: 'portfolio', label: 'Portfolio', url: fact('portfolio-url', stress ? LONG_URL : LINK) }] },
    education: [{ id: 'education', school: fact('school', 'Example University 大学'), degree: fact('degree', HIDDEN_DEGREE),
      end: fact('expected', 'Expected 2027 — 尚未毕业'), details: [] }],
    activities: [
      { id: 'project-one', kind: 'project', title: fact('title-one', 'First project 第一项'), details: [{ id: 'experience-one', revision: 1 }] },
      { id: 'project-hidden', kind: 'project', title: fact('hidden-title', HIDDEN_BLOCK), details: [] },
      { id: 'project-last', kind: 'project', title: fact('title-last', 'Last project moved first'), details: [{ id: 'experience-last', revision: 1 }] },
    ],
    publications: [{ id: 'paper', title: fact('paper-title', 'Instrument study'), authors: fact('authors', 'J. Lee; Alex 王; M. Doe'),
      publication_status: fact('paper-status', 'Submitted, not accepted'), details: [] }],
    skills: [fact('hidden-skill', HIDDEN_SECTION)],
    other_sections: [{ id: 'notes', heading: 'Additional notes 补充说明', items: [
      fact('long-note', stress ? LONG_WORD : 'A short complete note.'), fact('last-item', LAST_ITEM),
    ] }],
    section_order: ['basics', 'education', 'activities', 'publications', 'skills', 'notes'], unmapped_ranges: [],
  };
  return { institution: 'UIUC', college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore',
    name: ORIGINAL_NAME, is_international: false, research_interests: 'instrumentation', skills: [], coursework: [],
    resume_text: RAW_PRIVATE, resume_master: master,
    experience_entries: [
      { id: 'experience-one', revision: 1, status: 'confirmed', source: { kind: 'manual' },
        text: stress ? 'Reviewed instrument readings. 项目记录 王🧪 '.repeat(90) + '完整经历尾部。' : 'Compared instrument readings; I assisted and did not lead the project.' },
      { id: 'experience-last', revision: 1, status: 'confirmed', source: { kind: 'manual' }, text: 'Documented the final calibration procedure.' },
      { id: 'candidate', revision: 1, status: 'candidate', source: { kind: 'manual' }, text: CANDIDATE },
    ] };
}

async function openDraft(page: Page, value = profile()) {
  await page.addInitScript(({ profileKey, localeKey, value }) => {
    if (!localStorage.getItem('export-browser-seeded')) {
      localStorage.setItem(profileKey, JSON.stringify(value));
      localStorage.setItem(localeKey, 'en');
      localStorage.setItem('export-browser-seeded', '1');
    }
  }, { profileKey: STORAGE_KEYS.PROFILE, localeKey: STORAGE_KEYS.LOCALE, value });
  await page.goto(`/opportunities/${TARGET}`);
  await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
  await expect(dialog(page)).toBeVisible();
  await dialog(page).getByRole('button', { name: 'Create from confirmed master', exact: true }).click();
  await expect(dialog(page).getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue(ORIGINAL_NAME);
  await expect(panel(page).getByRole('button', { name: 'Export PDF', exact: true })).toBeEnabled();
}

function traffic(page: Page) {
  const exports: TargetResumeExportRequest[] = [];
  const writes: string[] = [];
  const ai: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/resume/full-target/export') exports.push(request.postDataJSON());
    if (/\/rest\/v1\/rpc\/commit_(?:target_resume|profile_patch)_cas/.test(request.url())) writes.push(request.url());
    if (new URL(request.url()).pathname.startsWith('/api/tailor/')) ai.push(request.url());
  });
  return { exports, writes, ai };
}

async function masterUnchanged(page: Page, value: ProfileData) {
  const stored = await page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? '{}'), STORAGE_KEYS.PROFILE);
  expect(stored.resume_master).toEqual(value.resume_master);
  expect(stored.experience_entries).toEqual(value.experience_entries);
  expect(stored.resume_text).toBe(value.resume_text);
}

async function downloadFile(page: Page, format: 'pdf' | 'docx', info: TestInfo, stem: string) {
  const pending = page.waitForEvent('download');
  await panel(page).getByRole('button', { name: format === 'pdf' ? 'Export PDF' : 'Export Word', exact: true }).click();
  const download = await pending;
  expect(download.suggestedFilename()).toMatch(new RegExp(`^resume-(en|zh)\\.${format}$`));
  const path = info.outputPath(`${stem}.${format}`);
  await download.saveAs(path);
  expect(await download.failure()).toBeNull();
  const bytes = await readFile(path);
  expect(bytes.length).toBeGreaterThan(100);
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

function projectionTexts(request: TargetResumeExportRequest): string[] {
  return request.projection.sections.flatMap(section => section.blocks.flatMap(block => block.lines.map(line => line.text)));
}
function expectCurrentContent(text: string) {
  const normalized = compact(text);
  for (const included of [EDITED_NAME, 'Expected 2027 — 尚未毕业', 'J. Lee; Alex 王; M. Doe', 'Submitted, not accepted', LAST_ITEM]) {
    expect(normalized).toContain(compact(included));
  }
  for (const excluded of [RAW_PRIVATE, CANDIDATE, HIDDEN_DEGREE, HIDDEN_BLOCK, HIDDEN_SECTION]) expect(normalized).not.toContain(compact(excluded));
  expect(normalized.indexOf(compact('Last project moved first'))).toBeLessThan(normalized.indexOf(compact('First project 第一项')));
}

function switchedSession(uid: string) {
  const now = Math.floor(Date.now() / 1000);
  const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
  return { access_token: `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode({ sub: uid, aud: 'authenticated', role: 'authenticated', iat: now, exp: now + 3600, is_anonymous: true })}.e2e-only`,
    refresh_token: `stub-refresh-${uid}`, token_type: 'bearer', expires_in: 3600, expires_at: now + 3600,
    user: { id: uid, aud: 'authenticated', role: 'authenticated', is_anonymous: true,
      app_metadata: { provider: 'anonymous', providers: ['anonymous'] }, user_metadata: {}, identities: [], created_at: '2026-01-01T00:00:00Z' } };
}

test.describe('Complete target résumé export', () => {
  test.describe.configure({ timeout: 90_000 });

  test('PDF and editable Word download the current selected, reordered and manually edited draft without saving it', async ({ page }, info) => {
    const value = profile(); const net = traffic(page);
    await openDraft(page, value);
    await dialog(page).getByRole('textbox', { name: 'Edit Full name', exact: true }).fill(EDITED_NAME);
    await dialog(page).getByRole('checkbox', { name: 'Include field: Degree', exact: true }).uncheck();
    await page.getByTestId('target-block-project-hidden').getByRole('checkbox', { name: /Include whole block/ }).uncheck();
    await dialog(page).getByRole('group', { name: 'Skills', exact: true }).getByRole('checkbox', { name: 'Include this section', exact: true }).uncheck();
    await dialog(page).getByRole('button', { name: 'Move block up 3 Experience and projects', exact: true }).click();
    await dialog(page).getByRole('button', { name: 'Move block up 2 Experience and projects', exact: true }).click();
    await expect(panel(page)).toContainText('Includes unsaved edits. Exporting does not save this version to your account.');
    const pdf = await readPdf(await downloadFile(page, 'pdf', info, 'selected-current-draft'));
    const docx = await readDocx(page, await downloadFile(page, 'docx', info, 'selected-current-draft'));
    await panel(page).scrollIntoViewIfNeeded();
    const layout = await panel(page).evaluate(element => {
      const box = element.getBoundingClientRect();
      const modal = element.closest('[role="dialog"]') as HTMLElement;
      return { left: box.left, right: box.right, viewport: document.documentElement.clientWidth,
        pageWidth: document.documentElement.scrollWidth, panelWidth: element.scrollWidth,
        panelClient: element.clientWidth, modalWidth: modal.scrollWidth, modalClient: modal.clientWidth };
    });
    expect(layout.left).toBeGreaterThanOrEqual(-1);
    expect(layout.right).toBeLessThanOrEqual(layout.viewport + 1);
    expect(layout.pageWidth).toBeLessThanOrEqual(layout.viewport + 1);
    expect(layout.panelWidth).toBeLessThanOrEqual(layout.panelClient + 1);
    expect(layout.modalWidth).toBeLessThanOrEqual(layout.modalClient + 1);
    const screenshot = info.outputPath('target-resume-export-panel.png');
    await page.screenshot({ path: screenshot, fullPage: false });
    await info.attach('Export controls after successful downloads', { path: screenshot, contentType: 'image/png' });
    expectCurrentContent(pdf.text); expectCurrentContent(docx.text);
    expect(pdf.links).toContain(LINK); expect(docx.links).toContain(LINK);
    expect(pdf.sizes[0][0]).toBeCloseTo(612, 0); expect(pdf.sizes[0][1]).toBeCloseTo(792, 0);
    expect(net.exports).toHaveLength(2);
    expect(net.exports[0].projection).toEqual(net.exports[1].projection);
    for (const request of net.exports) {
      expectCurrentContent(projectionTexts(request).join('\n'));
      expect(Object.keys(request).sort()).toEqual(['version', 'request_id', 'format', 'document_signature', 'export_signature', 'projection'].sort());
      expect(JSON.stringify(request)).not.toContain(RAW_PRIVATE);
      expect(JSON.stringify(request)).not.toContain(CANDIDATE);
    }
    expect(net.writes).toEqual([]); expect(net.ai).toEqual([]);
    await expect(dialog(page).getByText('Unsaved local edits', { exact: true })).toBeVisible();
    await masterUnchanged(page, value);
  });

  test('both files preserve Chinese, non-BMP text, a long unbroken field and URL, and the final item across multiple A4 pages', async ({ page }, info) => {
    const value = profile(true); const net = traffic(page);
    await openDraft(page, value);
    await panel(page).getByRole('combobox', { name: 'Section headings language', exact: true }).selectOption('zh');
    await panel(page).getByRole('combobox', { name: 'Paper size', exact: true }).selectOption('a4');
    const pdf = await readPdf(await downloadFile(page, 'pdf', info, 'complete-chinese-long-a4'));
    const docx = await readDocx(page, await downloadFile(page, 'docx', info, 'complete-chinese-long-a4'));
    expect(pdf.pages.length).toBeGreaterThan(1);
    for (const text of [pdf.text, docx.text]) {
      for (const original of [ORIGINAL_NAME, LONG_WORD, LONG_URL, LAST_ITEM, value.experience_entries![0].text, '教育经历', '论文与发表']) {
        expect(compact(text)).toContain(compact(original));
      }
      expect(compact(text)).not.toContain(compact(RAW_PRIVATE));
      expect(text).not.toContain(CANDIDATE);
    }
    expect(compact(pdf.pages.at(-1)!)).toContain(compact(LAST_ITEM));
    expect(docx.paragraphs.some(text => text.endsWith(LONG_WORD))).toBe(true);
    expect(docx.paragraphs.at(-1)).toContain(LAST_ITEM);
    expect(pdf.links).toContain(LONG_URL); expect(docx.links).toContain(LONG_URL);
    expect(pdf.sizes[0][0]).toBeCloseTo(595.28, 1); expect(pdf.sizes[0][1]).toBeCloseTo(841.89, 1);
    expect(net.exports.every(request => request.projection.locale === 'zh' && request.projection.page_size === 'a4')).toBe(true);
    expect(net.writes).toEqual([]); expect(net.ai).toEqual([]);
    await masterUnchanged(page, value);
  });

  test('an export failure keeps the draft and starts no download or hidden retry; the student can explicitly retry a real export', async ({ page }, info) => {
    const net = traffic(page); const downloads: Download[] = [];
    page.on('download', download => downloads.push(download));
    let attempts = 0;
    await page.route(EXPORT_URL, async route => {
      attempts += 1;
      if (attempts === 1) await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'fonts_unavailable', private: 'PRIVATE ERROR BODY MUST NOT SHOW' } }) });
      else await route.continue();
    });
    await openDraft(page);
    await dialog(page).getByRole('textbox', { name: 'Edit Full name', exact: true }).fill(EDITED_NAME);
    await panel(page).getByRole('button', { name: 'Export PDF', exact: true }).click();
    await expect(panel(page).getByRole('alert')).toHaveText('The export fonts are temporarily unavailable. Your draft is kept.');
    await expect(panel(page).getByRole('button', { name: 'Export PDF', exact: true })).toBeEnabled();
    expect(attempts).toBe(1); expect(downloads).toHaveLength(0);
    await expect(dialog(page).getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue(EDITED_NAME);
    await expect(dialog(page)).not.toContainText('PRIVATE ERROR BODY MUST NOT SHOW');
    const pdf = await readPdf(await downloadFile(page, 'pdf', info, 'explicit-retry'));
    expect(compact(pdf.text)).toContain(compact(EDITED_NAME));
    expect(attempts).toBe(2); expect(downloads).toHaveLength(1);
    expect(net.writes).toEqual([]); expect(net.ai).toEqual([]);
    await expect(panel(page).getByRole('alert')).toHaveCount(0);
  });

  test('a real file delivered late cannot download after a later edit or an auth owner change', async ({ page, context }) => {
    const net = traffic(page); const downloads: Download[] = [];
    page.on('download', download => downloads.push(download));
    const held: Array<{ request: Request; release: () => void; settled: Promise<void> }> = [];
    await page.route(EXPORT_URL, async (route: Route) => {
      // Render first on the real backend, then hold only delivery to the browser.
      const response = await route.fetch({ maxRetries: 0 });
      expect(response.status()).toBe(200);
      const bytes = await response.body();
      const format = (route.request().postDataJSON() as TargetResumeExportRequest).format;
      expect(bytes.subarray(0, format === 'pdf' ? 5 : 2).toString()).toBe(format === 'pdf' ? '%PDF-' : 'PK');
      let release!: () => void, settle!: () => void;
      const gate = new Promise<void>(resolve => { release = resolve; });
      const settled = new Promise<void>(resolve => { settle = resolve; });
      held.push({ request: route.request(), release, settled });
      await gate;
      try { await route.fulfill({ response, body: bytes }); }
      catch (error) { if (!route.request().failure()) throw error; }
      finally { settle(); }
    });
    try {
      await openDraft(page);
      await panel(page).getByRole('button', { name: 'Export PDF', exact: true }).click();
      await expect.poll(() => held.length).toBe(1);
      await dialog(page).getByRole('textbox', { name: 'Edit Full name', exact: true }).fill(EDITED_NAME);
      await expect.poll(() => held[0].request.failure()).not.toBeNull();
      held[0].release(); await held[0].settled;
      await expect(panel(page).getByRole('button', { name: 'Export PDF', exact: true })).toBeEnabled();
      await expect(panel(page)).not.toContainText('Download started.');
      expect(downloads).toHaveLength(0);
      await expect(dialog(page).getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue(EDITED_NAME);
      await panel(page).getByRole('button', { name: 'Export Word', exact: true }).click();
      await expect.poll(() => held.length).toBe(2);
      const nextOwner = '66666666-6666-4666-8666-666666666666';
      const secondTab = await context.newPage();
      try {
        await secondTab.goto('/robots.txt');
        await secondTab.evaluate(session => {
          localStorage.setItem('ofe_auth', JSON.stringify(session));
          const channel = new BroadcastChannel('ofe_auth');
          channel.postMessage({ event: 'SIGNED_IN', session }); channel.close();
        }, switchedSession(nextOwner));
        await expect.poll(() => page.evaluate(key => localStorage.getItem(key), STORAGE_KEYS.LOCAL_IDENTITY_OWNER)).toContain(nextOwner);
        await expect(dialog(page)).toHaveCount(0);
        await expect.poll(() => held[1].request.failure()).not.toBeNull();
        held[1].release(); await held[1].settled;
        expect(downloads).toHaveLength(0);
        await expect(page.getByText(EDITED_NAME, { exact: true })).toHaveCount(0);
      } finally { await secondTab.close(); }
      expect(net.exports).toHaveLength(2); expect(net.writes).toEqual([]); expect(net.ai).toEqual([]);
    } finally { for (const item of held) item.release(); }
  });
});
