/**
 * Display formatters used across the dashboard. Pure functions; no React,
 * no DOM, fully unit-testable.
 */

import { formatDistanceToNowStrict, parseISO } from 'date-fns';

/**
 * Format an event count for compact display.
 *   1234         → "1.2k"
 *   12345        → "12.3k"
 *   1234567      → "1.2M"
 *   12345678     → "12.3M"
 *   < 1000       → as-is, no suffix
 *   negative     → with leading minus, same logic on absolute value
 */
export function formatEventCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  if (Number.isNaN(n)) return '—';
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  if (abs < 1000) return `${sign}${abs}`;
  if (abs < 1_000_000) return `${sign}${(abs / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  if (abs < 1_000_000_000)
    return `${sign}${(abs / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  return `${sign}${(abs / 1_000_000_000).toFixed(1).replace(/\.0$/, '')}B`;
}

/**
 * Compact integer formatter for axis labels — same behaviour as
 * `formatEventCount` but documents intent at the call site.
 */
export const formatAxisCount = formatEventCount;

/**
 * Relative time string ("3 minutes ago", "2 hours ago"). Returns "—"
 * for null/undefined/unparseable input.
 */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return `${formatDistanceToNowStrict(parseISO(iso))} ago`;
  } catch {
    return '—';
  }
}

/**
 * Pad a 2-digit value.
 */
function pad2(n: number): string {
  return n.toString().padStart(2, '0');
}

/**
 * Format an ISO 8601 timestamp for axis ticks.
 *   bucket=1h  →  "HH:mm" UTC
 *   bucket=1d  →  "MMM d"
 */
export function formatTimelineTick(iso: string, bucket: '1h' | '1d'): string {
  try {
    const d = parseISO(iso);
    if (Number.isNaN(d.getTime())) return iso;
    if (bucket === '1h') {
      return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
    }
    const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
    return `${month} ${d.getUTCDate()}`;
  } catch {
    return iso;
  }
}

/**
 * Title-Case-ish technique label for display (brute_force → "Brute force").
 */
export function formatTechnique(t: string | null | undefined): string {
  if (!t) return '—';
  const words = t.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Detects the `<filtered:len=N>` marker the backend uses for non-dictionary
 * passwords (ADR-005). If matched, returns the integer N. Otherwise null.
 */
export function parseFilteredPassword(value: string | null | undefined): number | null {
  if (!value) return null;
  const m = value.match(/^<filtered:len=(\d+)>$/);
  if (!m || !m[1]) return null;
  return Number.parseInt(m[1], 10);
}
