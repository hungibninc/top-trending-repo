import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

// E2E for API error states (PRD AC-7):
//   1. When latest.json carries stale: true, the page shows the alert
//      banner AND still renders the last good list.
//   2. When the fetcher's API call fails, it exits non-zero and never
//      modifies data/latest.json.

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const LATEST_JSON = path.join(REPO_ROOT, "data", "latest.json");

test.describe("API error states", () => {
  test("stale build shows the alert banner and keeps the last good list", async ({ page }) => {
    await page.goto("http://localhost:8091/");
    const banner = page.locator(".banner[role='alert']");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/API fetch failed/);
    // Last good data still served (10 fixture cards, non-empty)
    await expect(page.locator("article.card")).toHaveCount(10);
    await expect(page.locator("article.card .card-title a").first()).toHaveText(
      "owner/repo-1"
    );
  });

  test("healthy build shows no stale banner", async ({ page }) => {
    await page.goto("http://localhost:8090/");
    await expect(page.locator(".banner[role='alert']")).toHaveCount(0);
  });

  test("fetcher exits 1 on API failure and leaves latest.json untouched", async () => {
    const before = readFileSync(LATEST_JSON);
    let exitCode: number | null = null;
    let stderr = "";
    try {
      execFileSync(
        "python3",
        [
          "scripts/fetch_trending.py",
          "--api-url", "https://api.github.com/does-not-exist", // deterministic 404, no rate-limit cost
          "--max-retries", "1",
        ],
        { cwd: REPO_ROOT, stdio: ["ignore", "pipe", "pipe"] }
      );
      exitCode = 0;
    } catch (err: any) {
      exitCode = err.status ?? null;
      stderr = String(err.stderr ?? "");
    }
    expect(exitCode).toBe(1);
    expect(stderr).toContain("HTTP 404");
    const after = readFileSync(LATEST_JSON);
    expect(after.equals(before)).toBe(true); // AC-7: never publish on failure
  });
});
