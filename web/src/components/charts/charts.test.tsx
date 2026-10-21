import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { ColumnChart } from './ColumnChart';
import { columnPath, niceScale, rowPath } from './common';
import { HBarChart } from './HBarChart';
import { LineChart } from './LineChart';

const money = (n: number): string => `$${n}`;
const two = [
  { id: 'a', label: 'Billed', color: 'var(--series-1)', values: [100, 200] },
  { id: 'b', label: 'Paid', color: 'var(--series-2)', values: [60, null] },
];

describe('niceScale', () => {
  it('always holds zero and ends on round ticks', () => {
    const s = niceScale(0, 270);
    expect(s.min).toBe(0);
    expect(s.max).toBeGreaterThanOrEqual(270);
    expect(s.ticks[0]).toBe(0);
    expect(s.ticks.every((t) => Number.isInteger(t) || Math.abs(t * 10 - Math.round(t * 10)) < 1e-6)).toBe(true);
    expect(s.ticks.at(-1)).toBe(s.max);
  });

  it('covers negative values and a lone zero', () => {
    const s = niceScale(-26, 13);
    expect(s.min).toBeLessThanOrEqual(-26);
    expect(s.max).toBeGreaterThanOrEqual(13);
    expect(s.ticks).toContain(0);
    expect(niceScale(0, 0).max).toBeGreaterThan(0);
  });
});

describe('niceScale kinds', () => {
  it('whole numbers: a count never gets a fractional tick', () => {
    const s = niceScale(0, 1, 4, 'integer');
    expect(s.ticks).toEqual([0, 1]);
    expect(niceScale(0, 7, 4, 'integer').ticks.every(Number.isInteger)).toBe(true);
    expect(niceScale(0, 1, 4).ticks).toContain(0.25); // the plain scale would
  });

  it('durations: ticks fall on natural time steps', () => {
    expect(niceScale(0, 2880, 4, 'duration').ticks).toEqual([0, 720, 1440, 2160, 2880]); // 12 h, 1 d, 1.5 d, 2 d
    expect(niceScale(0, 501, 4, 'duration').ticks).toEqual([0, 180, 360, 540]); // 3 h, 6 h, 9 h
    expect(niceScale(0, 60, 4, 'duration').ticks).toEqual([0, 15, 30, 45, 60]);
    expect(niceScale(0, 1740, 4, 'duration').ticks.at(-1)).toBeGreaterThanOrEqual(1740);
  });
});

describe('mark paths', () => {
  it('rounds the data end of a column and keeps the baseline square', () => {
    const d = columnPath(10, 100, 40, 20, 4);
    expect(d.startsWith('M10,100V44')).toBe(true); // up the left edge to just under the rounded tip
    expect(d.match(/Q/g)).toHaveLength(2); // two rounded corners, both at the tip
    expect(d.endsWith('V100Z')).toBe(true);
  });

  it('rounds the tip of a bar that goes below the baseline', () => {
    const d = columnPath(10, 100, 160, 20, 4);
    expect(d).toContain('V156'); // the tip is at y=160, rounded below the baseline
    expect(d.match(/Q/g)).toHaveLength(2);
  });

  it('draws nothing for a zero-height mark and never rounds more than the mark is thick', () => {
    expect(columnPath(0, 100, 100, 20, 4)).toBe('');
    expect(columnPath(0, 100, 99.8, 20, 4)).toBe('');
    expect(rowPath(50, 50, 0, 10, 4)).toBe('');
    expect(rowPath(0, 3, 0, 20, 4)).toMatch(/H1\b|H0/);
  });

  it('can leave a row segment square at both ends', () => {
    expect(rowPath(0, 50, 0, 20, 4, false)).not.toContain('Q');
    expect(rowPath(0, 50, 0, 20, 4, true)).toContain('Q');
  });
});

describe('legend', () => {
  it('is there for two series and not for one', () => {
    const { rerender } = render(<ColumnChart categories={['Sep', 'Oct']} series={two} format={money} ariaLabel="x" />);
    expect(screen.getByRole('list', { name: 'Legend' })).toBeInTheDocument();
    rerender(<ColumnChart categories={['Sep', 'Oct']} series={[two[0]!]} format={money} ariaLabel="x" />);
    expect(screen.queryByRole('list', { name: 'Legend' })).toBeNull();
  });

  it('hides a series on click but never the last one', async () => {
    render(<ColumnChart categories={['Sep', 'Oct']} series={two} format={money} ariaLabel="x" />);
    const billed = screen.getByRole('button', { name: 'Billed' });
    const paid = screen.getByRole('button', { name: 'Paid' });
    await userEvent.click(paid);
    expect(paid).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(billed);
    expect(billed).toHaveAttribute('aria-pressed', 'true'); // one has to stay
    await userEvent.click(paid);
    expect(paid).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('ColumnChart', () => {
  it('gives every series at the hovered position in one tooltip, and clears it', () => {
    render(<ColumnChart categories={['Sep 2026', 'Oct 2026']} series={two} format={money} ariaLabel="Billed and paid" />);
    const first = screen.getByLabelText('Sep 2026: Billed $100, Paid $60');
    fireEvent.pointerEnter(first);
    const tip = screen.getByRole('tooltip');
    expect(within(tip).getByText('Sep 2026')).toBeInTheDocument();
    expect(within(tip).getByText('$100')).toBeInTheDocument();
    expect(within(tip).getByText('$60')).toBeInTheDocument();
    fireEvent.pointerLeave(first);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('shows the same on keyboard focus and says "none" for a missing value', () => {
    render(<ColumnChart categories={['Sep 2026', 'Oct 2026']} series={two} format={money} ariaLabel="x" />);
    const second = screen.getByLabelText('Oct 2026: Billed $200, Paid none');
    fireEvent.focus(second);
    expect(within(screen.getByRole('tooltip')).getByText('–')).toBeInTheDocument();
    fireEvent.blur(second);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('puts names into the page as text, never as markup', () => {
    const hostile = [{ id: 'x', label: '<img src=x onerror=alert(1)>', color: 'var(--series-1)', values: [1] }];
    const { container } = render(<ColumnChart categories={['<b>bold</b>']} series={hostile} format={money} ariaLabel="x" />);
    fireEvent.focus(screen.getByLabelText(/bold/));
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
    expect(within(screen.getByRole('tooltip')).getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
  });

  it('draws no bar thicker than 24px', () => {
    const { container } = render(<ColumnChart categories={['Sep']} series={[two[0]!]} format={money} ariaLabel="x" />);
    const d = container.querySelector('path.mark')?.getAttribute('d') ?? '';
    const x = [...d.matchAll(/[MHVQ]?(-?\d+(?:\.\d+)?),/g)].map((m) => Number(m[1]));
    expect(Math.max(...x) - Math.min(...x)).toBeLessThanOrEqual(24);
  });

  it('labels the last category even when the axis is thinned', () => {
    const months = Array.from({ length: 12 }, (_, i) => `M${i}`);
    render(<ColumnChart categories={months} series={[{ id: 'a', label: 'A', color: 'red', values: months.map(() => 1) }]} format={money} ariaLabel="x" />);
    expect(screen.getAllByText('M11').length).toBeGreaterThan(0);
  });
});

describe('LineChart', () => {
  const lines = [
    { id: 'r', label: 'Revenue', color: 'var(--series-1)', values: [10, 20, null, 40] },
    { id: 'y', label: 'A year earlier', color: 'var(--series-other)', values: [5, 5, 5, 5] },
  ];

  it('moves the readout with the arrow keys and closes on Escape', () => {
    render(<LineChart categories={['Jul', 'Aug', 'Sep', 'Oct']} series={lines} format={money} ariaLabel="Revenue" />);
    const area = screen.getByLabelText(/arrow keys/);
    fireEvent.focus(area);
    expect(within(screen.getByRole('tooltip')).getByText('Oct')).toBeInTheDocument();
    fireEvent.keyDown(area, { key: 'ArrowLeft' });
    const tip = screen.getByRole('tooltip');
    expect(within(tip).getByText('Sep')).toBeInTheDocument();
    expect(within(tip).getByText('–')).toBeInTheDocument(); // no revenue in Sep
    fireEvent.keyDown(area, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('breaks the line where a value is missing', () => {
    const { container } = render(<LineChart categories={['a', 'b', 'c', 'd']} series={[lines[0]!]} format={money} ariaLabel="x" />);
    const d = container.querySelector('path[stroke]')?.getAttribute('d') ?? '';
    expect((d.match(/M/g) ?? []).length).toBe(2);
  });

  it('keeps a lone series without a legend box', () => {
    render(<LineChart categories={['a', 'b']} series={[lines[0]!]} format={money} ariaLabel="x" />);
    expect(screen.queryByRole('list', { name: 'Legend' })).toBeNull();
  });
});

describe('HBarChart', () => {
  it('stacked: lists every segment and the total in one tooltip', () => {
    render(
      <HBarChart
        mode="stacked"
        categories={['OHIP', 'Patient']}
        format={money}
        ariaLabel="Aging"
        series={[
          { id: 'cur', label: 'Current', color: 'var(--age-1)', values: [200, 0] },
          { id: 'o', label: '1–30 days', color: 'var(--age-2)', values: [10, 50] },
        ]}
      />,
    );
    fireEvent.pointerEnter(screen.getByLabelText('OHIP: Current $200, 1–30 days $10'));
    const tip = screen.getByRole('tooltip');
    expect(within(tip).getByText('Total')).toBeInTheDocument();
    expect(within(tip).getByText('$210')).toBeInTheDocument();
  });

  it('grouped: one bar per series, value at the tip of the first only', () => {
    const { container } = render(
      <HBarChart
        mode="grouped"
        categories={['Clinic']}
        format={money}
        ariaLabel="x"
        series={[
          { id: 'a', label: 'This', color: 'blue', values: [200] },
          { id: 'b', label: 'Last', color: 'gray', values: [90] },
        ]}
      />,
    );
    expect(container.querySelectorAll('path.mark')).toHaveLength(2);
    expect(screen.getByText('$200')).toBeInTheDocument();
    expect(screen.queryByText('$90')).toBeNull();
  });

  it('shortens a long name and keeps the whole one as a title', () => {
    const long = 'A very long line of business name that does not fit';
    const { container } = render(
      <HBarChart mode="grouped" categories={[long]} format={money} ariaLabel="x" series={[{ id: 'a', label: 'A', color: 'blue', values: [1] }]} />,
    );
    expect(container.querySelector('title')?.textContent).toBe(long);
    expect(container.textContent).toContain('A very long line of bus…');
    expect(container.querySelector('text.value-text')?.lastChild?.textContent).toBe('A very long line of bus…');
  });
});
