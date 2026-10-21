import { existsSync } from 'node:fs';
import { defineConfig } from '@playwright/test';

// A cloud session has Chromium preinstalled; elsewhere `npx playwright install chromium` provides one.
const preinstalled = '/opt/pw-browsers/chromium';
const executablePath =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ?? (existsSync(preinstalled) ? preinstalled : undefined);

export default defineConfig({
  testDir: './e2e',
  // One fake sign-in whose current user the tests switch: tests run one after the other.
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5601',
    launchOptions: { executablePath, args: ['--no-sandbox'] },
    acceptDownloads: true,
  },
  webServer: [
    {
      // Fake ClinicHub sign-in on :5301 and the API on :5600 over a synthetic warehouse.
      command: 'uv run python -m tests.e2e_stack',
      cwd: '..',
      url: 'http://127.0.0.1:5600/healthz',
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: 'npm run build && npm run preview',
      url: 'http://localhost:5601',
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
