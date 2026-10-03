import { test, expect, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import { account, seed, type Owner } from './contact-materials-fixture';

// Every private import id has a ':', and every link to its page escapes it as '%3A'. Next 16
// hands a page component encodeURIComponent(segment), so the page passed '%3A' on and the
// client's id check refused it before any request: every import page, opened from a link or
// loaded directly, said "This import could not be loaded."
const ID = 'private-import:12345678-1234-4234-9234-123456789abc';
const TARGET_PATH = `/api/private-import-targets/${encodeURIComponent(ID)}`;

// The E2E backend has no Supabase service key, so these specs answer the target read
// themselves. What is under test is which id the page asks for; the answer is the
// backend's reply for an id this account does not hold.
async function targetReads(page: Page): Promise<string[]> {
  const asked: string[] = [];
  await page.route(url => /^\/api\/private-import-targets\/[^/]+$/.test(url.pathname), route => {
    asked.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 404, json: { detail: { code: 'private_target_not_found' } } });
  });
  return asked;
}

async function expectImportRequested(page: Page, asked: string[]) {
  await expect(page.getByText('This import is not available in this account.')).toBeVisible();
  await expect(page.getByText(/This import could not be loaded/)).toHaveCount(0);
  expect([...new Set(asked)]).toEqual([TARGET_PATH]);
}

function listItem(owner: Owner) {
  const ownerId = owner.session.user.id; const revision = 1; const at = '2026-09-30T12:00:00.000Z';
  const version = createHash('sha256').update(JSON.stringify({ id: ID, owner_id: ownerId, revision })).digest('hex');
  return { id: ID, owner_id: ownerId, revision, created_at: at, updated_at: at, deleted_at: null,
    target_scope: 'private_import', verification: 'unverified', target_version: 'pit1:' + version,
    title: 'Imported lab posting', organization: null, source_url: 'https://example.test/lab', url: 'https://example.test/lab', source: 'url_parser' };
}

test.describe('Private import page', () => {
  test('a direct load reads the import named in the URL', async ({ page }) => {
    const owner = await account(); try {
      await seed(page, owner);
      const asked = await targetReads(page);
      await page.goto(`/private-imports/${encodeURIComponent(ID)}`);
      await expectImportRequested(page, asked);
    } finally { await owner.http.dispose(); }
  });

  test('"View records" in the saved list reads the import it names', async ({ page }) => {
    const owner = await account(); try {
      await seed(page, owner);
      await page.route(url => url.pathname === '/api/private-import-targets', route =>
        route.fulfill({ json: { version: 1, items: [listItem(owner)], next_cursor: null } }));
      const asked = await targetReads(page);
      const documents: string[] = [];
      page.on('request', request => { if (request.resourceType() === 'document') documents.push(request.url()); });
      await page.goto('/favorites');
      await page.getByRole('link', { name: 'View records' }).click();
      await expectImportRequested(page, asked);
      expect(documents, 'the link should navigate on the client').toHaveLength(1);
    } finally { await owner.http.dispose(); }
  });
});
