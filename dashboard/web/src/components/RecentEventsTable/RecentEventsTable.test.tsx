import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// jsdom has no layout, so @tanstack/react-virtual sees 0 scroll height and
// renders 0 virtual items. Mock the virtualizer to render every row
// synchronously so the test can inspect cells.
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

import { RecentEventsTable } from './RecentEventsTable';

describe('RecentEventsTable', () => {
  it('renders the static final-run events with title and row count', () => {
    render(<RecentEventsTable />);
    // 30 events in the static dataset (RecentEventsTable.data.ts).
    expect(screen.getByText('Recent events (30)')).toBeInTheDocument();
    // A correlated source IP from the dataset:
    expect(screen.getAllByText('212.154.234.9').length).toBeGreaterThan(0);
    // A safe-list dictionary password renders verbatim:
    expect(screen.getAllByText('3245gs5662d34').length).toBeGreaterThan(0);
    // A filtered password renders as bullet characters via PasswordCell:
    expect(screen.getAllByText('•'.repeat(8)).length).toBeGreaterThan(0);
  });
});
