export const MAX_FILE_BYTES = 16 * 1024 * 1024;
export const VALID_DPI = [72, 144, 216];

export function fileProblem(file) {
  if (!file) return 'Choose a PDF file.';
  if (!/\.pdf$/i.test(file.name || '')) return 'Please choose a file with a .pdf extension.';
  if (!Number.isFinite(file.size) || file.size <= 0) return 'This file is empty or cannot be read.';
  if (file.size > MAX_FILE_BYTES) return 'This PDF exceeds the 16 MiB per-file limit.';
  return '';
}

export function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function sideNumbers(sheet) {
  if (!Number.isInteger(sheet) || sheet < 1) return null;
  return { front: sheet * 2 - 1, back: sheet * 2 };
}

export function actionDescription(row) {
  if (row.action === 'keep') return `Keep old sheet ${row.oldSheet} in place`;
  if (row.action === 'move') return `Move old sheet ${row.oldSheet} here`;
  return row.forced ? `Forced reprint · patch sheet ${row.patchSheet}` : `Print patch sheet ${row.patchSheet}`;
}

export function validResult(result) {
  return Boolean(result && result.old && result.new && result.summary &&
    VALID_DPI.includes(result.dpi) && Array.isArray(result.assembly) && result.assembly.length > 0 &&
    result.assembly.every((row, index) => row.newSheet === index + 1 &&
      ['keep', 'move', 'reprint'].includes(row.action) &&
      (row.oldSheet === null || (Number.isInteger(row.oldSheet) && row.oldSheet > 0))) &&
    Array.isArray(result.retire));
}
