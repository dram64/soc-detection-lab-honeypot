import { useMemo } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatAxisCount, formatTimelineTick } from '../../lib/format';
import { Card } from '../ui/Card';

interface Datum {
  ts: string;
  tick: string;
  count: number | null;
}

/**
 * Event timeline for the completed 14-day collection run (May 6–21, 2026).
 *
 * Rendered as static daily buckets aggregated from the raw S3 event archive so
 * the chart permanently spans the whole run, rather than a rolling API window
 * that would empty once the sensor was decommissioned (consistent with the
 * static counters and top-passwords chart).
 */
const RUN_BUCKETS: { ts: string; count: number }[] = [
  { ts: '2026-05-06T00:00:00Z', count: 2004 },
  { ts: '2026-05-07T00:00:00Z', count: 2215 },
  { ts: '2026-05-08T00:00:00Z', count: 1657 },
  { ts: '2026-05-09T00:00:00Z', count: 11387 },
  { ts: '2026-05-10T00:00:00Z', count: 6313 },
  { ts: '2026-05-11T00:00:00Z', count: 9904 },
  { ts: '2026-05-12T00:00:00Z', count: 9609 },
  { ts: '2026-05-13T00:00:00Z', count: 6279 },
  { ts: '2026-05-14T00:00:00Z', count: 33410 },
  { ts: '2026-05-15T00:00:00Z', count: 64997 },
  { ts: '2026-05-16T00:00:00Z', count: 13901 },
  { ts: '2026-05-17T00:00:00Z', count: 11245 },
  { ts: '2026-05-18T00:00:00Z', count: 26742 },
  { ts: '2026-05-19T00:00:00Z', count: 8141 },
  { ts: '2026-05-20T00:00:00Z', count: 17645 },
  { ts: '2026-05-21T00:00:00Z', count: 6481 },
];

export function TimelineChart() {
  const rows = useMemo<Datum[]>(
    () =>
      RUN_BUCKETS.map((b) => ({
        ts: b.ts,
        tick: formatTimelineTick(b.ts, '1d'),
        count: b.count,
      })),
    [],
  );

  return (
    <Card title="Event timeline">
      <div className="h-[280px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
            <defs>
              <linearGradient id="timelineFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#2dd4bf" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#2dd4bf" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1f2933" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="tick"
              stroke="#5a6473"
              fontSize={11}
              tickMargin={8}
              minTickGap={20}
            />
            <YAxis
              stroke="#5a6473"
              fontSize={11}
              tickFormatter={formatAxisCount}
              width={40}
            />
            <Tooltip
              cursor={{ stroke: '#2dd4bf', strokeOpacity: 0.4 }}
              contentStyle={{
                backgroundColor: '#121821',
                border: '1px solid #1f2933',
                borderRadius: 8,
                color: '#e6edf3',
                fontSize: 12,
              }}
              labelFormatter={(label) => String(label)}
              formatter={(value) => [value ?? '—', 'Events']}
            />
            <Area
              type="monotone"
              dataKey="count"
              stroke="#2dd4bf"
              strokeWidth={2}
              fill="url(#timelineFill)"
              connectNulls={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
