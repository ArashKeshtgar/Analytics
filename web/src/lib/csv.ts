export type Cell = string | number | null | undefined;

const NEEDS_QUOTES = /[",\r\n]/;
// A spreadsheet would run a text cell that starts with one of these as a formula.
const FORMULA_START = /^[=+\-@\t\r]/;

function cell(value: Cell): string {
  if (value == null) return '';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '';
  const text = FORMULA_START.test(value) ? `'${value}` : value;
  return NEEDS_QUOTES.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** RFC 4180: CRLF between rows, quotes doubled. Numbers are written raw so a spreadsheet can add them up. */
export function toCsv(headers: string[], rows: Cell[][]): string {
  return [headers, ...rows].map((row) => row.map(cell).join(',')).join('\r\n') + '\r\n';
}

/** Saves text as a file. The byte order mark lets Excel read UTF-8. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
