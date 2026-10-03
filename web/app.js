import { fileProblem, formatBytes, sideNumbers, actionDescription, validResult, MAX_FILE_BYTES } from './model.js';

const $ = id => document.getElementById(id);
const state = {
  version: 0,
  files: { old: null, new: null },
  fileEpoch: { old: 0, new: 0 },
  loading: { old: false, new: false },
  demoLoading: false,
  busy: false,
  activeJob: null,
  result: null,
  resultJob: null,
  stale: false,
  selected: 1,
  force: new Set(),
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const dpiValue = () => Number(document.querySelector('input[name="dpi"]:checked').value);

function status(message, tone = '') {
  $('status-text').textContent = message;
  $('status-region').className = `status-region ${tone}`;
  $('status-icon').textContent = tone === 'busy' ? '◌' : tone === 'success' ? '✓' : '○';
}
function showError(message = '') {
  $('error-region').textContent = message;
  $('error-region').hidden = !message;
}
function updateControls() {
  const reading = state.loading.old || state.loading.new || state.demoLoading;
  $('analyze-button').disabled = state.busy || reading || !state.files.old || !state.files.new;
  $('analyze-button').firstChild.textContent = state.busy ? 'Comparing sheets ' : state.result && state.stale ? 'Rebuild sheet plan ' : 'Build sheet plan ';
  $('cancel-button').hidden = !state.busy;
  $('demo-button').disabled = state.demoLoading;
  $('demo-button').lastChild.textContent = state.demoLoading ? ' Loading sample…' : ' Try a sample revision';
  updateExport();
}
function updateExport() {
  const ready = state.result && !state.stale && !state.busy && $('review-confirmation').checked;
  const link = $('export-link');
  link.setAttribute('aria-disabled', String(!ready));
  link.tabIndex = ready ? 0 : -1;
  if (ready) {
    link.href = `api/jobs/${encodeURIComponent(state.resultJob)}/packet.zip`;
    link.setAttribute('download', 'sheet-patch-packet.zip');
  } else {
    link.removeAttribute('href');
    link.removeAttribute('download');
  }
  $('review-confirmation').disabled = !state.result || state.stale || state.busy;
  $('export-hint').textContent = state.stale ? 'Rebuild the plan to enable export' : state.busy ? 'Comparison in progress' : ready ? 'Patch PDF + assembly instructions' : 'Review the plan to enable export';
}
async function cancelJob(id) {
  if (!id) return;
  try { await fetch(`api/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch { /* Local invalidation remains effective if cancellation cannot reach the server. */ }
}
function invalidate(message, { clear = false, resetForce = false } = {}) {
  state.version += 1;
  state.demoLoading = false;
  const priorJob = state.activeJob;
  state.activeJob = null;
  state.busy = false;
  if (priorJob) void cancelJob(priorJob);
  state.stale = Boolean(state.result);
  $('review-confirmation').checked = false;
  if (resetForce) state.force.clear();
  if (clear) {
    state.result = null;
    state.resultJob = null;
    state.stale = false;
    $('results-section').hidden = true;
    clearPreviews();
  }
  $('stale-notice').hidden = !state.stale;
  $('result-state').textContent = state.stale ? 'Rebuild required' : 'Ready for review';
  $('result-state').classList.toggle('stale', state.stale);
  showError();
  if (message) status(message);
  updateControls();
  return state.version;
}
function clearPreviews() {
  for (const kind of ['old', 'new']) {
    for (const side of ['front', 'back']) {
      $(`${kind}-${side}-image`).removeAttribute('src');
      $(`${kind}-${side}-image`).alt = '';
      $(`${kind}-${side}-link`).removeAttribute('href');
    }
  }
}
function displayFile(kind, file, detail) {
  $(`${kind}-file-name`).textContent = file ? file.name : `Choose the ${kind} PDF`;
  $(`${kind}-file-detail`).textContent = detail || (file ? `${formatBytes(file.size)} · ready to compare` : 'or drop it here · PDF, up to 16 MiB');
  $(`${kind}-drop`).classList.toggle('has-file', Boolean(file));
}
function fieldError(kind, message = '') {
  $(`${kind}-file-error`).textContent = message;
  $(`${kind}-file-error`).hidden = !message;
  $(`${kind}-file`).setAttribute('aria-invalid', String(Boolean(message)));
}
function base64FromBuffer(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return btoa(binary);
}
async function chooseFile(kind, file) {
  const epoch = ++state.fileEpoch[kind];
  invalidate('Inputs changed. Build a fresh sheet plan when both PDFs are ready.', { clear: true, resetForce: true });
  state.files[kind] = null;
  state.loading[kind] = false;
  fieldError(kind);
  if (!file) {
    displayFile(kind, null);
    updateControls();
    return;
  }
  const problem = fileProblem(file);
  if (problem) {
    fieldError(kind, problem);
    displayFile(kind, null);
    updateControls();
    return;
  }
  state.loading[kind] = true;
  displayFile(kind, file, `${formatBytes(file.size)} · reading locally…`);
  updateControls();
  try {
    const buffer = await file.arrayBuffer();
    if (state.fileEpoch[kind] !== epoch) return;
    state.files[kind] = { name: file.name, data: base64FromBuffer(buffer), size: file.size };
    displayFile(kind, file);
  } catch {
    if (state.fileEpoch[kind] !== epoch) return;
    displayFile(kind, null);
    fieldError(kind, 'This file could not be read. Please choose it again.');
  } finally {
    if (state.fileEpoch[kind] === epoch) {
      state.loading[kind] = false;
      updateControls();
      if (!state.loading.old && !state.loading.new && state.files.old && state.files.new) status('Both PDFs are ready. Build your sheet plan to compare whole front/back pairs.');
    }
  }
}
async function readJSON(response) {
  let data;
  try { data = await response.json(); } catch { throw new Error('The local service returned an unreadable response. Check that Sheet Patch is still running.'); }
  if (!response.ok) throw new Error(typeof data.error === 'string' ? data.error : `The local service returned error ${response.status}.`);
  return data;
}
async function loadDemo() {
  state.fileEpoch.old += 1;
  state.fileEpoch.new += 1;
  state.loading.old = state.loading.new = false;
  const version = invalidate('Preparing a sample revision…', { clear: true, resetForce: true });
  state.demoLoading = true;
  state.files.old = state.files.new = null;
  for (const kind of ['old', 'new']) {
    $(`${kind}-file`).value = '';
    fieldError(kind);
    displayFile(kind, null);
  }
  updateControls();
  try {
    const demo = await readJSON(await fetch('api/demo', { cache: 'no-store' }));
    if (state.version !== version) return;
    for (const kind of ['old', 'new']) {
      const item = demo[kind];
      if (!item || typeof item.name !== 'string' || typeof item.data !== 'string' || !item.data.length || item.data.length > Math.ceil(MAX_FILE_BYTES / 3) * 4) throw new Error('The sample files were not valid. Please try again.');
    }
    for (const kind of ['old', 'new']) {
      const item = demo[kind];
      const size = Math.floor(item.data.length * 3 / 4) - (item.data.endsWith('==') ? 2 : item.data.endsWith('=') ? 1 : 0);
      state.files[kind] = { ...item, size };
      displayFile(kind, state.files[kind], `${formatBytes(size)} · built-in sample PDF`);
    }
    status('Sample loaded: 3 old sheets → 4 new sheets, including a changed back side. Build the plan to see what can be reused.');
  } catch (error) {
    if (state.version !== version) return;
    showError(error.message || 'The sample could not be loaded.');
    status('The sample was not loaded. Choose two PDFs or try again.');
  } finally {
    if (state.version === version) { state.demoLoading = false; updateControls(); }
  }
}
async function analyze() {
  if ($('analyze-button').disabled) return;
  const version = invalidate('Starting the local comparison…');
  const body = {
    old: { name: state.files.old.name, data: state.files.old.data },
    new: { name: state.files.new.name, data: state.files.new.data },
    dpi: dpiValue(),
    force: [...state.force].sort((a, b) => a - b),
  };
  state.busy = true;
  status('Comparing both sides of each sheet… This can take up to 180 seconds.', 'busy');
  updateControls();
  try {
    const created = await readJSON(await fetch('api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));
    if (!created || typeof created.id !== 'string' || !created.id) throw new Error('The local service did not return a comparison ID.');
    if (state.version !== version) { void cancelJob(created.id); return; }
    state.activeJob = created.id;
    while (state.version === version) {
      const job = await readJSON(await fetch(`api/jobs/${encodeURIComponent(created.id)}`, { cache: 'no-store' }));
      if (state.version !== version) return;
      if (job.status === 'done') {
        if (!validResult(job.result)) throw new Error('The local service returned an incomplete sheet plan. Try the comparison again.');
        state.activeJob = null;
        state.busy = false;
        state.result = job.result;
        state.resultJob = created.id;
        state.stale = false;
        state.selected = Math.min(state.selected, job.result.assembly.length);
        state.force = new Set(job.result.assembly.filter(row => row.forced).map(row => row.newSheet));
        renderResult();
        status(`Plan ready: ${job.result.summary.reused} reuse candidates, ${job.result.summary.reprint} whole sheets to print. Review both sides before exporting.`, 'success');
        updateControls();
        $('results-title').focus({ preventScroll: true });
        $('results-section').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
        return;
      }
      if (job.status === 'error') throw new Error(typeof job.error === 'string' ? job.error : 'The PDF comparison failed. Check that both PDFs have an even number of sides and are within the limits.');
      if (job.status === 'cancelled') {
        state.activeJob = null;
        state.busy = false;
        status('Comparison cancelled. Your files are still ready for another run.');
        updateControls();
        return;
      }
      if (!['queued', 'running'].includes(job.status)) throw new Error('The local service returned an unknown job status.');
      status(typeof job.progress === 'string' && job.progress ? job.progress : 'Comparing both sides of each sheet…', 'busy');
      await sleep(650);
    }
  } catch (error) {
    if (state.version !== version) return;
    const active = state.activeJob;
    state.activeJob = null;
    state.busy = false;
    if (active) void cancelJob(active);
    showError(error.message || 'Could not connect to the local service. Check that Sheet Patch is still running.');
    status('No new plan was completed. Correct the problem and try again.');
    updateControls();
  }
}
function renderResult() {
  const result = state.result;
  $('results-section').hidden = false;
  $('stale-notice').hidden = true;
  $('result-state').textContent = 'Ready for review';
  $('result-state').classList.remove('stale');
  $('reuse-count').textContent = result.summary.reused;
  $('reuse-detail').textContent = `${result.summary.keep} keep + ${result.summary.move} move · of ${result.new.sheetCount} new sheets`;
  $('reprint-count').textContent = result.summary.reprint;
  $('reprint-detail').textContent = `${result.summary.reprint * 2} PDF sides in the patch`;
  $('retire-count').textContent = result.summary.retire;
  $('sheet-count-label').textContent = `${result.new.sheetCount} SHEETS`;
  $('raster-warning').textContent = `Raster equality is checked at ${result.dpi} DPI. Small details, color, overprint, and other print properties may differ. Review both sides and the original PDFs before printing or assembling.`;
  const warnings = $('server-warnings');
  warnings.replaceChildren();
  for (const warning of result.warnings || []) { const li = document.createElement('li'); li.textContent = String(warning); warnings.append(li); }
  warnings.hidden = !warnings.childElementCount;
  const retire = $('retire-list');
  retire.replaceChildren();
  const strong = document.createElement('strong');
  strong.textContent = result.retire.length ? 'Set aside from the old edition: ' : 'Nothing to retire. ';
  retire.append(strong, document.createTextNode(result.retire.length ? result.retire.map(n => `sheet ${n}`).join(', ') + '. Keep these separate from your new stack.' : 'All old sheets have a place in the new assembly.'));
  for (const kind of ['old', 'new']) {
    const file = result[kind];
    const geometry = Array.isArray(file.geometryPoints) && file.geometryPoints.length === 4 ? ` · ${file.geometryPoints[2]} × ${file.geometryPoints[3]} pt` : '';
    $(`${kind}-file-fingerprint`).textContent = `${file.name} · ${file.sideCount} sides / ${file.sheetCount} sheets${geometry}\nSHA-256: ${file.sha256}`;
  }
  const verification = result.verification || {};
  const details = [`${result.dpi} DPI · ordered front/back pairs · schema ${result.schemaVersion ?? '1'}`];
  if (Number.isFinite(verification.elapsedSeconds)) details.push(`${verification.elapsedSeconds.toFixed(2)} seconds`);
  if (Number.isFinite(verification.inputPixels)) details.push(`${verification.inputPixels.toLocaleString()} input pixels`);
  if (verification.replacementRerenderPerformed === false) details.push('No replacement PDF needed; no replacement rerender performed');
  else if (typeof verification.replacementRerenderMatched === 'boolean') details.push(`Replacement re-render check: ${verification.replacementRerenderMatched ? 'matched' : 'not matched'}`);
  $('comparison-settings').textContent = details.join(' · ');
  renderRows();
  renderPreview();
}
function renderRows() {
  const tbody = $('assembly-rows');
  tbody.replaceChildren();
  for (const row of state.result.assembly) {
    const tr = document.createElement('tr');
    tr.classList.toggle('selected', row.newSheet === state.selected);
    const numberCell = document.createElement('td');
    const select = document.createElement('button');
    select.type = 'button';
    select.className = 'sheet-select';
    select.textContent = String(row.newSheet).padStart(2, '0');
    select.setAttribute('aria-label', `Inspect new sheet ${row.newSheet}`);
    select.setAttribute('aria-pressed', String(row.newSheet === state.selected));
    select.addEventListener('click', () => selectSheet(row.newSheet));
    numberCell.append(select);
    const actionCell = document.createElement('td');
    const action = document.createElement('span');
    action.className = `action-chip ${row.action}`;
    action.textContent = row.action;
    const source = document.createElement('span');
    source.className = 'source-line';
    source.textContent = actionDescription(row);
    actionCell.append(action, source);
    const forceCell = document.createElement('td');
    forceCell.className = 'force-cell';
    const label = document.createElement('label');
    label.className = 'force-toggle';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = state.force.has(row.newSheet);
    checkbox.disabled = row.action === 'reprint' && !row.forced;
    if (checkbox.disabled) label.title = 'This sheet already requires reprinting.';
    checkbox.setAttribute('aria-label', `Force reprint of new sheet ${row.newSheet}`);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.force.add(row.newSheet); else state.force.delete(row.newSheet);
      invalidate('Reprint preference changed. Rebuild the plan to apply it.');
    });
    label.append(checkbox);
    forceCell.append(label);
    tr.append(numberCell, actionCell, forceCell);
    tbody.append(tr);
  }
}
function selectSheet(number) {
  if (!state.result || number < 1 || number > state.result.assembly.length) return;
  state.selected = number;
  for (const row of $('assembly-rows').rows) {
    const button = row.querySelector('.sheet-select');
    const selected = Number(button.textContent) === number;
    row.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  }
  renderPreview();
}
function setPreview(kind, sheet) {
  const sides = sideNumbers(sheet);
  for (const side of ['front', 'back']) {
    const img = $(`${kind}-${side}-image`);
    const link = $(`${kind}-${side}-link`);
    if (!sides) { img.removeAttribute('src'); img.alt = ''; link.removeAttribute('href'); continue; }
    const url = `api/jobs/${encodeURIComponent(state.resultJob)}/preview/${kind}/${sides[side]}.png`;
    img.alt = `${kind === 'new' ? 'New' : 'Old'} sheet ${sheet}, ${side} side (PDF side ${sides[side]})`;
    img.src = url;
    link.href = url;
    link.setAttribute('aria-label', `Open ${img.alt.toLowerCase()} thumbnail preview`);
    $(`${kind}-${side}-caption`).textContent = `PDF SIDE ${String(sides[side]).padStart(2, '0')}`;
  }
}
function renderPreview() {
  const row = state.result.assembly[state.selected - 1];
  $('selected-sheet-number').textContent = row.newSheet;
  $('inspection-note').textContent = `${actionDescription(row)}. Keep the front and back together.`;
  $('new-preview-label').textContent = `Sheet ${row.newSheet}`;
  $('old-preview-label').textContent = row.oldSheet ? `Sheet ${row.oldSheet}` : 'No assigned source';
  setPreview('new', row.newSheet);
  setPreview('old', row.oldSheet);
  $('old-preview-pair').hidden = !row.oldSheet;
  $('no-old-preview').hidden = Boolean(row.oldSheet);
  $('previous-sheet').disabled = state.selected <= 1;
  $('next-sheet').disabled = state.selected >= state.result.assembly.length;
}

for (const kind of ['old', 'new']) {
  $(`${kind}-file`).addEventListener('change', event => void chooseFile(kind, event.target.files[0]));
  const drop = $(`${kind}-drop`);
  let dragDepth = 0;
  drop.addEventListener('dragenter', event => { event.preventDefault(); dragDepth += 1; drop.classList.add('drag-over'); });
  drop.addEventListener('dragover', event => { event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'; });
  drop.addEventListener('dragleave', event => { event.preventDefault(); dragDepth -= 1; if (dragDepth <= 0) drop.classList.remove('drag-over'); });
  drop.addEventListener('drop', event => {
    event.preventDefault(); dragDepth = 0; drop.classList.remove('drag-over');
    const files = event.dataTransfer?.files;
    if (!files?.length) return;
    $(`${kind}-file`).value = '';
    if (files.length !== 1) {
      state.fileEpoch[kind] += 1;
      state.files[kind] = null;
      state.loading[kind] = false;
      invalidate('Choose one PDF for each edition.', { clear: true, resetForce: true });
      displayFile(kind, null);
      fieldError(kind, 'Drop exactly one PDF into each edition.');
      return;
    }
    void chooseFile(kind, files[0]);
  });
}
for (const input of document.querySelectorAll('input[name="dpi"]')) input.addEventListener('change', () => invalidate('Comparison detail changed. Rebuild the plan at the new DPI.'));
$('demo-button').addEventListener('click', () => void loadDemo());
$('analyze-button').addEventListener('click', () => void analyze());
$('cancel-button').addEventListener('click', () => invalidate('Comparison cancelled. Your files are still ready for another run.'));
$('previous-sheet').addEventListener('click', () => selectSheet(state.selected - 1));
$('next-sheet').addEventListener('click', () => selectSheet(state.selected + 1));
$('review-confirmation').addEventListener('change', updateExport);
$('export-link').addEventListener('click', event => { if ($('export-link').getAttribute('aria-disabled') === 'true') event.preventDefault(); });
for (const image of document.querySelectorAll('.preview-pair img')) image.addEventListener('error', () => { image.alt = 'Preview unavailable. Inspect this side in the original PDF.'; });
updateControls();
