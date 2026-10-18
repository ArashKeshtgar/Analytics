import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as csv from '../lib/csv';
import { Card } from './Card';
import { csvOf, DataTable, type TableSpec } from './DataTable';
import { StatTile } from './StatTile';

const spec: TableSpec = {
  csvName: 'revenue',
  caption: 'Revenue',
  columns: [
    { key: 'name', label: 'Line' },
    { key: 'amount', label: 'Amount', numeric: true, format: (v) => `$${v.toFixed(2)}` },
  ],
  rows: [
    { name: 'Clinic, main', amount: 200 },
    { name: '=Evil', amount: null },
  ],
  totals: { name: 'Total', amount: 200 },
};

afterEach(() => vi.restoreAllMocks());

describe('DataTable', () => {
  it('shows formatted values and a dash for nothing, with totals in the footer', () => {
    render(<DataTable spec={spec} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: 'Clinic, main' })).toBeInTheDocument();
    expect(screen.getByText('$200.00', { selector: 'tbody td' })).toBeInTheDocument();
    expect(screen.getByText('–')).toBeInTheDocument();
    expect(within(screen.getAllByRole('row').at(-1)!).getByText('Total')).toBeInTheDocument();
  });

  it('exports raw numbers, the totals row and safe text', () => {
    expect(csvOf(spec)).toBe("Line,Amount\r\n\"Clinic, main\",200\r\n'=Evil,\r\nTotal,200\r\n");
  });
});

describe('Card', () => {
  it('starts on the chart, switches to the table and back, and always offers the CSV', async () => {
    const download = vi.spyOn(csv, 'downloadCsv').mockImplementation(() => {});
    render(<Card title="Revenue" table={spec} chart={<div>the chart</div>} />);
    expect(screen.getByText('the chart')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: 'Table' }));
    expect(screen.queryByText('the chart')).toBeNull();
    expect(screen.getByRole('table')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Download CSV' }));
    expect(download).toHaveBeenCalledWith('revenue', csvOf(spec));

    await userEvent.click(screen.getByRole('button', { name: 'Chart' }));
    expect(screen.getByText('the chart')).toBeInTheDocument();
  });

  it('is just a table, with its CSV, when there is no chart', () => {
    render(<Card title="By provider" table={spec} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Chart' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Download CSV' })).toBeInTheDocument();
  });

  it('dims itself while a reload is in flight', () => {
    const { container } = render(<Card title="x" table={spec} stale />);
    expect(container.querySelector('section.stale')).toHaveAttribute('aria-busy', 'true');
  });
});

describe('StatTile', () => {
  it('colours a delta by whether the direction is good', () => {
    const { container, rerender } = render(<StatTile label="Revenue" value="$270" delta={{ text: '+80.0%', direction: 'up' }} />);
    expect(container.querySelector('.up')).not.toBeNull();
    rerender(<StatTile label="Revenue" value="$270" delta={{ text: '−5.0%', direction: 'down' }} />);
    expect(container.querySelector('.down')).not.toBeNull();
    // refused claims going up is bad news
    rerender(<StatTile label="Refused" value="5%" delta={{ text: '+1.0%', direction: 'up', goodWhenUp: false }} />);
    expect(container.querySelector('.down')).not.toBeNull();
    rerender(<StatTile label="x" value="1" delta={{ text: '0.0%', direction: 'flat' }} />);
    expect(container.querySelector('.up, .down')).toBeNull();
  });

  it('says the same in words, not only in colour', () => {
    render(<StatTile label="Revenue" value="$270" delta={{ text: '+80.0% vs Oct 2025', direction: 'up' }} />);
    expect(screen.getByText('+80.0% vs Oct 2025')).toBeInTheDocument();
  });

  it('marks the hero', () => {
    const { container } = render(<StatTile hero label="Revenue" value="$270" />);
    expect(container.querySelector('.tile-hero')).not.toBeNull();
  });
});
