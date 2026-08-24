import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { webkit } from '@playwright/test';

const [specPath, outputDir] = process.argv.slice(2);
if (!specPath || !outputDir) {
  console.error('usage: node runner.mjs RUN_SPEC OUTPUT_DIR');
  process.exit(64);
}

const spec = JSON.parse(await fs.readFile(specPath, 'utf8'));
if (spec.backend?.kind !== 'playwright') {
  console.error('oracle accepts only backend.kind=playwright');
  process.exit(64);
}

await fs.mkdir(outputDir, { recursive: true });
const browser = await webkit.launch({ headless: true });
const context = await browser.newContext({ acceptDownloads: false });
const page = await context.newPage();
const events = [];
const steps = [];
let sequence = 0;
const event = (kind, payload = {}) => events.push({
  schema_version: 'browser-workbench.event/v1',
  event_id: `oracle-${String(++sequence).padStart(6, '0')}`,
  event_seq: sequence,
  kind,
  source: 'oracle',
  payload
});
page.on('console', message => event('console.message', { level: message.type(), text: message.text() }));
page.on('request', request => event('network.request', { url: request.url(), method: request.method() }));
page.on('response', response => event('network.response', { url: response.url(), status: response.status() }));
page.on('dialog', async dialog => { event('dialog.opened', { type: dialog.type() }); await dialog.dismiss(); });
page.on('download', download => event('download.created', { suggested_filename: download.suggestedFilename() }));
page.on('crash', () => event('page.terminated', { reason: 'oracle-crash' }));

let terminal = null;
for (const declaration of spec.workflow) {
  if (terminal) {
    steps.push({ step_id: declaration.step_id, method: declaration.method, status: 'skipped' });
    continue;
  }
  try {
    let result;
    if (declaration.method === 'session.create') result = { session_id: 'oracle-session', page_id: 'oracle-page-1' };
    else if (declaration.method === 'page.navigate') result = { url: (await page.goto(declaration.params.url, { waitUntil: 'commit' })).url() };
    else if (declaration.method === 'page.await') { await page.waitForLoadState('load'); result = { satisfied: true }; }
    else if (declaration.method === 'page.observe') result = { url: page.url(), title: await page.title(), html: await page.content() };
    else if (declaration.method === 'page.act' && declaration.params.intent?.kind === 'javascript') result = { value: await page.evaluate(declaration.params.intent.value) };
    else throw new Error(`unsupported oracle operation: ${declaration.method}`);
    steps.push({ step_id: declaration.step_id, method: declaration.method, status: 'passed', result });
  } catch (error) {
    terminal = { code: 'backend_rejected', message: String(error) };
    steps.push({ step_id: declaration.step_id, method: declaration.method, status: 'failed', error: terminal });
  }
}
await fs.writeFile(path.join(outputDir, 'raw-events.json'), `${JSON.stringify(events, null, 2)}\n`);
await fs.writeFile(path.join(outputDir, 'result.json'), `${JSON.stringify({
  schema_version: 'browser-workbench.result/v1', run_id: spec.run_id,
  status: terminal ? 'failed' : 'passed', backend: spec.backend, steps,
  terminal_reason: terminal ?? { code: 'completed' }, retry_count: 0
}, null, 2)}\n`);
await browser.close();
process.exit(terminal ? 1 : 0);
