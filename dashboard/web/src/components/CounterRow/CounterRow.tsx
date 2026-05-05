import { useSummary } from '../../api/queries';
import { Counter } from '../ui/Counter';

/**
 * Top row of four big stat counters. The component fetches its own data
 * via `useSummary()` and renders skeletons until the first response arrives.
 *
 * Silent stale data pattern (see dashboard/web/README.md): we never look
 * at `query.isError`. If `data` is undefined we render skeletons; otherwise
 * we render the data. Background refetch errors leave the previous data
 * on screen.
 */
export function CounterRow() {
  const { data } = useSummary();
  const loading = data === undefined;

  return (
    <div
      role="region"
      aria-label="Honeypot summary counters"
      className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4"
    >
      <Counter label="Total events" value={data?.total} loading={loading} />
      <Counter label="Last 24h" value={data?.last_24h} loading={loading} />
      <Counter label="Last 1h" value={data?.last_1h} loading={loading} />
      <Counter label="Unique IPs (24h)" value={data?.unique_ips_24h} loading={loading} />
    </div>
  );
}
