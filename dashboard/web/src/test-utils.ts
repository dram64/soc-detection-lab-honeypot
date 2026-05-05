/**
 * Centralizes the "partial UseQueryResult" cast used by every component
 * test. A real `UseQueryResult` has 25+ fields and discriminated union
 * variants; for tests we only care about `data` and `isError` (which is
 * what the components themselves read). One narrow `unknown` cast here
 * keeps the test files clean and the lint rule honest.
 */

import type { UseQueryResult } from '@tanstack/react-query';

export interface PartialQuery<T> {
  data: T | undefined;
  isError?: boolean;
  isPending?: boolean;
}

export function mockQuery<T>(partial: PartialQuery<T>): UseQueryResult<T, Error> {
  return partial as unknown as UseQueryResult<T, Error>;
}
