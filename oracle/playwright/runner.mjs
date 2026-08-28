import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { createHash } from 'node:crypto';
import { webkit } from '@playwright/test';

// The oracle executes declared steps only. It plans nothing, retries nothing,
// and mirrors the workbench result shape just far enough that the same
// declared `expect` clauses and `$step` references resolve on both lanes.
// It emits no receipts, evaluates no gates, and reports no capabilities.

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

// Mirrors workbench/errors.py so a step's status class agrees across lanes.
const ERROR_STATUS = {
  capability_unsupported: 'unsupported',
  capability_blocked: 'blocked',
  invalid_request: 'invalid',
  protocol_mismatch: 'invalid',
  evidence_incomplete: 'invalid',
  integrity_mismatch: 'invalid',
  candidate_mutated: 'invalid',
  internal_invariant: 'invalid'
};

class OracleError extends Error {
  constructor(code, message, data = {}) {
    super(message);
    this.code = code;
    this.data = data;
  }
}

const isTimeout = error => error?.name === 'TimeoutError' || /Timeout \d+ms exceeded/.test(String(error?.message));
const asOracleError = error => {
  if (error instanceof OracleError) return error;
  if (isTimeout(error)) return new OracleError('deadline_exceeded', String(error.message));
  return new OracleError('backend_rejected', String(error?.message ?? error));
};

// -- declared reference resolution, mirrored from workbench/runner.py --------
const lookupPath = (value, dotted) => {
  let current = value;
  if (dotted) {
    for (const part of dotted.split('.')) {
      if (current && typeof current === 'object' && !Array.isArray(current) && part in current) current = current[part];
      else if (Array.isArray(current) && /^\d+$/.test(part) && Number(part) < current.length) current = current[Number(part)];
      else throw new OracleError('invalid_request', 'workflow reference does not resolve', { path: dotted });
    }
  }
  return structuredClone(current);
};
const resolve = (value, outputs) => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const keys = Object.keys(value);
    if (keys.includes('$step') && keys.every(key => key === '$step' || key === 'path')) {
      if (!(value.$step in outputs)) throw new OracleError('invalid_request', 'workflow references an unavailable step', { step_id: value.$step });
      return lookupPath(outputs[value.$step], String(value.path ?? ''));
    }
    return Object.fromEntries(keys.map(key => [key, resolve(value[key], outputs)]));
  }
  if (Array.isArray(value)) return value.map(item => resolve(item, outputs));
  return value;
};
const expect = (result, expectation) => {
  if (!expectation || Object.keys(expectation).length === 0) return;
  const observed = 'path' in expectation ? lookupPath(result, String(expectation.path)) : result;
  if ('equals' in expectation && JSON.stringify(observed) !== JSON.stringify(expectation.equals)) {
    throw new OracleError('precondition_failed', 'step expectation did not match', { expected: expectation.equals, observed });
  }
  if (expectation.truthy && !(Array.isArray(observed) ? observed.length : observed)) {
    throw new OracleError('precondition_failed', 'step expectation was not truthy');
  }
};

// -- the same target enumeration the native lane injects ----------------------
// Kept byte-for-byte in spirit: same selector, same roles, same ordering, so
// `data.targets.N` names the same element on both lanes. The oracle then
// acts on it with a real pointer, which is its independent contribution.
const TARGET_SCRIPT = `(() => {
  const selector = 'a[href], button, input, select, textarea, [contenteditable="true"]';
  return Array.from(document.querySelectorAll(selector)).map((element, index) => {
    const id = 'target-' + (index + 1);
    element.setAttribute('data-wb-target', id);
    const tag = element.tagName.toLowerCase();
    const type = (element.getAttribute('type') || '').toLowerCase();
    const role = element.getAttribute('role')
      || (tag === 'a' ? 'link'
      : tag === 'button' ? 'button'
      : (tag === 'input' && type === 'file') ? 'file'
      : (tag === 'input' || tag === 'textarea') ? 'textbox'
      : tag);
    const name = (element.getAttribute('aria-label') || element.textContent
      || element.value || element.id || '').trim().slice(0, 80);
    return { target_id: id, role, name, actions: role === 'textbox' ? ['type', 'click'] : ['click'] };
  });
})()`;

await fs.mkdir(outputDir, { recursive: true });
const browser = await webkit.launch({ headless: true });
const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1024, height: 768 } });
const page = await context.newPage();

const events = [];
let sequence = 0;
let generation = 1;
const event = (kind, payload = {}) => {
  events.push({
    schema_version: 'browser-workbench.event/v1',
    event_id: `oracle-${String(++sequence).padStart(6, '0')}`,
    event_seq: sequence,
    kind,
    source: 'oracle',
    generation,
    payload
  });
  return sequence;
};
const since = (cursor, predicate) => events.filter(item => item.event_seq > cursor && predicate(item));

// Browser-owned requests the oracle holds open until a declared decision.
const dialogs = new Map();
const downloads = new Map();
let dialogCounter = 0;
let downloadCounter = 0;

page.on('console', message => event('console.message', { level: message.type(), text: message.text() }));
page.on('request', request => event('network.request', { url: request.url(), method: request.method() }));
page.on('response', response => event('network.response', { url: response.url(), status: response.status() }));
page.on('requestfailed', request => event('network.failed', { url: request.url() }));
page.on('framenavigated', frame => {
  if (frame !== page.mainFrame()) return;
  generation += 1;
  event('navigation.committed', { url: frame.url() });
});
page.on('load', () => event('navigation.finished', { url: page.url() }));
page.on('dialog', dialog => {
  // Not dismissed here: the page stays blocked until a declared decision,
  // exactly as the native engine holds a script dialog open for the host.
  const token = `oracle-dialog-${String(++dialogCounter).padStart(4, '0')}`;
  dialogs.set(token, { token, kind: 'dialog', dialog_type: dialog.type(), message: dialog.message(), status: 'pending', default: 'deny', handle: dialog });
  event('dialog.opened', { token, dialog_type: dialog.type() });
});
page.on('download', download => {
  const token = `oracle-download-${String(++downloadCounter).padStart(4, '0')}`;
  const record = { token, download_id: token, url: download.url(), status: 'pending', destination: null, handle: download };
  downloads.set(token, record);
  event('download.started', { token, url: download.url() });
  download.path().then(destination => {
    record.status = 'completed';
    record.destination = destination;
    event('download.finished', { token, destination });
  }).catch(error => {
    record.status = 'failed';
    record.error = String(error);
    event('download.failed', { token, error: String(error) });
  });
});
page.on('crash', () => event('page.terminated', { reason: 'oracle-crash' }));

const publicRecord = record => Object.fromEntries(Object.entries(record).filter(([key]) => key !== 'handle'));

const awaitCondition = async (condition, deadline) => {
  const expected = condition.equals;
  switch (condition.kind) {
    case 'load_state':
      if (expected !== 'idle') throw new OracleError('invalid_request', `unsupported load_state: ${expected}`);
      return page.waitForLoadState('load', { timeout: deadline });
    case 'title':
      return page.waitForFunction(value => document.title === value, expected, { timeout: deadline, polling: 25 });
    case 'url':
      return page.waitForURL(expected, { timeout: deadline });
    case 'generation':
      if (generation !== expected) throw new OracleError('deadline_exceeded', 'generation condition unsatisfied', { expected, observed: generation });
      return undefined;
    case 'event_kind': {
      const until = Date.now() + deadline;
      while (!events.some(item => item.kind === expected)) {
        if (Date.now() >= until) throw new OracleError('deadline_exceeded', 'await deadline elapsed', { unsatisfied: [condition] });
        await new Promise(resolveWait => setTimeout(resolveWait, 25));
      }
      return undefined;
    }
    default:
      throw new OracleError('invalid_request', `unknown await condition: ${condition.kind}`);
  }
};

const selectorFor = target => {
  if (!target?.target_id) throw new OracleError('invalid_request', 'action requires a target');
  return `[data-wb-target="${target.target_id}"]`;
};

const operations = {
  'session.create': async params => ({
    session_id: 'oracle-session',
    page_id: 'oracle-page-1',
    profile: params.profile ?? { mode: 'ephemeral' },
    backend: { kind: 'playwright', variant: spec.backend.variant }
  }),
  'page.navigate': async params => {
    const response = await page.goto(params.url, { waitUntil: 'commit' });
    return { accepted: true, url: response?.url() ?? page.url(), provider: 'oracle' };
  },
  'page.await': async params => {
    const conditions = params.conditions ?? [];
    if (!conditions.length) throw new OracleError('invalid_request', 'await requires at least one condition');
    const deadline = Number(params.deadline_ms ?? 30000);
    for (const condition of conditions) await awaitCondition(condition, deadline);
    return { satisfied: true, conditions, event_cursor: sequence };
  },
  'page.observe': async params => {
    const projections = Array.isArray(params.projection) ? params.projection : [params.projection ?? 'state'];
    const cursor = Number(params.since_event ?? 0);
    const data = {};
    for (const projection of projections) {
      if (projection === 'state') data.state = { page_id: 'oracle-page-1', url: page.url(), title: await page.title(), generation };
      else if (projection === 'dom') { const html = await page.content(); data.dom = { html, sha256: createHash('sha256').update(html).digest('hex') }; }
      else if (projection === 'console') data.console = since(cursor, item => item.kind === 'console.message');
      else if (projection === 'network') data.network = since(cursor, item => item.kind.startsWith('network.'));
      else if (projection === 'screenshot') {
        const png = await page.screenshot({ type: 'png' });
        const file = `screenshot-${String(sequence).padStart(6, '0')}.png`;
        await fs.writeFile(path.join(outputDir, file), png);
        data.screenshot = { media_type: 'image/png', size_bytes: png.length, sha256: createHash('sha256').update(png).digest('hex'), path: file };
      }
      else if (projection === 'targets') data.targets = (await page.evaluate(TARGET_SCRIPT)).map(item => ({ ...item, generation }));
      else if (projection === 'dialogs') data.dialogs = [...dialogs.values()].map(publicRecord);
      else if (projection === 'permissions') data.permissions = []; // structurally absent: no request event in Playwright
      else if (projection === 'downloads') data.downloads = [...downloads.values()].map(publicRecord);
      else if (projection === 'raw-events') data['raw-events'] = since(cursor, () => true);
      else throw new OracleError('capability_unsupported', 'observation projection is not supported by the oracle', { projection });
    }
    return { page_id: 'oracle-page-1', generation, since_event: cursor, next_event: sequence, returned_projections: projections, provider: 'oracle', data };
  },
  'page.act': async params => {
    const intent = params.intent ?? {};
    const kind = intent.kind;
    let effects;
    if (kind === 'javascript') effects = [{ kind: 'javascript', value: await page.evaluate(intent.value) }];
    else if (kind === 'click') {
      const selector = selectorFor(params.target);
      await page.click(selector, { timeout: 15000 });
      effects = [{ kind: 'click', target_id: params.target.target_id }];
    }
    else if (kind === 'type') {
      const selector = selectorFor(params.target);
      await page.fill(selector, String(intent.value ?? ''), { timeout: 15000 });
      effects = [{ kind: 'type', target_id: params.target.target_id, value: await page.inputValue(selector) }];
    }
    else if (kind === 'dialog.resolve') {
      const record = dialogs.get(String(intent.decision_token));
      if (!record || record.status !== 'pending') throw new OracleError('precondition_failed', 'decision token is unknown or already resolved', { decision_token: intent.decision_token });
      const decision = String(intent.decision ?? record.default);
      if (!['accept', 'dismiss'].includes(decision)) throw new OracleError('invalid_request', 'unknown decision', { decision });
      if (decision === 'accept') await record.handle.accept(intent.value ?? ''); else await record.handle.dismiss();
      record.status = 'resolved';
      record.decision = decision;
      event('dialog.resolved', { token: record.token, decision });
      effects = [{ kind: 'dialog.decision', decision, token: record.token }];
    }
    else if (kind === 'permission.resolve') {
      throw new OracleError('capability_unsupported', 'Playwright exposes no permission request to decide on; permissions are granted per context in advance');
    }
    else if (kind === 'upload') {
      const selector = selectorFor(params.target);
      const file = String(intent.path ?? '');
      const bytes = await fs.readFile(file);
      await page.setInputFiles(selector, file);
      const chosen = await page.evaluate(sel => { const element = document.querySelector(sel); return element && element.files && element.files.length ? element.files[0].name : null; }, selector);
      effects = [{ kind: 'upload', path: file, file_name: chosen, sha256: createHash('sha256').update(bytes).digest('hex') }];
    }
    else if (kind === 'download.accept') {
      const record = downloads.get(String(intent.download_id ?? ''));
      if (!record) throw new OracleError('precondition_failed', 'unknown download', { download_id: intent.download_id });
      const until = Date.now() + 30000;
      while (record.status === 'pending' && Date.now() < until) await new Promise(resolveWait => setTimeout(resolveWait, 25));
      if (record.status !== 'completed') throw new OracleError('backend_failed', 'download did not complete', { download_id: record.token, status: record.status });
      const payload = await fs.readFile(record.destination);
      const file = path.join('downloads', record.handle.suggestedFilename());
      await fs.mkdir(path.join(outputDir, 'downloads'), { recursive: true });
      await fs.writeFile(path.join(outputDir, file), payload);
      const sha256 = createHash('sha256').update(payload).digest('hex');
      record.status = 'quarantined';
      record.artifact_ref = `sha256:${sha256}`;
      effects = [{ kind: 'download', download_id: record.token, status: 'quarantined', artifact_ref: record.artifact_ref, bytes: payload.length }];
    }
    else if (kind === 'test.crash') {
      throw new OracleError('capability_unsupported', 'Playwright exposes no web-process termination for WebKit');
    }
    else throw new OracleError('capability_unsupported', 'intent family is not supported by the oracle', { intent: kind });
    return { attempted: true, accepted: true, executed: true, provider: 'oracle', effects };
  }
};

let terminal = null;
const steps = [];
const outputs = {};
for (const declaration of spec.workflow) {
  const record = { step_id: declaration.step_id, method: declaration.method, status: 'skipped', result: null, error: null };
  if (!terminal) {
    try {
      const operation = operations[declaration.method];
      if (!operation) throw new OracleError('capability_unsupported', `unsupported oracle operation: ${declaration.method}`);
      const params = resolve(declaration.params ?? {}, outputs);
      const result = await operation(params);
      expect(result, declaration.expect);
      record.status = 'passed';
      record.result = result;
      outputs[declaration.step_id] = result;
    } catch (error) {
      const failure = asOracleError(error);
      terminal = { code: failure.code, message: failure.message, data: failure.data };
      record.status = ERROR_STATUS[failure.code] ?? 'failed';
      record.error = terminal;
    }
  }
  steps.push(record);
}

await fs.writeFile(path.join(outputDir, 'raw-events.json'), `${JSON.stringify(events, null, 2)}\n`);
await fs.writeFile(path.join(outputDir, 'result.json'), `${JSON.stringify({
  schema_version: 'browser-workbench.result/v1',
  run_id: spec.run_id,
  status: terminal ? (ERROR_STATUS[terminal.code] ?? 'failed') : 'passed',
  backend: spec.backend,
  steps,
  terminal_reason: terminal ?? { code: 'completed' },
  retry_count: 0,
  oracle: { playwright: (await import('@playwright/test/package.json', { with: { type: 'json' } })).default.version, engine: browser.version() }
}, null, 2)}\n`);

// Any dialog still open would keep the browser from closing cleanly.
for (const record of dialogs.values()) if (record.status === 'pending') await record.handle.dismiss().catch(() => {});
await browser.close();
process.exit(terminal ? 1 : 0);
