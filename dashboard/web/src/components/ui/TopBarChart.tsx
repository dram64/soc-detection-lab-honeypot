import { useMemo } from 'react';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TopListResponse } from '../../api/types';
import { formatEventCount } from '../../lib/format';
import { Card } from './Card';
import { Skeleton } from './Skeleton';

export interface TopBarChartProps {
  title: string;
  data: TopListResponse | undefined;
  /** Right-aligned column header (e.g. "Username", "Password"). */
  valueLabel?: string;
  /** Renders a teal accent bar with each row darker the further down the list. */
  accentColor?: string;
  /** When provided, transforms each value before display (e.g. masking long passwords). */
  formatValue?: (value: string) => string;
}

interface Datum {
  value: string;
  display: string;
  count: number;
}

const SKELETON_ROWS = 12;

export function TopBarChart({
  title,
  data,
  valueLabel = 'Value',
  accentColor = '#2dd4bf',
  formatValue,
}: TopBarChartProps) {
  const rows = useMemo<Datum[]>(() => {
    if (!data) return [];
    return data.items.map((item) => ({
      value: item.value,
      display: formatValue ? formatValue(item.value) : item.value,
      count: item.count,
    }));
  }, [data, formatValue]);

  if (!data) {
    return (
      <Card title={title}>
        <div className="space-y-2" aria-label={`Loading ${title}`}>
          {Array.from({ length: SKELETON_ROWS }).map((_, i) => (
            <Skeleton
              key={i}
              className="h-5"
              style={{ width: `${100 - i * 4}%` }}
              label={`Loading ${title} row ${i + 1}`}
            />
          ))}
        </div>
      </Card>
    );
  }

  if (rows.length === 0) {
    return (
      <Card title={title}>
        <p className="py-12 text-center text-sm text-fg-muted">No data yet.</p>
      </Card>
    );
  }

  // Recharts renders values top-to-bottom in array order with `layout="vertical"`.
  return (
    <Card title={title}>
      <div className="h-[420px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
          >
            <XAxis
              type="number"
              tickFormatter={formatEventCount}
              stroke="#5a6473"
              fontSize={11}
            />
            <YAxis
              type="category"
              dataKey="display"
              stroke="#5a6473"
              fontSize={11}
              width={140}
              interval={0}
              tick={{ fill: '#8b96a3' }}
            />
            <Tooltip
              cursor={{ fill: '#1f2933', opacity: 0.5 }}
              contentStyle={{
                backgroundColor: '#121821',
                border: '1px solid #1f2933',
                borderRadius: 8,
                color: '#e6edf3',
                fontSize: 12,
              }}
              labelFormatter={(label) => `${valueLabel}: ${String(label)}`}
              formatter={(value) => [
                formatEventCount(typeof value === 'number' ? value : Number(value)),
                'Count',
              ]}
            />
            <Bar dataKey="count" radius={[0, 3, 3, 0]}>
              {rows.map((row) => (
                <Cell key={row.value} fill={accentColor} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
