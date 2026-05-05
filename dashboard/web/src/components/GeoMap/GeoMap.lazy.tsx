/**
 * Lazy-loading wrapper for the GeoMap. Splits react-simple-maps + d3-scale +
 * world-atlas TopoJSON (~110 KB raw, ~30 KB gzipped) into a separate chunk
 * that the browser only fetches when the dashboard route mounts.
 *
 * The Suspense fallback is the same Skeleton the Card-mounted component
 * renders during data load; from a viewer's perspective the lazy load and
 * the data load look identical (both show a low-detail outline).
 */

import { lazy, Suspense } from 'react';
import { Card } from '../ui/Card';
import { Skeleton } from '../ui/Skeleton';

const GeoMapInner = lazy(() => import('./GeoMap'));

function GeoMapFallback() {
  return (
    <Card title="Attack origins (24h)">
      <Skeleton className="h-[420px] w-full" label="Loading attack origins map" />
    </Card>
  );
}

export function GeoMap() {
  return (
    <Suspense fallback={<GeoMapFallback />}>
      <GeoMapInner />
    </Suspense>
  );
}
