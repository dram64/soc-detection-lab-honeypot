/**
 * Single fetcher used by every endpoint wrapper. Handles base URL,
 * error normalization, and JSON parsing. Anything non-2xx becomes an
 * `ApiError` with the parsed error body when available.
 */

import { ApiError, type ApiErrorBody } from './types';

const RAW_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '') as string;
const BASE_URL = RAW_BASE_URL.replace(/\/$/, '');

if (!BASE_URL && import.meta.env.MODE !== 'test') {
  // eslint-disable-next-line no-console
  console.warn(
    '[api] VITE_API_BASE_URL is not set. Configure it in .env.development for local runs.',
  );
}

interface ApiFetchOptions {
  signal?: AbortSignal;
  query?: Record<string, string | number | undefined>;
}

function buildUrl(path: string, query?: ApiFetchOptions['query']): string {
  const url = new URL(path, BASE_URL || 'http://localhost');
  if (!BASE_URL) {
    // Tests / runs without a base URL configured — keep the path-only form.
    // URL constructor demands an absolute origin, so we stripped to a relative path.
    const search = url.search;
    return path + search;
  }
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null) {
        url.searchParams.set(k, String(v));
      }
    }
  }
  return url.toString();
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const url = buildUrl(path, options.query);
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      throw err;
    }
    throw new ApiError(0, `Network error contacting ${path}: ${(err as Error).message}`);
  }

  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // body wasn't JSON — that's fine, leave null
    }
    throw new ApiError(response.status, body?.error ?? response.statusText, body);
  }

  return (await response.json()) as T;
}

export const __test__ = { buildUrl };
