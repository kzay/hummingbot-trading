import { expect, test } from "@playwright/test";

test("check grid layout elements", async ({ page }) => {
  await page.goto("/");
  await page.waitForTimeout(2000);
  
  const items = await page.locator('.react-grid-item').all();
  console.log(`Found ${items.length} grid items`);
  
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const box = await item.boundingBox();
    const classes = await item.getAttribute('class');
    const style = await item.getAttribute('style');
    console.log(`Item ${i}: class=${classes}, box=${JSON.stringify(box)}, style=${style}`);
  }
});
