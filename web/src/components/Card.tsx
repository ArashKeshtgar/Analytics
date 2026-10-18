import { type ReactNode, useState } from 'react';
import { CsvButton, DataTable, type TableSpec } from './DataTable';

interface Props {
  title: string;
  subtitle?: string;
  /** The data behind the card: shown as the table view and downloaded as CSV. */
  table: TableSpec;
  /** The chart. Without it the card is just the table. */
  chart?: ReactNode;
  /** A reload is in flight: the previous render stays, dimmed. */
  stale?: boolean;
}

export function Card({ title, subtitle, table, chart, stale }: Props) {
  const [view, setView] = useState<'chart' | 'table'>(chart ? 'chart' : 'table');
  return (
    <section className={`card${stale ? ' stale' : ''}`} aria-busy={stale || undefined}>
      <div className="card-head">
        <div>
          <h2 className="card-title">{title}</h2>
          {subtitle && <p className="card-sub">{subtitle}</p>}
        </div>
        <div className="spacer">
          {chart && (
            <>
              <button type="button" className="btn" aria-pressed={view === 'chart'} onClick={() => setView('chart')}>
                Chart
              </button>
              <button type="button" className="btn" aria-pressed={view === 'table'} onClick={() => setView('table')}>
                Table
              </button>
            </>
          )}
          <CsvButton spec={table} />
        </div>
      </div>
      {view === 'chart' && chart ? chart : <DataTable spec={table} />}
    </section>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return <p className="notice">{children}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
