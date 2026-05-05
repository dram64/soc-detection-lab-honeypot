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
    <div className="rounded-lg border border-bg-border bg-bg-elevated p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">
        {label}
      </p>
      {loading ? (
        <Skeleton className="mt-3 h-9 w-24" />
      ) : (
        <p
          className="mt-2 font-mono text-3xl font-semibold tracking-tight text-fg"
          aria-label={`${label}: ${value ?? 'unknown'}`}
        >
          {formatEventCount(value)}
        </p>
      )}
    </div>
  );
}
