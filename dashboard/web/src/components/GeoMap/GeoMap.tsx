
import { scaleLinear } from 'd3-scale';
import { useMemo, useState } from 'react';
import {
  ComposableMap,
  Geographies,
  Geography,
} from 'react-simple-maps';
import countriesTopo from 'world-atlas/countries-110m.json';
import { useTopCountries } from '../../api/queries';
import { alpha2ToName, alpha2ToNumeric, NUMERIC_TO_ALPHA2 } from '../../lib/country-codes';
import { formatEventCount } from '../../lib/format';
import { Card } from '../ui/Card';
import { Skeleton } from '../ui/Skeleton';

interface GeographyFeature {
  rsmKey: string;
  id?: string | number;
  properties?: { name?: string };
}

const COLOR_LOW = '#0f3a3a'; // teal at low saturation
const COLOR_HIGH = '#5eead4'; // teal at high saturation
const COLOR_NO_DATA = '#1f2933'; // neutral bg-border tone
const STROKE = '#0b0f14'; // page background, draws subtle borders

function GeoMapContent() {
  const { data } = useTopCountries({ limit: 20, window: '24h' });

  // Build numeric-id → count lookup and the saturation scale.
  const { countByNumeric, colorScale, maxCount } = useMemo(() => {
    if (!data || data.items.length === 0) {
      return {
        countByNumeric: new Map<string, number>(),
        colorScale: null,
        maxCount: 0,
      };
    }
    const map = new Map<string, number>();
    let max = 0;
    for (const item of data.items) {
      const numeric = alpha2ToNumeric(item.value);
      if (numeric === undefined) continue;
      map.set(numeric, item.count);
      if (item.count > max) max = item.count;
    }
    const scale = scaleLinear<string>().domain([0, max]).range([COLOR_LOW, COLOR_HIGH]);
    return { countByNumeric: map, colorScale: scale, maxCount: max };
  }, [data]);

  const [hover, setHover] = useState<{ name: string; count: number } | null>(null);

  if (!data) {
    return (
      <Card title="Attack origins (24h)">
        <Skeleton className="h-[420px] w-full" label="Loading attack origins map" />
      </Card>
    );
  }

  // Use the resolved-country count, not data.items.length — items whose
  // alpha-2 code isn't in the mapping table are silently dropped.
  const headerNote = (
    <span className="font-mono text-xs text-fg-subtle">
      {countByNumeric.size} countries
      {maxCount > 0 ? ` · max ${formatEventCount(maxCount)}` : ''}
    </span>
  );

  return (
    <Card title="Attack origins (24h)" rightSlot={headerNote}>
      <div className="relative h-[420px] w-full">
        <ComposableMap
          projection="geoEqualEarth"
          projectionConfig={{ scale: 160 }}
          style={{ width: '100%', height: '100%' }}
        >
          <Geographies geography={countriesTopo}>
            {({ geographies }: { geographies: GeographyFeature[] }) =>
              geographies.map((geo) => {
                const numeric = String(geo.id ?? '').padStart(3, '0');
                const count = countByNumeric.get(numeric);
                const fill = count !== undefined && colorScale ? colorScale(count) : COLOR_NO_DATA;
                const alpha = NUMERIC_TO_ALPHA2[numeric];
                const name = alpha ? alpha2ToName(alpha) : (geo.properties?.name ?? 'Unknown');
                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    fill={fill}
                    stroke={STROKE}
                    strokeWidth={0.4}
                    onMouseEnter={() => setHover({ name, count: count ?? 0 })}
                    onMouseLeave={() => setHover(null)}
                    style={{
                      default: { outline: 'none' },
                      hover: { outline: 'none', fill: COLOR_HIGH },
                      pressed: { outline: 'none' },
                    }}
                  />
                );
              })
            }
          </Geographies>
        </ComposableMap>
        {hover ? (
          <div
            role="tooltip"
            className="pointer-events-none absolute left-4 top-4 rounded-md border border-bg-border bg-bg/95 px-3 py-2 text-xs shadow-lg"
          >
            <div className="font-medium text-fg">{hover.name}</div>
            <div className="font-mono text-fg-muted">
              {hover.count > 0 ? `${formatEventCount(hover.count)} events` : 'no events in window'}
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// Default export so the lazy wrapper can `import('./GeoMap')`.
export default GeoMapContent;
export { GeoMapContent as GeoMap };
