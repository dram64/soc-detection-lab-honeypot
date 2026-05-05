import { useTopPasswords } from '../../api/queries';
import { parseFilteredPassword } from '../../lib/format';
import { TopBarChart } from '../ui/TopBarChart';

/**
 * Top-passwords chart. Values arrive from the backend as either:
 *   - A literal dictionary password (rendered verbatim)
 *   - The `<filtered:len=N>` marker for non-dictionary attempts (ADR-005)
 * We render the marker as `<filtered (N chars)>` so the label is readable.
 */
function formatPasswordLabel(value: string): string {
  const len = parseFilteredPassword(value);
  if (len !== null) return `<filtered (${len} chars)>`;
  return value;
}

export function TopPasswordsChart() {
  const { data } = useTopPasswords({ limit: 20, window: '24h' });
  return (
    <TopBarChart
      title="Top passwords (24h)"
      data={data}
      valueLabel="Password"
      formatValue={formatPasswordLabel}
    />
  );
}
