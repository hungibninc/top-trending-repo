import { expect, test } from "@playwright/test";

// E2E for the happy path: the top-10 list renders fully and correctly
// against the real public/ build (data/latest.json from the weekly job).

test.describe("top-10 list renders", () => {
  test("shows exactly 10 repo cards", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("article.card")).toHaveCount(10);
  });

  test("cards are ranked 1..10 in order", async ({ page }) => {
    await page.goto("/");
    const ranks = await page.locator("article.card .card-rank").allTextContents();
    expect(ranks).toEqual(Array.from({ length: 10 }, (_, i) => `#${i + 1}`));
  });

  test("every card shows name, description, stars, forks, and language", async ({ page }) => {
    await page.goto("/");
    const cards = page.locator("article.card");
    for (let i = 0; i < await cards.count(); i++) {
      const card = cards.nth(i);
      await expect(card.locator(".card-title a")).toHaveText(/.+\/.+/); // owner/repo
      await expect(card.locator(".card-desc")).not.toBeEmpty(); // or fallback text
      await expect(card.locator(".card-meta")).toContainText(/^\s*\d{1,3}(,\d{3})*\s*$/m); // formatted stars
      await expect(card.locator(".stat.lang")).not.toBeEmpty(); // language or "Unknown"
      await expect(card.locator("svg").nth(0)).toBeVisible(); // star icon
      await expect(card.locator("svg").nth(1)).toBeVisible(); // fork icon
    }
  });

  test("every repo link opens github.com in a new tab, safely", async ({ page }) => {
    await page.goto("/");
    const links = page.locator("article.card .card-title a");
    await expect(links).toHaveCount(10);
    for (let i = 0; i < await links.count(); i++) {
      const link = links.nth(i);
      await expect(link).toHaveAttribute("target", "_blank");
      await expect(link).toHaveAttribute("rel", /noopener/);
      await expect(link).toHaveAttribute("href", /^https:\/\/github\.com\/.+\/.+$/);
    }
  });

  test("shows the 'as of' UTC timestamp", async ({ page }) => {
    await page.goto("/");
    const time = page.locator("time");
    await expect(time).toHaveCount(1);
    await expect(time).toHaveAttribute("datetime", /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    await expect(time).toContainText(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}/);
    await expect(page.locator(".asof")).toContainText("UTC");
  });

  test("no horizontal scroll at phone width (~400px, AC-10)", async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 800 });
    await page.goto("/");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("page has an H1 heading and semantic main region", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("main#main")).toBeVisible();
  });
});
