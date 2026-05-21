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

import { TopPasswordsChart } from './TopPasswordsChart';

// The chart renders the final top-20 from the completed run as static data
// (real high-frequency attack credentials; see component doc + ADR-005).
// Recharts axis ticks aren't laid out by jsdom, so we assert the chart wiring
// (title + container present) rather than individual bar labels.
describe('TopPasswordsChart', () => {
  it('renders the title and chart container', () => {
    render(<TopPasswordsChart />);
    expect(screen.getByText('Top passwords')).toBeInTheDocument();
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
  });
});
