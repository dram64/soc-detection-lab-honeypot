
import { scaleLinear } from 'd3-scale';
import { useMemo, useState } from 'react';
import {
  ComposableMap,
  Geographies,
  Geography,
} from 'react-simple-maps';
import countriesTopo from 'world-atlas/countries-110m.json';
import type { TopListResponse } from '../../api/types';
import { alpha2ToName, alpha2ToNumeric, NUMERIC_TO_ALPHA2 } from '../../lib/country-codes';
import { formatEventCount } from '../../lib/format';
import { Card } from '../ui/Card';

interface GeographyFeature {
  rsmKey: string;
  id?: string | number;
  properties?: { name?: string };
}

const COLOR_LOW = '#0f3a3a'; // teal at low saturation
const COLOR_HIGH = '#5eead4'; // teal at high saturation
const COLOR_NO_DATA = '#1f2933'; // neutral bg-border tone
const STROKE = '#0b0f14'; // page background, draws subtle borders

/**
 * Top attacker source countries from the completed 14-day collection run
 * (May 6-21, 2026), aggregated from the raw S3 HAProxy archive and GeoIP-
 * resolved to alpha-2 codes. Static for the same reason TopPasswordsChart +
 * TopUsernamesChart are: the live API window emptied post-decommission.
 *
 * The full run touched 84 distinct source countries; this is the top 20 by
 * connection count.
 */
const RUN_COUNTRIES: TopListResponse = {
  items: [
    { value: 'NL', count: 12539 },
    { value: 'UZ', count: 6274 },
    { value: 'US', count: 2519 },
    { value: 'MU', count: 2457 },
    { value: 'HK', count: 1333 },
    { value: 'DE', count: 1321 },
    { value: 'IN', count: 1186 },
    { value: 'SG', count: 1160 },
    { value: 'ID', count: 895 },
    { value: 'VN', count: 854 },
    { value: 'PL', count: 764 },
    { value: 'GB', count: 737 },
    { value: 'CN', count: 665 },
    { value: 'BR', count: 530 },
    { value: 'KR', count: 394 },
    { value: 'MN', count: 346 },
    { value: 'RU', count: 240 },
    { value: 'BE', count: 205 },
    { value: 'FR', count: 175 },
    { value: 'ES', count: 145 },
  ],
};

function GeoMapContent() {
  const data = RUN_COUNTRIES;

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

  // Use the resolved-country count, not data.items.length — items whose
  // alpha-2 code isn't in the mapping table are silently dropped.
  const headerNote = (
    <span className="font-mono text-xs text-fg-subtle">
      {countByNumeric.size} countries
      {maxCount > 0 ? ` · max ${formatEventCount(maxCount)}` : ''}
    </span>
  );

  return (
    <Card title="Attack origins" rightSlot={headerNote}>
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
