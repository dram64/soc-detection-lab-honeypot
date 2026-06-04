import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import type * as RechartsModule from 'recharts';
import { describe, expect, it, vi } from 'vitest';

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

import { TopUsernamesChart } from './TopUsernamesChart';

// Static final-run data; assert title + chart container render.
describe('TopUsernamesChart', () => {
  it('renders the title and chart container', () => {
    render(<TopUsernamesChart />);
    expect(screen.getByText('Top usernames')).toBeInTheDocument();
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
  });
});
