import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EventsResponse, PublicEvent } from '../../api/types';
import { mockQuery } from '../../test-utils';

vi.mock('../../api/queries', () => ({
  useEvents: vi.fn(),
}));

// jsdom has no layout, so @tanstack/react-virtual sees 0 scroll height and
// renders 0 virtual items. Mock the virtualizer to return a synchronous
// "render all rows" view so component tests can inspect the actual cells.
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: <T,>({ count }: { count: number; getScrollElement: () => T }) => ({
    getTotalSize: () => count * 36,
    getVirtualItems: () =>
      Array.from({ length: count }).map((_, index) => ({
        key: index,
        index,
        start: index * 36,
        size: 36,
      })),
  }),
}));

import { useEvents } from '../../api/queries';
import { RecentEventsTable } from './RecentEventsTable';

const mocked = vi.mocked(useEvents);

function makeEvent(overrides: Partial<PublicEvent> = {}): PublicEvent {
  return {
    eventid: 'cowrie.login.failed',
    session: 'sess-1',
    src_ip: '203.0.113.5',
    ts: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    sensor: 'honeypot',
    src_port: null,
    dst_ip: null,
    dst_port: null,
    protocol: null,
    message: null,
    username: 'root',
    password: '123456',
    input: null,
    url: null,
    shasum: null,
    duration: null,
    country: 'US',
    asn: null,
    asn_org: null,
    ...overrides,
  };
}

describe('RecentEventsTable', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(() => vi.clearAllMocks());

  it('renders skeletons when data is undefined', () => {
    mocked.mockReturnValue(mockQuery<EventsResponse>({ data: undefined }));
    render(<RecentEventsTable />);
    expect(screen.getAllByLabelText(/Loading event row/).length).toBeGreaterThan(0);
  });

  it('renders the empty state when items is empty', () => {
    mocked.mockReturnValue(mockQuery({ data: { items: [], next_before: null } }));
    render(<RecentEventsTable />);
    expect(screen.getByText(/No events yet/)).toBeInTheDocument();
  });

  it('renders dictionary password verbatim', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [makeEvent({ password: '123456' })],
          next_before: null,
        },
      }),
    );
    render(<RecentEventsTable />);
    expect(screen.getByText('123456')).toBeInTheDocument();
  });

  it('renders the filtered marker as a readable label', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [makeEvent({ password: '<filtered:len=14>' })],
          next_before: null,
        },
      }),
    );
    render(<RecentEventsTable />);
    expect(screen.getByText(/<filtered \(14 chars\)>/)).toBeInTheDocument();
  });

  it('keeps showing data on isError (silent stale)', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: { items: [makeEvent({ src_ip: '198.51.100.1' })], next_before: null },
        isError: true,
      }),
    );
    render(<RecentEventsTable />);
    expect(screen.getByText('198.51.100.1')).toBeInTheDocument();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
  });

  it('shows the country column with em-dash for null', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [makeEvent({ country: null })],
          next_before: null,
        },
      }),
    );
    render(<RecentEventsTable />);
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThan(0);
  });
});
