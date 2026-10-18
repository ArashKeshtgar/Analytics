import { describe, expect, it } from 'vitest';
import { addMonths, endOfMonth, monthsBetween, quarterOf, rangeFor } from './periods';

describe('periods', () => {
  it('adds months across year ends, both ways', () => {
    expect(addMonths('2026-10-01', 3)).toBe('2027-01-01');
    expect(addMonths('2026-01-01', -1)).toBe('2025-12-01');
    expect(addMonths('2026-10-01', -12)).toBe('2025-10-01');
    expect(addMonths('2026-10-01', 0)).toBe('2026-10-01');
  });

  it('lists the months of a range, both ends included', () => {
    expect(monthsBetween('2026-11-01', '2027-02-01')).toEqual(['2026-11-01', '2026-12-01', '2027-01-01', '2027-02-01']);
    expect(monthsBetween('2026-10-01', '2026-10-01')).toEqual(['2026-10-01']);
    expect(monthsBetween('2026-10-01', '2026-09-01')).toEqual([]);
  });

  it('counts the presets back from the latest month with data', () => {
    expect(rangeFor('last12', '2026-10-01')).toEqual({ from: '2025-11-01', to: '2026-10-01' });
    expect(rangeFor('last6', '2026-10-01')).toEqual({ from: '2026-05-01', to: '2026-10-01' });
    expect(rangeFor('last3', '2026-10-01')).toEqual({ from: '2026-08-01', to: '2026-10-01' });
    expect(rangeFor('ytd', '2026-10-01')).toEqual({ from: '2026-01-01', to: '2026-10-01' });
    expect(rangeFor('lastYear', '2026-10-01')).toEqual({ from: '2025-01-01', to: '2025-12-01' });
    expect(rangeFor('last12', '2026-01-01')).toEqual({ from: '2025-02-01', to: '2026-01-01' });
  });

  it('puts months in quarters', () => {
    expect(quarterOf('2026-01-01')).toBe('2026 Q1');
    expect(quarterOf('2026-03-01')).toBe('2026 Q1');
    expect(quarterOf('2026-04-01')).toBe('2026 Q2');
    expect(quarterOf('2026-12-01')).toBe('2026 Q4');
  });

  it('finds the last day of a month, leap years included', () => {
    expect(endOfMonth('2026-10-01')).toBe('2026-10-31');
    expect(endOfMonth('2026-02-01')).toBe('2026-02-28');
    expect(endOfMonth('2028-02-01')).toBe('2028-02-29');
    expect(endOfMonth('2026-12-01')).toBe('2026-12-31');
    expect(endOfMonth('2026-04-01')).toBe('2026-04-30');
  });
});
