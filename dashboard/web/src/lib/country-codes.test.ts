import { describe, expect, it } from 'vitest';
import {
  ALPHA2_TO_NUMERIC,
  NUMERIC_TO_ALPHA2,
  alpha2ToName,
  alpha2ToNumeric,
} from './country-codes';

describe('country-codes', () => {
  it('maps alpha-2 to numeric for the Phase 7 distribution top countries', () => {
    expect(alpha2ToNumeric('CN')).toBe('156');
    expect(alpha2ToNumeric('US')).toBe('840');
    expect(alpha2ToNumeric('RU')).toBe('643');
    expect(alpha2ToNumeric('BR')).toBe('076');
    expect(alpha2ToNumeric('IN')).toBe('356');
    expect(alpha2ToNumeric('VN')).toBe('704');
    expect(alpha2ToNumeric('KR')).toBe('410');
    expect(alpha2ToNumeric('DE')).toBe('276');
    expect(alpha2ToNumeric('TR')).toBe('792');
    expect(alpha2ToNumeric('ID')).toBe('360');
    expect(alpha2ToNumeric('TW')).toBe('158');
    expect(alpha2ToNumeric('HK')).toBe('344');
    expect(alpha2ToNumeric('FR')).toBe('250');
    expect(alpha2ToNumeric('GB')).toBe('826');
  });

  it('returns undefined for unknown codes', () => {
    expect(alpha2ToNumeric('XX')).toBeUndefined();
    expect(alpha2ToNumeric('ZZ')).toBeUndefined();
  });

  it('is case-insensitive on input', () => {
    expect(alpha2ToNumeric('cn')).toBe('156');
    expect(alpha2ToNumeric('us')).toBe('840');
  });

  it('round-trips alpha-2 ↔ numeric', () => {
    for (const [alpha, numeric] of Object.entries(ALPHA2_TO_NUMERIC)) {
      expect(NUMERIC_TO_ALPHA2[numeric]).toBe(alpha);
    }
  });

  it('returns human-readable country names', () => {
    expect(alpha2ToName('CN')).toBe('China');
    expect(alpha2ToName('US')).toBe('United States');
    expect(alpha2ToName('GB')).toBe('United Kingdom');
  });

  it('falls back to the code itself for unknown countries', () => {
    expect(alpha2ToName('XX')).toBe('XX');
  });
});
