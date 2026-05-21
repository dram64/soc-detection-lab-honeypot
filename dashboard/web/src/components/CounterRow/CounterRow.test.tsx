import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CounterRow } from './CounterRow';

describe('CounterRow', () => {
  it('renders the four final run-total counters', () => {
    render(<CounterRow />);
    expect(screen.getByText('Total events')).toBeInTheDocument();
    expect(screen.getByText('Attack sessions')).toBeInTheDocument();
    expect(screen.getByText('Login attempts')).toBeInTheDocument();
    expect(screen.getByText('Unique attacker IPs')).toBeInTheDocument();
  });

  it('renders the compact-formatted run totals', () => {
    render(<CounterRow />);
    // 231,930 → "231.9k"
    expect(screen.getByText('231.9k')).toBeInTheDocument();
    // 1,322 → "1.3k"
    expect(screen.getByText('1.3k')).toBeInTheDocument();
    // 36,440 (sessions) and 36,405 (login attempts) both compact to "36.4k"
    expect(screen.getAllByText('36.4k')).toHaveLength(2);
  });
});
