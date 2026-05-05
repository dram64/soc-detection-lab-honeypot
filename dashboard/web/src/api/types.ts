
export type Window24h7d = '24h' | '7d';
export type Window24h7d30d = '24h' | '7d' | '30d';
export type TimelineBucket = '1h' | '1d';

// --- /api/healthz -----------------------------------------------------------

export interface HealthResponse {
  status: 'ok';
  version: string;
}

// --- /api/summary -----------------------------------------------------------

export interface SummaryResponse {
  total: number;
  last_24h: number;
  last_1h: number;
  unique_ips_24h: number;
  sensor_last_seen: string | null;
}

// --- /api/timeline ----------------------------------------------------------

export interface TimelineBucketRow {
  ts: string;
  /** `null` indicates the underlying per-bucket DDB query failed; render
   *  as a gap rather than a zero. */
  count: number | null;
}

export interface TimelineResponse {
  buckets: TimelineBucketRow[];
}

// --- /api/top/{dimension} ---------------------------------------------------

export interface TopListItem {
  value: string;
  count: number;
}

export interface TopListResponse {
  items: TopListItem[];
}

export interface TopAsnItem {
  asn: number;
  asn_org: string | null;
  count: number;
}

export interface TopAsnsResponse {
  items: TopAsnItem[];
}

// --- /api/events + /api/sessions/{id} ---------------------------------------

/**
 * The shape of a single event returned by /api/events and /api/sessions/{id}.
 * Mirrors `PublicEvent` in functions/shared/event_dto.py exactly. Note the
 * absence of `password_raw` — that is the load-bearing security contract.
 */
export interface PublicEvent {
  eventid: string;
  session: string;
  src_ip: string;
  ts: string;
  sensor: string;

  src_port: number | null;
  dst_ip: string | null;
  dst_port: number | null;
  protocol: string | null;
  message: string | null;

  username: string | null;
  /** Dictionary-classified attempted password OR `<filtered:len=N>`
   *  marker for non-dictionary attempts. The actual non-dictionary value
   *  never leaves the backend (ADR-005). */
  password: string | null;

  input: string | null;
  url: string | null;
  shasum: string | null;
  duration: number | null;

  country: string | null;
  asn: number | null;
  asn_org: string | null;
}

export interface EventsResponse {
  items: PublicEvent[];
  next_before: string | null;
}

export interface SessionEventsResponse {
  events: PublicEvent[];
}

// --- /api/breakdown ---------------------------------------------------------

export interface BreakdownResponse {
  brute_force: number;
  credential_stuffing: number;
  scanner: number;
  other: number;
}

// --- API errors -------------------------------------------------------------

export interface ApiErrorBody {
  error: string;
}

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody | null;

  constructor(status: number, message: string, body: ApiErrorBody | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}
