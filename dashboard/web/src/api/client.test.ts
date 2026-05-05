/**
 * Smoke test for the typed API client. Mocks fetch, verifies that:
 *   1. getHealth() returns the expected shape on success
 *   2. an HTTP 4xx response gets normalized to ApiError with the parsed body
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getHealth, getSummary } from './endpoints';
import { ApiError } from './types';

describe('api client', () => {
  const realFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn() as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it('returns typed response on 200', async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({ status: 'ok', version: 'test-sha' }),
    });
    const data = await getHealth();
    expect(data.status).toBe('ok');
    expect(data.version).toBe('test-sha');
  });

  it('normalizes 4xx into ApiError with parsed body', async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      json: () => Promise.resolve({ error: 'invalid params' }),
    });
    await expect(getSummary()).rejects.toBeInstanceOf(ApiError);
    try {
      await getSummary();
    } catch (err) {
      expect((err as ApiError).status).toBe(400);
      expect((err as ApiError).body?.error).toBe('invalid params');
    }
  });
});
