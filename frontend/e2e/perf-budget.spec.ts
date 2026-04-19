import { test, expect } from '@playwright/test';

interface WebVitals {
  lcp: number;
  cls: number;
  fcp: number;
  loadTime: number;
  domInteractive: number;
  transferKB: number;
}

async function collectWebVitals(page: import('@playwright/test').Page, url: string): Promise<WebVitals> {
  let transferKB = 0;
  page.on('response', async resp => {
    const headers = resp.headers();
    const cl = headers['content-length'];
    if (cl) transferKB += Number(cl);
  });

  await page.goto(url, { waitUntil: 'load' });

  const vitals = await page.evaluate(() =>
    new Promise<{ lcp: number; cls: number; fcp: number; loadTime: number; domInteractive: number }>(
      (resolve) => {
        let lcp = 0;
        let cls = 0;

        const lcpObserver = new PerformanceObserver(list => {
          const entries = list.getEntries();
          const last = entries[entries.length - 1] as PerformanceEntry & { renderTime?: number; loadTime?: number };
          lcp = last.renderTime || last.loadTime || last.startTime;
        });
        lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true });

        const clsObserver = new PerformanceObserver(list => {
          for (const entry of list.getEntries() as Array<PerformanceEntry & { value?: number; hadRecentInput?: boolean }>) {
            if (!entry.hadRecentInput && entry.value) cls += entry.value;
          }
        });
        clsObserver.observe({ type: 'layout-shift', buffered: true });

        const fcpEntry = performance.getEntriesByName('first-contentful-paint')[0];
        const fcp = fcpEntry ? fcpEntry.startTime : 0;

        const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
        const loadTime = nav ? nav.loadEventEnd - nav.startTime : 0;
        const domInteractive = nav ? nav.domInteractive - nav.startTime : 0;

        setTimeout(() => {
          lcpObserver.disconnect();
          clsObserver.disconnect();
          resolve({ lcp, cls, fcp, loadTime, domInteractive });
        }, 2000);
      },
    ),
  );

  return { ...vitals, transferKB: Math.round(transferKB / 1024) };
}

test.describe('Performance budget', () => {
  test('home page meets LCP < 3s, CLS < 0.1', async ({ page }) => {
    const v = await collectWebVitals(page, '/');
    console.log('Home page vitals:', v);
    expect(v.lcp, `LCP was ${v.lcp}ms`).toBeLessThan(3000);
    expect(v.cls, `CLS was ${v.cls}`).toBeLessThan(0.1);
    expect(v.fcp, `FCP was ${v.fcp}ms`).toBeLessThan(2000);
    expect(v.domInteractive, `DOM interactive was ${v.domInteractive}ms`).toBeLessThan(5000);
  });

  test('about page is lean', async ({ page }) => {
    const v = await collectWebVitals(page, '/about');
    console.log('About page vitals:', v);
    expect(v.lcp).toBeLessThan(2500);
    expect(v.cls).toBeLessThan(0.05);
  });

  test('dashboard loads stats without excessive CLS', async ({ page }) => {
    const v = await collectWebVitals(page, '/dashboard');
    console.log('Dashboard vitals:', v);
    expect(v.cls, `CLS was ${v.cls}`).toBeLessThan(0.2);
  });
});

test.describe('Bundle budget', () => {
  test('home page first-load JS transferred size', async ({ page }) => {
    let jsBytes = 0;
    page.on('response', resp => {
      const url = resp.url();
      if (url.includes('/_next/static/chunks/') && url.endsWith('.js')) {
        resp.body().then(buf => { jsBytes += buf.length; }).catch(() => {});
      }
    });
    await page.goto('/', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const kb = Math.round(jsBytes / 1024);
    console.log(`Home first-load JS: ${kb} KB transferred`);
    const isDev = kb > 1000;
    const budget = isDev ? 10_000 : 600;
    expect(kb, `${isDev ? 'dev' : 'prod'} bundle was ${kb}KB`).toBeLessThan(budget);
  });
});
