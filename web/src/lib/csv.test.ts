import { afterEach, describe, expect, it, vi } from 'vitest';
import { downloadCsv, toCsv } from './csv';

describe('toCsv', () => {
  it('joins rows with CRLF and ends with one', () => {
    expect(toCsv(['a', 'b'], [[1, 'x']])).toBe('a,b\r\n1,x\r\n');
  });

  it('quotes cells with commas, quotes or line breaks, and doubles the quotes', () => {
    expect(toCsv(['n'], [['a,b'], ['say "hi"'], ['two\nlines']])).toBe('n\r\n"a,b"\r\n"say ""hi"""\r\n"two\nlines"\r\n');
  });

  it('writes numbers raw so a spreadsheet can add them up, and empty for missing values', () => {
    expect(toCsv(['x', 'y', 'z'], [[1234.5, null, undefined]])).toBe('x,y,z\r\n1234.5,,\r\n');
    expect(toCsv(['x'], [[-12.5], [Number.NaN], [Number.POSITIVE_INFINITY]])).toBe('x\r\n-12.5\r\n\r\n\r\n');
  });

  it('keeps a text cell from running as a formula in a spreadsheet', () => {
    for (const bad of ['=SUM(A1)', '+1', '-1', '@cmd', '\tTAB', '\rCR']) {
      const csv = toCsv(['x'], [[bad]]);
      expect(csv.split('\r\n')[1]).toMatch(/^"?'/);
    }
    // a negative number is a number, not a formula
    expect(toCsv(['x'], [[-5]])).toBe('x\r\n-5\r\n');
  });

  it('writes the header cells with the same care', () => {
    expect(toCsv(['=bad', 'ok,1'], [])).toBe("'=bad,\"ok,1\"\r\n");
  });
});

describe('downloadCsv', () => {
  afterEach(() => vi.restoreAllMocks());

  it('saves a UTF-8 file with a byte order mark and the given name', async () => {
    let blob: Blob | undefined;
    URL.createObjectURL = vi.fn((b: Blob) => {
      blob = b;
      return 'blob:test';
    });
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadCsv('revenue', 'a,b\r\n1,2\r\n');

    expect(click).toHaveBeenCalledOnce();
    expect(blob?.type).toBe('text/csv;charset=utf-8');
    const bytes = new Uint8Array(await blob!.arrayBuffer());
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    expect(document.querySelector('a[download]')).toBeNull();
  });

  it('adds .csv once', () => {
    URL.createObjectURL = vi.fn(() => 'blob:test');
    URL.revokeObjectURL = vi.fn();
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    downloadCsv('a', '');
    downloadCsv('b.csv', '');
    expect(names).toEqual(['a.csv', 'b.csv']);
  });
});
