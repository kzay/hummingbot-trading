import { expect, test } from "@playwright/test";

test("check wide grid layout elements", async ({ page }) => {
  await page.setViewportSize({ width: 2560, height: 1440 });
  await page.goto("/");
  await page.waitForTimeout(2000);
  
  const container = await page.locator('.layout').boundingBox();
  console.log(`Container box: ${JSON.stringify(container)}`);
  
  const items = await page.locator('.react-grid-item').all();
  console.log(`Found ${items.length} grid items`);
  
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const box = await item.boundingBox();
    console.log(`Item ${i}: box=${JSON.stringify(box)}`);
  }
});
