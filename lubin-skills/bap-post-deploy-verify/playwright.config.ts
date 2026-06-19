import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.HEYBAP_URL ?? "https://heybap.com";

export default defineConfig({
  testDir: "./playwright-tests",
  testMatch: /.*\.spec\.ts$/,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: process.env.CI ? "github" : "json",
  outputDir: "/tmp/bap-verify-playwright",
  use: {
    baseURL,
    storageState: process.env.HEYBAP_PLAYWRIGHT_AUTH ?? `${process.env.HOME}/.heybap-playwright-auth.json`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
