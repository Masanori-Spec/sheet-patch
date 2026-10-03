import test from 'node:test';
import assert from 'node:assert/strict';
import { fileProblem, formatBytes, sideNumbers, actionDescription, validResult, MAX_FILE_BYTES } from '../model.js';

test('PDF input size and extension validation', () => {
  assert.equal(fileProblem({ name: 'ART.PDF', size: MAX_FILE_BYTES }), '');
  assert.match(fileProblem({ name: 'x.pdf', size: MAX_FILE_BYTES + 1 }), /16 MiB/);
  assert.match(fileProblem({ name: 'x.pdf', size: 0 }), /empty/);
  assert.match(fileProblem({ name: 'x.html', size: 123 }), /extension/);
  assert.match(fileProblem(null), /Choose/);
});
test('ordered front and back are inseparable sheet pairs', () => {
  assert.deepEqual(sideNumbers(1), { front: 1, back: 2 });
  assert.deepEqual(sideNumbers(40), { front: 79, back: 80 });
  assert.equal(sideNumbers(null), null);
  assert.equal(sideNumbers(-1), null);
  assert.equal(sideNumbers(1.5), null);
});
test('format filenames and action description without markup', () => {
  assert.equal(formatBytes(512), '1 KiB');
  assert.equal(formatBytes(1048576), '1.0 MiB');
  assert.equal(actionDescription({ action: 'move', oldSheet: 3 }), 'Move old sheet 3 here');
  assert.equal(actionDescription({ action: 'reprint', forced: true, patchSheet: 2 }), 'Forced reprint · patch sheet 2');
});
test('only complete ordered result skeleton accepted', () => {
  const result = { old: {}, new: {}, summary: {}, dpi: 144, assembly: [{ newSheet: 1, action: 'keep', oldSheet: 1 }], retire: [] };
  assert.equal(validResult(result), true);
  assert.equal(validResult({ ...result, dpi: 12 }), false);
  assert.equal(validResult({ ...result, assembly: [] }), false);
  assert.equal(validResult({ ...result, assembly: [{ newSheet: 2, action: 'keep', oldSheet: 1 }] }), false);
  assert.equal(validResult(null), false);
});
