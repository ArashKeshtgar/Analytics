import { describe, expect, it } from 'vitest';
import { compact, money, money2, monthLabel, monthShort, percent, signedPercent } from './format';

describe('format', () => {
  it('writes dollars with and without cents, and a dash for nothing', () => {
    expect(money(1234.56)).toBe('$1,235');
    expect(money2(1234.5)).toBe('$1,234.50');
    expect(money(-40)).toMatch(/-\$40|\$-40|−\$40/);
    expect(money(null)).toBe('–');
    expect(money2(undefined)).toBe('–');
  });

  it('shortens axis numbers', () => {
    expect(compact(0)).toBe('0');
    expect(compact(950)).toBe('950');
    expect(compact(1200)).toBe('1.2K');
    expect(compact(3_400_000)).toBe('3.4M');
    expect(compact(-2500)).toBe('-2.5K');
  });

  it('writes fractions as percentages', () => {
    expect(percent(0.153)).toBe('15.3%');
    expect(percent(0.05, 0)).toBe('5%');
    expect(percent(null)).toBe('–');
    expect(percent(0)).toBe('0.0%');
  });

  it('names months from the calendar date, whatever the time zone', () => {
    expect(monthLabel('2026-10-01')).toBe('Oct 2026');
    expect(monthLabel('2026-01-01')).toBe('Jan 2026');
    expect(monthShort('2026-12-01')).toBe('Dec');
  });

  it('writes a change with its sign', () => {
    expect(signedPercent(0.8)).toBe('+80.0%');
    expect(signedPercent(-0.031)).toBe('−3.1%');
    expect(signedPercent(0)).toBe('0.0%');
  });
});
