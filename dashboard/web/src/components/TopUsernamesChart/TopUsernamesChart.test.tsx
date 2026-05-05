import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import type * as RechartsModule from 'recharts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TopListResponse } from '../../api/types';

vi.mock('../../api/queries', () => ({
  useTopUsernames: vi.fn(),
}));

// Recharts uses ResponsiveContainer which needs measurable dimensions.
// jsdom doesn't lay out, so we stub ResponsiveContainer.
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof RechartsModule>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div data-testid="responsive-container" style={{ width: 800, height: 420 }}>
        {children}
      </div>
    ),
  };
});

import { useTopUsernames } from '../../api/queries';
import { mockQuery } from '../../test-utils';
import { TopUsernamesChart } from './TopUsernamesChart';

const mocked = vi.mocked(useTopUsernames);

describe('TopUsernamesChart', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(() => vi.clearAllMocks());

  it('renders skeleton rows when data is undefined', () => {
    mocked.mockReturnValue(mockQuery<TopListResponse>({ data: undefined }));
    render(<TopUsernamesChart />);
    expect(screen.getAllByLabelText(/Loading Top usernames/).length).toBeGreaterThan(0);
  });

  it('renders the chart container when data is present', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [
            { value: 'root', count: 142 },
            { value: 'admin', count: 88 },
          ],
        },
      }),
    );
    render(<TopUsernamesChart />);
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
    expect(screen.getByText('Top usernames (24h)')).toBeInTheDocument();
  });

  it('renders the empty state when data is present but items is empty', () => {
    mocked.mockReturnValue(mockQuery({ data: { items: [] } }));
    render(<TopUsernamesChart />);
    expect(screen.getByText(/No data yet/)).toBeInTheDocument();
  });

  it('keeps showing data even when isError is true (silent stale)', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: { items: [{ value: 'root', count: 142 }] },
        isError: true,
      }),
    );
    render(<TopUsernamesChart />);
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
  });
});
