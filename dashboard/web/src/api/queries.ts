/**
 * TanStack Query hooks — one per endpoint. Default `staleTime` and
 * `refetchInterval` are set on the QueryClient (see App.tsx); per-hook
 * overrides go here when an endpoint warrants different polling cadence
 * (e.g. /api/healthz wants polling at all, but at a slower cadence than
 * the dashboard's data endpoints).
 */

import { useQuery, type UseQueryOptions } from '@tanstack/react-query';
import {
  getBreakdown,
  getEvents,
  getHealth,
  getSession,
  getSummary,
  getTimeline,
  getTopAsns,
  getTopCountries,
  getTopPasswords,
  getTopUsernames,
  type BreakdownParams,
  type EventsParams,
  type TimelineParams,
  type TopAsnsParams,
  type TopListParams,
} from './endpoints';
import type {
  BreakdownResponse,
  EventsResponse,
  HealthResponse,
  SessionEventsResponse,
  SummaryResponse,
  TimelineResponse,
  TopAsnsResponse,
  TopListResponse,
} from './types';

// Per-endpoint stable cache keys; objects passed for params are stringified
// by TanStack Query's structural-key matching.
export const queryKeys = {
  health: () => ['health'] as const,
  summary: () => ['summary'] as const,
  timeline: (params: TimelineParams) => ['timeline', params] as const,
  topUsernames: (params: TopListParams) => ['top', 'usernames', params] as const,
  topPasswords: (params: TopListParams) => ['top', 'passwords', params] as const,
  topCountries: (params: TopListParams) => ['top', 'countries', params] as const,
  topAsns: (params: TopAsnsParams) => ['top', 'asns', params] as const,
  events: (params: EventsParams) => ['events', params] as const,
  breakdown: (params: BreakdownParams) => ['breakdown', params] as const,
  session: (id: string) => ['session', id] as const,
};

type QueryOptions<T> = Omit<UseQueryOptions<T, Error, T>, 'queryKey' | 'queryFn'>;

export function useHealth(options: QueryOptions<HealthResponse> = {}) {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: ({ signal }) => getHealth(signal),
    // Health probe: poll less aggressively than data endpoints; cache-bust
    // the QueryClient defaults explicitly.
    staleTime: 60_000,
    refetchInterval: 60_000,
    ...options,
  });
}

export function useSummary(options: QueryOptions<SummaryResponse> = {}) {
  return useQuery({
    queryKey: queryKeys.summary(),
    queryFn: ({ signal }) => getSummary(signal),
    ...options,
  });
}

export function useTimeline(
  params: TimelineParams = {},
  options: QueryOptions<TimelineResponse> = {},
) {
  return useQuery({
    queryKey: queryKeys.timeline(params),
    queryFn: ({ signal }) => getTimeline(params, signal),
    ...options,
  });
}

export function useTopUsernames(
  params: TopListParams = {},
  options: QueryOptions<TopListResponse> = {},
) {
  return useQuery({
    queryKey: queryKeys.topUsernames(params),
    queryFn: ({ signal }) => getTopUsernames(params, signal),
    ...options,
  });
}

export function useTopPasswords(
  params: TopListParams = {},
  options: QueryOptions<TopListResponse> = {},
) {
  return useQuery({
    queryKey: queryKeys.topPasswords(params),
    queryFn: ({ signal }) => getTopPasswords(params, signal),
    ...options,
  });
}

export function useTopCountries(
  params: TopListParams = {},
  options: QueryOptions<TopListResponse> = {},
) {
  return useQuery({
    queryKey: queryKeys.topCountries(params),
    queryFn: ({ signal }) => getTopCountries(params, signal),
    ...options,
  });
}

export function useTopAsns(
  params: TopAsnsParams = {},
  options: QueryOptions<TopAsnsResponse> = {},
) {
  return useQuery({
    queryKey: queryKeys.topAsns(params),
    queryFn: ({ signal }) => getTopAsns(params, signal),
    ...options,
  });
}

export function useEvents(params: EventsParams = {}, options: QueryOptions<EventsResponse> = {}) {
  return useQuery({
    queryKey: queryKeys.events(params),
    queryFn: ({ signal }) => getEvents(params, signal),
    ...options,
  });
}

export function useBreakdown(
  params: BreakdownParams = {},
  options: QueryOptions<BreakdownResponse> = {},
) {
  return useQuery({
    queryKey: queryKeys.breakdown(params),
    queryFn: ({ signal }) => getBreakdown(params, signal),
    ...options,
  });
}

export function useSession(id: string, options: QueryOptions<SessionEventsResponse> = {}) {
  return useQuery({
    queryKey: queryKeys.session(id),
    queryFn: ({ signal }) => getSession(id, signal),
    enabled: !!id,
    // Sessions are immutable once closed — cache a long time, no auto-refetch.
    staleTime: 5 * 60_000,
    refetchInterval: false as const,
    ...options,
  });
}
