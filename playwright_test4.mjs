import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1024 }
  });
  const page = await context.newPage();

  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(`[CONSOLE ERROR] ${msg.text()}`);
    }
  });
  page.on('pageerror', error => {
    errors.push(`[PAGE ERROR] ${error.message}`);
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
    console.log(`\n--- Checking ${view} ---`);
    const btn = await page.locator(`button:has-text("${view}")`).first();
    if (await btn.count() > 0) {
      await btn.click();
      await page.waitForTimeout(1500);
      
      const body = await page.evaluate(() => document.body.innerText);
      // Look for obvious error text in the body
      if (body.toLowerCase().includes('error') || body.toLowerCase().includes('failed') || body.toLowerCase().includes('undefined') || body.toLowerCase().includes('null')) {
        console.log(`Warning: Possible error text found in ${view} view.`);
      }
      
      if (view === 'ML Features' || view === 'Research' || view === 'Service Monitor') {
         console.log(body.substring(200, 800).replace(/\n+/g, ' '));
      }
    } else {
      console.log(`Could not find button for ${view}`);
    }
  }

  console.log('\n--- Errors Captured ---');
  if (errors.length === 0) {
    console.log('None.');
  } else {
    errors.forEach(e => console.log(e));
  }

  await browser.close();
})();
