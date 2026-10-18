import { type Cell, downloadCsv, toCsv } from '../lib/csv';

export interface Column {
  key: string;
  label: string;
  /** Right-aligned, formatted with `format`. */
  numeric?: boolean;
  format?(value: number): string;
}

/** A table, and what its CSV is made of. The CSV holds raw values, the table the formatted ones. */
export interface TableSpec {
  columns: Column[];
  rows: Record<string, Cell>[];
  totals?: Record<string, Cell>;
  csvName: string;
  caption?: string;
  /** Rows to set in bold (totals of a pivot). */
  emphasis?(row: Record<string, Cell>): boolean;
}

function show(column: Column, value: Cell): string {
  if (value == null) return '–';
  if (typeof value === 'number') return column.format ? column.format(value) : String(value);
  return value;
}

export function csvOf(spec: TableSpec): string {
  const rows = spec.rows.map((r) => spec.columns.map((c) => r[c.key]));
  if (spec.totals) rows.push(spec.columns.map((c) => spec.totals?.[c.key]));
  return toCsv(
    spec.columns.map((c) => c.label),
    rows,
  );
}

export function CsvButton({ spec }: { spec: TableSpec }) {
  return (
    <button type="button" className="btn" onClick={() => downloadCsv(spec.csvName, csvOf(spec))}>
      Download CSV
    </button>
  );
}

export function DataTable({ spec }: { spec: TableSpec }) {
  return (
    <div className="table-wrap">
      <table>
        {spec.caption && <caption>{spec.caption}</caption>}
        <thead>
          <tr>
            {spec.columns.map((c) => (
              <th key={c.key} scope="col" className={c.numeric ? 'num' : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.map((row, i) => (
            <tr key={i} style={spec.emphasis?.(row) ? { fontWeight: 600 } : undefined}>
              {spec.columns.map((c, k) =>
                k === 0 ? (
                  <th key={c.key} scope="row" style={{ fontWeight: 'inherit', color: 'inherit' }}>
                    {show(c, row[c.key])}
                  </th>
                ) : (
                  <td key={c.key} className={c.numeric ? 'num' : undefined}>
                    {show(c, row[c.key])}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
        {spec.totals && (
          <tfoot>
            <tr>
              {spec.columns.map((c) => (
                <td key={c.key} className={c.numeric ? 'num' : undefined}>
                  {show(c, spec.totals?.[c.key])}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
