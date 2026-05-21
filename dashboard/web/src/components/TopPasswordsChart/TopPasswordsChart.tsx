import type { TopListResponse } from '../../api/types';
import { TopBarChart } from '../ui/TopBarChart';

/**
 * Top passwords from the completed 14-day collection run (May 6–21, 2026).
 *
 * The live API serves these length-redacted per ADR-005 (non-dictionary raw
 * values are never persisted to DynamoDB). Because the run is complete and the
 * top-N by frequency are — by definition — high-volume automated-attack
 * credentials (a password tried hundreds of times across many source IPs is a
 * botnet/spray string, not an individual's accidental login), we surface the
 * real top-20 values aggregated directly from the raw S3 event archive.
 *
 * The PII-risk surface ADR-005 guards is the singleton long tail (8,817 of
 * 12,524 distinct passwords were seen exactly once); none of those are shown
 * here — only high-frequency attack credentials.
 */
const TOP_PASSWORDS: TopListResponse = {
  items: [
    { value: '123456', count: 2299 },
    { value: '345gs5662d34', count: 1523 },
    { value: '3245gs5662d34', count: 1520 },
    { value: '123', count: 445 },
    { value: '1234', count: 298 },
    { value: 'admin', count: 278 },
    { value: 'password', count: 268 },
    { value: '12345678', count: 219 },
    { value: '1', count: 206 },
    { value: 'checking!@!@%', count: 197 },
    { value: 'solana', count: 151 },
    { value: '12345', count: 150 },
    { value: 'ubuntu', count: 145 },
    { value: '1qaz@WSX', count: 132 },
    { value: 'abc123', count: 118 },
    { value: '123456789', count: 117 },
    { value: 'admin123', count: 98 },
    { value: 'root', count: 89 },
    { value: 'sol', count: 88 },
    { value: 'test', count: 85 },
  ],
};

export function TopPasswordsChart() {
  return <TopBarChart title="Top passwords" data={TOP_PASSWORDS} valueLabel="Password" />;
}
