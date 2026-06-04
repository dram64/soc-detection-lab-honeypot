import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// world-atlas TopoJSON is loaded as JSON; mock to a tiny synthetic shape so
// the test doesn't depend on the actual file's contents.
vi.mock('world-atlas/countries-110m.json', () => ({
  default: {
    type: 'Topology',
    objects: { countries: { type: 'GeometryCollection', geometries: [] } },
  },
}));

// react-simple-maps renders SVG paths for every country, which jsdom doesn't
// lay out — stub the topojson-reading parts to empty geographies.
vi.mock('react-simple-maps', () => ({
  ComposableMap: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="composable-map">{children}</div>
  ),
  Geographies: ({ children }: { children: (p: { geographies: never[] }) => React.ReactNode }) =>
    children({ geographies: [] }),
  Geography: () => null,
}));

import GeoMap from './GeoMap';

// Static final-run data; assert title + map container render.
describe('GeoMap', () => {
  it('renders the title and map container with the static run data', () => {
    render(<GeoMap />);
    expect(screen.getByText('Attack origins')).toBeInTheDocument();
    expect(screen.getByTestId('composable-map')).toBeInTheDocument();
  });
});
