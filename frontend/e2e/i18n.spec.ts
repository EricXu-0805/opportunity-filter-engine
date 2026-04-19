import { test, expect } from '@playwright/test';

test.describe('i18n: language switcher', () => {
  test('default English renders "Find Matches" and "Generate Matches"', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: /Find Matches|^Match$/ }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /Generate Matches/i })).toBeVisible();
  });

  test('switcher toggles page to Chinese', async ({ page }) => {
    await page.goto('/');
    const switcher = page.getByRole('button', { name: /Switch to Chinese/i });
    await switcher.click();
    await expect(page.getByRole('link', { name: /匹配机会|^匹配$/ }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /生成匹配/ })).toBeVisible();
  });

  test('html lang attribute updates on switch', async ({ page }) => {
    await page.goto('/');
    expect(await page.locator('html').getAttribute('lang')).toBe('en');
    await page.getByRole('button', { name: /Switch to Chinese/i }).click();
    expect(await page.locator('html').getAttribute('lang')).toBe('zh');
  });

  test('language preference persists across navigations via cookie', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /Switch to Chinese/i }).click();
    await expect(page.getByRole('link', { name: /匹配机会|^匹配$/ }).first()).toBeVisible();

    await page.goto('/about');
    await expect(page.getByRole('link', { name: /匹配机会|^匹配$/ }).first()).toBeVisible();

    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: '仪表盘' })).toBeVisible();
  });

  test('SSR respects cookie on first byte (no English flash)', async ({ page, context }) => {
    await context.addCookies([{
      name: 'ofe_lang',
      value: 'zh',
      url: page.url().startsWith('http') ? page.url() : 'http://127.0.0.1:3100',
    }]);
    const response = await page.goto('/');
    const html = await response!.text();
    expect(html).toContain('匹配机会');
    expect(html).toContain('生成匹配');
  });

  test('Accept-Language header is used when no cookie', async ({ browser }) => {
    const zhContext = await browser.newContext({ locale: 'zh-CN' });
    const page = await zhContext.newPage();
    const response = await page.goto('/');
    const html = await response!.text();
    expect(html).toContain('匹配机会');
    await zhContext.close();
  });

  test('switching back to English works', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /Switch to Chinese/i }).click();
    await expect(page.getByRole('button', { name: /生成匹配/ })).toBeVisible();
    await page.getByRole('button', { name: /Switch to English/i }).click();
    await expect(page.getByRole('button', { name: /Generate Matches/i })).toBeVisible();
  });

  test('results page tabs and summary translate', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /Switch to Chinese/i }).click();

    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    await page.getByRole('button', { name: /生成匹配/ }).click();
    await page.waitForURL('**/results*');

    await expect(page.getByRole('heading', { name: '你的匹配' })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('tab', { name: /高优先级/ })).toBeVisible();
    await expect(page.getByRole('tab', { name: /匹配良好/ })).toBeVisible();
  });
});
