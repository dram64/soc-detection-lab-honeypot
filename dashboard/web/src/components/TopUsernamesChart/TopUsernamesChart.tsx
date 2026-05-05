import { useTopUsernames } from '../../api/queries';
import { TopBarChart } from '../ui/TopBarChart';

export function TopUsernamesChart() {
  const { data } = useTopUsernames({ limit: 20, window: '24h' });
  return <TopBarChart title="Top usernames (24h)" data={data} valueLabel="Username" />;
}
