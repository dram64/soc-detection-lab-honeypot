import { describe, expect, it } from 'vitest';
import {
  formatEventCount,
  formatRelative,
  formatTechnique,
  formatTimelineTick,
  parseFilteredPassword,
} from './format';

describe('formatEventCount', () => {
  it('returns "—" for null/undefined/NaN', () => {
    expect(formatEventCount(null)).toBe('—');
    expect(formatEventCount(undefined)).toBe('—');
    expect(formatEventCount(NaN)).toBe('—');
  });

  it('returns small integers as-is', () => {
    expect(formatEventCount(0)).toBe('0');
    expect(formatEventCount(42)).toBe('42');
    expect(formatEventCount(999)).toBe('999');
  });

  it('compresses to k', () => {
    expect(formatEventCount(1000)).toBe('1k');
    expect(formatEventCount(1234)).toBe('1.2k');
    expect(formatEventCount(12345)).toBe('12.3k');
  });

  it('compresses to M', () => {
    expect(formatEventCount(1_234_567)).toBe('1.2M');
    expect(formatEventCount(12_345_678)).toBe('12.3M');
  });

  it('compresses to B', () => {
    expect(formatEventCount(1_500_000_000)).toBe('1.5B');
  });

  it('handles negatives', () => {
    expect(formatEventCount(-1234)).toBe('-1.2k');
    expect(formatEventCount(-42)).toBe('-42');
  });
});

describe('formatRelative', () => {
  it('returns "—" for nullish', () => {
    expect(formatRelative(null)).toBe('—');
    expect(formatRelative(undefined)).toBe('—');
    expect(formatRelative('')).toBe('—');
  });

  it('returns "—" for unparseable', () => {
    expect(formatRelative('not-a-date')).toBe('—');
  });

  it('formats parseable timestamps', () => {
    const long_ago = new Date(Date.now() - 1000 * 60 * 60).toISOString();
    expect(formatRelative(long_ago)).toMatch(/ago$/);
  });
});

describe('formatTimelineTick', () => {
  it('formats 1h buckets as HH:mm UTC', () => {
    expect(formatTimelineTick('2026-04-29T03:00:00Z', '1h')).toBe('03:00');
    expect(formatTimelineTick('2026-04-29T14:30:00Z', '1h')).toBe('14:30');
  });

  it('formats 1d buckets as MMM d', () => {
    expect(formatTimelineTick('2026-04-29T00:00:00Z', '1d')).toBe('Apr 29');
  });

  it('returns original on parse failure', () => {
    expect(formatTimelineTick('not-a-date', '1h')).toBe('not-a-date');
  });
});

describe('formatTechnique', () => {
  it('handles nullish', () => {
    expect(formatTechnique(null)).toBe('—');
    expect(formatTechnique(undefined)).toBe('—');
    expect(formatTechnique('')).toBe('—');
  });

  it('replaces underscores and title-cases the first word', () => {
    expect(formatTechnique('brute_force')).toBe('Brute force');
    expect(formatTechnique('credential_stuffing')).toBe('Credential stuffing');
    expect(formatTechnique('scanner')).toBe('Scanner');
    expect(formatTechnique('other')).toBe('Other');
  });
});

describe('parseFilteredPassword', () => {
  it('returns null for nullish/missing', () => {
    expect(parseFilteredPassword(null)).toBe(null);
    expect(parseFilteredPassword(undefined)).toBe(null);
    expect(parseFilteredPassword('')).toBe(null);
  });

  it('returns null for non-marker strings', () => {
    expect(parseFilteredPassword('123456')).toBe(null);
    expect(parseFilteredPassword('password')).toBe(null);
    expect(parseFilteredPassword('<filtered>')).toBe(null);
  });

  it('parses the length out of the marker', () => {
    expect(parseFilteredPassword('<filtered:len=8>')).toBe(8);
    expect(parseFilteredPassword('<filtered:len=24>')).toBe(24);
    expect(parseFilteredPassword('<filtered:len=0>')).toBe(0);
  });
});
