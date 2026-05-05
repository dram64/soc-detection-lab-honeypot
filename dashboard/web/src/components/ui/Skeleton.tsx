import type { CSSProperties } from 'react';

/**
 * Animated placeholder block. Tailwind `animate-pulse` + a low-contrast
 * neutral background. Used while a query has no cached data yet.
 *
 * Once a query has cached data, components render the data even on
 * background-refetch errors — Skeleton is for first-load only (the
 * "silent stale data" pattern documented in dashboard/web/README.md).
 */
export interface SkeletonProps {
  className?: string;
  style?: CSSProperties;
  /** ARIA label for screen readers; defaults to "Loading". */
  label?: string;
}

export function Skeleton({ className = '', style, label = 'Loading' }: SkeletonProps) {
  return (
    <div
      role="status"
      aria-label={label}
      aria-busy="true"
      className={`animate-pulse rounded-md bg-bg-border ${className}`}
      style={style}
    />
  );
}
