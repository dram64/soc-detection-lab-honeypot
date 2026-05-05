/**
 * Mapping from ISO 3166-1 alpha-2 (returned by the API) to ISO numeric
 * codes (used as `id` in world-atlas TopoJSON features).
 *
 * Coverage: every country in the synthetic generator's distribution plus
 * a wider safety margin of frequently-seen attacker-source nations. If a
 * country code arrives at the GeoMap that isn't in this table, the map
 * falls back to "uncoded" and the country renders in the neutral fill —
 * the data point is effectively dropped from the choropleth (logged, not
 * an error).
 *
 * Source: https://www.iso.org/iso-3166-country-codes.html
 */

export const ALPHA2_TO_NUMERIC: Record<string, string> = {
  AE: '784',
  AR: '032',
  AU: '036',
  AT: '040',
  BD: '050',
  BE: '056',
  BR: '076',
  CA: '124',
  CH: '756',
  CL: '152',
  CN: '156',
  CO: '170',
  CZ: '203',
  DE: '276',
  DK: '208',
  EG: '818',
  ES: '724',
  FI: '246',
  FR: '250',
  GB: '826',
  GR: '300',
  HK: '344',
  HU: '348',
  ID: '360',
  IE: '372',
  IL: '376',
  IN: '356',
  IR: '364',
  IT: '380',
  JP: '392',
  KR: '410',
  KZ: '398',
  MX: '484',
  MY: '458',
  NG: '566',
  NL: '528',
  NO: '578',
  NZ: '554',
  PE: '604',
  PH: '608',
  PK: '586',
  PL: '616',
  PT: '620',
  RO: '642',
  RU: '643',
  SA: '682',
  SE: '752',
  SG: '702',
  TH: '764',
  TR: '792',
  TW: '158',
  UA: '804',
  US: '840',
  VE: '862',
  VN: '704',
  ZA: '710',
};

export const NUMERIC_TO_ALPHA2: Record<string, string> = Object.fromEntries(
  Object.entries(ALPHA2_TO_NUMERIC).map(([alpha, numeric]) => [numeric, alpha]),
);

/**
 * Display name lookup for tooltips. Only countries we expect to see in
 * synthetic + likely-real data are here. Unknown alpha-2 codes fall back
 * to the code itself.
 */
export const ALPHA2_TO_NAME: Record<string, string> = {
  AE: 'United Arab Emirates',
  AR: 'Argentina',
  AU: 'Australia',
  AT: 'Austria',
  BD: 'Bangladesh',
  BE: 'Belgium',
  BR: 'Brazil',
  CA: 'Canada',
  CH: 'Switzerland',
  CL: 'Chile',
  CN: 'China',
  CO: 'Colombia',
  CZ: 'Czechia',
  DE: 'Germany',
  DK: 'Denmark',
  EG: 'Egypt',
  ES: 'Spain',
  FI: 'Finland',
  FR: 'France',
  GB: 'United Kingdom',
  GR: 'Greece',
  HK: 'Hong Kong',
  HU: 'Hungary',
  ID: 'Indonesia',
  IE: 'Ireland',
  IL: 'Israel',
  IN: 'India',
  IR: 'Iran',
  IT: 'Italy',
  JP: 'Japan',
  KR: 'South Korea',
  KZ: 'Kazakhstan',
  MX: 'Mexico',
  MY: 'Malaysia',
  NG: 'Nigeria',
  NL: 'Netherlands',
  NO: 'Norway',
  NZ: 'New Zealand',
  PE: 'Peru',
  PH: 'Philippines',
  PK: 'Pakistan',
  PL: 'Poland',
  PT: 'Portugal',
  RO: 'Romania',
  RU: 'Russia',
  SA: 'Saudi Arabia',
  SE: 'Sweden',
  SG: 'Singapore',
  TH: 'Thailand',
  TR: 'Turkey',
  TW: 'Taiwan',
  UA: 'Ukraine',
  US: 'United States',
  VE: 'Venezuela',
  VN: 'Vietnam',
  ZA: 'South Africa',
};

export function alpha2ToNumeric(code: string): string | undefined {
  return ALPHA2_TO_NUMERIC[code.toUpperCase()];
}

export function alpha2ToName(code: string): string {
  return ALPHA2_TO_NAME[code.toUpperCase()] ?? code;
}
