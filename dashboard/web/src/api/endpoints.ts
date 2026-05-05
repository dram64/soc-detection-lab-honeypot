/**
 * Typed endpoint wrappers — one function per HTTP route on the API Lambda.
 * Each returns a strongly-typed Promise<T> matching the backend's
 * Pydantic response DTO.
 */

import { apiFetch } from './client';
import type {
  BreakdownResponse,
  EventsResponse,
  HealthResponse,
  SessionEventsResponse,
  SummaryResponse,
  TimelineBucket,
  TimelineResponse,
  TopAsnsResponse,
  TopListResponse,
  Window24h7d,
  Window24h7d30d,
} from './types';

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/api/healthz', { signal });
}

export function getSummary(signal?: AbortSignal): Promise<SummaryResponse> {
  return apiFetch<SummaryResponse>('/api/summary', { signal });
}

export interface TimelineParams {
  bucket?: TimelineBucket;
  window?: Window24h7d30d;
}

export function getTimeline(
  params: TimelineParams = {},
  signal?: AbortSignal,
): Promise<TimelineResponse> {
  return apiFetch<TimelineResponse>('/api/timeline', {
    signal,
    query: { bucket: params.bucket, window: params.window },
  });
}

export interface TopListParams {
  limit?: number;
  window?: Window24h7d;
}

export function getTopUsernames(
  params: TopListParams = {},
  signal?: AbortSignal,
): Promise<TopListResponse> {
  return apiFetch<TopListResponse>('/api/top/usernames', {
    signal,
    query: { limit: params.limit, window: params.window },
  });
}

export function getTopPasswords(
  params: TopListParams = {},
  signal?: AbortSignal,
): Promise<TopListResponse> {
  return apiFetch<TopListResponse>('/api/top/passwords', {
    signal,
    query: { limit: params.limit, window: params.window },
  });
}

export function getTopCountries(
  params: TopListParams = {},
  signal?: AbortSignal,
): Promise<TopListResponse> {
  return apiFetch<TopListResponse>('/api/top/countries', {
    signal,
    query: { limit: params.limit, window: params.window },
  });
}

export interface TopAsnsParams {
  limit?: number;
  window?: Window24h7d;
}

export function getTopAsns(
  params: TopAsnsParams = {},
  signal?: AbortSignal,
): Promise<TopAsnsResponse> {
  return apiFetch<TopAsnsResponse>('/api/top/asns', {
    signal,
    query: { limit: params.limit, window: params.window },
  });
}

export interface EventsParams {
  limit?: number;
  before?: string;
}

export function getEvents(
  params: EventsParams = {},
  signal?: AbortSignal,
): Promise<EventsResponse> {
  return apiFetch<EventsResponse>('/api/events', {
    signal,
    query: { limit: params.limit, before: params.before },
  });
}

export interface BreakdownParams {
  window?: Window24h7d;
}

export function getBreakdown(
  params: BreakdownParams = {},
  signal?: AbortSignal,
): Promise<BreakdownResponse> {
  return apiFetch<BreakdownResponse>('/api/breakdown', {
    signal,
    query: { window: params.window },
  });
}

export function getSession(id: string, signal?: AbortSignal): Promise<SessionEventsResponse> {
  return apiFetch<SessionEventsResponse>(`/api/sessions/${encodeURIComponent(id)}`, { signal });
}
