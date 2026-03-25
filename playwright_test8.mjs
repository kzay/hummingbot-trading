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
    console.log(`\n=================== ${view} ===================`);
    const btn = await page.locator(`button:has-text("${view}")`).first();
    if (await btn.count() > 0) {
      await btn.click();
      await page.waitForTimeout(1500); // allow data to fetch
      
      const body = await page.evaluate(() => {
        const root = document.querySelector('main');
        return root ? root.innerText : document.body.innerText;
      });
      console.log(body);
    } else {
      console.log(`BUTTON NOT FOUND: ${view}`);
    }
  }

  await browser.close();
})();
