import { Counter } from '../ui/Counter';

/**
 * Top row of four stat counters.
 *
 * The Cowrie sensor completed its collection run (May 6–21, 2026) and was
 * decommissioned, so these show the FINAL run totals rather than rolling
 * time windows (which would empty out once the sensor stopped reporting).
 * Figures are the authoritative totals aggregated from the raw S3 event
 * archive — the same numbers surfaced on the portfolio Collection Summary.
 */
const RUN_TOTALS = {
  events: 231930,
  sessions: 36440,
  loginAttempts: 36405,
  uniqueIps: 1322,
} as const;

export function CounterRow() {
  return (
    <div
      role="region"
      aria-label="Honeypot run totals"
      className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4"
    >
      <Counter label="Total events" value={RUN_TOTALS.events} />
      <Counter label="Attack sessions" value={RUN_TOTALS.sessions} />
      <Counter label="Login attempts" value={RUN_TOTALS.loginAttempts} />
      <Counter label="Unique attacker IPs" value={RUN_TOTALS.uniqueIps} />
    </div>
  );
}
