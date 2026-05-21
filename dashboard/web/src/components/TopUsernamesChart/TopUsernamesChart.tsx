import { useTopUsernames } from '../../api/queries';
import { TopBarChart } from '../ui/TopBarChart';

export function TopUsernamesChart() {
  const { data } = useTopUsernames({ limit: 20, window: '7d' });
  return <TopBarChart title="Top usernames" data={data} valueLabel="Username" />;
}
