import { test } from '@playwright/test';

test('probe: why does the grade pick vanish after the zh switch?', async ({ page }) => {
  page.on('request', (r) => {
    const u = r.url();
    if (u.includes(':54321/rest/v1/rpc') || u.includes(':54321/rest/v1/profiles') || u.includes(':54321/auth')) {
      console.log(`[REQ ${Date.now() % 100000}] ${r.method()} ${u.replace(/^http:\/\/127\.0\.0\.1:54321/, '').slice(0, 90)} ${(r.postData() ?? '').slice(0, 200)}`);
    }
  });
  page.on('response', async (r) => {
    const u = r.url();
    if (u.includes(':54321/rest/v1/rpc')) {
      console.log(`[RES ${Date.now() % 100000}] ${r.status()} ${(await r.text().catch(() => '')).slice(0, 200)}`);
    }
  });

  await page.goto('/');
  await page.getByRole('button', { name: /Switch to Chinese/i }).click();
  console.log(`[T ${Date.now() % 100000}] switched to zh`);

  await page.selectOption('#college', 'Grainger College of Engineering');
  console.log(`[T ${Date.now() % 100000}] picked college`);
  await page.selectOption('#major', { index: 1 });
  console.log(`[T ${Date.now() % 100000}] picked major`);
  await page.selectOption('#grade', { index: 1 });
  console.log(`[T ${Date.now() % 100000}] picked grade -> ${await page.locator('#grade').inputValue()}`);

  for (let i = 0; i < 10; i += 1) {
    await page.waitForTimeout(500);
    const grade = await page.locator('#grade').inputValue();
    const btnDisabled = await page.locator('[data-testid="generate-matches"]').isDisabled();
    console.log(`[T ${Date.now() % 100000}] +${(i + 1) * 500}ms grade="${grade}" generateDisabled=${btnDisabled}`);
  }
});
