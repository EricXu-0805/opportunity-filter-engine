import { expect, test } from '@playwright/test';
test('the previous account dashboard rendered a confirmed zero and no saves after a real SDK favorites 503', async ({ page }) => {
  let failed = 0;
  await page.route('**/rest/v1/favorites?**', route => {
    expect(route.request().method()).toBe('GET'); failed++;
    return route.fulfill({ status:503, json:{ message:'synthetic favorites read outage' } });
  });
  await page.goto('/dashboard');
  const saved=page.getByTestId('saved-summary');
  await expect(saved).toHaveAttribute('data-state','ready');
  await expect(saved).toContainText('0');
  await expect(page.getByText('No saved opportunities yet')).toBeVisible();
  expect(failed).toBeGreaterThan(0);
});
