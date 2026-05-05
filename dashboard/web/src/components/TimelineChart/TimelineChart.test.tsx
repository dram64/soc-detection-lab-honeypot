import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import type * as RechartsModule from 'recharts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TimelineResponse } from '../../api/types';

vi.mock('../../api/queries', () => ({
  useTimeline: vi.fn(),
}));

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof RechartsModule>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div data-testid="responsive-container" style={{ width: 800, height: 280 }}>
        {children}
      </div>
    ),
  };
});

import { useTimeline } from '../../api/queries';
import { mockQuery } from '../../test-utils';
import { TimelineChart } from './TimelineChart';

const mocked = vi.mocked(useTimeline);

describe('TimelineChart', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(() => vi.clearAllMocks());

  it('renders skeleton when data is undefined', () => {
    mocked.mockReturnValue(mockQuery<TimelineResponse>({ data: undefined }));
    render(<TimelineChart />);
    expect(screen.getByLabelText('Loading event timeline')).toBeInTheDocument();
  });

  it('renders the area chart with data', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          buckets: [
            { ts: '2026-04-29T00:00:00Z', count: 10 },
            { ts: '2026-04-29T01:00:00Z', count: 25 },
            { ts: '2026-04-29T02:00:00Z', count: 15 },
          ],
        },
      }),
    );
    render(<TimelineChart />);
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
    expect(screen.getByText('Event timeline (24h)')).toBeInTheDocument();
  });

  it('handles null counts (failed bucket queries) without crashing', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          buckets: [
            { ts: '2026-04-29T00:00:00Z', count: 10 },
            { ts: '2026-04-29T01:00:00Z', count: null },
            { ts: '2026-04-29T02:00:00Z', count: 25 },
          ],
        },
      }),
    );
    render(<TimelineChart />);
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
  });

  it('keeps showing data on isError (silent stale)', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: { buckets: [{ ts: '2026-04-29T00:00:00Z', count: 10 }] },
        isError: true,
      }),
    );
    render(<TimelineChart />);
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
  });
});
