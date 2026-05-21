import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import type * as RechartsModule from 'recharts';
import { describe, expect, it, vi } from 'vitest';

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

import { TimelineChart } from './TimelineChart';

// The timeline renders the completed run's daily buckets as static data
// (full 14-day span; see component doc). Recharts axis ticks aren't laid out
// by jsdom, so we assert the chart wiring (title + container present).
describe('TimelineChart', () => {
  it('renders the title and area-chart container', () => {
    render(<TimelineChart />);
    expect(screen.getByText('Event timeline')).toBeInTheDocument();
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
  });
});
