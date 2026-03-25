import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1024 }
  });
  const page = await context.newPage();

  page.on('response', response => {
    if (response.status() >= 400 && response.status() !== 403) { // Ignore 403 for WS
      console.error(`NETWORK BAD STATUS: ${response.status()} ${response.url()}`);
    }
  });

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
      
      const errors = await page.locator('.error-message, .error').allTextContents();
      if (errors.length > 0) {
          console.log(`Found error class in ${view}:`, errors);
      }
    }
  }

  await browser.close();
})();
