import { useVirtualizer } from '@tanstack/react-virtual';
import { useMemo, useRef } from 'react';
import { useEvents } from '../../api/queries';
import type { PublicEvent } from '../../api/types';
import { formatRelative, parseFilteredPassword } from '../../lib/format';
import { Card } from '../ui/Card';
import { Skeleton } from '../ui/Skeleton';

const ROW_HEIGHT = 36;
const VISIBLE_ROWS = 12;
const TABLE_HEIGHT = ROW_HEIGHT * VISIBLE_ROWS;

interface ColumnDef {
  key: string;
  label: string;
  /** Tailwind width class. */
  className: string;
}

const COLUMNS: ColumnDef[] = [
  { key: 'ts', label: 'Time', className: 'w-28' },
  { key: 'src_ip', label: 'Source IP', className: 'w-36' },
  { key: 'country', label: 'Country', className: 'w-20' },
  { key: 'username', label: 'Username', className: 'w-28' },
  { key: 'password', label: 'Password', className: 'w-44' },
  { key: 'eventid', label: 'Event', className: 'flex-1' },
];

function PasswordCell({ value }: { value: string | null }) {
  if (value === null) return <span className="text-fg-subtle">—</span>;
  const filteredLen = parseFilteredPassword(value);
  if (filteredLen !== null) {
    return (
      <span className="font-mono text-fg-muted" title="Non-dictionary attempt; raw value redacted (ADR-005)">
        &lt;filtered ({filteredLen} chars)&gt;
      </span>
    );
  }
  return <span className="font-mono text-fg">{value}</span>;
}

function Row({ event, top }: { event: PublicEvent; top: number }) {
  const successRow = event.eventid === 'cowrie.login.success';
  const baseClass = successRow
    ? 'absolute left-0 right-0 flex items-center gap-3 px-4 text-sm bg-danger/10 hover:bg-bg-border/40'
    : 'absolute left-0 right-0 flex items-center gap-3 px-4 text-sm hover:bg-bg-border/40';
  return (
    <div
      role="row"
      className={baseClass}
      style={{ height: ROW_HEIGHT, top }}
      // eslint-disable-next-line no-console
      onClick={() => console.log('row click', event.session, event.ts)}
    >
      <div className="w-28 truncate font-mono text-xs text-fg-muted" title={event.ts}>
        {formatRelative(event.ts)}
      </div>
      <div className="w-36 truncate font-mono text-xs text-fg">{event.src_ip}</div>
      <div className="w-20 truncate text-xs text-fg-muted">{event.country ?? '—'}</div>
      <div className="w-28 truncate font-mono text-xs text-fg">{event.username ?? '—'}</div>
      <div className="w-44 truncate text-xs">
        <PasswordCell value={event.password} />
      </div>
      <div className="flex-1 truncate text-xs text-fg-muted" title={event.eventid}>
        {event.eventid}
      </div>
    </div>
  );
}

export function RecentEventsTable() {
  const { data } = useEvents({ limit: 50 });
  const parentRef = useRef<HTMLDivElement>(null);

  const items = useMemo(() => data?.items ?? [], [data]);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 6,
  });

  if (!data) {
    return (
      <Card title="Recent events">
        <div className="space-y-2">
          {Array.from({ length: VISIBLE_ROWS }).map((_, i) => (
            <Skeleton key={i} className="h-7 w-full" label={`Loading event row ${i + 1}`} />
          ))}
        </div>
      </Card>
    );
  }

  if (items.length === 0) {
    return (
      <Card title="Recent events">
        <p className="py-12 text-center text-sm text-fg-muted">No events yet.</p>
      </Card>
    );
  }

  return (
    <Card title={`Recent events (${items.length})`}>
      <div
        role="table"
        aria-label="Recent events"
        className="rounded-md border border-bg-border"
      >
        <div
          role="row"
          className="flex items-center gap-3 border-b border-bg-border bg-bg/40 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-fg-subtle"
        >
          {COLUMNS.map((col) => (
            <div key={col.key} className={col.className}>
              {col.label}
            </div>
          ))}
        </div>
        <div
          ref={parentRef}
          style={{ height: TABLE_HEIGHT, overflow: 'auto', position: 'relative' }}
        >
          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const event = items[virtualRow.index];
              if (!event) return null;
              return (
                <Row key={`${event.session}-${event.ts}`} event={event} top={virtualRow.start} />
              );
            })}
          </div>
        </div>
      </div>
    </Card>
  );
}
