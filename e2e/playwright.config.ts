import path from "node:path";
import { defineConfig } from "@playwright/test";

// Two static servers (absolute paths: webServer cwd is the config dir):
//   8090 -> public/            the real site build
//   8091 -> e2e/fixtures/stale the AC-7 fixture (stale: true build)
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:8090",
  },
  webServer: [
    {
      command: `python3 -m http.server 8090 --directory ${path.resolve(__dirname, "..", "public")}`,
      url: "http://localhost:8090/",
      reuseExistingServer: true,
    },
    {
      command: `python3 -m http.server 8091 --directory ${path.resolve(__dirname, "fixtures", "stale")}`,
      url: "http://localhost:8091/",
      reuseExistingServer: true,
    },
  ],
});
