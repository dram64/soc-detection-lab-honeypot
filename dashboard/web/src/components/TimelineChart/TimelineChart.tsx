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
import { useTimeline } from '../../api/queries';
import type { TimelineBucket, Window24h7d30d } from '../../api/types';
import { formatAxisCount, formatTimelineTick } from '../../lib/format';
import { Card } from '../ui/Card';
import { Skeleton } from '../ui/Skeleton';

export interface TimelineChartProps {
  bucket?: TimelineBucket;
  window?: Window24h7d30d;
}

interface Datum {
  ts: string;
  tick: string;
  count: number | null;
}

export function TimelineChart({ bucket = '1h', window = '24h' }: TimelineChartProps) {
  const { data } = useTimeline({ bucket, window });

  const rows = useMemo<Datum[]>(() => {
    if (!data) return [];
    return data.buckets.map((b) => ({
      ts: b.ts,
      tick: formatTimelineTick(b.ts, bucket),
      count: b.count,
    }));
  }, [data, bucket]);

  if (!data) {
    return (
      <Card title="Event timeline (24h)">
        <Skeleton className="h-[280px] w-full" label="Loading event timeline" />
      </Card>
    );
  }

  return (
    <Card title="Event timeline (24h)">
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
              labelFormatter={(label) => `Hour: ${String(label)}`}
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
