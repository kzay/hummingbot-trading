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
  
  page.on('requestfailed', request => {
    console.error(`NETWORK FAILED: ${request.method()} ${request.url()} - ${request.failure().errorText}`);
  });

  page.on('response', response => {
    if (response.status() >= 400) {
      console.error(`NETWORK BAD STATUS: ${response.status()} ${response.url()}`);
    }
  });

  console.log('Navigating to dashboard...');
  await page.goto('http://127.0.0.1:8088', { waitUntil: 'networkidle', timeout: 30000 });
  
  await page.waitForTimeout(5000); // give it plenty of time
  
  console.log('Done.');

  await browser.close();
})();
