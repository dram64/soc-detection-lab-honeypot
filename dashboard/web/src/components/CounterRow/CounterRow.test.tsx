import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../api/queries', () => ({
  useSummary: vi.fn(),
}));

import { useSummary } from '../../api/queries';
import type { SummaryResponse } from '../../api/types';
import { mockQuery } from '../../test-utils';
import { CounterRow } from './CounterRow';

const mockedUseSummary = vi.mocked(useSummary);

describe('CounterRow', () => {
  beforeEach(() => {
    mockedUseSummary.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders skeletons while data is undefined', () => {
    mockedUseSummary.mockReturnValue(mockQuery<SummaryResponse>({ data: undefined }));
    render(<CounterRow />);
    const placeholders = screen.getAllByRole('status', { name: 'Loading' });
    expect(placeholders).toHaveLength(4);
    expect(screen.getByText('Total events')).toBeInTheDocument();
  });

  it('renders all four counters when data is present', () => {
    mockedUseSummary.mockReturnValue(
      mockQuery({
        data: {
          total: 12345,
          last_24h: 678,
          last_1h: 9,
          unique_ips_24h: 42,
          sensor_last_seen: null,
        },
      }),
    );
    render(<CounterRow />);
    expect(screen.getByText('12.3k')).toBeInTheDocument();
    expect(screen.getByText('678')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('keeps showing previous data on background refetch error (silent stale)', () => {
    mockedUseSummary.mockReturnValue(
      mockQuery({
        data: {
          total: 100,
          last_24h: 50,
          last_1h: 5,
          unique_ips_24h: 10,
          sensor_last_seen: null,
        },
        isError: true,
      }),
    );
    render(<CounterRow />);
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();
  });
});
