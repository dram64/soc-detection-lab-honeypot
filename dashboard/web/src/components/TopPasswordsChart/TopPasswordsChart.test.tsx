import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import type * as RechartsModule from 'recharts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TopListResponse } from '../../api/types';

vi.mock('../../api/queries', () => ({
  useTopPasswords: vi.fn(),
}));

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

import { useTopPasswords } from '../../api/queries';
import { mockQuery } from '../../test-utils';
import { TopPasswordsChart } from './TopPasswordsChart';

const mocked = vi.mocked(useTopPasswords);

describe('TopPasswordsChart', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(() => vi.clearAllMocks());

  it('renders skeleton when data is undefined', () => {
    mocked.mockReturnValue(mockQuery<TopListResponse>({ data: undefined }));
    render(<TopPasswordsChart />);
    expect(screen.getAllByLabelText(/Loading Top passwords/).length).toBeGreaterThan(0);
  });

  // Note: Recharts renders axis ticks to SVG <text> elements which jsdom
  // doesn't lay out. The label-formatting logic is unit-tested in
  // src/lib/format.test.ts (parseFilteredPassword); these tests assert the
  // chart wiring (title + container present, data flowing).

  it('renders the chart container when given dictionary password values', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [
            { value: '123456', count: 999 },
            { value: 'password', count: 500 },
          ],
        },
      }),
    );
    render(<TopPasswordsChart />);
    expect(screen.getByText('Top passwords (24h)')).toBeInTheDocument();
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
  });

  it('renders the chart container when values include the <filtered:len=N> marker', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [{ value: '<filtered:len=14>', count: 50 }],
        },
      }),
    );
    render(<TopPasswordsChart />);
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
  });
});
