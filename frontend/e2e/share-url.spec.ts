import { test, expect } from '@playwright/test';

test.describe('Profile share URL', () => {
  test('generates a copyable share URL with encoded profile', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    await page.getByRole('textbox', { name: /Research Interests/i }).fill('signed-profile-marker-abc123');

    const shareBtn = page.getByRole('button', { name: /Share profile/i });
    await expect(shareBtn).toBeVisible();
    await shareBtn.click();

    await expect(page.getByText(/Copied!/)).toBeVisible();

    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboard).toContain('?share=');
    expect(clipboard.split('?share=')[1].length).toBeGreaterThan(20);
  });

  test('loading a share URL pre-fills the form and shows banner', async ({ page }) => {
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    await page.getByRole('textbox', { name: /Research Interests/i })
      .fill('MARKER_SHARED_E2E_ZZZ');

    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.getByRole('button', { name: /Share profile/i }).click();
    await expect(page.getByText(/Copied!/)).toBeVisible();
    const shareUrl = await page.evaluate(() => navigator.clipboard.readText());

    const victim = await page.context().newPage();
    await victim.goto(shareUrl);

    await expect(victim.getByText(/Loaded a shared profile/i)).toBeVisible();
    await expect(victim.locator('#research_interests'))
      .toHaveValue(/MARKER_SHARED_E2E_ZZZ/);
  });

  test('rejects malformed share payload gracefully', async ({ page }) => {
    await page.goto('/?share=not-a-valid-payload!!!');
    await expect(page.getByText(/Loaded a shared profile/i)).not.toBeVisible();
    await expect(page.getByRole('heading', { name: /Find Your Perfect/i })).toBeVisible();
  });
});
