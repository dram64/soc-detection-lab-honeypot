import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TopListResponse } from '../../api/types';
import { mockQuery } from '../../test-utils';

vi.mock('../../api/queries', () => ({
  useTopCountries: vi.fn(),
}));

// world-atlas TopoJSON is loaded as JSON; mock to a tiny synthetic shape so
// the test doesn't depend on the actual file's contents.
vi.mock('world-atlas/countries-110m.json', () => ({
  default: {
    type: 'Topology',
    objects: { countries: { type: 'GeometryCollection', geometries: [] } },
  },
}));

// react-simple-maps renders SVG paths for every country, which jsdom doesn't
// lay out. Stub the surface to expose the data binding for assertion.
vi.mock('react-simple-maps', () => ({
  ComposableMap: ({ children }: { children: ReactNode }) => (
    <div data-testid="composable-map">{children}</div>
  ),
  Geographies: ({
    children,
  }: {
    children: (props: {
      geographies: Array<{ rsmKey: string; id: string; properties: { name: string } }>;
    }) => ReactNode;
  }) =>
    children({
      geographies: [
        { rsmKey: 'cn', id: '156', properties: { name: 'China' } },
        { rsmKey: 'us', id: '840', properties: { name: 'United States' } },
        { rsmKey: 'fr', id: '250', properties: { name: 'France' } },
      ],
    }),
  Geography: ({
    fill,
    geography,
    onMouseEnter,
    onMouseLeave,
  }: {
    fill: string;
    geography: { rsmKey: string };
    onMouseEnter?: () => void;
    onMouseLeave?: () => void;
  }) => (
    <div
      data-testid={`geo-${geography.rsmKey}`}
      data-fill={fill}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    />
  ),
}));

import { useTopCountries } from '../../api/queries';
import GeoMap from './GeoMap';

const mocked = vi.mocked(useTopCountries);

describe('GeoMap', () => {
  beforeEach(() => mocked.mockReset());
  afterEach(() => vi.clearAllMocks());

  it('renders skeleton when data is undefined', () => {
    mocked.mockReturnValue(mockQuery<TopListResponse>({ data: undefined }));
    render(<GeoMap />);
    expect(screen.getByLabelText('Loading attack origins map')).toBeInTheDocument();
  });

  it('renders the map and assigns choropleth fills based on the country counts', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [
            { value: 'CN', count: 100 },
            { value: 'US', count: 25 },
          ],
        },
      }),
    );
    render(<GeoMap />);
    expect(screen.getByTestId('composable-map')).toBeInTheDocument();
    // CN has the high count → ends up at the top of the teal scale
    const cn = screen.getByTestId('geo-cn');
    const us = screen.getByTestId('geo-us');
    const fr = screen.getByTestId('geo-fr');
    expect(cn.getAttribute('data-fill')).toBeTruthy();
    expect(us.getAttribute('data-fill')).toBeTruthy();
    // CN's fill differs from US's (saturation by count)
    expect(cn.getAttribute('data-fill')).not.toBe(us.getAttribute('data-fill'));
    // FR has no data → renders in the neutral "no data" tone
    expect(fr.getAttribute('data-fill')).toBe('#1f2933');
  });

  it('shows a header note with country count and max', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [
            { value: 'CN', count: 1500 },
            { value: 'US', count: 600 },
          ],
        },
      }),
    );
    render(<GeoMap />);
    expect(screen.getByText(/2 countries/)).toBeInTheDocument();
    expect(screen.getByText(/max 1\.5k/)).toBeInTheDocument();
  });

  it('keeps showing data on isError (silent stale)', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: { items: [{ value: 'CN', count: 100 }] },
        isError: true,
      }),
    );
    render(<GeoMap />);
    expect(screen.getByTestId('composable-map')).toBeInTheDocument();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
  });

  it('handles empty items without crashing', () => {
    mocked.mockReturnValue(mockQuery({ data: { items: [] } }));
    render(<GeoMap />);
    expect(screen.getByTestId('composable-map')).toBeInTheDocument();
    // All three test geographies render in the no-data tone
    const fr = screen.getByTestId('geo-fr');
    expect(fr.getAttribute('data-fill')).toBe('#1f2933');
  });

  it('drops country codes the mapping table does not know', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: {
          items: [
            { value: 'CN', count: 100 },
            { value: 'XX', count: 50 }, // not in alpha2→numeric table
          ],
        },
      }),
    );
    render(<GeoMap />);
    // 1 country in the count, not 2
    expect(screen.getByText(/1 countries/)).toBeInTheDocument();
  });

  it('shows the hover tooltip when a country is mouse-entered', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: { items: [{ value: 'CN', count: 1234 }] },
      }),
    );
    render(<GeoMap />);
    const cn = screen.getByTestId('geo-cn');
    fireEvent.mouseEnter(cn);
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toBeInTheDocument();
    expect(tooltip.textContent).toContain('China');
    expect(tooltip.textContent).toContain('1.2k events');

    fireEvent.mouseLeave(cn);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('shows "no events in window" tooltip for a hovered country with no data', () => {
    mocked.mockReturnValue(
      mockQuery({
        data: { items: [{ value: 'CN', count: 100 }] },
      }),
    );
    render(<GeoMap />);
    fireEvent.mouseEnter(screen.getByTestId('geo-fr'));
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip.textContent).toContain('France');
    expect(tooltip.textContent).toContain('no events in window');
  });
});
