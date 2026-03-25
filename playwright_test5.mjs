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

  const views = ['Bots', 'Backtest', 'Weekly Review'];

  for (const view of views) {
    console.log(`\n--- Checking ${view} ---`);
    const btn = await page.locator(`button:has-text("${view}")`).first();
    if (await btn.count() > 0) {
      await btn.click();
      await page.waitForTimeout(1500);
      
      const body = await page.evaluate(() => document.body.innerText.toLowerCase());
      const words = ['error', 'failed', 'undefined', 'null'];
      
      for (const word of words) {
        let index = body.indexOf(word);
        while (index !== -1) {
          const start = Math.max(0, index - 30);
          const end = Math.min(body.length, index + 30);
          console.log(`Found "${word}": ...${body.substring(start, end).replace(/\n/g, ' ')}...`);
          index = body.indexOf(word, index + 1);
        }
      }
    }
  }

  await browser.close();
})();
