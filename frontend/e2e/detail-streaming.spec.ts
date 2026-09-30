import { test, expect, type Page } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { createServer, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo, Socket } from 'node:net';
import path from 'node:path';
import type { Opportunity } from '../src/lib/types';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

/** Real production Next/RSC streaming against a loopback HTTP upstream.
 * Only unrelated browser auth/storage calls are replaced. In particular,
 * page.route never supplies the SSR detail or similar response under test.
 * Requires the same safe, prebuilt production app as the main E2E suite.
 */
const frontendDir = path.resolve(__dirname, '..');
const A = 'stream-fixture-a';
const B = 'stream-fixture-b';
const BODY = 'Complete primary description is available independently of recommendations.';
type StreamProbe = { responses: number; markers: number; closedWithoutMarker: number; errors: string[] };
type ProbeWindow = Window & { __detailStreamingProbe?: StreamProbe };
function opportunity(id: string, title: string): Opportunity {
  return {
    id, title, organization: 'Streaming Test University', opportunity_type: 'research',
    source_type: 'campus_program', record_kind: 'listing', source: 'manual',
    school: 'uiuc', audience: 'campus', paid: 'no', location: 'Campus', on_campus: true,
    source_url: 'https://example.edu/streaming-fixture', description_clean: BODY,
    description_raw: BODY, keywords: ['streaming fixture'], is_rolling: true,
    target_truth: { listing_state: 'open', reference_only: false, actionable: true,
      accepting_state: 'accepting', reason_code: null, verified_at: '2026-09-24', expires_at: null },
    eligibility: { international_friendly: 'yes', preferred_year: [], majors: [], skills_required: [], citizenship_required: false },
    application: { application_effort: 'low', requires_resume: 'no', contact_method: 'website' },
    metadata: { is_active: true, confidence_score: 1 },
  };
}
const records = new Map([
  [A, opportunity(A, 'Streaming target A')],
  [B, opportunity(B, 'Streaming target B')],
]);
type Reply = { status: number; body: unknown };
const pending = new Map<string, Set<ServerResponse>>();
const replies = new Map<string, Reply>();
const requests = new Map<string, number>();
const sockets = new Set<Socket>();
let upstream: Server | undefined;
let next: ChildProcess | undefined;
let origin = '';
let nextOutput = '';

function respond(response: ServerResponse, reply: Reply) {
  if (response.destroyed || response.writableEnded) return;
  response.writeHead(reply.status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
  response.end(JSON.stringify(reply.body));
}
function release(id: string, reply: Reply) {
  replies.set(id, reply);
  for (const response of pending.get(id) ?? []) respond(response, reply);
}
function openRequests(id: string) {
  return [...(pending.get(id) ?? [])].filter(response => !response.destroyed && !response.writableEnded).length;
}
function recommendations(...rows: Opportunity[]): Reply {
  return { status: 200, body: { opportunities: rows.map(row => ({ ...row, _similarity: 0.8 })) } };
}
async function stopOwnedServices() {
  const child = next;
  next = undefined;
  try {
    if (child && child.exitCode === null && child.signalCode === null) {
      await new Promise<void>((resolve, reject) => {
        const kill = setTimeout(() => child.kill('SIGKILL'), 3000);
        const deadline = setTimeout(() => { cleanup(); reject(new Error('Owned Next process did not stop')); }, 5000);
        const cleanup = () => { clearTimeout(kill); clearTimeout(deadline); child.off('exit', done); };
        const done = () => { cleanup(); resolve(); };
        child.once('exit', done);
        child.kill('SIGTERM');
      });
    }
  } finally {
    if (upstream) {
      const server = upstream;
      upstream = undefined;
      for (const socket of sockets) socket.destroy();
      server.closeAllConnections();
      if (server.listening) {
        await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
      }
    }
  }
}
async function startOwnedServices() {
  // Refuse a build whose browser API proxy could reach a hosted backend.
  // The suite build normally points this at the existing loopback :8100.
  const manifest = JSON.parse(await readFile(path.join(frontendDir, '.next/routes-manifest.json'), 'utf8'));
  const rewrites: { destination: string }[] = Array.isArray(manifest.rewrites)
    ? manifest.rewrites : Object.values(manifest.rewrites ?? {}).flat() as { destination: string }[];
  for (const rewrite of rewrites) {
    if (!/^https?:\/\//.test(rewrite.destination)) continue;
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(rewrite.destination).hostname)) {
      throw new Error('Detail streaming tests require a build with loopback-only API rewrites');
    }
  }
  upstream = createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1');
    const match = url.pathname.match(/^\/api\/opportunities\/([^/]+)(\/similar)?$/);
    if (request.method !== 'GET' || !match) { respond(response, { status: 404, body: {} }); return; }
    const id = decodeURIComponent(match[1]);
    if (!match[2]) {
      respond(response, records.has(id) ? { status: 200, body: records.get(id) } : { status: 404, body: {} });
      return;
    }
    requests.set(id, (requests.get(id) ?? 0) + 1);
    const ready = replies.get(id);
    if (ready) { respond(response, ready); return; }
    const held = pending.get(id) ?? new Set<ServerResponse>();
    held.add(response); pending.set(id, held);
    response.once('close', () => held.delete(response));
  });
  upstream.on('connection', (socket) => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
  await new Promise<void>((resolve, reject) => {
    upstream!.once('error', reject);
    upstream!.listen(0, '127.0.0.1', () => { upstream!.off('error', reject); resolve(); });
  });
  const backendUrl = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`;
  next = spawn(process.execPath, [path.join(frontendDir, 'node_modules/next/dist/bin/next'), 'start', '--hostname', '127.0.0.1', '--port', '0'], {
    cwd: frontendDir, stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, NODE_ENV: 'production', BACKEND_URL: backendUrl, NEXT_TELEMETRY_DISABLED: '1' },
  });
  const child = next;
  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => { cleanup(); reject(new Error(`Owned Next did not start: ${nextOutput}`)); }, 15_000);
    const cleanup = () => { clearTimeout(timeout); child.off('error', failed); child.off('exit', exited); };
    const failed = (error: Error) => { cleanup(); reject(error); };
    const exited = () => { cleanup(); reject(new Error(`Owned Next exited before readiness: ${nextOutput}`)); };
    const output = (chunk: Buffer) => {
      nextOutput = (nextOutput + chunk.toString()).slice(-12_000);
      const found = nextOutput.match(/http:\/\/127\.0\.0\.1:(\d+)/);
      if (found) origin = `http://127.0.0.1:${found[1]}`;
      if (origin && /Ready in/.test(nextOutput)) { cleanup(); resolve(); }
    };
    child.once('error', failed); child.once('exit', exited);
    child.stdout!.on('data', output); child.stderr!.on('data', output);
  });
}

async function openHeldDetail(page: Page, id: string) {
  await page.goto(`${origin}/opportunities/${id}?returnTo=${encodeURIComponent('/results?tab=all')}`, { waitUntil: 'commit' });
  await expect(page.getByRole('heading', { level: 1, name: records.get(id)!.title })).toBeVisible();
  await expect(page.getByText(BODY, { exact: true })).toBeVisible();
  await expect(page.getByTestId('return-to-results')).toHaveAttribute('href', '/results?tab=all');
  await expect.poll(() => openRequests(id), { message: 'SSR similar request remains held by the real upstream' }).toBeGreaterThan(0);
  expect(replies.has(id)).toBe(false);
}
async function expectHealthyMain(page: Page, id: string) {
  await expect(page.getByRole('heading', { level: 1, name: records.get(id)!.title })).toBeVisible();
  await expect(page.getByText(BODY, { exact: true })).toBeVisible();
  await expect(page.getByTestId('return-to-results')).toBeVisible();
}

test.describe('Production detail streams independently of similar recommendations', () => {
  test.beforeAll(async () => {
    try { await startOwnedServices(); } catch (error) { await stopOwnedServices(); throw error; }
  });
  test.afterAll(async () => { await stopOwnedServices(); });
  test.beforeEach(async ({ page, context }) => {
    pending.clear(); replies.clear(); requests.clear();
    await context.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) { await route.abort('blockedbyclient'); return; }
      // No account/cloud/provider work is needed to read or translate details.
      if (/\/(?:auth|rest)\/v1\//.test(url.pathname) || /^\/api\/(?:cold-email|tailor|resume)(?:\/|$)/.test(url.pathname)) {
        await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }); return;
      }
      await route.continue();
    });
    await page.addInitScript(({ seen, locale }) => {
      localStorage.setItem(seen, '1'); localStorage.setItem(locale, 'en');
      sessionStorage.setItem('ofe_school_confirm_deferred', '1');
    }, { seen: STORAGE_KEYS.ONBOARDING_SEEN, locale: STORAGE_KEYS.LOCALE });
  });
  test.afterEach(async () => {
    for (const id of pending.keys()) release(id, { status: 503, body: {} });
  });

  test('shows usable main content before release, then places localized recommendations above the source footer', async ({ page }) => {
    await openHeldDetail(page, A);
    await page.getByRole('button', { name: /Switch to Chinese/i }).click();
    await expect(page.getByTestId('return-to-results')).toHaveText('返回匹配列表');
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh');
    expect(openRequests(A), 'still pending when the main content is already interactive').toBeGreaterThan(0);
    await expect(page.getByRole('heading', { name: '相似机会', exact: true })).toHaveCount(0);
    release(A, recommendations(records.get(B)!));
    await page.waitForLoadState('load');
    const rail = page.getByRole('region', { name: '相似机会', exact: true });
    await expect(rail.getByRole('link', { name: /Streaming target B/ })).toBeVisible();
    const order = await page.locator('main').last().evaluate(main => {
      const keywords = [...main.querySelectorAll('h2')].find(node => node.textContent === '关键词');
      const similar = main.querySelector('#similar-heading');
      const source = [...main.querySelectorAll('p')].find(node => node.textContent?.startsWith('来源：'));
      return !!keywords && !!similar && !!source
        && !!(keywords.compareDocumentPosition(similar) & Node.DOCUMENT_POSITION_FOLLOWING)
        && !!(similar.compareDocumentPosition(source) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(order, 'keywords → similar rail → original source footer').toBe(true);
    await expectHealthyMain(page, A);
  });

  for (const kind of ['failed', 'malformed'] as const) {
    test(`${kind} recommendation response leaves the primary detail usable`, async ({ page }) => {
      const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
      await openHeldDetail(page, A);
      release(A, kind === 'failed' ? { status: 503, body: {} } : { status: 200, body: { opportunities: { title: 'Malformed rail poison' } } });
      await page.waitForLoadState('load');
      await expectHealthyMain(page, A);
      await expect(page.getByRole('heading', { name: 'Similar opportunities', exact: true })).toHaveCount(0);
      await expect(page.getByText('Malformed rail poison')).toHaveCount(0);
      await page.getByRole('button', { name: /Switch to Chinese/i }).click();
      await expect(page.getByTestId('return-to-results')).toHaveText('返回匹配列表');
      expect(errors).toEqual([]);
    });
  }

  test('returning from A to B cannot paint an old A recommendation into B', async ({ page }) => {
    // Reach A via a real Next Link, then return via browser history while A's
    // RSC stream is incomplete. No synthetic router calls or RSC payloads.
    const lateId = 'late-a-only';
    await page.addInitScript(({ targetPath, marker }) => {
      const state: StreamProbe = { responses: 0, markers: 0, closedWithoutMarker: 0, errors: [] };
      (window as ProbeWindow).__detailStreamingProbe = state;
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (...args: Parameters<typeof fetch>) => {
        const response = await originalFetch(...args);
        if (new URL(response.url, window.location.href).pathname !== targetPath) return response;
        state.responses += 1;
        // Observe the real response without delaying or replacing the branch
        // consumed by Next. RSC can intentionally leave its stream open.
        const reader = response.clone().body?.getReader();
        if (!reader) { state.errors.push('missing-response-body'); return response; }
        void (async () => {
          const decoder = new TextDecoder();
          let tail = '';
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) { state.closedWithoutMarker += 1; return; }
              const text = tail + decoder.decode(value, { stream: true });
              if (text.includes(marker)) {
                state.markers += 1;
                // Cancelling one tee branch can itself wait for the original
                // branch to end, so do not await this optional probe cleanup.
                void reader.cancel().catch(() => {});
                return;
              }
              tail = text.slice(-(marker.length - 1));
            }
          } catch (error) { state.errors.push(error instanceof Error ? error.name : 'stream-read-failed'); }
        })();
        return response;
      };
    }, { targetPath: `/opportunities/${A}`, marker: lateId });
    release(B, recommendations(records.get(A)!));
    const responseForA = page.waitForResponse(response => new URL(response.url()).pathname === `/opportunities/${A}`);
    await page.goto(`${origin}/opportunities/${B}`);
    await expectHealthyMain(page, B);
    const rail = page.getByRole('region', { name: 'Similar opportunities', exact: true });
    await rail.getByRole('link', { name: /Streaming target A/ }).click({ noWaitAfter: true });
    await expect(page.getByRole('heading', { level: 1, name: 'Streaming target A' })).toBeVisible();
    await expect.poll(() => openRequests(A)).toBeGreaterThan(0);
    expect((await responseForA).status()).toBe(200);
    await expect.poll(() => page.evaluate(() => (window as ProbeWindow).__detailStreamingProbe?.responses ?? 0)).toBeGreaterThan(0);
    await page.goBack({ waitUntil: 'commit' });
    await expectHealthyMain(page, B);
    // This receipt must arrive only AFTER B has become the current page.
    expect(await page.evaluate(() => (window as ProbeWindow).__detailStreamingProbe?.markers)).toBe(0);
    expect(replies.has(A)).toBe(false);
    const late = opportunity(lateId, 'Late A recommendation must stay with A');
    release(A, recommendations(late));
    await expect.poll(() => page.evaluate(() => (window as ProbeWindow).__detailStreamingProbe?.markers ?? 0), {
      message: 'the browser reads the real late A payload after returning to B, without waiting for RSC EOF',
    }).toBeGreaterThan(0);
    await page.getByRole('button', { name: /Switch to Chinese/i }).click();
    await expect(page.getByTestId('return-to-results')).toHaveText('返回匹配列表');
    await expect(page.getByRole('region', { name: '相似机会', exact: true }).getByRole('link', { name: /Streaming target A/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Late A recommendation must stay with A/ })).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`/opportunities/${B}$`));
    await expectHealthyMain(page, B);
    expect(requests.get(A)).toBeGreaterThan(0);
  });
});
