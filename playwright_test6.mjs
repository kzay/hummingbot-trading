import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1024 }
  });
  const page = await context.newPage();

  console.log('Navigating to dashboard...');
  await page.goto('http://127.0.0.1:8088', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(2000);

  const views = [
    'Bots', 'Backtest', 'Research', 'ML Features', 
    'Daily Review', 'Weekly Review', 'Journal', 
    'Service Monitor', 'History Monitor'
  ];

  for (const view of views) {
    const btn = await page.locator(`button:has-text("${view}")`).first();
    if (await btn.count() > 0) {
      await btn.click();
      await page.waitForTimeout(1000);
      
      const body = await page.evaluate(() => document.body.innerText);
      if (body.includes('NaN')) {
        console.log(`Found NaN in ${view} view!`);
        let index = body.indexOf('NaN');
        while (index !== -1) {
          const start = Math.max(0, index - 20);
          const end = Math.min(body.length, index + 20);
          console.log(`  Context: ...${body.substring(start, end).replace(/\n/g, ' ')}...`);
          index = body.indexOf('NaN', index + 1);
        }
      }
    }
  }

  await browser.close();
})();
