import process from 'node:process';
import { createRequire } from 'node:module';
import { webkit } from '@playwright/test';

const require = createRequire(import.meta.url);
const packageInfo = require('@playwright/test/package.json');
const expected = '1.62.1';
if (packageInfo.version !== expected) {
  console.error(`@playwright/test ${packageInfo.version} does not match pin ${expected}`);
  process.exit(1);
}

const report = { package: '@playwright/test', version: packageInfo.version, matches_pin: true, browser_launch: false };
if (process.argv.includes('--launch')) {
  const browser = await webkit.launch({ headless: true });
  report.browser_launch = true;
  report.browser_version = browser.version();
  await browser.close();
}
console.log(JSON.stringify(report));
