import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import type * as RechartsModule from 'recharts';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../api/queries', () => ({
  useHealth: vi.fn().mockReturnValue({
    data: { status: 'ok', version: 'test-sha-1234567890abcdef' },
    isPending: false,
    isError: false,
  }),
  useSummary: vi.fn().mockReturnValue({ data: undefined, isError: false }),
  useTimeline: vi.fn().mockReturnValue({ data: undefined, isError: false }),
  useTopUsernames: vi.fn().mockReturnValue({ data: undefined, isError: false }),
  useTopPasswords: vi.fn().mockReturnValue({ data: undefined, isError: false }),
  useTopCountries: vi.fn().mockReturnValue({ data: undefined, isError: false }),
  useEvents: vi.fn().mockReturnValue({ data: undefined, isError: false }),
}));

// Stub the lazy GeoMap surface so the route test doesn't wait on the
// dynamic import (or the world-atlas TopoJSON file).
vi.mock('../components/GeoMap/GeoMap.lazy', () => ({
  GeoMap: () => <div data-testid="geomap-placeholder" />,
}));

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof RechartsModule>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div data-testid="responsive-container" style={{ width: 800, height: 300 }}>
        {children}
      </div>
    ),
  };
});

import { Dashboard } from './Dashboard';

describe('Dashboard route', () => {
  it('mounts header, counter row, both top charts, timeline, and events table', () => {
    render(<Dashboard />);
    expect(screen.getByText('Honeypot Dashboard')).toBeInTheDocument();
    expect(
      screen.getByText('Cowrie SSH honeypot · 14-day collection run · May 6–21, 2026'),
    ).toBeInTheDocument();
    expect(screen.getByText('[ ONLINE ]')).toBeInTheDocument();
    // Version is sliced to 7-char short-SHA convention.
    expect(screen.getByText('test-sh')).toBeInTheDocument();
    expect(screen.getByText('Total events')).toBeInTheDocument();
    expect(screen.getByText('Top usernames')).toBeInTheDocument();
    expect(screen.getByText('Top passwords')).toBeInTheDocument();
    expect(screen.getByText('Event timeline')).toBeInTheDocument();
    expect(screen.getByText(/Recent events/)).toBeInTheDocument();
    expect(screen.getByTestId('geomap-placeholder')).toBeInTheDocument();
    expect(screen.getByText(/dictionary-classified attempts/)).toBeInTheDocument();
  });
});
