/* Run with: node web/ui-tests/browser.test.cjs
   Uses only a loopback mock service and the installed Chromium/Playwright. */
const { chromium } = require('playwright');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const artifacts = process.env.UI_ARTIFACT_DIR || '/tmp/sheet-patch-ui-artifacts';
const prefix = '/test-token/';
const jobs = new Map();
const cancelled = [];
let jobCounter = 0;
let createDelay = 0;
let pollDelay = 0;
let demoDelay = 0;
let jobError = '';
let jobBodies = [];
const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jEQsAAAAASUVORK5CYII=', 'base64');
const demo = { old: { name: 'old-edition.pdf', data: Buffer.from('%PDF-old').toString('base64') }, new: { name: 'new-edition.pdf', data: Buffer.from('%PDF-new').toString('base64') } };
const info = (name, sheetCount) => ({ name, sha256: 'a'.repeat(64), sideCount: sheetCount * 2, sheetCount });
function result(body) {
  const forced = new Set(body.force);
  let patch = 0;
  const assembly = [
    { newSheet: 1, action: 'keep', oldSheet: 1 },
    { newSheet: 2, action: 'move', oldSheet: 3 },
    { newSheet: 3, action: 'reprint', oldSheet: null },
    { newSheet: 4, action: 'reprint', oldSheet: null },
  ].map(row => {
    if (forced.has(row.newSheet)) { row.action = 'reprint'; row.oldSheet = null; }
    return { ...row, patchSheet: row.action === 'reprint' ? ++patch : null, forced: forced.has(row.newSheet), frontHash: 'front', backHash: 'back' };
  });
  const keep = assembly.filter(r => r.action === 'keep').length;
  const move = assembly.filter(r => r.action === 'move').length;
  const retired = [1, 2, 3].filter(id => !assembly.some(row => row.oldSheet === id));
  return { schemaVersion: 1, dpi: body.dpi, old: info(body.old.name, 3), new: info(body.new.name, 4), summary: { keep, move, reprint: patch, retire: retired.length, reused: keep + move }, assembly, retire: retired, warnings: [], verification: { elapsedSeconds: .15, inputPixels: 400000, replacementRerenderMatched: true } };
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function json(res, data, status = 200) { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); }
const server = http.createServer(async (req, res) => {
  try {
    assert.ok(req.url.startsWith(prefix));
    const name = req.url.slice(prefix.length).split('?')[0];
    if (name === 'api/demo') { await delay(demoDelay); return json(res, demo); }
    if (name === 'api/jobs' && req.method === 'POST') {
      let raw = ''; for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw); jobBodies.push(body);
      const id = `job-${++jobCounter}`; jobs.set(id, { body, error: jobError });
      await delay(createDelay);
      return json(res, { id });
    }
    const jobRoute = name.match(/^api\/jobs\/([^/]+)(.*)$/);
    if (jobRoute) {
      const [, id, suffix] = jobRoute;
      if (suffix === '/cancel') { cancelled.push(id); return json(res, { status: 'cancelled' }); }
      if (suffix.startsWith('/preview/')) { res.writeHead(200, { 'Content-Type': 'image/png' }); return res.end(pixel); }
      if (suffix === '/packet.zip') { res.writeHead(200, { 'Content-Type': 'application/zip', 'Content-Disposition': 'attachment; filename="packet.zip"' }); return res.end('mock zip'); }
      await delay(pollDelay);
      const job = jobs.get(id);
      return json(res, job.error ? { id, status: 'error', error: job.error } : { id, status: 'done', progress: 'Ready', result: result(job.body) });
    }
    const filename = path.join(root, name || 'index.html');
    const ext = path.extname(filename);
    res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml' })[ext] || 'text/plain' });
    res.end(await fs.readFile(filename));
  } catch (error) { json(res, { error: error.message }, 500); }
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}${prefix}`;
  await fs.mkdir(artifacts, { recursive: true });
  const browser = await chromium.launch({ ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}), chromiumSandbox: true, headless: true });
  const page = await browser.newPage({ viewport: { width: 1380, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const outsideRequests = [];
  page.on('request', request => { if (!request.url().startsWith(url) && !request.url().startsWith('data:')) outsideRequests.push(request.url()); });
  try {
    await page.goto(url);
    assert.equal(await page.locator('#analyze-button').isDisabled(), true);
    await page.screenshot({ path: path.join(artifacts, 'initial-desktop.png'), fullPage: true });
    await page.locator('#demo-button').click();
    await page.waitForFunction(() => !document.getElementById('analyze-button').disabled);
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => !document.getElementById('results-section').hidden);
    assert.equal(await page.locator('#reuse-count').textContent(), '2');
    assert.equal(await page.locator('#reprint-count').textContent(), '2');
    assert.equal(await page.locator('#retire-count').textContent(), '1');
    assert.equal(await page.locator('#assembly-rows tr').count(), 4);
    assert.match(await page.locator('#old-back-image').getAttribute('src'), /\/old\/2.png$/);
    assert.equal(await page.locator('#export-link').getAttribute('href'), null);
    await page.locator('#review-confirmation').check();
    assert.match(await page.locator('#export-link').getAttribute('href'), /packet.zip$/);
    await page.locator('[aria-label="Inspect new sheet 2"]').click();
    assert.match(await page.locator('#old-back-image').getAttribute('src'), /\/old\/6.png$/);
    await page.locator('#next-sheet').click();
    assert.equal(await page.locator('#no-old-preview').isVisible(), true);
    assert.match(await page.locator('#new-back-image').getAttribute('src'), /\/new\/6.png$/);
    await page.locator('[aria-label="Force reprint of new sheet 1"]').check();
    assert.equal(await page.locator('#stale-notice').isVisible(), true);
    assert.equal(await page.locator('#export-link').getAttribute('href'), null);
    assert.equal(await page.locator('#review-confirmation').isChecked(), false);
    assert.equal(jobCounter, 1, 'Force selection must not automatically run comparison');
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => document.getElementById('reuse-count').textContent === '1');
    assert.deepEqual(jobBodies.at(-1).force, [1]);
    assert.equal(await page.locator('[aria-label="Force reprint of new sheet 1"]').isChecked(), true);
    await page.locator('[aria-label="Force reprint of new sheet 1"]').uncheck();
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => document.getElementById('reuse-count').textContent === '2');
    await page.screenshot({ path: path.join(artifacts, 'plan-desktop.png'), fullPage: true });
    await page.locator('input[name="dpi"][value="216"]').check();
    assert.equal(await page.locator('#stale-notice').isVisible(), true);
    assert.equal(await page.locator('#export-link').getAttribute('href'), null);
    createDelay = 180;
    await page.locator('#analyze-button').click();
    await page.locator('#cancel-button').click();
    await delay(280);
    assert.ok(cancelled.includes('job-4'), 'Late-created cancelled job must be cancelled at backend');
    assert.match(await page.locator('#status-text').textContent(), /cancelled/);
    assert.equal(await page.locator('#stale-notice').isVisible(), true);
    createDelay = 0;
    pollDelay = 150;
    await page.locator('#analyze-button').click();
    await delay(30);
    await page.locator('input[name="dpi"][value="72"]').check();
    await delay(220);
    assert.equal(await page.locator('#stale-notice').isVisible(), true, 'Late stale result must not restore a ready plan');
    assert.match(await page.locator('#status-text').textContent(), /detail changed/);
    pollDelay = 0;
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => document.getElementById('stale-notice').hidden);
    assert.equal(jobBodies.at(-1).dpi, 72);
    assert.match(await page.locator('#raster-warning').textContent(), /72 DPI/);
    await page.locator('#old-file').setInputFiles({ name: '<img onerror=alert(1)>.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-safe') });
    await page.waitForFunction(() => !document.getElementById('analyze-button').disabled);
    assert.equal(await page.locator('#results-section').isVisible(), false);
    assert.equal(await page.locator('#old-file-name').textContent(), '<img onerror=alert(1)>.pdf');
    assert.equal(await page.locator('#old-file-name img').count(), 0, 'Filenames must be rendered as plain text');
    await page.locator('#old-file').setInputFiles({ name: 'not-a-pdf.txt', mimeType: 'text/plain', buffer: Buffer.from('not PDF') });
    assert.equal(await page.locator('#old-file-error').isVisible(), true);
    assert.equal(await page.locator('#analyze-button').isDisabled(), true);
    await page.locator('#old-file').setInputFiles({ name: 'large.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(16 * 1024 * 1024 + 1) });
    assert.match(await page.locator('#old-file-error').textContent(), /16 MiB/);
    demoDelay = 130;
    await page.locator('#demo-button').click();
    await page.locator('#old-file').setInputFiles({ name: 'replacement.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-latest') });
    await delay(230);
    assert.equal(await page.locator('#old-file-name').textContent(), 'replacement.pdf', 'Late demo must not overwrite a selected file');
    assert.equal(await page.locator('#analyze-button').isDisabled(), true, 'Missing new file must remain blocked');
    demoDelay = 0;
    await page.locator('#demo-button').click();
    await page.waitForFunction(() => !document.getElementById('analyze-button').disabled);
    jobError = 'Odd side count: each sheet needs a front and a back.';
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => !document.getElementById('error-region').hidden);
    assert.match(await page.locator('#error-region').textContent(), /Odd side count/);
    assert.equal(await page.locator('#analyze-button').isDisabled(), false);
    jobError = '';
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => !document.getElementById('results-section').hidden);
    for (const width of [320, 375, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `No horizontal overflow at ${width}px`);
    }
    await page.setViewportSize({ width: 375, height: 850 });
    await page.screenshot({ path: path.join(artifacts, 'plan-mobile.png'), fullPage: true });
    assert.deepEqual(errors, [], 'No browser JavaScript errors');
    assert.deepEqual(outsideRequests, [], 'No non-loopback resource requests');
    console.log('PASS: demo, assembly, paired previews, export review gate, force/unforce rerun, DPI invalidation, delayed create cancellation, stale poll rejection, local file replacement, safe filename rendering, input size/type errors, stale demo rejection, server error recovery, five responsive widths, and no external requests.');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; server.close(); });
