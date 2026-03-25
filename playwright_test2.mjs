import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1024 }
  });
  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log(`PAGE LOG [${msg.type()}]: ${msg.text()}`);
    }
  });

  page.on('pageerror', error => {
    console.error(`PAGE ERROR: ${error.message}`);
  });

  console.log('Navigating to dashboard...');
  await page.goto('http://127.0.0.1:8088', { waitUntil: 'networkidle', timeout: 30000 });
  
  await page.waitForTimeout(2000);

  // Navigate to ML Features view
  console.log('Clicking ML Features...');
  const mlButton = await page.locator('button:has-text("ML Features")').first();
  if (await mlButton.count() > 0) {
    await mlButton.click();
    await page.waitForTimeout(2000);
    
    const mlBody = await page.evaluate(() => document.body.innerText);
    console.log('--- ML Features Body Start ---');
    console.log(mlBody.substring(0, 1500));
    console.log('--- ML Features Body End ---');
  } else {
    console.log('ML Features button not found');
  }

  // Also check research page
  console.log('Clicking Research...');
  const researchBtn = await page.locator('button:has-text("Research")').first();
  if (await researchBtn.count() > 0) {
    await researchBtn.click();
    await page.waitForTimeout(2000);
    const rsBody = await page.evaluate(() => document.body.innerText);
    console.log('--- Research Body Start ---');
    console.log(rsBody.substring(0, 1500));
    console.log('--- Research Body End ---');
  }

  await browser.close();
})();
