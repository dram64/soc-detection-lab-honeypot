import { formatEventCount } from '../../lib/format';
import { Skeleton } from './Skeleton';

/**
 * Single big-number stat display. Used 4× in CounterRow.
 */
export interface CounterProps {
  label: string;
  value: number | null | undefined;
  /** When true, render the skeleton placeholder instead of the value. */
  loading?: boolean;
}

export function Counter({ label, value, loading = false }: CounterProps) {
  return (
    <div className="scan-lines border border-bg-border border-l-4 border-l-accent bg-bg-elevated p-5">
      <p className="font-mono text-sm font-bold uppercase tracking-widest text-fg-muted">
        {label}
      </p>
      {loading ? (
        <Skeleton className="mt-3 h-16 w-32" />
      ) : (
        <p
          className="mt-2 font-display text-6xl leading-none tracking-wide text-accent drop-shadow-[0_0_18px_rgba(245,209,31,0.35)]"
          aria-label={`${label}: ${value ?? 'unknown'}`}
        >
          {formatEventCount(value)}
        </p>
      )}
    </div>
  );
}
