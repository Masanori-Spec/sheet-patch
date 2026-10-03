/* Real local-service UI smoke test. Run after installing Python requirements,
   Poppler, Playwright, and its Chromium browser. No external resources are used. */
const { chromium } = require('playwright');
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const artifacts = process.env.UI_ARTIFACT_DIR || '/tmp/sheet-patch-ui-artifacts';
const python = process.env.PYTHON || 'python';
const service = spawn(python, ['-m', 'sheet_patch', 'serve', '--no-open'], { cwd: root, env: { ...process.env, PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
let browser;
let stderr = '';
service.stderr.on('data', chunk => { stderr += chunk; });
const localURL = new Promise((resolve, reject) => {
  let output = '';
  const timeout = setTimeout(() => reject(new Error('Local service startup timed out')), 10000);
  service.stdout.on('data', chunk => {
    output += chunk;
    const match = output.match(/http:\/\/127\.0\.0\.1:\d+\/[A-Za-z0-9_-]+\//);
    if (match) { clearTimeout(timeout); resolve(match[0]); }
  });
  service.once('error', error => { clearTimeout(timeout); reject(error); });
  service.once('exit', code => { clearTimeout(timeout); reject(new Error(`Local service exited before startup (code ${code}): ${stderr}`)); });
});
(async () => {
  try {
    const url = await localURL;
    await fs.mkdir(artifacts, { recursive: true });
    browser = await chromium.launch({ ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}), chromiumSandbox: true, headless: true });
    const page = await browser.newPage({ viewport: { width: 1380, height: 1000 }, reducedMotion: 'reduce' });
    page.setDefaultTimeout(190000);
    const browserErrors = [];
    const outsideRequests = [];
    page.on('pageerror', error => browserErrors.push(error.message));
    page.on('request', request => { if (!request.url().startsWith(url) && !request.url().startsWith('data:')) outsideRequests.push(request.url()); });
    await page.goto(url);
    await page.screenshot({ path: path.join(artifacts, 'real-initial-desktop.png'), fullPage: true });
    await page.locator('#demo-button').click();
    await page.waitForFunction(() => !document.getElementById('analyze-button').disabled);
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => !document.getElementById('results-section').hidden || !document.getElementById('error-region').hidden, undefined, { timeout: 190000 });
    assert.equal(await page.locator('#error-region').isVisible(), false, await page.locator('#error-region').textContent());
    assert.equal(await page.locator('#reuse-count').textContent(), '2');
    assert.equal(await page.locator('#reprint-count').textContent(), '2');
    assert.equal(await page.locator('#retire-count').textContent(), '1');
    assert.equal(await page.locator('#assembly-rows tr').count(), 4);
    await page.waitForFunction(() => [...document.querySelectorAll('.preview-pair img')].every(image => image.complete && image.naturalWidth > 1));
    await page.locator('[aria-label="Inspect new sheet 2"]').click();
    assert.match(await page.locator('#old-back-image').getAttribute('src'), /\/old\/6.png$/);
    await page.locator('#next-sheet').click();
    assert.equal(await page.locator('#no-old-preview').isVisible(), true);
    await page.locator('[aria-label="Inspect new sheet 1"]').click();
    await page.waitForFunction(() => [...document.querySelectorAll('.preview-pair img')].every(image => image.complete && image.naturalWidth > 1));
    await page.screenshot({ path: path.join(artifacts, 'real-plan-desktop.png'), fullPage: true });
    await page.locator('#review-confirmation').check();
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#export-link').click();
    const download = await downloadPromise;
    const downloadedPath = await download.path();
    assert.equal(await download.failure(), null);
    const packetInfo = JSON.parse(execFileSync(python, ['-c', "import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps({'files':z.namelist(),'plan':json.loads(z.read('plan.json'))}))", downloadedPath], { encoding: 'utf8' }));
    assert.deepEqual([...packetInfo.files].sort(), ['assembly.html', 'plan.json', 'replacement.pdf']);
    assert.equal(packetInfo.plan.verification.replacementRerenderMatched, true);
    assert.deepEqual(packetInfo.plan.summary, { keep: 1, move: 1, reprint: 2, retire: 1, reused: 2 });
    await page.locator('[aria-label="Force reprint of new sheet 1"]').check();
    assert.equal(await page.locator('#export-link').getAttribute('href'), null);
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => document.getElementById('reuse-count').textContent === '1' || !document.getElementById('error-region').hidden);
    assert.equal(await page.locator('#error-region').isVisible(), false, await page.locator('#error-region').textContent());
    assert.equal(await page.locator('#reprint-count').textContent(), '3');
    await page.locator('[aria-label="Force reprint of new sheet 1"]').uncheck();
    await page.locator('#analyze-button').click();
    await page.waitForFunction(() => document.getElementById('reuse-count').textContent === '2' || !document.getElementById('error-region').hidden);
    assert.equal(await page.locator('#error-region').isVisible(), false, await page.locator('#error-region').textContent());
    for (const width of [320, 375, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `No horizontal overflow at ${width}px`);
    }
    await page.setViewportSize({ width: 375, height: 850 });
    await page.screenshot({ path: path.join(artifacts, 'real-plan-mobile.png'), fullPage: true });
    assert.deepEqual(browserErrors, []);
    assert.deepEqual(outsideRequests, []);
    console.log('PASS: real local service demo, paired sheet plan, rendered previews, verified replacement ZIP download, force/unforce rerun, five responsive widths, and no external requests.');
  } finally {
    if (browser) await browser.close();
    if (service.exitCode === null) {
      service.kill('SIGINT');
      await Promise.race([new Promise(resolve => service.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 5000))]);
      if (service.exitCode === null) service.kill('SIGTERM');
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
