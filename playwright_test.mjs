import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  const logs = [];
  const errors = [];
  const networkErrors = [];

  page.on('console', msg => {
    logs.push(`[${msg.type()}] ${msg.text()}`);
    console.log(`PAGE LOG: [${msg.type()}] ${msg.text()}`);
  });
  
  page.on('pageerror', error => {
    errors.push(error.message);
    console.error(`PAGE ERROR: ${error.message}`);
  });

  page.on('requestfailed', request => {
    networkErrors.push(`${request.method()} ${request.url()} - ${request.failure().errorText}`);
    console.error(`NETWORK ERROR: ${request.method()} ${request.url()} - ${request.failure().errorText}`);
  });

  page.on('response', response => {
    if (response.status() >= 400) {
      console.error(`NETWORK BAD STATUS: ${response.status()} ${response.url()}`);
    }
  });

  console.log('Navigating to http://127.0.0.1:8088...');
  try {
    await page.goto('http://127.0.0.1:8088', { waitUntil: 'networkidle', timeout: 30000 });
  } catch (e) {
    console.error('Failed to navigate:', e.message);
  }

  // Wait a bit for WS and React to render
  await page.waitForTimeout(5000);

  // Get some text from the page to see if it rendered
  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('--- Page Body Start ---');
  console.log(bodyText.substring(0, 1000) + (bodyText.length > 1000 ? '...' : ''));
  console.log('--- Page Body End ---');

  // Let's also check for specific elements
  const hasApp = await page.evaluate(() => !!document.querySelector('#root'));
  console.log(`Has #root element: ${hasApp}`);

  const html = await page.content();
  console.log('--- Page HTML Start ---');
  console.log(html.substring(0, 500) + '...');
  console.log('--- Page HTML End ---');

  await browser.close();
})();
