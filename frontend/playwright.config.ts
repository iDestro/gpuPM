import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir:'./e2e',
  fullyParallel:false,
  workers:1,
  retries:0,
  use:{channel:process.env.GPUPM_PLAYWRIGHT_CHANNEL || undefined,baseURL:'http://127.0.0.1:8001',trace:'retain-on-failure',screenshot:'only-on-failure'},
  projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
  webServer:{command:'cd .. && uv run --project backend python scripts/e2e_server.py',url:'http://127.0.0.1:8001/api/health',reuseExistingServer:false,timeout:60000},
});
