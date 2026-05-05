import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import type * as RechartsModule from 'recharts';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../api/queries', () => ({
  useHealth: vi.fn().mockReturnValue({
    data: { status: 'ok', version: 'test-sha' },
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
    expect(screen.getByText('Cowrie SSH honeypot, real-time')).toBeInTheDocument();
    expect(screen.getByText('● healthy')).toBeInTheDocument();
    expect(screen.getByText('test-sha')).toBeInTheDocument();
    expect(screen.getByText('Total events')).toBeInTheDocument();
    expect(screen.getByText('Top usernames (24h)')).toBeInTheDocument();
    expect(screen.getByText('Top passwords (24h)')).toBeInTheDocument();
    expect(screen.getByText('Event timeline (24h)')).toBeInTheDocument();
    expect(screen.getAllByLabelText(/Loading event row/).length).toBeGreaterThan(0);
    expect(screen.getByTestId('geomap-placeholder')).toBeInTheDocument();
    expect(screen.getByText(/dictionary-classified attempts/)).toBeInTheDocument();
  });
});
