import type { TopListResponse } from '../../api/types';
import { TopBarChart } from '../ui/TopBarChart';

/**
 * Top usernames from the completed 14-day collection run (May 6-21, 2026).
 *
 * Static final data aggregated directly from the raw S3 event archive — same
 * pattern as TopPasswordsChart. The live API window had emptied within hours
 * of the sensor's decommission as rolling-window aggregates rolled past the
 * last captured data; this preserves the run's results permanently.
 *
 * `root` dominates (botnets always try root first); `345gs5662d34` appearing
 * as both a top username AND a top password is the signature of a specific
 * automated SSH-scanner family that uses that string as a marker on both
 * sides of the credential pair.
 */
const TOP_USERNAMES: TopListResponse = {
  items: [
    { value: 'root', count: 16458 },
    { value: 'admin', count: 1856 },
    { value: 'user', count: 1562 },
    { value: '345gs5662d34', count: 1523 },
    { value: 'ubuntu', count: 694 },
    { value: 'sol', count: 380 },
    { value: 'test', count: 299 },
    { value: 'deploy', count: 263 },
    { value: 'user1', count: 210 },
    { value: 'solv', count: 193 },
    { value: 'solana', count: 192 },
    { value: 'oracle', count: 187 },
    { value: 'postgres', count: 182 },
    { value: 'steam', count: 162 },
    { value: 'minecraft', count: 162 },
    { value: 'git', count: 143 },
    { value: 'hadoop', count: 132 },
    { value: 'guest', count: 121 },
    { value: 'ftpuser', count: 119 },
    { value: 'mysql', count: 115 },
  ],
};

export function TopUsernamesChart() {
  return <TopBarChart title="Top usernames" data={TOP_USERNAMES} valueLabel="Username" />;
}
